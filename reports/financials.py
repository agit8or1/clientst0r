"""
Financial definitions — one place, used by every report.

Every revenue, cost, profit and margin figure the product shows is computed
here (or by `reports.queries` functions that call into here), so a customer,
period and figure name give the same number on every page, card, widget,
export and API. Read-side only: nothing in this module writes to an invoice,
payment or any stored amount.

Definitions
-----------
Billed revenue
    Issued invoices — status sent, partially paid, paid or overdue; drafts
    and void invoices are excluded — dated in the period by **invoice date**,
    **excluding tax** (`total - tax_amount`, which is the invoice subtotal),
    **net of credit notes**: an issued credit memo is a negative invoice and
    reduces billed revenue on its own invoice date. A credit memo is
    attributed to the contract, project and service line of the invoice it
    credits. Customer = the invoice's customer (`client_org`, else
    `organization`).

Collected revenue
    Payments received in the period by **payment date** (`Payment.paid_on`),
    **net of refunds**: a gateway refund or a lost dispute is a negative
    payment row, so it reduces collected revenue on its own date. The tax
    portion is removed in proportion to the paid invoice:
    `amount × (total − tax) ÷ total`. When the invoice has no tax the whole
    payment counts; when it has tax but a zero total the split cannot be
    determined, the payment counts in full and the figure is marked partial.
    Payments recorded against a void invoice still count (the cash was
    received) and mark the figure partial so somebody looks at them.
    `gross` carries the same payments including tax.

Recognized revenue
    Billed revenue spread over the service period it pays for. Only
    contract-period invoices carry a service period (`billing_period_start`
    plus the contract's billing frequency: one month, three months or a
    year); their net amount is recognized pro rata by day across that
    period. Every other invoice — ticket time, items, projects, one-off
    charges — is recognized in full on its invoice date, because invoice
    lines carry no service period. A credit memo is recognized over the
    period of the invoice it credits. Limitation: this is a straight-line
    approximation from billing data, not accounting-system revenue
    recognition; rounding is to the cent per invoice per period.

Direct cost
    The cost of delivering work in the period, by the date of the work:
      * labour — every time entry (billable or not) started in the period,
        at the technician's loaded cost rate on that day
        (`reports.costing`: entry snapshot, else effective-dated
        `TechCostRate`, else unknown — never an assumed rate);
      * items — ticket items (a ticket expense with a sell price) incurred
        in the period at `unit_cost × quantity`; an item without a unit
        cost is unknown;
      * expenses — ticket expenses without a sell price (mileage,
        subcontractors, purchases billed at cost) at their amount;
      * invoice lines — lines on issued invoices dated in the period that
        carry a unit-cost snapshot (price-book items sold straight onto an
        invoice or a quote), excluding lines that bill time or a ticket
        expense (those are already counted above).
    Credits to the customer (credit items) are not costs. Purchase orders,
    licence subscriptions and overheads are not direct cost here.

Gross profit
    **Billed revenue − direct cost** for the same customer and period.
    Billed (not recognized) revenue is the basis so the figure reconciles
    to invoices the customer received.

Margin
    Gross profit ÷ billed revenue, as a percentage; None when billed
    revenue is zero.

Partial figures
    Any unknown cost (an hour without a cost rate, an item without a cost)
    makes direct cost **partial**: the amount shown is the known part only,
    and gross profit and margin are None ("unknown") rather than a number
    that overstates profit. Every result carries `partial` and `reasons`
    (e.g. "2 technicians have no cost rate (6.5 h)") for the UI to show.

Other figures, named differently on purpose
    * Contracted MRR / ARR (`reports.queries.recurring_revenue`) — contract
      recurring amounts normalized to a month; a commitment, not revenue.
    * Attributed labour revenue (`profitability_by_tech`, margin
      analytics) — billable hours × the entry's bill rate; a measure of
      labour value, not of what was invoiced.
    * Contract-terms estimate (`Contract.profitability_snapshot`) — revenue
      from the contract's terms over its whole window.
    * Receivables (aging, balances, reconciliation) — amounts owed,
      including tax.

Scoping: every function takes `organization` — one customer, a list of
customers or None — and filters by the customer field exactly as
`reports.queries.scope_to_organizations` does, so the caller's permission
scope (reports.access.viewer_client_scope) carries through unchanged.
Amounts are single-currency; multi-currency installs are summed as stored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q

ZERO = Decimal('0')
CENT = Decimal('0.01')

#: Invoice statuses that count as issued (billed). Drafts and void are not.
ISSUED_STATUSES = ('sent', 'partial', 'paid', 'overdue')

#: Invoice line sources whose cost is counted from the source record itself.
_LINE_SOURCES_COSTED_ELSEWHERE = ('time', 'expense')

_FREQUENCY_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}

DIMENSIONS = (None, 'client', 'contract', 'project')

#: Short definitions for tooltips and the definitions panel on report pages.
DEFINITIONS = (
    ('Billed revenue', 'Issued invoices (not drafts or void) by invoice date, excluding tax, '
                       'net of credit notes.'),
    ('Collected revenue', 'Payments received by payment date, net of refunds, with the tax '
                          'share of each paid invoice removed.'),
    ('Recognized revenue', 'Billed revenue spread over the service period of contract-period '
                           'invoices; other invoices on their invoice date.'),
    ('Direct cost', 'Labour at each technician\'s cost rate on the day of the work, plus ticket '
                    'items at unit cost, ticket expenses, and invoice lines with a unit cost.'),
    ('Gross profit', 'Billed revenue minus direct cost. Unknown while any cost is unknown.'),
    ('Margin', 'Gross profit as a percentage of billed revenue; none when revenue is zero.'),
)


def _dec(v):
    if v is None:
        return ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q(v):
    return _dec(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _scope(qs, field_name, organization):
    from .queries import scope_to_organizations
    return scope_to_organizations(qs, field_name, organization)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Figure:
    """One financial figure, overall and per group.

    `amount` is the total (Decimal). `by` maps a group key to its amount and
    `rows` the same key to the group's identifying fields (client / contract /
    project ids and names). `partial` is True when part of the figure could
    not be determined; `reasons` says why. `notes` are informational.
    """
    amount: Decimal = ZERO
    partial: bool = False
    reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    by: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)
    count: int = 0
    gross: Decimal = ZERO   # collected revenue only: the same payments including tax

    def add(self, key, base, amount):
        self.amount += amount
        if key is not None:
            self.by[key] = self.by.get(key, ZERO) + amount
            self.rows.setdefault(key, base)


@dataclass
class BilledRow:
    base: dict
    billed: Decimal = ZERO
    gross: Decimal = ZERO
    tax: Decimal = ZERO
    paid: Decimal = ZERO
    invoices: int = 0


@dataclass
class CostRow:
    """Direct cost for one group. `total` is the known part."""
    base: dict = field(default_factory=dict)
    labour: Decimal = ZERO
    items: Decimal = ZERO
    expenses: Decimal = ZERO
    invoice_lines: Decimal = ZERO
    hours: Decimal = ZERO
    unknown_cost_hours: Decimal = ZERO
    unknown_cost_entries: int = 0
    unknown_rate_technicians: set = field(default_factory=set)
    entries_without_technician: int = 0
    unknown_item_count: int = 0

    @property
    def total(self):
        return self.labour + self.items + self.expenses + self.invoice_lines

    @property
    def partial(self):
        return bool(self.unknown_cost_entries or self.unknown_item_count)

    @property
    def reasons(self):
        return cost_reasons(len(self.unknown_rate_technicians), self.unknown_cost_hours,
                            self.entries_without_technician, self.unknown_item_count)


def cost_reasons(technicians=0, hours=0, entries_without_technician=0, items=0, bill_hours=0):
    """Human-readable reasons a cost (or margin) is partial."""
    out = []
    hours = float(hours or 0)
    if technicians:
        noun = 'technician has' if technicians == 1 else 'technicians have'
        out.append(f'{technicians} {noun} no cost rate ({round(hours, 2):g} h)')
    elif hours:
        out.append(f'{round(hours, 2):g} h without a cost rate')
    if entries_without_technician:
        noun = 'time entry has' if entries_without_technician == 1 else 'time entries have'
        out.append(f'{entries_without_technician} {noun} no technician')
    if items:
        noun = 'item has' if items == 1 else 'items have'
        out.append(f'{items} {noun} no cost')
    if bill_hours:
        out.append(f'{round(float(bill_hours), 2):g} billable h without a bill rate')
    return out


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def attributed_invoice(inv):
    """The invoice whose contract / project / ticket a document is counted
    under: the credited invoice for a credit memo, else the invoice itself."""
    if getattr(inv, 'is_credit_memo', False) and inv.credits_invoice_id:
        return inv.credits_invoice
    return inv


def _client_base(org):
    return {'client_id': org.id, 'client_name': org.name}


def invoice_client(inv):
    return inv.client_org or inv.organization


def invoice_project(inv):
    src = attributed_invoice(inv)
    if src.project_id:
        return src.project
    ticket = src.source_ticket if src.source_ticket_id else None
    return ticket.project if ticket is not None and ticket.project_id else None


def invoice_key(inv, by):
    """(key, base row) of an invoice in dimension `by`, or None when the
    invoice does not belong to any group in that dimension."""
    if by is None:
        return None
    if by == 'client':
        client = invoice_client(inv)
        return (client.id, _client_base(client)) if client else False
    if by == 'contract':
        c = attributed_invoice(inv).source_contract
        if c is None:
            return False
        return c.id, {'contract_id': c.id, 'contract_name': c.name, 'client_id': c.client_org_id,
                      'client_name': c.client_org.name if c.client_org_id else ''}
    if by == 'project':
        p = invoice_project(inv)
        if p is None:
            return False
        ticket = attributed_invoice(inv).source_ticket
        client = p.client_org or (ticket.organization if ticket is not None else None) or invoice_client(inv)
        return p.id, {'project_id': p.id, 'project_name': p.name,
                      'client_id': client.id if client else None,
                      'client_name': client.name if client else ''}
    raise ValueError(f'unknown dimension {by!r}')


def _project_base(project, ticket_org):
    client = project.client_org or ticket_org
    return {'project_id': project.id, 'project_name': project.name,
            'client_id': client.id if client else None, 'client_name': client.name if client else ''}


def _contract_base(c):
    return {'contract_id': c.id, 'contract_name': c.name, 'client_id': c.client_org_id,
            'client_name': c.client_org.name if c.client_org_id else ''}


_INVOICE_RELATED = ('client_org', 'organization', 'source_contract__client_org', 'project__client_org',
                    'source_ticket__project__client_org', 'source_ticket__organization',
                    'credits_invoice__source_contract__client_org', 'credits_invoice__project__client_org',
                    'credits_invoice__source_ticket__project__client_org',
                    'credits_invoice__source_ticket__organization')


# ---------------------------------------------------------------------------
# Billed revenue
# ---------------------------------------------------------------------------

def issued_invoices(start_date, end_date, organization=None):
    """Issued invoices and credit memos dated in [start, end] — the set billed
    revenue counts — scoped by customer."""
    from psa.models import Invoice
    qs = Invoice.objects.filter(invoice_date__gte=start_date, invoice_date__lte=end_date,
                                status__in=ISSUED_STATUSES)
    return _scope(qs, 'client_org', organization)


def invoice_revenue(inv):
    """Billed revenue of one issued invoice: its total excluding tax
    (negative for a credit memo)."""
    return _q(_dec(inv.total) - _dec(inv.tax_amount))


def billed_rows(start_date, end_date, organization=None, by='client'):
    """Billed revenue per group with the invoice gross, tax and amount paid
    alongside: {key: BilledRow}. Invoices outside every group of `by` are
    left out (e.g. invoices with no contract when by='contract')."""
    out = {}
    qs = issued_invoices(start_date, end_date, organization).select_related(*_INVOICE_RELATED)
    for inv in qs:
        keyed = invoice_key(inv, by)
        if not keyed:
            continue
        key, base = keyed
        row = out.get(key)
        if row is None:
            row = out[key] = BilledRow(base=base)
        row.billed += invoice_revenue(inv)
        row.gross += _dec(inv.total)
        row.tax += _dec(inv.tax_amount)
        row.paid += _dec(inv.amount_paid)
        row.invoices += 1
    return out


def billed_revenue(start_date, end_date, organization=None, by=None):
    """Billed revenue (see module docstring) as a Figure."""
    fig = Figure()
    qs = issued_invoices(start_date, end_date, organization).select_related(*_INVOICE_RELATED)
    for inv in qs:
        keyed = invoice_key(inv, by)
        key, base = keyed if keyed else (None, None)
        if by is not None and not keyed:
            fig.amount += invoice_revenue(inv)
            fig.count += 1
            continue
        fig.add(key, base, invoice_revenue(inv))
        fig.count += 1
    return fig


# ---------------------------------------------------------------------------
# Collected revenue
# ---------------------------------------------------------------------------

def payment_net_of_tax(payment, invoice):
    """(net amount, determinable) for one payment row."""
    amount = _dec(payment.amount)
    tax = _dec(invoice.tax_amount)
    total = _dec(invoice.total)
    if not tax:
        return _q(amount), True
    if not total:
        return _q(amount), False
    return _q(amount * (total - tax) / total), True


def collected_revenue(start_date, end_date, organization=None, by=None):
    """Collected revenue (see module docstring) as a Figure, with `gross`
    (including tax) set as an attribute."""
    from psa.models import Payment
    qs = Payment.objects.filter(paid_on__gte=start_date, paid_on__lte=end_date)
    qs = _scope(qs, 'invoice__client_org', organization)
    qs = qs.select_related(*('invoice__' + r for r in _INVOICE_RELATED), 'invoice')
    fig = Figure()
    gross = ZERO
    undeterminable = void = 0
    for pay in qs:
        inv = pay.invoice
        net, ok = payment_net_of_tax(pay, inv)
        if not ok:
            undeterminable += 1
        if inv.status == 'void':
            void += 1
        gross += _dec(pay.amount)
        keyed = invoice_key(inv, by)
        if by is not None and keyed:
            fig.add(keyed[0], keyed[1], net)
        else:
            fig.amount += net
        fig.count += 1
    if undeterminable:
        fig.partial = True
        fig.reasons.append(f'{undeterminable} payment(s) on invoices with tax but a zero total: '
                           'tax could not be separated')
    if void:
        fig.partial = True
        fig.reasons.append(f'{void} payment(s) are recorded against void invoices')
    fig.gross = gross
    return fig


# ---------------------------------------------------------------------------
# Recognized revenue
# ---------------------------------------------------------------------------

def service_period(inv):
    """(start, end) inclusive service period of an issued invoice, or None
    when it has none (recognized on its invoice date)."""
    from dateutil.relativedelta import relativedelta
    src = attributed_invoice(inv)
    contract = src.source_contract if src.source_contract_id else None
    months = _FREQUENCY_MONTHS.get(getattr(contract, 'billing_frequency', None))
    if not src.billing_period_start or not months:
        return None
    start = src.billing_period_start
    return start, start + relativedelta(months=months) - timedelta(days=1)


def recognized_amount(inv, start_date, end_date):
    """The part of one invoice's billed revenue recognized in [start, end]."""
    net = invoice_revenue(inv)
    period = service_period(inv)
    if period is None:
        return net if start_date <= inv.invoice_date <= end_date else ZERO
    p_start, p_end = period
    lo, hi = max(p_start, start_date), min(p_end, end_date)
    if hi < lo:
        return ZERO
    days = (p_end - p_start).days + 1
    if lo == p_start and hi == p_end:
        return net
    return _q(net * Decimal((hi - lo).days + 1) / Decimal(days))


