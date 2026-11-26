"""Phase 101.4: what a ticket invoice bills, from the ledger, rate cards and
billing rules.

`ticket_billing_lines(ticket)` returns `(lines, info)`: InvoiceLineItem field
dicts for the ticket's billable work not yet on a live invoice (not void,
not a credit memo), and a summary for the person invoicing. It only reads; a
draft invoice is created by the explicit "Invoice ticket" action
(psa.views.invoice_from_ticket) and nothing re-prices an existing invoice.

Per time entry (billable, stopped, positive duration):

* **Prepaid agreement.** The ledger decides. Only time the ledger holds is
  billed: approved time (101.3) and time counted in the opening balance on
  upgrade. The consumed hours go on as a zero-priced "covered" line, the
  ledger's overage hours at the agreement's overage rate (or hourly rate),
  rounded up to the billing rule's increment. Time not approved yet is left
  off and reported (`info['awaiting_approval']`), as is approved time waiting
  for an agreement choice (`info['needs_choice']`).
* **Flat-fee agreement without an allowance** (managed services, retainer):
  zero-priced covered line, as before.
* **Chargeable** (another agreement, or none: time and materials): priced
  per entry. Rate precedence: a customer or contract rate-card line in the
  entry's rate snapshot > the agreement's hourly rate > the snapshot's
  MSP-wide or role-default rate > the rate cards resolved now. No rate at
  all: the entry is left off and reported (`info['no_rate']`), never billed
  at $0. The billing rule (pricing.BillingRule, most specific for customer
  and agreement on the work date) applies its minimum and increment to each
  chargeable entry. Each day with chargeable onsite work (rate type
  "onsite") gets the rule's dispatch and travel fees once per ticket
  (source 'fee', so a fee is never billed twice).
* **Before the upgrade cutoff** (psa.BillingEngineSettings.
  ticket_pricing_from): chargeable time worked before it is billed exactly as
  before 101.4 (agreement hourly rate, or $0 without an agreement; no rules,
  no fees) unless `include_before_cutoff=True`, which someone invoicing
  chooses on purpose. Prepaid time follows the ledger either way.

Holiday rate type: new time entries worked on a resourcing.Holiday date are
rated with the rate card's holiday line when one exists
(pricing.services.snapshot_time_entry). After-hours and weekend rate types are
not set automatically: there is no business-hours calendar yet (Phase 93).

Classification (Phase 101.5): non-billable, warranty and goodwill time is
not billable; time awaiting classification (or classified "covered" with no
agreement covering it) is left off and reported (`info['needs_classification']`).

Expenses are billed as before. "Add Item" rows (Phase 101.6: a TicketExpense
with a unit price) bill quantity x unit price with the catalog item, cost
snapshot and taxability; a credit bills negative; stock only reserved for the
ticket is left off until it is marked used (`info['unused_stock']`).
"""
from __future__ import annotations

import contextlib
import contextvars
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from . import coverage, ledger

ZERO = Decimal('0')
CUSTOMER_SCOPES = ('customer_contract', 'customer', 'contract')


