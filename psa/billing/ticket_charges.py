"""Phase 101.5-101.7: Time & Charges, Add Item and the billing summary of a
ticket.

Nothing here prices anything on its own. The estimate shown on the ticket is
built from `invoicing.ticket_billing_lines` - the same lines "Invoice this
ticket" turns into a draft invoice - so the ticket shows exactly what the
invoice will bill. Time under prepaid hours that is not approved yet is not
on those lines (the ledger only bills approved time); for it the ticket shows
a forecast from the ledger's own planner and the same overage terms, marked
as a forecast.

Items ("Add Item") are psa.TicketExpense rows with a unit price (see the
model). Stock is reserved when an inventory item is added, deducted once
when it is marked used (an atomic state change guards the deduction, so a
double click or retry deducts nothing more), released when the line is
removed, and put back when a used line is removed.

Billing status (Ticket.billing_status): "Send to Billing" marks the ticket
ready for invoicing review; closing a ticket with unbilled work flags it for
review. Neither creates or sends an invoice.

Permissions (per customer, MSP staff only):

* cost and margin: `pricing_view_internal_cost_rates` (left out of the data,
  not hidden in the template);
* agreement choice and credit lines: `billing_manage_charges`;
* a catalog price below the item minimum: `pricing_approve_discounts`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import coverage, invoicing, ledger

ZERO = Decimal('0')
CENT = Decimal('0.01')

VIEW_COSTS = 'pricing_view_internal_cost_rates'
CHOOSE_AGREEMENT = ledger.ADJUST_PERMISSION      # billing_manage_charges
ADD_CREDIT = 'billing_manage_charges'
APPROVE_DISCOUNT = 'pricing_approve_discounts'

WORK_TYPES = [
    ('standard', 'Standard'),
    ('remote', 'Remote'),
    ('onsite', 'Onsite'),
    ('travel', 'Travel'),
]
# What the technician can pick on the time forms; '' keeps the old default.
CLASSIFICATION_FORM_CHOICES = [
    ('billable', 'Billable'),
    ('covered', 'Covered by agreement'),
    ('non_billable', 'Non-billable'),
    ('warranty', 'Warranty'),
    ('goodwill', 'Goodwill'),
    ('awaiting', 'Awaiting classification'),
]
CLASSIFICATION_CODES = {c for c, _ in CLASSIFICATION_FORM_CHOICES}

STATE_LABELS = {
    'running': 'Timer running',
    'invoiced': 'On an invoice',
    'ready': 'Ready to invoice',
    'forecast': 'Forecast (bills when the timesheet is approved)',
    'needs_choice': 'Needs an agreement choice',
    'needs_classification': 'Needs classification',
    'no_rate': 'No labor rate',
    'no_charge': 'No charge',
    'unused_stock': 'Reserved - mark used to bill',
    'not_billable': 'Not billable',
    'held': 'On hold at billing',
    'excluded': 'Excluded from billing',
    '': '',
}


def _q2(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


# --- permissions --------------------------------------------------------------

def _is_staff(user):
    from psa.visibility import is_msp_staff
    return bool(user and (user.is_superuser or is_msp_staff(user)))


def _perm(user, org, perm):
    from accounts.permission_utils import has_perm_for_org
    return _is_staff(user) and has_perm_for_org(user, getattr(org, 'pk', org), perm)


def can_view_costs(user, org):
    return _perm(user, org, VIEW_COSTS)


def can_choose_agreement(user, org):
    return _perm(user, org, CHOOSE_AGREEMENT)


def can_add_credit(user, org):
    return _perm(user, org, ADD_CREDIT)


def can_approve_discount(user, org):
    return _perm(user, org, APPROVE_DISCOUNT)


# --- the estimate -------------------------------------------------------------

def _live_invoice_by_source(source, ids):
    from psa.models import InvoiceLineItem
    out = {}
    if not ids:
        return out
    for li in (InvoiceLineItem.objects.filter(source=source, source_id__in=[str(i) for i in ids])
               .exclude(invoice__status='void').exclude(invoice__is_credit_memo=True)
               .select_related('invoice')):
        try:
            out.setdefault(int(li.source_id), li.invoice)
        except (TypeError, ValueError):
            continue
    return out


def _line_total(ln):
    return _q2(Decimal(str(ln['quantity'])) * Decimal(str(ln['unit_price'])))


def forecast(ticket, pending, *, include_before_cutoff=False, cut=None):
    """Prepaid time not approved yet: what approval would consume and what
    would be billed as overage, in work order, using the ledger planner and
    `invoicing.overage_terms`. {entry_pk: {...}}. Read-only."""
    out = {}
    client = ticket.organization
    state = {}
    cut = cut if cut is not None else invoicing.cutoff()
    for te in sorted(pending, key=lambda e: (e.started_at, e.pk)):
        res = coverage.resolve(te, plan=False)
        c = res.agreement
        if c is None or res.treatment != 'prepaid':
            continue
        st = state.setdefault(c.pk, {'balances': dict(ledger.block_balances(c)), 'virtual': {}})
        allocs, over, _neg = ledger.plan(c, res.on_date, res.minutes, exclude_entry=te, balances=st['balances'])
        for block, m in allocs:
            if block is None:
                # A cycle (or window) block not opened yet: the planner offers
                # the full allowance each time, so count what earlier entries
                # of this ticket already took from it.
                key = ledger.cycle_bounds(c, res.on_date) or 'window'
                used = st['virtual'].get(key, 0)
                take = min(m, max(0, ledger.minutes_of(c.total_hours or ZERO) - used))
                over += m - take
                st['virtual'][key] = used + take
            else:
                st['balances'][block.pk] = st['balances'].get(block.pk, ZERO) - coverage.hours(m)
        pre = invoicing.before_cutoff(te, cut) and not include_before_cutoff
        rate, rule, billed = invoicing.overage_terms(c, client, res.on_date, over, pre=pre) if over else (
            Decimal(str(c.overage_rate or c.hourly_rate or 0)), None, 0)
        qty = invoicing._hours2(billed)
        out[te.pk] = {
            'agreement': c, 'prepaid_minutes': res.minutes - over, 'overage_minutes': over,
            'billed_minutes': billed, 'rate': rate, 'amount': _q2(qty * rate) if billed else ZERO,
            'covered_hours': invoicing._hours2(res.minutes - over), 'charged_hours': qty,
        }
    return out


@dataclass
class TicketEstimate:
    lines: list
    info: dict
    entries: list = field(default_factory=list)
    items: list = field(default_factory=list)
    fees: list = field(default_factory=list)
    ready_total: Decimal = ZERO          # what "Invoice this ticket" bills now (before tax)
    labor_total: Decimal = ZERO
    items_total: Decimal = ZERO
    fees_total: Decimal = ZERO
    forecast_total: Decimal = ZERO       # pending approval, forecast
    actual_minutes: int = 0
    billable_minutes: int = 0
    agreement: object = None
    hours: dict = field(default_factory=dict)
    blockers: list = field(default_factory=list)
    show_costs: bool = False
    cost_total: Decimal | None = None
    margin_total: Decimal | None = None

    @property
    def unbilled_total(self):
        return self.ready_total + self.forecast_total

    @property
    def has_unbilled(self):
        return bool(self.lines or self.blockers or self.forecast_total)


def ticket_estimate(ticket, *, show_costs=False, include_before_cutoff=False):
    from psa.models import Contract
    lines, info = invoicing.ticket_billing_lines(ticket, include_before_cutoff=include_before_cutoff)
    est = TicketEstimate(lines=lines, info=info, show_costs=show_costs)
    by_src = defaultdict(list)
    for ln in lines:
        by_src[(ln['source'], str(ln['source_id']))].append(ln)

    entries = list(ticket.time_entries.select_related('user', 'billing_contract', 'contract')
                   .order_by('started_at', 'pk'))
    on_invoice = _live_invoice_by_source('time', [e.pk for e in entries])
    sets = {k: {e.pk for e in info.get(k, [])}
            for k in ('awaiting_approval', 'needs_choice', 'needs_classification', 'before_cutoff')}
    no_rate = {e.pk: why for e, why in info.get('no_rate', [])}
    # Phase 102.3: held / excluded at the Ready for Billing queue.
    withheld = {}
    for kind in ('held', 'excluded'):
        for ln, d in info.get(kind, []):
            withheld[(ln['source'], str(ln['source_id']))] = (kind, d)
    fc = forecast(ticket, info.get('awaiting_approval', []), include_before_cutoff=include_before_cutoff,
                  cut=info.get('cutoff'))
    cost_total = ZERO
    revenue_for_margin = ZERO
    for te in entries:
        est.actual_minutes += te.duration_minutes or 0
        if te.is_billable:
            est.billable_minutes += te.duration_minutes or 0
        row = {
            'entry': te, 'actual_minutes': te.duration_minutes or 0,
            'classification': (te.get_classification_display() if te.classification
                               else ('Billable' if te.is_billable else 'Non-billable')),
            'classification_code': te.classification or ('billable' if te.is_billable else 'non_billable'),
            'work_type': te.get_rate_type_display() if te.rate_type else '',
            'agreement': te.billing_contract, 'billed_hours': None, 'covered_hours': ZERO,
            'charged_hours': ZERO, 'rate': None, 'charge': ZERO, 'state': '', 'note': '', 'invoice': None,
        }
        mine = by_src.get(('time', str(te.pk)), [])
        if te.ended_at is None:
            row['state'] = 'running'
        elif te.pk in on_invoice:
            row['state'] = 'invoiced'
            row['invoice'] = on_invoice[te.pk]
        elif mine:
            row['state'] = 'ready'
            for ln in mine:
                q = Decimal(str(ln['quantity']))
                price = Decimal(str(ln['unit_price']))
                if price == 0:
                    row['covered_hours'] += q
                else:
                    row['charged_hours'] += q
                    row['rate'] = price
                row['charge'] += _line_total(ln)
            row['billed_hours'] = row['covered_hours'] + row['charged_hours']
            row['note'] = mine[0]['description']
        elif ('time', str(te.pk)) in withheld:
            kind, d = withheld[('time', str(te.pk))]
            row['state'] = kind
            row['note'] = d.reason
        elif te.pk in fc:
            f = fc[te.pk]
            row.update(state='forecast', agreement=f['agreement'], covered_hours=f['covered_hours'],
                       charged_hours=f['charged_hours'], charge=f['amount'],
                       rate=f['rate'] if f['overage_minutes'] else None,
                       billed_hours=f['covered_hours'] + f['charged_hours'])
            est.forecast_total += f['amount']
        elif te.pk in sets['needs_choice']:
            row['state'] = 'needs_choice'
        elif te.pk in sets['needs_classification']:
            row['state'] = 'needs_classification'
            row['note'] = coverage.resolve(te, plan=False).reason
        elif te.pk in no_rate:
            row['state'] = 'no_rate'
            row['note'] = no_rate[te.pk]
        elif not te.is_billable:
            row['state'] = 'no_charge'
        if row['state'] in ('ready',):
            est.labor_total += row['charge']
        if show_costs and te.cost_rate_snapshot is not None and te.duration_minutes:
            row['cost'] = _q2(coverage.hours(te.duration_minutes) * te.cost_rate_snapshot)
            cost_total += row['cost']
            revenue_for_margin += row['charge']
            row['margin'] = row['charge'] - row['cost']
        row['state_label'] = STATE_LABELS.get(row['state'], '')
        est.entries.append(row)

    expenses = list(ticket.expenses.select_related('user', 'inventory_item', 'price_book_item')
                    .order_by('incurred_on', 'pk'))
    item_inv = _live_invoice_by_source('expense', [e.pk for e in expenses])
    unused = {e.pk for e in info.get('unused_stock', [])}
    for e in expenses:
        mine = by_src.get(('expense', str(e.pk)), [])
        row = {'item': e, 'quantity': e.quantity if e.is_item else Decimal('1'),
               'unit_price': e.unit_price if e.is_item else e.amount, 'total': e.signed_total,
               'state': '', 'invoice': None}
        if e.pk in item_inv:
            row['state'] = 'invoiced'
            row['invoice'] = item_inv[e.pk]
        elif mine:
            row['state'] = 'ready'
            row['total'] = sum((_line_total(ln) for ln in mine), ZERO)
            est.items_total += row['total']
        elif ('expense', str(e.pk)) in withheld:
            kind, d = withheld[('expense', str(e.pk))]
            row['state'] = kind
        elif e.pk in unused:
            row['state'] = 'unused_stock'
        elif not e.is_billable:
            row['state'] = 'not_billable'
        if show_costs and e.is_item and e.unit_cost is not None:
            row['unit_cost'] = e.unit_cost
            row['cost'] = _q2(e.unit_cost * e.quantity)
            if not e.is_credit:
                cost_total += row['cost']
                revenue_for_margin += row['total']
                row['margin'] = row['total'] - row['cost']
                row['margin_pct'] = (row['margin'] / row['total'] * 100).quantize(Decimal('0.1')) \
                    if row['total'] else None
        row['state_label'] = STATE_LABELS.get(row['state'], '')
        est.items.append(row)

    for ln in lines:
        if ln['source'] == 'fee':
            est.fees.append({'description': ln['description'], 'total': _line_total(ln)})
            est.fees_total += _line_total(ln)

    est.ready_total = invoicing.lines_total(lines)
    if show_costs:
        est.cost_total = cost_total
        est.margin_total = revenue_for_margin - cost_total

    # Agreement and hours before / after approval.
    c = invoicing.single_agreement(info)
    if c is None:
        ids = {f['agreement'].pk for f in fc.values()}
        c = Contract.objects.filter(pk=next(iter(ids))).first() if len(ids) == 1 else Contract.for_ticket(ticket)
    est.agreement = c
    if c is not None:
        if coverage.has_allowance(c):
            s = ledger.summary(c)
            pending = sum((Decimal(f['prepaid_minutes']) for f in fc.values() if f['agreement'].pk == c.pk), ZERO)
            pending_h = (pending / 60).quantize(CENT, rounding=ROUND_HALF_UP)
            est.hours = {'prepaid': True, 'remaining_now': s.remaining_hours, 'pending': pending_h,
                         'remaining_after': (s.remaining_hours - pending_h), 'low': s.low}
        else:
            est.hours = {'prepaid': False, 'unlimited': c.contract_type in Contract.FLAT_FEE_TYPES}

    est.blockers = blockers(ticket, info)
    return est


def blockers(ticket, info):
    """What stops this ticket being billed cleanly, as sentences."""
    out = []

    def n(key):
        return len(info.get(key) or [])

    if ticket.time_entries.filter(ended_at__isnull=True).exists():
        out.append('A timer is still running.')
    if n('awaiting_approval'):
        out.append(f'{n("awaiting_approval")} time entr{"y waits" if n("awaiting_approval") == 1 else "ies wait"} '
                   f'for timesheet approval before prepaid hours are used.')
    if n('needs_choice'):
        out.append(f'{n("needs_choice")} time entr{"y needs" if n("needs_choice") == 1 else "ies need"} '
                   f'an agreement choice.')
    if n('needs_classification'):
        out.append(f'{n("needs_classification")} time entr{"y needs" if n("needs_classification") == 1 else "ies need"} '
                   f'classification before invoicing.')
    if n('no_rate'):
        out.append(f'{n("no_rate")} time entr{"y has" if n("no_rate") == 1 else "ies have"} no labor rate.')
    if n('unused_stock'):
        out.append(f'{n("unused_stock")} reserved stock item{"" if n("unused_stock") == 1 else "s"} not marked used.')
    return out


# --- time entries -------------------------------------------------------------

class ChargeError(ValueError):
    """A change refused with a reason to show the person."""


def entry_on_invoice(entry):
    return bool(_live_invoice_by_source('time', [entry.pk]))


def entry_locked(entry):
    from psa.models import TimesheetSubmission
    return bool(entry.submission_id and TimesheetSubmission.objects.filter(
        pk=entry.submission_id, status='approved').exists())


def agreement_choices(entry):
    """Agreements valid for the entry's customer, date and role code."""
    return coverage.candidate_agreements(entry.ticket.organization_id, coverage.work_date(entry), entry.role_code)