def recognized_revenue(start_date, end_date, organization=None, by=None):
    """Recognized revenue (see module docstring) as a Figure."""
    from psa.models import Invoice
    reach = start_date - timedelta(days=366)
    qs = Invoice.objects.filter(status__in=ISSUED_STATUSES).filter(
        Q(invoice_date__gte=start_date, invoice_date__lte=end_date)
        | Q(billing_period_start__gte=reach, billing_period_start__lte=end_date)
        | Q(credits_invoice__billing_period_start__gte=reach,
            credits_invoice__billing_period_start__lte=end_date))
    qs = _scope(qs, 'client_org', organization).select_related(*_INVOICE_RELATED).distinct()
    fig = Figure()
    undated = 0
    for inv in qs:
        amount = recognized_amount(inv, start_date, end_date)
        if not amount:
            continue
        if service_period(inv) is None:
            undated += 1
        keyed = invoice_key(inv, by)
        if by is not None and keyed:
            fig.add(keyed[0], keyed[1], amount)
        else:
            fig.amount += amount
        fig.count += 1
    if undated:
        fig.notes.append(f'{undated} invoice(s) have no service period and are recognized on '
                         'their invoice date.')
    return fig


# ---------------------------------------------------------------------------
# Direct cost
# ---------------------------------------------------------------------------

