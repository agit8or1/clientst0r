"""Phase 102.3: Ready for Billing queue actions (the queue is shown on the
billing review page, psa.views.billing_review; logic in psa.billing.queue).

POST billing-review/queue/<customer>/decide/  approve / hold / exclude / include selected lines
POST billing-review/queue/<customer>/adjust/  add an adjustment (charge or credit with a reason)
POST billing-review/queue/<customer>/draft/   draft invoices for selected tickets / account charges
                                              (one per ticket, or one consolidated draft when
                                              `consolidated` is posted: Phase 102.4)
GET  billing-review/queue/<customer>/draft/preview/  113.9: every line, coverage and total the
                                              draft will have (defaults: every ticket with lines to
                                              draft and the account charges)
POST billing-review/queue/<customer>/draft/confirm/  113.9: draft exactly what the preview showed
                                              (refused when anything changed since)

MSP staff only. Decisions and adjustments need `billing_manage_charges` at
the customer, drafts `billing_send_invoices`; customers outside the user's
scope are 404.
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
import hmac

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.decorators import require_write
from core.middleware import get_request_organization

from .billing import queue as bq
from .feature_flags import require_psa_enabled


def _client(request, org_id):
    from core.models import Organization
    if not bq._is_staff(request.user):
        raise Http404
    allowed = bq.allowed_customers(request.user, bq.VIEW)
    qs = Organization.objects.all()
    if allowed is not None:
        qs = qs.filter(pk__in=allowed)
    return get_object_or_404(qs, pk=org_id)


def _back(request, client=None):
    url = reverse('psa:billing_review')
    period = (request.POST.get('period') or '')[:7]
    params = []
    if period:
        params.append(f'period={period}')
    if request.POST.get('customer_filter') and client is not None:
        params.append(f'customer={client.pk}')
    return redirect(url + (('?' + '&'.join(params)) if params else '') + '#ready-for-billing')


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def queue_decide(request, org_id):
    client = _client(request, org_id)
    until = None
    raw = (request.POST.get('hold_until') or '').strip()
    try:
        if raw:
            until = date.fromisoformat(raw)
        n = bq.decide(client, request.POST.getlist('item'), request.POST.get('decision') or '',
                      actor=request.user, reason=request.POST.get('reason') or '', hold_until=until)
    except ValueError as exc:
        messages.error(request, str(exc) if isinstance(exc, bq.QueueError) else 'Enter the date as YYYY-MM-DD.')
        return _back(request, client)
    messages.success(request, f'{client.name}: {n} line(s) updated.')
    return _back(request, client)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def queue_adjust(request, org_id):
    from .models import Ticket
    client = _client(request, org_id)
    ticket = None
    number = (request.POST.get('ticket_number') or '').strip()
    if number:
        ticket = Ticket.objects.filter(organization=client, ticket_number=number).first()
        if ticket is None:
            messages.error(request, f'{number} is not one of {client.name}\'s tickets.')
            return _back(request, client)
    try:
        charge = bq.add_adjustment(
            client, actor=request.user, description=request.POST.get('description') or '',
            amount=request.POST.get('amount') or '', is_credit=request.POST.get('is_credit') in ('1', 'on'),
            reason=request.POST.get('reason') or '', ticket=ticket, msp_org=get_request_organization(request))
    except bq.QueueError as exc:
        messages.error(request, str(exc))
        return _back(request, client)
    messages.success(request, f'Adjustment of {"-" if charge.is_credit else ""}{charge.amount} added for '
                              f'{client.name}; it bills with the account charges.')
    return _back(request, client)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def queue_draft(request, org_id):
    client = _client(request, org_id)
    if request.POST.get('consolidated') in ('1', 'on'):
        invoice, notes = bq.draft_consolidated_from_queue(
            client, actor=request.user, msp_org=get_request_organization(request),
            ticket_ids=request.POST.getlist('ticket'),
            include_charges=request.POST.get('include_charges') in ('1', 'on'),
            contract_id=request.POST.get('contract') or None)
        for n in notes:
            messages.info(request, n)
        if invoice is not None:
            messages.success(request, f'Consolidated draft invoice {invoice.invoice_number} created — '
                                      'review it before sending.')
            return redirect('psa:invoice_detail', pk=invoice.pk)
        if not notes:
            messages.info(request, 'Select tickets, the account charges or an agreement fee to draft.')
        return _back(request, client)
    invoices, notes = bq.draft_from_queue(
        client, actor=request.user, msp_org=get_request_organization(request),
        ticket_ids=request.POST.getlist('ticket'),
        include_charges=request.POST.get('include_charges') in ('1', 'on'))
    for n in notes:
        messages.info(request, n)
    if invoices:
        messages.success(request, 'Draft invoice(s) created — review before sending: '
                         + ', '.join(i.invoice_number for i in invoices))
    elif not notes:
        messages.info(request, 'Select tickets or the account charges to draft.')
    return _back(request, client)


# --- 113.9: Create draft -> preview -> Confirm -------------------------------------------

def _draft_client(request, org_id):
    """The customer for the draft preview and its confirmation. Not MSP staff:
    404 (as every queue action). Staff without billing_view_invoices at any
    customer: 403. A customer outside the user's scope: 404. Drafting needs
    billing_send_invoices at the customer (as queue_draft): 403."""
    if not bq._is_staff(request.user):
        raise Http404
    allowed = bq.allowed_customers(request.user, bq.VIEW)
    if allowed is not None and not allowed:
        raise PermissionDenied("You don't have the 'billing_view_invoices' permission.")
    client = _client(request, org_id)
    if not bq.can(request.user, client, bq.DRAFT):
        raise PermissionDenied("You don't have the 'billing_send_invoices' permission for this customer.")
    return client


def _preview_url(client, period, ticket_ids, include_charges):
    from urllib.parse import urlencode
    q = [('sel', '1')] + [('ticket', i) for i in ticket_ids]
    if include_charges:
        q.append(('include_charges', '1'))
    if period:
        q.append(('period', period))
    return reverse('psa:billing_queue_draft_preview', args=[client.pk]) + '?' + urlencode(q)


@login_required
@require_psa_enabled
@require_http_methods(['GET'])
def queue_draft_preview(request, org_id):
    """Every line the draft(s) will have, how each is covered and the totals,
    from the same queue the Billing Review shows (psa.billing.queue)."""
    client = _draft_client(request, org_id)
    explicit = request.GET.get('sel') == '1'
    preview = bq.draft_preview(
        request.user, client, msp_org=get_request_organization(request),
        ticket_ids=request.GET.getlist('ticket') if explicit else None,
        include_charges=(request.GET.get('include_charges') in ('1', 'on')) if explicit else None)
    return render(request, 'psa/billing_queue_draft_preview.html', {
        'client': client, 'preview': preview, 'g': preview.group,
        'period': (request.GET.get('period') or '')[:7],
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def queue_draft_confirm(request, org_id):
    """Draft what the preview showed, through the existing draft code
    (bq.draft_from_queue / bq.draft_consolidated_from_queue, under the
    customer billing lock). When a line or amount changed since the preview,
    or nothing is left (a second click), nothing is drafted."""
    from audit.models import AuditLog
    client = _draft_client(request, org_id)
    period = (request.POST.get('period') or '')[:7]
    ticket_ids = request.POST.getlist('ticket')
    include_charges = request.POST.get('include_charges') in ('1', 'on')
    msp_org = get_request_organization(request)
    preview = bq.draft_preview(request.user, client, msp_org=msp_org, ticket_ids=ticket_ids,
                               include_charges=include_charges)
    if preview.is_empty:
        messages.info(request, f'Nothing is left to draft for {client.name}; '
                               'it may already be on a draft invoice.')
        return _back(request, client)
    sent = (request.POST.get('fingerprint') or '')[:64]
    if not hmac.compare_digest(sent, preview.fingerprint):
        messages.warning(request, 'The charges changed since the preview, so nothing was drafted. '
                                  'Check them again, then confirm.')
        return redirect(_preview_url(client, period, preview.ticket_ids, include_charges))
    consolidated = request.POST.get('mode') == 'consolidated'
    if consolidated:
        invoice, notes = bq.draft_consolidated_from_queue(
            client, actor=request.user, msp_org=msp_org, ticket_ids=preview.ticket_ids,
            include_charges=bool(preview.charges), contract_id=request.POST.get('contract') or None)
        invoices = [invoice] if invoice is not None else []
    else:
        invoices, notes = bq.draft_from_queue(
            client, actor=request.user, msp_org=msp_org, ticket_ids=preview.ticket_ids,
            include_charges=bool(preview.charges))
    for n in notes:
        messages.info(request, n)
    if invoices:
        AuditLog.log(
            user=request.user, action='create', organization=client, object_type='psa.Invoice',
            object_id=invoices[0].pk, object_repr=invoices[0].invoice_number,
            description=(f'Confirmed draft invoice(s) for {client.name} from the Billing Review preview: '
                         + ', '.join(i.invoice_number for i in invoices))[:500],
            extra_data={'event': 'billing_queue_draft_confirm', 'mode': 'consolidated' if consolidated else 'separate',
                        'fingerprint': preview.fingerprint, 'previewed_total': str(preview.total),
                        'tickets': [t.ticket.ticket_number for t in preview.tickets],
                        'charges': [c.source_id for c in preview.charges],
                        'invoices': [i.invoice_number for i in invoices]})
        messages.success(request, 'Draft invoice(s) created — review before sending: '
                         + ', '.join(i.invoice_number for i in invoices))
        if len(invoices) == 1:
            return redirect('psa:invoice_detail', pk=invoices[0].pk)
    return _back(request, client)