def agreements_for_ticket(ticket, on_date=None, role_code=''):
    return coverage.candidate_agreements(ticket.organization_id, on_date or timezone.localdate(), role_code)


def update_entry(entry, *, actor, classification=None, work_type=None, notes=None, minutes=None):
    """Change an unapproved, uninvoiced entry. Approved time goes through
    the correction on its history page (ledger re-allocation), invoiced time
    through a credit memo or void first. Returns the changed field names."""
    if entry_on_invoice(entry):
        raise ChargeError('This time is on an invoice. Void or credit the invoice before changing it.')
    if entry_locked(entry):
        raise ChargeError('This time is on an approved timesheet. Use "Correct approved entry" on its '
                          'history page; the prepaid hours are re-allocated there.')
    changed = []
    if classification is not None and classification != entry.classification:
        if classification not in CLASSIFICATION_CODES:
            raise ChargeError('Pick a classification.')
        entry.classification = classification
        changed.append('classification')
    if work_type is not None and work_type != (entry.rate_type or 'standard'):
        if work_type not in dict(WORK_TYPES):
            raise ChargeError('Pick a work type.')
        entry.rate_type = work_type
        # Not approved, not billed: take the rate snapshot again for the new type.
        entry.bill_rate_snapshot = None
        entry.rate_card_line = None
        entry.included_vs_overage = ''
        try:
            from pricing.services import snapshot_time_entry
            snapshot_time_entry(entry)
        except Exception:  # pragma: no cover - pricing never blocks time
            entry.rate_missing = bool(entry.is_billable)
        changed.append('work type')
    if notes is not None and notes != entry.notes:
        entry.notes = notes[:2000]
        changed.append('notes')
    if minutes is not None and entry.ended_at is not None and minutes != entry.duration_minutes:
        if minutes <= 0 or minutes > 24 * 60:
            raise ChargeError('Minutes must be between 1 and 1440.')
        entry.duration_minutes = minutes
        entry.ended_at = entry.started_at + timezone.timedelta(minutes=minutes)
        changed.append('minutes')
    if changed:
        entry.save(_audit_user=actor)
    return changed


