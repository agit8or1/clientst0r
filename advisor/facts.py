"""
Per-customer facts the detectors read.

Every fact is a `Fact`: a value (Decimal) or None when it cannot be known,
whether it is complete, which inputs are missing, how it was obtained
(`basis`: verified = a recorded amount such as an invoice or a contract term;
estimate = derived with rates, e.g. labour cost; unknown = no value) and the
records behind it, so the page can show the calculation and link to them.

Figures come from the canonical reporting functions (reports.queries /
reports.costing) where they exist, so the advisor and the profitability
reports agree. Nothing is filled in with a placeholder: an hour without a
cost rate makes labour cost unknown, and the known part is kept only as a
bound (`lower` for costs, `upper` for profit and margin). Costs are never
negative, so "revenue minus the costs we do know" is an upper bound on gross
profit: a loss below that bound is certain even when other costs are missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from . import inputs

ZERO = Decimal('0')
CENT = Decimal('0.01')
HUNDRED = Decimal('100')
RECORD_LIMIT = 25

LIVE_INVOICE_STATUSES = ('sent', 'partial', 'paid', 'overdue')
HARDWARE_EXPENSE = ('parts', 'software')
DELIVERY_EXPENSE = ('mileage', 'subcontractor', 'shipping', 'other')
LIVE_PO_EXCLUDE = ('draft', 'cancelled', 'void')


def q2(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def money_str(value):
    return None if value is None else f'{q2(value):.2f}'


def url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


@dataclass
class Fact:
    key: str
    label: str
    unit: str                       # money / pct / hours / count
    value: Optional[Decimal]
    basis: str = 'verified'         # verified / estimate / unknown / not_applicable
    is_complete: bool = True
    missing: List[str] = field(default_factory=list)
    source: str = ''
    records: List[dict] = field(default_factory=list)
    lower: Optional[Decimal] = None  # known part of an incomplete cost
    upper: Optional[Decimal] = None  # bound on an incomplete profit / margin
    note: str = ''

    def __post_init__(self):
        if self.value is None and self.basis in ('verified', 'estimate') and not self.is_complete:
            self.basis = 'unknown'

    def as_json(self):
        def num(v):
            return None if v is None else f'{q2(v):.2f}'
        return {
            'key': self.key, 'label': self.label, 'unit': self.unit, 'value': num(self.value),
            'basis': self.basis, 'is_complete': self.is_complete, 'missing': list(self.missing),
            'source': self.source, 'records': self.records[:RECORD_LIMIT],
            'lower': num(self.lower), 'upper': num(self.upper), 'note': self.note,
        }


def _dec(v):
    return None if v is None else Decimal(str(v))


# --- windows --------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    months: int
    start: date
    end: date

    @property
    def key(self):
        return f'{self.months}m:{self.end:%Y-%m}'

    @property
    def label(self):
        return f'{self.start:%b %Y} – {self.end:%b %Y}' if self.months > 1 else f'{self.end:%B %Y}'

    def prior(self):
        end = self.start - timedelta(days=1)
        return window_ending(end, self.months)

    def month_ends(self):
        out, d = [], self.start
        while d <= self.end:
            first = d.replace(day=1)
            last = first + relativedelta(months=1) - timedelta(days=1)
            out.append((first, last))
            d = last + timedelta(days=1)
        return out


def last_full_month_end(today):
    return today.replace(day=1) - timedelta(days=1)


def window_ending(end, months):
    start = (end.replace(day=1) - relativedelta(months=months - 1))
    return Window(months, start, end)


# --- the facts ----------------------------------------------------------------

class CustomerFacts:
    """Facts for one customer over one window. Cheap to construct; each
    group of facts is computed on first use."""

    def __init__(self, client, window: Window, rates: inputs.Rates = None, settings=None, today=None):
        from django.utils import timezone
        self.client = client
        self.window = window
        self.rates = rates or inputs.Rates()
        self.settings = settings
        self.today = today or timezone.localdate()
        self._cache = {}

    # -- helpers -------------------------------------------------------------

    def _memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def _entries(self):
        from psa.models import TicketTimeEntry
        return (TicketTimeEntry.objects
                .filter(ticket__organization=self.client, ended_at__isnull=False, duration_minutes__gt=0,
                        started_at__date__gte=self.window.start, started_at__date__lte=self.window.end)
                .select_related('ticket', 'user'))

    @staticmethod
    def _ticket_record(entry):
        t = entry.ticket
        return {'label': f'{t.ticket_number or t.pk} {t.subject[:60]}', 'model': 'psa.Ticket', 'id': t.pk,
                'url': url('psa:ticket_detail', t.ticket_number) if t.ticket_number else ''}

    def contracts(self):
        """Non-draft contracts of this customer that overlap the window."""
        from psa.models import Contract
        return self._memo('contracts', lambda: list(
            Contract.objects.filter(client_org=self.client, start_date__lte=self.window.end)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=self.window.start))
            .exclude(status='draft').order_by('pk')))

    def active_contracts(self):
        return [c for c in self.contracts() if c.status == 'active']

    # -- revenue -------------------------------------------------------------

    def revenue(self) -> Fact:
        def build():
            from psa.models import Invoice
            from reports.queries import revenue_by_client
            rows = revenue_by_client(self.window.start, self.window.end, self.client)
            value = sum((Decimal(str(r['invoiced'])) for r in rows if r['client_id'] == self.client.pk), ZERO)
            from reports.financials import invoice_revenue
            invs = (Invoice.objects.filter(client_org=self.client, invoice_date__gte=self.window.start,
                                           invoice_date__lte=self.window.end,
                                           status__in=LIVE_INVOICE_STATUSES).order_by('invoice_date'))
            records = [{'label': f'{i.invoice_number} {i.invoice_date:%Y-%m-%d} {i.currency} '
                                 f'{invoice_revenue(i)} excl. tax',
                        'model': 'psa.Invoice', 'id': i.pk, 'url': url('psa:invoice_detail', i.pk)}
                       for i in invs[:RECORD_LIMIT]]
            drafts = Invoice.objects.filter(client_org=self.client, invoice_date__gte=self.window.start,
                                            invoice_date__lte=self.window.end, status='draft').count()
            note = 'Billed revenue: issued invoices dated in the window, excluding tax, net of credit ' \
                   'notes (reports.financials), as in the profitability report.'
            if drafts:
                note += f' {drafts} draft invoice(s) in the window are not counted.'
            return Fact('revenue', 'Billed revenue', 'money', q2(value), 'verified',
                        source='reports.queries.revenue_by_client', records=records, note=note)
        return self._memo('revenue', build)

    def mrr(self) -> Fact:
        def build():
            from reports.queries import recurring_revenue
            rr = recurring_revenue(self.window.end, self.client)
            rows = [r for r in rr['contracts'] if r['client_id'] == self.client.pk]
            value = sum((Decimal(str(r['mrr'])) for r in rows), ZERO)
            missing = []
            if not rr.get('is_complete', True):
                missing.append('A stopped contract has no end date, so it cannot be placed in this month.')
            records = [{'label': f"{r['contract_name']} ({r['frequency']})", 'model': 'psa.Contract',
                        'id': r['contract_id'], 'url': url('psa:contract_detail', r['contract_id'])}
                       for r in rows]
            return Fact('mrr', 'Monthly recurring revenue', 'money', q2(value), 'verified',
                        is_complete=not missing, missing=missing, source='reports.queries.recurring_revenue',
                        records=records, note=f'Contract recurring amounts on {self.window.end:%Y-%m-%d}, '
                                              'normalized to a month.')
        return self._memo('mrr', build)

    def arr(self) -> Fact:
        m = self.mrr()
        return Fact('arr', 'Annual recurring revenue', 'money', q2(m.value * 12) if m.value is not None else None,
                    m.basis, is_complete=m.is_complete, missing=list(m.missing), source='MRR × 12')

    # -- costs ---------------------------------------------------------------

    def labor(self) -> Fact:
        def build():
            from reports.queries import cost_estimate_by_client
            rows = [r for r in cost_estimate_by_client(self.window.start, self.window.end, self.client)
                    if r['client_id'] == self.client.pk]
            row = rows[0] if rows else {'hours': 0.0, 'cost': 0.0, 'unknown_cost_hours': 0.0,
                                        'unknown_cost_entries': 0, 'cost_complete': True}
            known = q2(row['cost'])
            missing, records = [], []
            if not row['cost_complete']:
                by_tech = {}
                for e in self._entries():
                    if self.rates.cost_rate(e) is None:
                        name = e.user.get_username() if e.user_id else 'no technician'
                        by_tech[name] = by_tech.get(name, ZERO) + inputs.entry_hours(e)
                        if len(records) < RECORD_LIMIT:
                            records.append(self._ticket_record(e))
                for name, hours in sorted(by_tech.items()):
                    missing.append(f'No cost rate for {name} ({q2(hours)} h in the window).')
            complete = bool(row['cost_complete'])
            return Fact('labor_cost', 'Labour cost', 'money', known if complete else None, 'estimate',
                        is_complete=complete, missing=missing, lower=known,
                        source='reports.queries.cost_estimate_by_client (each hour at the technician\'s '
                               'cost rate on the day)', records=records,
                        note=f"{q2(row['hours'])} h logged; {q2(row['unknown_cost_hours'])} h without a "
                             'cost rate.')
        return self._memo('labor', build)

    def total_hours(self):
        from reports.queries import cost_estimate_by_client
        def build():
            rows = [r for r in cost_estimate_by_client(self.window.start, self.window.end, self.client)
                    if r['client_id'] == self.client.pk]
            return q2(rows[0]['hours']) if rows else ZERO
        return self._memo('total_hours', build)

    def licensing(self) -> Fact:
        def build():
            value, missing, records = inputs.license_cost(self.client, self.window.months)
            return Fact('licensing_cost', 'Vendor / licensing cost', 'money', value,
                        'verified' if value is not None else 'unknown', is_complete=not missing,
                        missing=missing, records=records,
                        source=inputs.sources()['licensing'] or 'not tracked on this install')
        return self._memo('licensing', build)

    def _expenses(self, categories):
        from psa.models import TicketExpense
        return TicketExpense.objects.filter(ticket__organization=self.client, category__in=categories,
                                            incurred_on__gte=self.window.start,
                                            incurred_on__lte=self.window.end).select_related('ticket')

    def hardware(self) -> Fact:
        def build():
            from psa.models import PurchaseOrder
            total, records = ZERO, []
            for x in self._expenses(HARDWARE_EXPENSE):
                total += x.amount or ZERO
                if len(records) < RECORD_LIMIT:
                    records.append({'label': f'Expense: {x.description[:60]} {x.amount}', 'model': 'psa.TicketExpense',
                                    'id': x.pk, 'url': url('psa:ticket_detail', x.ticket.ticket_number)
                                    if x.ticket.ticket_number else ''})
            pos = (PurchaseOrder.objects.filter(client_org=self.client).exclude(status__in=LIVE_PO_EXCLUDE)
                   .filter(Q(issue_date__gte=self.window.start, issue_date__lte=self.window.end)
                           | Q(issue_date__isnull=True, created_at__date__gte=self.window.start,
                               created_at__date__lte=self.window.end)))
            for po in pos:
                total += (po.subtotal or ZERO) + (po.shipping_cost or ZERO)
                if len(records) < RECORD_LIMIT:
                    records.append({'label': f'{po.po_number} {po.vendor_name[:40]} {po.subtotal}',
                                    'model': 'psa.PurchaseOrder', 'id': po.pk, 'url': url('psa:po_detail', po.pk)})
            return Fact('hardware_cost', 'Hardware / software cost', 'money', q2(total), 'verified',
                        source='ticket expenses (parts, software) + purchase orders for this customer',
                        records=records, note='Recorded expenses and purchase orders only.')
        return self._memo('hardware', build)

    def delivery(self) -> Fact:
        def build():
            total, records = ZERO, []
            for x in self._expenses(DELIVERY_EXPENSE):
                total += x.amount or ZERO
                if len(records) < RECORD_LIMIT:
                    records.append({'label': f'Expense: {x.description[:60]} {x.amount}', 'model': 'psa.TicketExpense',
                                    'id': x.pk, 'url': url('psa:ticket_detail', x.ticket.ticket_number)
                                    if x.ticket.ticket_number else ''})
            return Fact('delivery_cost', 'Delivery cost (travel, subcontractors, shipping, other)', 'money',
                        q2(total), 'verified', source='ticket expenses', records=records,
                        note='Recorded ticket expenses only.')
        return self._memo('delivery', build)

    def cost_parts(self):
        return [self.labor(), self.licensing(), self.hardware(), self.delivery()]

    def total_cost(self) -> Fact:
        parts = self.cost_parts()
        complete = all(p.is_complete for p in parts)
        lower = sum(((p.value if p.value is not None else (p.lower or ZERO)) for p in parts), ZERO)
        missing = [m for p in parts for m in p.missing]
        return Fact('total_cost', 'Total delivery cost', 'money', q2(lower) if complete else None, 'estimate',
                    is_complete=complete, missing=missing, lower=q2(lower),
                    source='labour + vendor / licensing + hardware / software + delivery')

    def gross_profit(self) -> Fact:
        rev, cost = self.revenue(), self.total_cost()
        upper = q2(rev.value - cost.lower)
        return Fact('gross_profit', 'Gross profit', 'money', upper if cost.is_complete else None, 'estimate',
                    is_complete=cost.is_complete, missing=list(cost.missing), upper=upper,
                    source='revenue − total delivery cost')

    def gross_margin(self) -> Fact:
        rev, gp = self.revenue(), self.gross_profit()
        if not rev.value:
            return Fact('gross_margin', 'Gross margin', 'pct', None, 'not_applicable', is_complete=gp.is_complete,
                        missing=list(gp.missing), source='gross profit ÷ revenue',
                        note='No invoiced revenue in the window.')
        upper = q2(gp.upper / rev.value * HUNDRED)
        return Fact('gross_margin', 'Gross margin', 'pct', upper if gp.is_complete else None, 'estimate',
                    is_complete=gp.is_complete, missing=list(gp.missing), upper=upper,
                    source='gross profit ÷ revenue × 100')

    def labor_margin(self) -> Fact:
        rev, lab = self.revenue(), self.labor()
        if not rev.value:
            return Fact('labor_margin', 'Margin after labour', 'pct', None, 'not_applicable',
                        is_complete=lab.is_complete, missing=list(lab.missing),
                        note='No invoiced revenue in the window.')
        value = q2((rev.value - lab.value) / rev.value * HUNDRED) if lab.is_complete else None
        return Fact('labor_margin', 'Margin after labour', 'pct', value, 'estimate', is_complete=lab.is_complete,
                    missing=list(lab.missing), source='(revenue − labour cost) ÷ revenue × 100',
                    note='Labour only: vendor, hardware and delivery costs are not subtracted.')

    # -- contracts -----------------------------------------------------------

    @staticmethod
    def monthly_allowance_hours(contract):
        """Included hours per month for a recurring-allowance contract, else None."""
        months = inputs.MONTHS_PER_PERIOD.get(contract.billing_frequency)
        if months is None or not contract.total_hours or contract.total_hours <= 0:
            return None
        return Decimal(str(contract.total_hours)) / months

    def contract_month_usage(self, contract):
        """[(month_start, hours used)] for each month of the window, counting the
        contract's qualifying entries (its own role gates and window)."""
        def build():
            entries = contract.qualifying_time_entries().filter(
                started_at__date__gte=self.window.start, started_at__date__lte=self.window.end)
            per = {}
            for e in entries:
                d = inputs.entry_date(e)
                key = d.replace(day=1)
                per[key] = per.get(key, ZERO) + inputs.entry_hours(e)
            return [(first, q2(per.get(first, ZERO))) for first, _last in self.window.month_ends()]
        return self._memo(('usage', contract.pk), build)

    def utilization(self) -> Fact:
        def build():
            used = included = ZERO
            records = []
            for c in self.active_contracts():
                allowance = self.monthly_allowance_hours(c)
                if allowance is None:
                    continue
                months = self.contract_month_usage(c)
                used += sum((h for _m, h in months), ZERO)
                included += allowance * len(months)
                records.append({'label': c.name, 'model': 'psa.Contract', 'id': c.pk,
                                'url': url('psa:contract_detail', c.pk)})
            if not included:
                return Fact('utilization', 'Contract utilization', 'pct', None, 'not_applicable',
                            note='No active contract with included hours per period.')
            return Fact('utilization', 'Contract utilization', 'pct', q2(used / included * HUNDRED), 'verified',
                        records=records, source='hours used ÷ hours included',
                        note=f'{q2(used)} h used of {q2(included)} h included.')
        return self._memo('utilization', build)

    def contract_rows(self):
        """Per active contract: hours, labour cost (complete or not), invoiced
        revenue, expected recurring revenue, effective rate."""
        def build():
            from psa.models import Invoice
            from reports.financials import invoice_revenue
            from reports.queries import cost_estimate_by_contract
            costs = {r['contract_id']: r for r in cost_estimate_by_contract(
                self.window.start, self.window.end, self.client)}
            out = []
            for c in self.active_contracts():
                cr = costs.get(c.pk, {'hours': 0.0, 'cost': 0.0, 'unknown_cost_hours': 0.0,
                                      'cost_complete': True})
                invs = list(Invoice.objects.filter(source_contract=c, invoice_date__gte=self.window.start,
                                                   invoice_date__lte=self.window.end,
                                                   status__in=LIVE_INVOICE_STATUSES))
                invoiced = sum((invoice_revenue(i) for i in invs), ZERO)
                monthly = inputs.monthly_amount(c)
                expected = q2(monthly * self.window.months) if monthly is not None else None
                if invs:
                    revenue, basis = q2(invoiced), 'verified'
                elif expected is not None:
                    revenue, basis = expected, 'estimate'
                else:
                    revenue, basis = ZERO, 'verified'
                hours = q2(cr['hours'])
                cost = q2(cr['cost']) if cr['cost_complete'] else None
                out.append({
                    'contract': c, 'hours': hours, 'cost': cost, 'cost_known_part': q2(cr['cost']),
                    'cost_complete': bool(cr['cost_complete']), 'unknown_cost_hours': q2(cr['unknown_cost_hours']),
                    'revenue': revenue, 'revenue_basis': basis, 'monthly': monthly,
                    'invoice_records': [{'label': f'{i.invoice_number} {invoice_revenue(i)}', 'model': 'psa.Invoice',
                                         'id': i.pk, 'url': url('psa:invoice_detail', i.pk)} for i in invs],
                    'effective_rate': q2(revenue / hours) if hours else None,
                    'cost_rate': q2(cost / hours) if (cost is not None and hours) else None,
                })
            return out
        return self._memo('contract_rows', build)

    # -- unbilled work and leakage ----------------------------------------------

    def _billing_split(self):
        def build():
            stale_days = getattr(self.settings, 'unbilled_stale_days', 14) if self.settings else 14
            cutoff = self.today - timedelta(days=stale_days)
            entries = [e for e in self._entries().filter(is_billable=True) if inputs.entry_date(e) <= cutoff]
            billed = inputs.billed_time_ids([e.pk for e in entries]) if entries else set()
            book = self.rates._book
            hourly_amount, hourly_unknown, hourly_records, hourly_hours = ZERO, ZERO, [], ZERO
            leak_hours, leak_amount, leak_unknown, leak_records = ZERO, ZERO, ZERO, []
            leak_cost, leak_cost_unknown = ZERO, ZERO
            allowance_contracts = {}
            for e in entries:
                if e.pk in billed:
                    continue
                contract = book.contract_for_entry(e) if book is not None else None
                h = inputs.entry_hours(e)
                if contract is None:
                    leak_hours += h
                    cost_rate = self.rates.cost_rate(e)
                    if cost_rate is None:
                        leak_cost_unknown += h
                    else:
                        leak_cost += h * cost_rate
                    rate = inputs._dec(getattr(e, 'bill_rate_snapshot', None))
                    if rate is None:
                        leak_unknown += h
                    else:
                        leak_amount += h * rate
                    if len(leak_records) < RECORD_LIMIT:
                        leak_records.append(self._ticket_record(e))
                    continue
                if contract.effective_total_minutes() > 0:
                    allowance_contracts[contract.pk] = contract
                    continue
                if contract.contract_type in contract.FLAT_FEE_TYPES:
                    continue  # covered by the flat fee
                hourly_hours += h
                rate = self.rates.bill_rate(e, contract)
                if rate is None:
                    hourly_unknown += h
                else:
                    hourly_amount += h * rate
                if len(hourly_records) < RECORD_LIMIT:
                    hourly_records.append(self._ticket_record(e))
            overage = []
            from psa.billing import ledger as _ledger
            from psa.models import InvoiceLineItem as _ILI
            for c in allowance_contracts.values():
                # Phase 101.4: approved overage from the prepaid-hour ledger
                # whose time is not on a live invoice yet.
                held = [p for p in c.prepaid_postings.filter(kind='overage', reversed_by__isnull=True)]
                if held or _ledger.totals(c) is not None:
                    billed = _ILI.billed_source_ids('time', [p.time_entry_ref for p in held])
                    over_min = sum(_ledger.minutes_of(p.hours) for p in held if p.time_entry_ref not in billed)
                else:
                    over_min = max(0, (c.hours_used_minutes or 0) - c.effective_total_minutes()
                                   - c.overage_minutes_invoiced())
                if over_min <= 0:
                    continue
                rate = overage_rate(c)
                hrs = Decimal(over_min) / Decimal('60')
                overage.append({'contract': c, 'hours': q2(hrs), 'rate': rate,
                                'amount': q2(hrs * rate) if rate is not None else None})
            return {
                'hourly_hours': q2(hourly_hours), 'hourly_amount': q2(hourly_amount),
                'hourly_unknown_hours': q2(hourly_unknown), 'hourly_records': hourly_records,
                'overage': overage, 'leak_hours': q2(leak_hours), 'leak_amount': q2(leak_amount),
                'leak_unknown_hours': q2(leak_unknown), 'leak_records': leak_records, 'cutoff': cutoff,
                'leak_cost': q2(leak_cost), 'leak_cost_unknown_hours': q2(leak_cost_unknown),
            }
        return self._memo('billing_split', build)

    def unbilled(self) -> Fact:
        s = self._billing_split()
        amount = s['hourly_amount']
        missing = []
        if s['hourly_unknown_hours']:
            missing.append(f"{s['hourly_unknown_hours']} h of unbilled work have no bill rate.")
        records = list(s['hourly_records'])
        for o in s['overage']:
            if o['amount'] is None:
                missing.append(f"{o['hours']} h over the allowance of {o['contract'].name} have no overage "
                               'or hourly rate.')
            else:
                amount += o['amount']
            records.append({'label': f"{o['contract'].name}: {o['hours']} h over allowance, not invoiced",
                            'model': 'psa.Contract', 'id': o['contract'].pk,
                            'url': url('psa:contract_detail', o['contract'].pk)})
        complete = not missing
        return Fact('unbilled', 'Unbilled billable work', 'money', q2(amount) if complete else None, 'estimate',
                    is_complete=complete, missing=missing, lower=q2(amount), records=records,
                    source='billable time not on any live invoice (older than '
                           f"{s['cutoff']:%Y-%m-%d}), valued at the contract rate; plus hours over an "
                           'allowance not yet invoiced as overage',
                    note='Work covered by a flat fee or inside an allowance is not counted.')

    def leakage_hours(self) -> Fact:
        s = self._billing_split()
        return Fact('leakage_hours', 'Billable hours with no contract or charge', 'hours', s['leak_hours'],
                    'verified', records=s['leak_records'],
                    source='billable, uninvoiced time on tickets with no covering contract')

    def leakage(self) -> Fact:
        s = self._billing_split()
        complete = not s['leak_unknown_hours']
        missing = [] if complete else [
            f"{s['leak_unknown_hours']} h have no bill rate (no contract and no rate on the entry)."]
        return Fact('leakage', 'Revenue leakage (work with no contract or charge)', 'money',
                    s['leak_amount'] if complete else None, 'estimate', is_complete=complete, missing=missing,
                    lower=s['leak_amount'], records=s['leak_records'],
                    source='leaked hours × the bill rate recorded on the entry')

    # -- other ---------------------------------------------------------------

    def device_count(self):
        def build():
            from assets.models import Asset
            return Asset.objects.filter(organization=self.client).count()
        return self._memo('devices', build)

    def after_hours_share(self):
        """(share %, after-hours hours, total hours) of this window's time."""
        def build():
            start_h = getattr(self.settings, 'business_hours_start', 8) if self.settings else 8
            end_h = getattr(self.settings, 'business_hours_end', 18) if self.settings else 18
            from django.utils import timezone
            total = after = ZERO
            for e in self._entries():
                h = inputs.entry_hours(e)
                total += h
                local = timezone.localtime(e.started_at) if timezone.is_aware(e.started_at) else e.started_at
                rate_type = getattr(e, 'rate_type', '') or ''
                if rate_type in ('after_hours', 'weekend', 'holiday', 'emergency'):
                    after += h
                elif rate_type in ('', 'standard') and (local.weekday() >= 5 or local.hour < start_h or local.hour >= end_h):
                    after += h
            share = q2(after / total * HUNDRED) if total else None
            return share, q2(after), q2(total)
        return self._memo('after_hours', build)

    # -- all -----------------------------------------------------------------

    def summary(self) -> Dict[str, Fact]:
        facts = [self.revenue(), self.mrr(), self.arr(), self.labor(), self.licensing(), self.hardware(),
                 self.delivery(), self.total_cost(), self.gross_profit(), self.gross_margin(), self.labor_margin(),
                 self.utilization(), self.unbilled(), self.leakage(), self.leakage_hours()]
        return {f.key: f for f in facts}

    def summary_json(self):
        return {k: f.as_json() for k, f in self.summary().items()}


def overage_rate(contract):
    """Rate an allowance contract bills its overage at: overage, else hourly."""
    for value in (contract.overage_rate, contract.hourly_rate):
        if value is not None and value > 0:
            return Decimal(str(value))
    return None