def _hours2(minutes):
    return (Decimal(int(minutes)) / Decimal(60)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# A read-only pass over many tickets (`ticket_billing_lines_many`): the rows
# each ticket would read are read once for all of them. Only reads are
# shared; every price, rule and rounding is computed per entry exactly as for
# one ticket.
_batch = contextvars.ContextVar('psa_invoicing_batch', default=None)


def cutoff():
    from psa.models import BillingEngineSettings
    b = _batch.get()
    if b is not None:
        if 'cutoff' not in b:
            b['cutoff'] = BillingEngineSettings.get().ticket_pricing_from
        return b['cutoff']
    return BillingEngineSettings.get().ticket_pricing_from


def before_cutoff(entry, cut=None):
    cut = cut if cut is not None else cutoff()
    return bool(cut and entry.started_at and entry.started_at < cut)


def billing_rule(client, contract, on_date):
    b = _batch.get()
    if b is not None:
        key = (getattr(client, 'pk', client), getattr(contract, 'pk', contract), on_date)
        rules = b.setdefault('rules', {})
        if key not in rules:
            book = b.get('rulebook')
            if book is not None and book.covers(key[0]):
                try:
                    rules[key] = book.resolve(client=client, contract=contract, on_date=on_date)
                except Exception:  # pragma: no cover - as _billing_rule
                    rules[key] = None
            else:
                rules[key] = _billing_rule(client, contract, on_date)
        return rules[key]
    return _billing_rule(client, contract, on_date)


def _billing_rule(client, contract, on_date):
    try:
        from pricing.services import resolve_billing_rule
        return resolve_billing_rule(client=client, contract=contract, on_date=on_date)
    except Exception:  # pragma: no cover - pricing misconfiguration never blocks invoicing
        return None


def round_minutes(rule, minutes, *, minimum=True):
    """Billing-rule minimum (optional) and increment rounding."""
    m = int(minutes or 0)
    if rule is None or m <= 0:
        return m
    if minimum:
        return rule.billable_minutes(m)
    inc = max(rule.increment_minutes or 1, 1)
    if inc > 1 and rule.rounding_mode != 'none':
        q, r = divmod(m, inc)
        if r and (rule.rounding_mode == 'up' or (rule.rounding_mode == 'nearest' and r * 2 >= inc)):
            q += 1
        m = q * inc
    return m


def labor_rate(entry, agreement):
    """(rate, source) for chargeable time, or (None, reason)."""
    line = entry.rate_card_line
    scope = getattr(getattr(line, 'rate_card', None), 'scope', '') if line is not None else ''
    if entry.bill_rate_snapshot is not None and scope in CUSTOMER_SCOPES:
        return Decimal(entry.bill_rate_snapshot), f'{scope.replace("_", " ")} rate card'
    if agreement is not None and (agreement.hourly_rate or ZERO) > 0:
        return Decimal(agreement.hourly_rate), 'agreement hourly rate'
    if entry.bill_rate_snapshot is not None:
        return Decimal(entry.bill_rate_snapshot), 'rate card' if scope else 'role default rate'
    try:
        from pricing.services import resolve_labor_rate
        res = resolve_labor_rate(technician=entry.user, client=entry.ticket.organization, contract=agreement,
                                 role=entry.labor_role, rate_type=entry.rate_type or 'standard',
                                 on_date=coverage.work_date(entry))
    except Exception:  # pragma: no cover
        return None, 'rate lookup failed'
    if res.missing or res.rate is None:
        return None, res.reason or 'no rate'
    return Decimal(res.rate), 'rate card (resolved at invoicing)'


def _work(entry):
    return (entry.notes or 'work').strip() or 'work'


def _fee_billed(key):
    from .billed import live_lines
    return live_lines('fee').filter(source_id=key).exists()


def ticket_billing_lines(ticket, *, include_before_cutoff=False, apply_decisions=True):
    """Lines and info (see the module docstring). With `apply_decisions`
    (the default, used by every invoice writer) lines held or excluded at the
    Ready for Billing queue (Phase 102.3) are taken off and listed in
    `info['held']` / `info['excluded']` as (line, decision)."""
    # Read-only pass: each customer's agreements for a date are read once.
    with coverage.agreements_read_once():
        lines, info = _ticket_billing_lines(ticket, include_before_cutoff=include_before_cutoff)
    info['held'], info['excluded'] = [], []
    if not apply_decisions or not lines:
        return lines, info
    from .billed import withheld
    by_source = {}
    for ln in lines:
        by_source.setdefault(ln['source'], set()).add(str(ln['source_id']))
    return _apply_withheld(lines, info, {src: withheld(src, ids) for src, ids in by_source.items()})


def _apply_withheld(lines, info, out):
    kept = []
    for ln in lines:
        d = out.get(ln['source'], {}).get(str(ln['source_id']))
        if d is None:
            kept.append(ln)
        else:
            info['excluded' if d.state == 'excluded' else 'held'].append((ln, d))
    return kept, info


def ticket_billing_lines_many(tickets):
    """{ticket pk: ticket_billing_lines(ticket)} for many tickets (the Ready
    for Billing queue), with the same lines and info as one call per ticket.
    The rows are read once for all tickets instead of once per ticket: unbilled
    time and items, ledger postings, the pricing cutoff, billing rules,
    agreements per customer and date, and held / excluded queue decisions.
    Read-only, like ticket_billing_lines."""
    from psa.models import TicketExpense, TicketTimeEntry

    from .billed import unbilled_expenses, unbilled_time, withheld
    tickets = list(tickets)
    if not tickets:
        return {}
    ids = [t.pk for t in tickets]
    entries, expenses = {i: [] for i in ids}, {i: [] for i in ids}
    # Same filters, related rows and order as _ticket_billing_lines, grouped
    # by ticket (ordering by ticket first keeps each ticket's own order).
    for te in (unbilled_time(TicketTimeEntry.objects.filter(ticket_id__in=ids))
               .select_related(*_ENTRY_RELATED).order_by('ticket_id', 'started_at', 'pk')):
        entries[te.ticket_id].append(te)
    for e in unbilled_expenses(TicketExpense.objects.filter(ticket_id__in=ids)).order_by(
            'ticket_id', 'incurred_on', 'pk'):
        expenses[e.ticket_id].append(e)
    postings = ledger.active_postings_by_entry([te.pk for rows in entries.values() for te in rows])
    raw = {}
    clients = {t.organization_id for t in tickets}
    batch = {'entries': entries, 'expenses': expenses, 'postings': postings}
    try:
        from pricing.services import BillingRuleBook
        batch['rulebook'] = BillingRuleBook(clients)
    except Exception:  # pragma: no cover - pricing misconfiguration: per-lookup reads
        pass
    token = _batch.set(batch)
    try:
        with coverage.agreements_read_once():
            coverage.preload_agreements(clients)
            for t in tickets:
                raw[t.pk] = _ticket_billing_lines(t)
    finally:
        _batch.reset(token)
    by_source = {}
    for lines, _info in raw.values():
        for ln in lines:
            by_source.setdefault(ln['source'], set()).add(str(ln['source_id']))
    out = {src: withheld(src, sids) for src, sids in by_source.items()}
    result = {}
    for pk, (lines, info) in raw.items():
        info['held'], info['excluded'] = [], []
        result[pk] = _apply_withheld(lines, info, out) if lines else (lines, info)
    return result


_ENTRY_RELATED = ('ticket', 'ticket__organization', 'ticket__ticket_type', 'user',
                  'rate_card_line__rate_card', 'labor_role')


def _ticket_billing_lines(ticket, *, include_before_cutoff=False):
    from .billed import unbilled_expenses, unbilled_time

    b = _batch.get()
    if b is not None and ticket.pk in b['entries']:
        entries, expenses = b['entries'][ticket.pk], b['expenses'][ticket.pk]
        postings = {te.pk: b['postings'].get(te.pk, []) for te in entries}
    else:
        # Phase 102.2: the one "is it billed" rule (psa.billing.billed).
        entries = list(unbilled_time(ticket.time_entries.all())
                       .select_related(*_ENTRY_RELATED)
                       .order_by('started_at', 'pk'))
        expenses = list(unbilled_expenses(ticket.expenses.all()).order_by('incurred_on', 'pk'))
        postings = ledger.active_postings_by_entry([te.pk for te in entries])

    cut = cutoff()
    client = ticket.organization
    lines = []
    info = {
        'covered_minutes': 0, 'overage_minutes': 0, 'chargeable_minutes': 0, 'billed_minutes': 0,
        'rate': ZERO, 'allowance': 0, 'agreements': set(),
        'awaiting_approval': [], 'needs_choice': [], 'no_rate': [], 'before_cutoff': [],
        'needs_classification': [], 'unused_stock': [],
        'fees': ZERO, 'cutoff': cut,
    }
    visits = {}

    for te in entries:
        work = _work(te)
        on = coverage.work_date(te)
        held = postings.get(te.pk, [])
        if held:
            c = held[0].contract
            info['agreements'].add(c.pk)
            consumed = sum(ledger.minutes_of(-p.hours) for p in held if p.kind == 'consumption')
            over = sum(ledger.minutes_of(p.hours) for p in held if p.kind == 'overage')
            if consumed > 0:
                info['covered_minutes'] += consumed
                lines.append({'description': f'Time (covered by {c.name} prepaid hours): {work}'[:300],
                              'quantity': _hours2(consumed), 'unit_price': ZERO,
                              'source': 'time', 'source_id': str(te.pk)})
            if over > 0:
                pre = before_cutoff(te, cut) and not include_before_cutoff
                rate, rule, billed_over = overage_terms(c, client, on, over, pre=pre)
                info['rate'] = rate
                info['overage_minutes'] += over
                info['billed_minutes'] += billed_over
                note = '' if billed_over == over else f' ({over} min worked, billed in {rule.increment_minutes}-min steps)'
                lines.append({'description': f'Time (beyond prepaid hours): {work}{note}'[:300],
                              'quantity': _hours2(billed_over), 'unit_price': rate,
                              'source': 'time', 'source_id': str(te.pk)})
                if te.rate_type == 'onsite' and not pre:
                    visits.setdefault(on, c)
            continue

        res = coverage.resolve(te, plan=False)
        agreement = res.agreement
        if res.status == 'needs_choice':
            info['needs_choice'].append(te)
            continue
        if res.status == 'needs_classification':
            # Phase 101.5: awaiting classification (or "covered" with no
            # agreement): never billed until someone classifies it.
            info['needs_classification'].append(te)
            continue
        if res.treatment == 'prepaid':
            info['awaiting_approval'].append(te)
            continue
        if agreement is not None:
            info['agreements'].add(agreement.pk)
        if res.treatment == 'covered':
            info['covered_minutes'] += te.duration_minutes
            lines.append({'description': f'Time (covered by {agreement.name}): {work}'[:300],
                          'quantity': _hours2(te.duration_minutes), 'unit_price': ZERO,
                          'source': 'time', 'source_id': str(te.pk)})
            continue
        # Chargeable: another agreement, or time and materials.
        if before_cutoff(te, cut) and not include_before_cutoff:
            # Exactly as before 101.4: no back-billing of old time.
            info['before_cutoff'].append(te)
            rate = Decimal(str(agreement.hourly_rate)) if agreement is not None else ZERO
            lines.append({'description': f'Time: {work}'[:300], 'quantity': _hours2(te.duration_minutes),
                          'unit_price': rate, 'source': 'time', 'source_id': str(te.pk)})
            continue
        rate, source = labor_rate(te, agreement)
        if rate is None:
            info['no_rate'].append((te, source))
            continue
        rule = billing_rule(client, agreement, on)
        billed_min = round_minutes(rule, te.duration_minutes)
        info['chargeable_minutes'] += te.duration_minutes
        info['billed_minutes'] += billed_min
        info['rate'] = rate
        kind = '' if (te.rate_type or 'standard') == 'standard' else f' [{te.get_rate_type_display().lower()}]'
        note = '' if billed_min == te.duration_minutes else f' ({te.duration_minutes} min worked)'
        lines.append({'description': f'Time{kind}: {work}{note}'[:300], 'quantity': _hours2(billed_min),
                      'unit_price': rate, 'source': 'time', 'source_id': str(te.pk),
                      'price_source': f'101.4:{source}'[:40], 'price_resolved_at': timezone.now()})
        if te.rate_type == 'onsite':
            visits.setdefault(on, agreement)

    for on, agreement in sorted(visits.items(), key=lambda kv: kv[0]):
        rule = billing_rule(client, agreement, on)
        if rule is None:
            continue
        for kind, amount in (('dispatch', rule.dispatch_fee), ('travel', rule.travel_fee)):
            if not amount:
                continue
            key = f'{kind}:{ticket.pk}:{on.isoformat()}'
            if _fee_billed(key):
                continue
            info['fees'] += Decimal(amount)
            lines.append({'description': f'{kind.title()} fee: onsite visit {on.isoformat()}',
                          'quantity': Decimal('1'), 'unit_price': Decimal(amount), 'source': 'fee',
                          'source_id': key, 'is_taxable': True, 'price_source': f'billing rule {rule.pk}'})

    for e in expenses:
        if e.unit_price is None:
            lines.append({'description': f'Expense: {e.description}'[:300], 'quantity': Decimal('1'),
                          'unit_price': Decimal(str(e.amount)), 'source': 'expense', 'source_id': str(e.pk)})
            continue
        line = item_line(e)
        if line is None:
            # Stock reserved for the ticket but not marked used: billed once
            # it is used (Phase 101.6), never while it may still go back.
            info['unused_stock'].append(e)
            continue
        lines.append(line)
    return lines, info


def item_line(e):
    """Invoice line for an "Add Item" row (TicketExpense with a unit price),
    or None while its stock is only reserved. A credit bills negative."""
    if e.inventory_item_id and e.inventory_state == 'reserved':
        return None
    price = Decimal(str(e.unit_price))
    label = 'Credit' if e.is_credit else 'Item'
    serial = f' (S/N {e.serial_number})' if e.serial_number else ''
    line = {'description': f'{label}: {e.description}{serial}'[:300], 'quantity': Decimal(str(e.quantity)),
            'unit_price': -price if e.is_credit else price, 'source': 'expense', 'source_id': str(e.pk),
            'is_taxable': bool(e.is_taxable), 'price_book_item_id': e.price_book_item_id,
            'unit_cost': e.unit_cost, 'price_source': (e.price_source or 'ticket item')[:40]}
    return line


def overage_terms(contract, client, on, over_minutes, *, pre=False):
    """(rate, rule, billed minutes) for prepaid overage: the agreement's
    overage rate (or hourly rate), rounded up to the billing rule's increment
    (no minimum); no rule before the upgrade cutoff. Shared by invoicing and
    the ticket's forecast so both say the same."""
    rate = Decimal(str(contract.overage_rate or contract.hourly_rate or 0))
    rule = None if pre else billing_rule(client, contract, on)
    return rate, rule, round_minutes(rule, over_minutes, minimum=False)


def lines_total(lines):
    total = ZERO
    for ln in lines:
        total += (Decimal(str(ln['quantity'])) * Decimal(str(ln['unit_price']))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
    return total


def single_agreement(info):
    """The agreement for Invoice.source_contract when all time is under one."""
    from psa.models import Contract
    ids = info.get('agreements') or set()
    if len(ids) == 1:
        return Contract.objects.filter(pk=next(iter(ids))).first()
    return None


__all__ = ['ticket_billing_lines', 'labor_rate', 'round_minutes', 'cutoff', 'lines_total']