def time_entries(start_date, end_date, organization=None):
    from psa.models import TicketTimeEntry
    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date, started_at__date__lte=end_date,
    ).select_related('user', 'ticket', 'ticket__organization', 'ticket__project',
                     'ticket__project__client_org')
    return _scope(qs, 'ticket__organization', organization)


def ticket_costs(start_date, end_date, organization=None):
    """Ticket items and expenses incurred in the period (credits excluded)."""
    from psa.models import TicketExpense
    qs = TicketExpense.objects.filter(incurred_on__gte=start_date, incurred_on__lte=end_date,
                                      is_credit=False).exclude(category='credit')
    qs = qs.select_related('ticket', 'ticket__organization', 'ticket__project',
                           'ticket__project__client_org')
    return _scope(qs, 'ticket__organization', organization)


def _ticket_key(ticket, on_date, by, book):
    if by is None:
        return None
    org = ticket.organization if ticket is not None else None
    if by == 'client':
        return (org.id, _client_base(org)) if org else False
    if by == 'contract':
        c = book.contract_for_client_on(getattr(ticket, 'organization_id', None), on_date)
        return (c.id, _contract_base(c)) if c else False
    if by == 'project':
        p = ticket.project if ticket is not None and ticket.project_id else None
        return (p.id, _project_base(p, org)) if p else False
    raise ValueError(f'unknown dimension {by!r}')