# --- items ----------------------------------------------------------------------

def _dec(raw, name, *, allow_blank=False):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if allow_blank:
            return None
        raise ChargeError(f'Enter the {name}.')
    try:
        v = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ChargeError(f'The {name} must be a number.')
    if not v.is_finite():
        raise ChargeError(f'The {name} must be a number.')
    return v


def reserved_quantity(inventory_item, exclude=None):
    from psa.models import TicketExpense
    qs = TicketExpense.objects.filter(inventory_item=inventory_item, inventory_state='reserved')
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.aggregate(t=Sum('quantity'))['t'] or ZERO


def available_quantity(inventory_item):
    return Decimal(inventory_item.quantity or 0) - reserved_quantity(inventory_item)


def catalog_items(ticket, q='', limit=200):
    """Active, in-effect price book items this customer can be sold."""
    from django.db.models import Q
    from pricing.models import PriceBookItem
    today = timezone.localdate()
    qs = (PriceBookItem.objects.filter(is_active=True, price_book__is_active=True)
          .filter(Q(price_book__organization__isnull=True) | Q(price_book__organization=ticket.organization_id))
          .filter(Q(effective_from__isnull=True) | Q(effective_from__lte=today))
          .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today))
          .exclude(is_recurring=True)
          .select_related('price_book').order_by('category', 'name'))
    q = (q or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(category__icontains=q))
    return list(qs[:limit])


