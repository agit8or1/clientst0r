"""Phase 101.5-101.7: Time & Charges, Add Item and the billing summary on a
ticket (logic in psa.billing.ticket_charges).

POST t/<n>/time/<id>/update/      classification, work type, notes, minutes (unapproved time)
POST t/<n>/time/<id>/agreement/   choose the agreement (billing_manage_charges)
POST t/<n>/items/add/             catalog item, stock item, one-off line or credit
POST t/<n>/items/<id>/used/       mark reserved stock used (deducted once)
POST t/<n>/items/<id>/remove/     remove a line not on an invoice (stock released)
POST t/<n>/billing/send/          Send to Billing (no invoice is created)
GET  t/<n>/charges/               Review Charges: the exact lines the invoice would have
GET  t/<n>/charges.json           the same as JSON (cost and margin only with permission)
GET  t/<n>/catalog.json?q=        catalog search for Add Item (cost only with permission)

MSP staff only; the ticket is reached through the same scoping as the
ticket page; writes need `tickets_edit` at the ticket's customer.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .billing import ledger
from .billing import ticket_charges as tc
from .feature_flags import require_psa_enabled


def _ticket(request, ticket_number, *, write=False):
    from . import views as v
    v._staff_or_403(request)
    ticket = v._kit_ticket(request, ticket_number)
    if write:
        v._require_ticket_perm(request, ticket, 'tickets_edit')
    return ticket


def _back(ticket, anchor='time-charges'):
    from django.urls import reverse
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}) + f'#{anchor}')


def _entry(ticket, entry_id):
    return get_object_or_404(ticket.time_entries.select_related('ticket', 'ticket__organization'), pk=entry_id)


def _minutes(raw):
    if raw in (None, ''):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise tc.ChargeError('Minutes must be a whole number.')


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def time_entry_update(request, ticket_number, entry_id):
    ticket = _ticket(request, ticket_number, write=True)
    entry = _entry(ticket, entry_id)
    cls = request.POST.get('classification')
    work = request.POST.get('work_type')
    notes = request.POST.get('notes') if 'notes' in request.POST else None
    try:
        changed = tc.update_entry(entry, actor=request.user, classification=cls or None, work_type=work or None,
                                  notes=notes, minutes=_minutes(request.POST.get('minutes')))
    except tc.ChargeError as exc:
        messages.error(request, str(exc))
        return _back(ticket)
    if changed:
        from audit.models import AuditLog
        AuditLog.log(user=request.user, action='update', organization=ticket.organization,
                     object_type='psa.TicketTimeEntry', object_id=entry.pk,
                     object_repr=f'time entry {entry.pk} on {ticket.ticket_number}',
                     description=f'Changed {", ".join(changed)} of time entry {entry.pk}'
                                 f' (classification {entry.classification or "-"})')
        messages.success(request, f'Time entry updated ({", ".join(changed)}).')
    return _back(ticket)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def time_entry_agreement(request, ticket_number, entry_id):
    ticket = _ticket(request, ticket_number, write=True)
    entry = _entry(ticket, entry_id)
    if not tc.can_choose_agreement(request.user, ticket.organization):
        raise PermissionDenied(f"Your role does not include '{tc.CHOOSE_AGREEMENT}' for this customer.")
    if tc.entry_on_invoice(entry):
        messages.error(request, 'This time is on an invoice. Void or credit the invoice before changing it.')
        return _back(ticket)
    ok = {c.pk: c for c in tc.agreement_choices(entry)}
    raw = request.POST.get('contract_id') or ''
    contract = ok.get(int(raw)) if raw.isdigit() else None
    if contract is None:
        messages.error(request, 'That agreement does not cover this entry (customer, date or role code).')
        return _back(ticket)
    try:
        outcome = ledger.choose_agreement(entry, contract, actor=request.user)
    except ledger.LedgerError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Time entry billed against {contract.name}'
                                  + (' (prepaid hours re-allocated).' if outcome == 'posted' else '.'))
    return _back(ticket)


def _scoped_catalog_item(ticket, raw):
    if not (raw or '').isdigit():
        return None
    from django.db.models import Q
    from pricing.models import PriceBookItem
    item = (PriceBookItem.objects.filter(pk=int(raw), is_active=True)
            .filter(Q(price_book__organization__isnull=True) | Q(price_book__organization=ticket.organization_id))
            .select_related('price_book').first())
    if item is None:
        raise Http404('Catalog item not found')
    return item


def _scoped_stock(ticket, raw):
    if not (raw or '').isdigit():
        return None
    from inventory.models import InventoryItem
    item = InventoryItem.objects.for_organization(ticket.organization).filter(pk=int(raw)).first()
    if item is None:
        raise Http404('Inventory item not found')
    return item


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def item_add(request, ticket_number):
    ticket = _ticket(request, ticket_number, write=True)
    p = request.POST
    try:
        row, warnings = tc.add_item(
            ticket, request.user, category=p.get('category') or '', description=(p.get('description') or ''),
            quantity=p.get('quantity') or '1', unit_price=p.get('unit_price'), unit_cost=p.get('unit_cost'),
            price_book_item=_scoped_catalog_item(ticket, p.get('price_book_item')),
            inventory_item=_scoped_stock(ticket, p.get('inventory_item')),
            serial_number=p.get('serial_number') or '',
            is_billable=p.get('is_billable') in ('1', 'on', 'true'),
            is_taxable=p.get('is_taxable') in ('1', 'on', 'true'))
    except tc.ChargeError as exc:
        messages.error(request, str(exc))
        return _back(ticket, 'ticket-items')
    for w in warnings:
        messages.warning(request, w)
    messages.success(request, f'Added {row.description}.')
    return _back(ticket, 'ticket-items')


def _item(ticket, pk):
    return get_object_or_404(ticket.expenses.select_related('ticket', 'ticket__organization'), pk=pk)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def item_used(request, ticket_number, pk):
    ticket = _ticket(request, ticket_number, write=True)
    row = _item(ticket, pk)
    if tc.consume(row, request.user):
        messages.success(request, f'{row.description}: stock deducted.')
    else:
        messages.info(request, f'{row.description} was already marked used (or holds no stock).')
    return _back(ticket, 'ticket-items')


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def item_remove(request, ticket_number, pk):
    ticket = _ticket(request, ticket_number, write=True)
    row = _item(ticket, pk)
    try:
        state = tc.remove_item(row, request.user)
    except tc.ChargeError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Line removed' + {'released': '; stock reservation released.',
                                                     'returned': '; stock returned.'}.get(state, '.'))
    return _back(ticket, 'ticket-items')


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def send_to_billing(request, ticket_number):
    ticket = _ticket(request, ticket_number, write=True)
    status, problems = tc.send_to_billing(ticket, request.user, note=(request.POST.get('note') or '')[:300])
    if status == 'ready':
        messages.success(request, f'{ticket.ticket_number} sent to billing for invoicing review. '
                                  f'No invoice was created.')
    else:
        messages.warning(request, f'{ticket.ticket_number} is flagged for billing review: ' + ' '.join(problems))
    return _back(ticket, 'billing-summary')


def _show_costs(request, ticket):
    return tc.can_view_costs(request.user, ticket.organization)


@login_required
@require_psa_enabled
def charges_review(request, ticket_number):
    from . import views as v
    ticket = _ticket(request, ticket_number)
    show = _show_costs(request, ticket)
    est = tc.ticket_estimate(ticket, show_costs=show)
    lines = []
    for ln in est.lines:
        row = {'description': ln['description'], 'quantity': ln['quantity'], 'unit_price': ln['unit_price'],
               'total': tc._line_total(ln), 'source': ln['source'], 'is_taxable': ln.get('is_taxable', True)}
        if show:
            row['unit_cost'] = ln.get('unit_cost')
        lines.append(row)
    return render(request, 'psa/ticket_charges_review.html', {
        'ticket': ticket, 'est': est, 'lines': lines,
        'can_invoice': v._org_perm(request, ticket.organization_id, 'billing_send_invoices'),
        'can_send': v._org_perm(request, ticket.organization_id, 'tickets_edit'),
    })


def _money(v):
    return None if v is None else str(v)


@login_required
@require_psa_enabled
def charges_json(request, ticket_number):
    ticket = _ticket(request, ticket_number)
    show = _show_costs(request, ticket)
    est = tc.ticket_estimate(ticket, show_costs=show)
    entries = []
    for r in est.entries:
        row = {'id': r['entry'].pk, 'minutes': r['actual_minutes'], 'classification': r['classification_code'],
               'state': r['state'], 'billed_hours': _money(r['billed_hours']), 'covered_hours': _money(r['covered_hours']),
               'charged_hours': _money(r['charged_hours']), 'rate': _money(r['rate']), 'charge': _money(r['charge']),
               'agreement': r['agreement'].name if r['agreement'] else None}
        if show:
            row['cost'] = _money(r.get('cost'))
            row['margin'] = _money(r.get('margin'))
        entries.append(row)
    items = []
    for r in est.items:
        e = r['item']
        row = {'id': e.pk, 'description': e.description, 'category': e.category, 'quantity': _money(r['quantity']),
               'unit_price': _money(r['unit_price']), 'total': _money(r['total']), 'is_credit': e.is_credit,
               'state': r['state'], 'inventory_state': e.inventory_state}
        if show:
            row['unit_cost'] = _money(r.get('unit_cost'))
            row['margin'] = _money(r.get('margin'))
        items.append(row)
    body = {'ticket': ticket.ticket_number, 'billing_status': ticket.billing_status,
            'ready_total': _money(est.ready_total), 'forecast_total': _money(est.forecast_total),
            'agreement': est.agreement.name if est.agreement else None, 'hours': {
                k: (_money(v) if not isinstance(v, bool) else v) for k, v in est.hours.items()},
            'blockers': est.blockers, 'entries': entries, 'items': items}
    if show:
        body['cost_total'] = _money(est.cost_total)
        body['margin_total'] = _money(est.margin_total)
    return JsonResponse(body)


@login_required
@require_psa_enabled
def catalog_json(request, ticket_number):
    ticket = _ticket(request, ticket_number)
    items = tc.catalog_items(ticket, request.GET.get('q') or '', limit=50)
    return JsonResponse({'results': tc.catalog_payload(ticket, items, show_costs=_show_costs(request, ticket))})