def direct_cost(start_date, end_date, organization=None, by=None):
    """Direct cost (see module docstring): {key: CostRow}. With by=None the
    single key is None."""
    from psa.models import InvoiceLineItem
    from .costing import RateBook, entry_date, entry_hours
    book = RateBook()
    out = {}

    def row_for(keyed):
        if by is None:
            keyed = (None, {})
        if not keyed:
            return None
        key, base = keyed
        row = out.get(key)
        if row is None:
            row = out[key] = CostRow(base=base)
        return row

    for te in time_entries(start_date, end_date, organization):
        if by == 'contract':
            c = book.contract_for_entry(te)
            keyed = (c.id, _contract_base(c)) if c else False
        else:
            keyed = _ticket_key(te.ticket, entry_date(te), by, book)
        row = row_for(keyed)
        if row is None:
            continue
        hours = entry_hours(te)
        rate = book.entry_cost_rate(te)
        row.hours += hours
        if rate is None:
            if hours > 0:
                row.unknown_cost_hours += hours
                row.unknown_cost_entries += 1
                if te.user_id:
                    row.unknown_rate_technicians.add(te.user_id)
                else:
                    row.entries_without_technician += 1
        else:
            row.labour += hours * rate

    for e in ticket_costs(start_date, end_date, organization):
        row = row_for(_ticket_key(e.ticket, e.incurred_on, by, book))
        if row is None:
            continue
        if e.unit_price is not None:      # an item: cost is its unit cost
            if e.unit_cost is None:
                row.unknown_item_count += 1
            else:
                row.items += _dec(e.unit_cost) * _dec(e.quantity)
        else:                             # an expense: cost is what was spent
            row.expenses += _dec(e.amount)

    lines = (InvoiceLineItem.objects
             .filter(invoice__in=issued_invoices(start_date, end_date, organization),
                     invoice__is_credit_memo=False, unit_cost__isnull=False)
             .exclude(source__in=_LINE_SOURCES_COSTED_ELSEWHERE)
             .select_related(*('invoice__' + r for r in _INVOICE_RELATED), 'invoice'))
    for li in lines:
        row = row_for(invoice_key(li.invoice, by))
        if row is None:
            continue
        row.invoice_lines += _dec(li.unit_cost) * _dec(li.quantity)

    for row in out.values():
        for attr in ('labour', 'items', 'expenses', 'invoice_lines'):
            setattr(row, attr, _q(getattr(row, attr)))
    return out