def catalog_payload(ticket, items, *, show_costs):
    """JSON-safe catalog rows; cost only with the permission."""
    from pricing.services import resolve_price
    out = []
    for it in items:
        res = resolve_price(it, client=ticket.organization, on_date=timezone.localdate())
        row = {'id': it.pk, 'sku': it.sku, 'name': it.name, 'category': it.category,
               'unit': it.unit_of_measure, 'price': None if res.missing else str(_q2(res.unit_price)),
               'currency': res.currency, 'missing_reason': res.reason if res.missing else ''}
        if show_costs:
            row['cost'] = None if res.unit_cost is None else str(res.unit_cost)
        out.append(row)
    return out


def add_item(ticket, actor, *, category, description='', quantity='1', unit_price=None, unit_cost=None,
             price_book_item=None, inventory_item=None, serial_number='', is_billable=True, is_taxable=True,
             incurred_on=None):
    """Add an item, one-off line or credit to a ticket. Returns (row, warnings).

    `price_book_item` / `inventory_item` must already be scoped by the caller
    (the customer's catalog, the customer's stock)."""
    from psa.models import TicketExpense
    org = ticket.organization
    if category not in dict(TicketExpense.CATEGORY_CHOICES):
        raise ChargeError('Pick what kind of item this is.')
    is_credit = category == 'credit'
    if is_credit and not can_add_credit(actor, org):
        raise PermissionDenied(f"Your role does not include '{ADD_CREDIT}' for this customer (credits).")
    if is_credit and inventory_item is not None:
        raise ChargeError('A credit cannot take stock.')
    qty = _dec(quantity, 'quantity')
    if qty <= 0:
        raise ChargeError('The quantity must be more than zero.')
    if inventory_item is not None and qty != qty.to_integral_value():
        raise ChargeError('Stock is counted in whole units.')
    price = _dec(unit_price, 'unit price', allow_blank=True)
    if price is not None and price < 0:
        raise ChargeError('Enter the price as a positive number (pick "Credit" to credit the customer).')
    costs_ok = can_view_costs(actor, org)
    cost = _dec(unit_cost, 'unit cost', allow_blank=True) if costs_ok else None
    if cost is not None and cost < 0:
        raise ChargeError('The unit cost must not be negative.')
    warnings = []
    source = 'one-off'
    sku = ''
    currency = 'USD'
    if price_book_item is not None:
        from pricing.services import resolve_price
        res = resolve_price(price_book_item, client=org, on_date=timezone.localdate(), qty=qty)
        sku = price_book_item.sku
        currency = res.currency or currency
        description = description or price_book_item.name
        if cost is None:
            cost = res.unit_cost
        if price is None:
            if res.missing:
                raise ChargeError(f'{price_book_item.sku}: {res.reason} Enter a price.')
            price = _q2(res.unit_price)
            source = f'pricing:{res.source}'
        else:
            source = 'pricing:entered'
            if res.minimum_price is not None and price < res.minimum_price and not can_approve_discount(actor, org):
                raise ChargeError(f'{price} is below the minimum price {res.minimum_price} of {sku}; that needs '
                                  f"'{APPROVE_DISCOUNT}'.")
        warnings.extend(res.warnings)
    if inventory_item is not None:
        description = description or inventory_item.name
        sku = sku or inventory_item.sku
        if cost is None and inventory_item.unit_cost is not None:
            cost = inventory_item.unit_cost
        short = qty - available_quantity(inventory_item)
        if short > 0:
            warnings.append(f'Only {available_quantity(inventory_item):.0f} of {inventory_item.name} available; '
                            f'reserved anyway, {short:.0f} short.')
    description = (description or '').strip()
    if not description:
        raise ChargeError('Describe the item.')
    if price is None:
        raise ChargeError('Enter a unit price.')
    total = _q2(qty * price)
    row = TicketExpense.objects.create(
        ticket=ticket, user=actor, category=category, description=description[:300], amount=total,
        currency=currency[:8], incurred_on=incurred_on or timezone.localdate(),
        is_billable=bool(is_billable) or is_credit, is_reimbursable=False, price_book_item=price_book_item,
        sku=sku[:80], quantity=qty, unit_price=price, unit_cost=cost, price_source=source[:40],
        is_credit=is_credit, is_taxable=bool(is_taxable), serial_number=(serial_number or '')[:120],
        inventory_item=inventory_item)
    if inventory_item is not None:
        reserve(row, actor)
    _audit(actor, ticket, row, 'create',
           f'Added {"credit" if is_credit else "item"} "{row.description}" ({qty} x {price}) to '
           f'{ticket.ticket_number}' + (' and reserved stock' if inventory_item is not None else ''))
    return row, warnings


