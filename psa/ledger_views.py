"""Phase 101.2: the prepaid-hour ledger page of a contract.

GET  /psa/contracts/<pk>/ledger/                 blocks, balances, postings, entries needing a choice
POST /psa/contracts/<pk>/ledger/adjust/          authorized manual adjustment
POST /psa/contracts/<pk>/ledger/block/           record an extra block of hours
POST /psa/time/<entry_id>/agreement/             choose the agreement of a time entry

Seeing a ledger needs `billing_view_invoices` at the contract's customer;
changing one needs `billing_manage_charges` there (per-permission reach:
client scope plus access groups granting it). MSP staff only. A contract the
user may not see answers 404.
"""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permission_utils import has_perm_for_org
from .billing import coverage, ledger
from .feature_flags import require_psa_enabled
from .models import Contract, PrepaidPosting, TicketTimeEntry
from .visibility import is_msp_staff


def _may(request, org, perm):
    user = request.user
    return (user.is_superuser or is_msp_staff(user)) and has_perm_for_org(user, org, perm)


def _contract_for(request, pk, perm=ledger.VIEW_PERMISSION):
    contract = get_object_or_404(Contract.objects.select_related('client_org', 'organization'), pk=pk)
    if not _may(request, contract.client_org_id, ledger.VIEW_PERMISSION):
        raise Http404
    if perm != ledger.VIEW_PERMISSION and not _may(request, contract.client_org_id, perm):
        raise PermissionDenied(f"Your role does not include '{perm}' for this customer.")
    return contract


@login_required
@require_psa_enabled
def contract_ledger(request, pk):
    contract = _contract_for(request, pk)
    balances = ledger.block_balances(contract)
    blocks = list(contract.prepaid_blocks.all().order_by('starts_on', 'pk'))
    for b in blocks:
        b.balance = balances.get(b.pk, Decimal('0'))
    postings = (PrepaidPosting.objects.filter(contract=contract)
                .select_related('block', 'actor', 'reverses').order_by('-created_at', '-pk')[:500])
    waiting = []
    for e in (TicketTimeEntry.objects.filter(billing_resolution='needs_choice',
                                             ticket__organization_id=contract.client_org_id)
              .select_related('ticket', 'user')[:100]):
        e.choices = coverage.candidate_agreements(contract.client_org_id, coverage.work_date(e), e.role_code)
        waiting.append(e)
    return render(request, 'psa/contract_ledger.html', {
        'item': contract,
        'summary': ledger.summary(contract),
        'blocks': blocks,
        'postings': postings,
        'waiting': waiting,
        'may_adjust': _may(request, contract.client_org_id, ledger.ADJUST_PERMISSION),
        'form_key': uuid.uuid4().hex,
        'grace_days': ledger.EXPIRY_GRACE_DAYS,
    })


def _decimal(raw):
    try:
        return Decimal((raw or '').strip())
    except (InvalidOperation, AttributeError):
        return None


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def contract_ledger_adjust(request, pk):
    contract = _contract_for(request, pk, ledger.ADJUST_PERMISSION)
    delta = _decimal(request.POST.get('hours'))
    block = None
    block_id = request.POST.get('block_id') or ''
    if block_id.isdigit():
        block = contract.prepaid_blocks.filter(pk=int(block_id)).first()
        if block is None:
            raise Http404
    if delta is None:
        messages.error(request, 'Enter the hours to add (positive) or remove (negative).')
        return redirect('psa:contract_ledger', pk=contract.pk)
    try:
        ledger.adjust(contract, delta, actor=request.user, reason=request.POST.get('reason', ''),
                      idempotency_key=(request.POST.get('form_key') or '')[:64], block=block)
    except ledger.LedgerError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Adjusted the prepaid balance by {delta:+.2f}h.')
    return redirect('psa:contract_ledger', pk=contract.pk)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def contract_ledger_block(request, pk):
    from datetime import date
    contract = _contract_for(request, pk, ledger.ADJUST_PERMISSION)
    qty = _decimal(request.POST.get('hours'))

    def _date(name):
        try:
            return date.fromisoformat((request.POST.get(name) or '').strip())
        except ValueError:
            return None
    if qty is None:
        messages.error(request, 'Enter the hours of the block.')
        return redirect('psa:contract_ledger', pk=contract.pk)
    try:
        ledger.purchase_block(contract, qty, actor=request.user, reason=request.POST.get('reason', ''),
                              idempotency_key=(request.POST.get('form_key') or '')[:64],
                              starts_on=_date('starts_on'), expires_on=_date('expires_on'))
    except ledger.LedgerError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Recorded a block of {qty:.2f}h. Bill it with an invoice or charge; '
                                  f'using the hours is not billed again.')
    return redirect('psa:contract_ledger', pk=contract.pk)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def time_entry_choose_agreement(request, entry_id):
    entry = get_object_or_404(TicketTimeEntry.objects.select_related('ticket', 'ticket__organization'),
                              pk=entry_id)
    org_id = entry.ticket.organization_id
    if not _may(request, org_id, ledger.VIEW_PERMISSION):
        raise Http404
    if not _may(request, org_id, ledger.ADJUST_PERMISSION):
        raise PermissionDenied(f"Your role does not include '{ledger.ADJUST_PERMISSION}' for this customer.")
    contract = get_object_or_404(Contract, pk=request.POST.get('contract_id') or 0, client_org_id=org_id)
    try:
        outcome = ledger.choose_agreement(entry, contract, actor=request.user)
    except ledger.LedgerError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Time entry {entry.pk} is billed against {contract.name} ({outcome}).')
    return redirect('psa:contract_ledger', pk=contract.pk)