def direct_cost_total(start_date, end_date, organization=None):
    return direct_cost(start_date, end_date, organization).get(None) or CostRow()


# ---------------------------------------------------------------------------
# Gross profit and margin
# ---------------------------------------------------------------------------

def gross_profit(revenue, cost_row):
    """Billed revenue − direct cost, or None while the cost is partial."""
    if cost_row.partial:
        return None
    return _q(_dec(revenue) - cost_row.total)


def margin_pct(revenue, profit):
    """Gross profit ÷ billed revenue × 100 (one decimal), None when revenue is
    zero or the profit is unknown."""
    revenue = _dec(revenue)
    if profit is None or not revenue:
        return None
    return round(float(profit / revenue * 100), 1)


def cost_fields(row):
    """The flat, JSON-friendly cost fields every profitability row carries."""
    return {
        'hours': float(round(row.hours, 2)),
        'cost': float(row.total),
        'labour_cost': float(row.labour),
        'item_cost': float(row.items),
        'expense_cost': float(row.expenses),
        'line_cost': float(row.invoice_lines),
        'unknown_cost_hours': float(round(row.unknown_cost_hours, 2)),
        'unknown_cost_entries': row.unknown_cost_entries,
        'unknown_item_count': row.unknown_item_count,
        'unknown_rate_technicians': sorted(row.unknown_rate_technicians),
        'entries_without_technician': row.entries_without_technician,
        'cost_complete': not row.partial,
    }