def _ref(row):
    return f'ticket-item:{row.pk} ({row.ticket.ticket_number})'


def _log_stock(inv, kind, change, actor, row, note):
    from inventory.models import InventoryTransaction
    InventoryTransaction.objects.create(item=inv, transaction_type=kind, quantity_change=change,
                                        quantity_after=inv.quantity, performed_by=actor,
                                        reference=_ref(row)[:255], notes=note)


def reserve(row, actor):
    """'' -> reserved. Does not change stock on hand. True when it happened."""
    from inventory.models import InventoryItem
    from psa.models import TicketExpense
    if row.inventory_item_id is None:
        return False
    with transaction.atomic():
        n = TicketExpense.objects.filter(pk=row.pk, inventory_state='').update(
            inventory_state='reserved', inventory_reserved_at=timezone.now())
        if not n:
            return False
        inv = InventoryItem.objects.select_for_update().get(pk=row.inventory_item_id)
        _log_stock(inv, 'reserve', 0, actor, row, f'Reserved {row.quantity:.0f} for {row.ticket.ticket_number}')
    row.refresh_from_db(fields=['inventory_state', 'inventory_reserved_at'])
    return True


def consume(row, actor):
    """reserved -> consumed: deduct the stock, once. A second call (double
    click, retry, racing worker) finds the state already moved and deducts
    nothing. True when this call deducted."""
    from inventory.models import InventoryItem
    from psa.models import TicketExpense
    if row.inventory_item_id is None:
        return False
    qty = int(row.quantity)
    with transaction.atomic():
        n = TicketExpense.objects.filter(pk=row.pk, inventory_state='reserved').update(
            inventory_state='consumed', inventory_consumed_at=timezone.now())
        if not n:
            return False
        InventoryItem.objects.filter(pk=row.inventory_item_id).update(quantity=F('quantity') - qty)
        inv = InventoryItem.objects.select_for_update().get(pk=row.inventory_item_id)
        _log_stock(inv, 'stock_out', -qty, actor, row, f'Used on {row.ticket.ticket_number}')
    row.refresh_from_db(fields=['inventory_state', 'inventory_consumed_at'])
    _audit(actor, row.ticket, row, 'update', f'Marked {qty} x {row.description} used on {row.ticket.ticket_number}')
    return True