def profitability(start_date, end_date, organization=None, by='client'):
    """Billed revenue, direct cost, gross profit and margin per group of `by`
    ('client', 'contract', 'project' or None for the total).

    Returns {key: row} where each row has the group's identifying fields and
    `revenue` (billed), `cost` (direct, known part), the cost split, `margin`
    (gross profit) / `margin_pct` (None while the cost is partial or revenue
    is zero), `is_complete`, `partial` and `partial_reasons`. Floats, so the
    rows serialize to JSON and CSV unchanged.
    """
    billed = billed_revenue(start_date, end_date, organization, by=by)
    costs = direct_cost(start_date, end_date, organization, by=by)
    keys = [None] if by is None else list(dict.fromkeys(list(billed.by) + list(costs)))
    out = {}
    for key in keys:
        revenue = billed.amount if by is None else billed.by.get(key, ZERO)
        c = costs.get(key) or CostRow()
        base = dict(billed.rows.get(key) or c.base or {})
        profit = gross_profit(revenue, c)
        row = dict(base)
        row['revenue'] = float(_q(revenue))
        row.update(cost_fields(c))
        row['margin'] = float(profit) if profit is not None else None
        row['margin_pct'] = margin_pct(revenue, profit)
        row['is_complete'] = not c.partial
        row['partial'] = c.partial
        row['partial_reasons'] = c.reasons
        out[key] = row
    return out


def totals(start_date, end_date, organization=None):
    """Every headline figure for one period and customer scope."""
    billed = billed_revenue(start_date, end_date, organization)
    collected = collected_revenue(start_date, end_date, organization)
    recognized = recognized_revenue(start_date, end_date, organization)
    cost = direct_cost_total(start_date, end_date, organization)
    profit = gross_profit(billed.amount, cost)
    return {
        'billed_revenue': _q(billed.amount),
        'collected_revenue': _q(collected.amount),
        'collected_gross': _q(collected.gross),
        'recognized_revenue': _q(recognized.amount),
        'direct_cost': cost.total,
        'labour_cost': cost.labour,
        'item_cost': cost.items,
        'expense_cost': cost.expenses,
        'line_cost': cost.invoice_lines,
        'gross_profit': profit,
        'margin_pct': margin_pct(billed.amount, profit),
        'cost_partial': cost.partial,
        'partial': cost.partial or collected.partial,
        'reasons': cost.reasons + collected.reasons,
        'notes': recognized.notes,
    }