def release(row, actor):
    """reserved -> released (nothing to put back); consumed -> returned (the
    stock goes back, once). Returns the new state or ''."""
    from inventory.models import InventoryItem
    from psa.models import TicketExpense
    if row.inventory_item_id is None:
        return ''
    qty = int(row.quantity)
    with transaction.atomic():
        if TicketExpense.objects.filter(pk=row.pk, inventory_state='reserved').update(inventory_state='released'):
            inv = InventoryItem.objects.select_for_update().get(pk=row.inventory_item_id)
            _log_stock(inv, 'release', 0, actor, row, f'Reservation released ({row.ticket.ticket_number})')
            return 'released'
        if TicketExpense.objects.filter(pk=row.pk, inventory_state='consumed').update(inventory_state='returned'):
            InventoryItem.objects.filter(pk=row.inventory_item_id).update(quantity=F('quantity') + qty)
            inv = InventoryItem.objects.select_for_update().get(pk=row.inventory_item_id)
            _log_stock(inv, 'stock_in', qty, actor, row, f'Returned from {row.ticket.ticket_number}')
            return 'returned'
    return ''


def remove_item(row, actor):
    """Remove an item that is not on a live invoice; its stock reservation is
    released (used stock goes back)."""
    if _live_invoice_by_source('expense', [row.pk]):
        raise ChargeError('This line is on an invoice. Void or credit the invoice instead of removing it.')
    if row.is_credit and not can_add_credit(actor, row.ticket.organization):
        raise PermissionDenied(f"Your role does not include '{ADD_CREDIT}' for this customer (credits).")
    ticket = row.ticket
    with transaction.atomic():
        state = release(row, actor)
        desc = row.description
        _audit(actor, ticket, row, 'delete', f'Removed "{desc}" from {ticket.ticket_number}'
               + (f' (stock {state})' if state else ''))
        row.delete()
    return state


def _audit(actor, ticket, row, action, description):
    try:
        from audit.models import AuditLog
        AuditLog.log(user=actor, action=action, organization=ticket.organization,
                     object_type='psa.TicketExpense', object_id=row.pk, object_repr=row.description[:200],
                     description=description[:500])
    except Exception:  # pragma: no cover - the audit log never blocks billing work
        import logging
        logging.getLogger('psa.billing').exception('audit log for ticket item failed')


# --- billing status -------------------------------------------------------------

def _set_status(ticket, status, note, actor=None):
    from psa.models import Ticket
    now = timezone.now()
    Ticket.objects.filter(pk=ticket.pk).update(billing_status=status, billing_status_note=note[:500],
                                               billing_status_at=now, billing_status_by=actor)
    ticket.billing_status, ticket.billing_status_note = status, note[:500]
    ticket.billing_status_at, ticket.billing_status_by = now, actor


def send_to_billing(ticket, actor, note=''):
    """Mark the ticket ready for invoicing review. Creates no invoice.
    Anything still to sort out makes it "needs billing review" instead.
    Returns (status, blockers)."""
    est_lines, info = invoicing.ticket_billing_lines(ticket)
    problems = blockers(ticket, info)
    status = 'review' if problems else 'ready'
    text = ' '.join(([note.strip()] if note and note.strip() else []) + problems)
    _set_status(ticket, status, text or 'Sent to billing.', actor)
    try:
        from audit.models import AuditLog
        AuditLog.log(user=actor, action='update', organization=ticket.organization, object_type='psa.Ticket',
                     object_id=ticket.pk, object_repr=ticket.ticket_number,
                     description=f'Sent {ticket.ticket_number} to billing ({status})'[:500],
                     extra_data={'billing_status': status, 'lines': len(est_lines)})
    except Exception:  # pragma: no cover
        pass
    return status, problems


def unbilled(ticket):
    """(has unbilled work, blockers). Work on hold at the Ready for Billing
    queue is still unbilled; excluded work is not."""
    lines, info = invoicing.ticket_billing_lines(ticket)
    problems = blockers(ticket, info)
    return bool(lines or problems or info.get('held')), problems


def flag_on_close(ticket):
    """Closing never hides unbilled work: flag it for billing review."""
    if ticket.billing_status in ('ready', 'review'):
        return False
    has, problems = unbilled(ticket)
    if not has:
        return False
    _set_status(ticket, 'review', ' '.join(['Closed with unbilled work.'] + problems))
    return True


def after_invoice(ticket):
    """After "Invoice this ticket": invoiced when nothing is left, else review."""
    has, problems = unbilled(ticket)
    if not has:
        _set_status(ticket, 'invoiced', 'Everything billable is on an invoice.')
    elif ticket.billing_status:
        _set_status(ticket, 'review', ' '.join(['Partly invoiced.'] + problems))


def billing_queue(user):
    """Tickets sent to billing or flagged for review that `user` may see
    (billing_view_invoices per customer)."""
    from accounts.permission_utils import orgs_with_perm
    from psa.models import Ticket
    if not _is_staff(user):
        return Ticket.objects.none()
    qs = Ticket.objects.filter(billing_status__in=('ready', 'review')).select_related('organization')
    allowed = orgs_with_perm(user, 'billing_view_invoices')
    if allowed is not None:
        qs = qs.filter(organization_id__in=allowed)
    return qs.order_by('billing_status', '-billing_status_at')
