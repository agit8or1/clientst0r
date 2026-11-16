"""
Canonical reporting queries.

One module. One source of truth for "what's the revenue for client X
this period". Every Phase 3 report — profitability, leakage, SLA
trends, dashboards — calls into this. Don't duplicate these queries
in views; ADD a new function here and wire to it.

Conventions:
- Periods are inclusive [start_date, end_date], date objects.
- Currency math uses Decimal throughout.
- Returns dicts of plain Python types (no querysets) so JSON export +
  template rendering both work.
"""
from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Sum, Count, Q, F
from django.contrib.auth.models import User


# ---- Hours -----------------------------------------------------------------

def scope_to_organizations(qs, field, organization):
    """
    Apply a client-org filter to `qs` on `field`.

    `organization` is either one Organization (or pk) — the long-standing
    single-client form these queries were written for — or an iterable of
    them, which is what a viewer who belongs to several client orgs needs.
    None means no filter: every client the caller is entitled to see.
    """
    if organization is None:
        return qs
    if isinstance(organization, (list, tuple, set, frozenset)):
        return qs.filter(**{f'{field}__in': list(organization)})
    return qs.filter(**{field: organization})


def hours_minutes_by_client(start_date, end_date, organization=None):
    """
    Total billable + non-billable minutes by client_org for the period.
    Returns: list of {'client_id', 'client_name', 'billable_minutes',
    'nonbillable_minutes', 'total_minutes'} dicts.
    """
    from psa.models import TicketTimeEntry, Ticket
    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('ticket__organization')
    qs = scope_to_organizations(qs, 'ticket__organization', organization)

    out = {}  # client_id → row
    for te in qs:
        org = te.ticket.organization
        if not org:
            continue
        row = out.setdefault(org.id, {
            'client_id': org.id, 'client_name': org.name,
            'billable_minutes': 0, 'nonbillable_minutes': 0, 'total_minutes': 0,
        })
        mins = te.duration_minutes or 0
        if te.is_billable:
            row['billable_minutes'] += mins
        else:
            row['nonbillable_minutes'] += mins
        row['total_minutes'] += mins
    return sorted(out.values(), key=lambda r: r['total_minutes'], reverse=True)


def hours_minutes_by_tech(start_date, end_date, organization=None):
    """Same shape as `hours_minutes_by_client` but grouped by user."""
    from psa.models import TicketTimeEntry
    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('user', 'ticket__organization')
    qs = scope_to_organizations(qs, 'ticket__organization', organization)

    out = {}
    for te in qs:
        if not te.user_id:
            continue
        row = out.setdefault(te.user_id, {
            'tech_id': te.user_id,
            'tech_username': te.user.username,
            'billable_minutes': 0, 'nonbillable_minutes': 0, 'total_minutes': 0,
        })
        mins = te.duration_minutes or 0
        if te.is_billable:
            row['billable_minutes'] += mins
        else:
            row['nonbillable_minutes'] += mins
        row['total_minutes'] += mins
    return sorted(out.values(), key=lambda r: r['total_minutes'], reverse=True)


def hours_minutes_by_contract(start_date, end_date, organization=None):
    """
    Total billable + non-billable minutes per `Contract` active for the
    ticket on the entry date. Looks up the active contract per
    TicketTimeEntry's ticket via `Contract.for_ticket`.

    Returns: list of {'contract_id', 'contract_name', 'client_id',
    'client_name', 'billable_minutes', 'nonbillable_minutes',
    'total_minutes'} dicts.
    """
    from psa.models import TicketTimeEntry, Contract
    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('ticket__organization')
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    out = {}
    for te in qs:
        contract = Contract.for_ticket(te.ticket)
        if contract is None:
            continue
        row = out.setdefault(contract.id, {
            'contract_id': contract.id,
            'contract_name': contract.name,
            'client_id': contract.client_org_id,
            'client_name': contract.client_org.name if contract.client_org else '',
            'billable_minutes': 0,
            'nonbillable_minutes': 0,
            'total_minutes': 0,
        })
        mins = te.duration_minutes or 0
        if te.is_billable:
            row['billable_minutes'] += mins
        else:
            row['nonbillable_minutes'] += mins
        row['total_minutes'] += mins
    return sorted(out.values(), key=lambda r: r['total_minutes'], reverse=True)


def hours_minutes_by_project(start_date, end_date, organization=None):
    """
    Total billable + non-billable minutes per `psa.Project`. Time entries
    are linked to a project via `Ticket.project`.

    Returns: list of {'project_id', 'project_name', 'client_id',
    'client_name', 'billable_minutes', 'nonbillable_minutes',
    'total_minutes'} dicts.
    """
    from psa.models import TicketTimeEntry
    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
        ticket__project__isnull=False,
    ).select_related('ticket__project', 'ticket__project__client_org',
                     'ticket__organization')
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    out = {}
    for te in qs:
        project = te.ticket.project
        if not project:
            continue
        client = project.client_org or te.ticket.organization
        row = out.setdefault(project.id, {
            'project_id': project.id,
            'project_name': project.name,
            'client_id': client.id if client else None,
            'client_name': client.name if client else '',
            'billable_minutes': 0,
            'nonbillable_minutes': 0,
            'total_minutes': 0,
        })
        mins = te.duration_minutes or 0
        if te.is_billable:
            row['billable_minutes'] += mins
        else:
            row['nonbillable_minutes'] += mins
        row['total_minutes'] += mins
    return sorted(out.values(), key=lambda r: r['total_minutes'], reverse=True)


# ---- Revenue ---------------------------------------------------------------

def revenue_by_client(start_date, end_date, organization=None):
    """
    Sum of invoice line totals issued in the period, grouped by client.
    Counts only `sent / partial / paid` invoices (excludes draft + void).

    Returns: list of {'client_id', 'client_name', 'invoiced',
    'paid', 'outstanding'} dicts.
    """
    from psa.models import Invoice
    qs = Invoice.objects.filter(
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        status__in=['sent', 'partial', 'paid', 'overdue'],
    ).select_related('client_org')
    if organization is not None:  # scoped by customer
        qs = scope_to_organizations(qs, 'client_org', organization)

    out = {}
    for inv in qs:
        client = inv.client_org or inv.organization
        if not client:
            continue
        row = out.setdefault(client.id, {
            'client_id': client.id, 'client_name': client.name,
            'invoiced': Decimal('0'), 'paid': Decimal('0'),
        })
        row['invoiced'] += (inv.total or Decimal('0'))
        row['paid'] += (inv.amount_paid or Decimal('0'))

    for r in out.values():
        r['outstanding'] = r['invoiced'] - r['paid']
        # Cast to floats so JSON export works without Decimal serializer
        r['invoiced'] = float(r['invoiced'])
        r['paid'] = float(r['paid'])
        r['outstanding'] = float(r['outstanding'])
    return sorted(out.values(), key=lambda r: r['invoiced'], reverse=True)


def revenue_by_contract(start_date, end_date, organization=None):
    """
    Revenue attributed to each Contract active in the window. Two
    components are summed:
      1. The contract's `bundled_subtotal()` — recurring per-period bundle.
      2. Invoiced amounts (status in sent/partial/paid/overdue) where
         `Invoice.source_contract` points at this contract.

    Returns: list of {'contract_id', 'contract_name', 'client_id',
    'client_name', 'invoiced', 'bundled', 'revenue'} dicts.
    """
    from psa.models import Contract, Invoice

    contract_qs = Contract.objects.select_related('client_org')
    if organization is not None:
        contract_qs = scope_to_organizations(contract_qs, 'client_org', organization)
    # We only care about contracts active during the window
    contract_qs = contract_qs.filter(
        Q(end_date__isnull=True) | Q(end_date__gte=start_date),
        start_date__lte=end_date,
    )

    out = {}
    for c in contract_qs:
        out[c.id] = {
            'contract_id': c.id,
            'contract_name': c.name,
            'client_id': c.client_org_id,
            'client_name': c.client_org.name if c.client_org else '',
            'invoiced': Decimal('0'),
            'bundled': c.bundled_subtotal(),
            'revenue': Decimal('0'),
        }

    inv_qs = Invoice.objects.filter(
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        status__in=['sent', 'partial', 'paid', 'overdue'],
        source_contract__isnull=False,
    )
    if organization is not None:
        inv_qs = scope_to_organizations(inv_qs, 'client_org', organization)
    for inv in inv_qs:
        cid = inv.source_contract_id
        if cid not in out:
            # Contract not in active window — still attribute its revenue
            c = inv.source_contract
            out[cid] = {
                'contract_id': c.id,
                'contract_name': c.name,
                'client_id': c.client_org_id,
                'client_name': c.client_org.name if c.client_org else '',
                'invoiced': Decimal('0'),
                'bundled': c.bundled_subtotal(),
                'revenue': Decimal('0'),
            }
        out[cid]['invoiced'] += (inv.total or Decimal('0'))

    for r in out.values():
        r['revenue'] = r['invoiced'] + r['bundled']
        r['invoiced'] = float(r['invoiced'])
        r['bundled'] = float(r['bundled'])
        r['revenue'] = float(r['revenue'])
    return sorted(out.values(), key=lambda r: r['revenue'], reverse=True)


def revenue_by_project(start_date, end_date, organization=None):
    """
    Revenue per `psa.Project`. Approximated as the sum of invoiced amounts
    on tickets attached to the project — i.e., where
    `Invoice.source_ticket.project_id == project.id`.

    Returns: list of {'project_id', 'project_name', 'client_id',
    'client_name', 'revenue'} dicts.
    """
    from psa.models import Invoice

    qs = Invoice.objects.filter(
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        status__in=['sent', 'partial', 'paid', 'overdue'],
        source_ticket__project__isnull=False,
    ).select_related('source_ticket__project',
                     'source_ticket__project__client_org',
                     'source_ticket__organization')
    if organization is not None:
        qs = scope_to_organizations(qs, 'client_org', organization)

    out = {}
    for inv in qs:
        ticket = inv.source_ticket
        project = ticket.project if ticket else None
        if not project:
            continue
        client = project.client_org or ticket.organization
        row = out.setdefault(project.id, {
            'project_id': project.id,
            'project_name': project.name,
            'client_id': client.id if client else None,
            'client_name': client.name if client else '',
            'revenue': Decimal('0'),
        })
        row['revenue'] += (inv.total or Decimal('0'))

    for r in out.values():
        r['revenue'] = float(r['revenue'])
    return sorted(out.values(), key=lambda r: r['revenue'], reverse=True)


# ---- Cost ------------------------------------------------------------------
#
# Every cost, margin and attributed-revenue figure below reads its rates
# from `reports.costing`: a per-entry snapshot when the time entry carries
# one, else the effective-dated rate on the day of the work, else UNKNOWN.
# There is no default rate. Rows carry `unknown_cost_hours`,
# `unknown_cost_entries` and `is_complete`; `margin` / `margin_pct` are None
# whenever any part of the cost (or attributed revenue) is unknown.

# Legacy constant kept only because `resourcing.TechCostRate.rate_for`
# imports it for its own display fallback. No report uses it: an hour with
# no configured cost rate is reported as unknown, never costed at $60.
DEFAULT_LOADED_RATE = Decimal('60')


def cost_for_period(user, minutes, on_date):
    """
    Decimal cost of `minutes` of `user`'s time at the `TechCostRate` in
    effect on `on_date`, or None when the user has no rate for that day.
    """
    from .costing import cost_rate_for
    rate = cost_rate_for(user, on_date)
    if rate is None:
        return None
    hours = Decimal(str(minutes or 0)) / Decimal('60')
    return (hours * rate).quantize(Decimal('0.01'))


def _period_midpoint(start_date, end_date):
    """Midpoint date of the inclusive [start, end] window."""
    if not start_date and not end_date:
        return date.today()
    if not start_date:
        return end_date
    if not end_date:
        return start_date
    delta = (end_date - start_date).days // 2
    return start_date + timedelta(days=delta)


def _time_entries(start_date, end_date, organization=None):
    from psa.models import TicketTimeEntry
    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('user', 'ticket', 'ticket__organization')
    return scope_to_organizations(qs, 'ticket__organization', organization)


def _cost_rows(entries, key_fn, book=None):
    """Group `entries` by `key_fn(entry) -> (key, base_row_dict) | None` and
    tally hours / known cost / unknown cost per group."""
    from .costing import LaborTally, RateBook, entry_hours
    book = book or RateBook()
    groups = {}
    for te in entries:
        keyed = key_fn(te)
        if keyed is None:
            continue
        key, base = keyed
        row = groups.get(key)
        if row is None:
            row = groups[key] = (dict(base), LaborTally())
        row[1].add_cost(entry_hours(te), book.entry_cost_rate(te))
    out = []
    for base, tally in groups.values():
        base.update(tally.cost_fields())
        base['is_complete'] = tally.cost_complete
        out.append(base)
    return sorted(out, key=lambda r: r['cost'], reverse=True)


def cost_estimate_by_client(start_date, end_date, organization=None):
    """
    Cost of delivery per client: each time entry costed at its technician's
    rate on the day of the work (see `reports.costing`).

    Returns: list of {'client_id', 'client_name', 'hours', 'cost',
    'unknown_cost_hours', 'unknown_cost_entries', 'cost_complete',
    'is_complete'} dicts. `cost` is the known part only.
    """
    def key(te):
        org = te.ticket.organization
        if not org:
            return None
        return org.id, {'client_id': org.id, 'client_name': org.name}
    return _cost_rows(_time_entries(start_date, end_date, organization), key)


def cost_estimate_by_contract(start_date, end_date, organization=None):
    """Per-contract cost, grouped by the contract each entry belongs to
    (`RateBook.contract_for_entry`: covering the entry date)."""
    from .costing import RateBook
    book = RateBook()

    def key(te):
        contract = book.contract_for_entry(te)
        if contract is None:
            return None
        return contract.id, {
            'contract_id': contract.id,
            'contract_name': contract.name,
            'client_id': contract.client_org_id,
            'client_name': contract.client_org.name if contract.client_org_id else '',
        }
    return _cost_rows(_time_entries(start_date, end_date, organization), key, book)


def cost_estimate_by_project(start_date, end_date, organization=None):
    """Per-project cost, each entry at its technician's rate on the day."""
    qs = _time_entries(start_date, end_date, organization).filter(
        ticket__project__isnull=False,
    ).select_related('ticket__project', 'ticket__project__client_org')

    def key(te):
        project = te.ticket.project
        if not project:
            return None
        client = project.client_org or te.ticket.organization
        return project.id, {
            'project_id': project.id,
            'project_name': project.name,
            'client_id': client.id if client else None,
            'client_name': client.name if client else '',
        }
    return _cost_rows(qs, key)


# ---- Profitability ---------------------------------------------------------

_EMPTY_COST = {'hours': 0.0, 'cost': 0.0, 'unknown_cost_hours': 0.0,
               'unknown_cost_entries': 0, 'cost_complete': True}


def _profit_row(base, revenue, c):
    from .costing import margin_fields
    cost = c.get('cost', 0.0)
    row = dict(base)
    row.update({
        'revenue': revenue,
        'cost': cost,
        'hours': c.get('hours', 0.0),
        'unknown_cost_hours': c.get('unknown_cost_hours', 0.0),
        'unknown_cost_entries': c.get('unknown_cost_entries', 0),
    })
    row.update(margin_fields(revenue, cost, cost_complete=c.get('cost_complete', True)))
    return row


def profitability_by_client(start_date, end_date, organization=None):
    """
    Combine invoiced revenue + labour cost into per-client rows.
    Returns: list of {'client_id', 'client_name', 'revenue', 'cost',
    'margin', 'margin_pct', 'hours', 'unknown_cost_hours',
    'unknown_cost_entries', 'is_complete'} dicts, sorted by revenue desc.
    `margin` / `margin_pct` are None when any hour lacks a cost rate.
    """
    rev = {r['client_id']: r for r in revenue_by_client(start_date, end_date, organization)}
    cost = {r['client_id']: r for r in cost_estimate_by_client(start_date, end_date, organization)}
    rows = []
    for cid in set(rev) | set(cost):
        r = rev.get(cid, {})
        c = cost.get(cid, _EMPTY_COST)
        rows.append(_profit_row({
            'client_id': cid,
            'client_name': r.get('client_name') or c.get('client_name') or '?',
        }, r.get('invoiced', 0.0), c))
    return sorted(rows, key=lambda r: r['revenue'], reverse=True)


def profitability_by_contract(start_date, end_date, organization=None):
    """Per-contract profitability. Same shape as `profitability_by_client`
    but pivoted on Contract."""
    rev = {r['contract_id']: r for r in revenue_by_contract(start_date, end_date, organization)}
    cost = {r['contract_id']: r for r in cost_estimate_by_contract(start_date, end_date, organization)}
    rows = []
    for cid in set(rev) | set(cost):
        r = rev.get(cid, {})
        c = cost.get(cid, _EMPTY_COST)
        rows.append(_profit_row({
            'contract_id': cid,
            'contract_name': r.get('contract_name') or c.get('contract_name') or '?',
            'client_id': r.get('client_id') or c.get('client_id'),
            'client_name': r.get('client_name') or c.get('client_name') or '',
        }, r.get('revenue', 0.0), c))
    return sorted(rows, key=lambda r: r['revenue'], reverse=True)


def profitability_by_project(start_date, end_date, organization=None):
    """Per-project profitability. Same shape pivoted on Project."""
    rev = {r['project_id']: r for r in revenue_by_project(start_date, end_date, organization)}
    cost = {r['project_id']: r for r in cost_estimate_by_project(start_date, end_date, organization)}
    rows = []
    for pid in set(rev) | set(cost):
        r = rev.get(pid, {})
        c = cost.get(pid, _EMPTY_COST)
        rows.append(_profit_row({
            'project_id': pid,
            'project_name': r.get('project_name') or c.get('project_name') or '?',
            'client_id': r.get('client_id') or c.get('client_id'),
            'client_name': r.get('client_name') or c.get('client_name') or '',
        }, r.get('revenue', 0.0), c))
    return sorted(rows, key=lambda r: r['revenue'], reverse=True)


def available_hours(user, start_date, end_date):
    """
    Hours `user` was available to work in [start, end], or (None, None)
    when nothing says so.

    Basis, in order: the shift schedule (non-on-call shifts), else
    WorkingHours rows, each skipping holidays and approved leave; else the
    weekly BillableTarget pro-rated to the window. Returns
    (hours: Decimal | None, basis: 'shifts' | 'working_hours' |
    'billable_target' | None).
    """
    from resourcing.models import BillableTarget, Holiday, LeaveRequest
    from resourcing import shifts as _shifts

    def _skip(day):
        return Holiday.is_holiday(day) or LeaveRequest.is_user_on_leave(user, day)

    days = []
    cur = start_date
    while cur <= end_date:
        days.append(cur)
        cur += timedelta(days=1)

    rows = list(_shifts.assignments_qs(user))
    if rows:
        tz = _shifts.user_tz(user)
        minutes = 0
        for day in days:
            if _skip(day):
                continue
            for s in _shifts.shifts_on(user, day, rows=rows, tz=tz):
                if not s.on_call:
                    minutes += s.template.duration_minutes
        return Decimal(minutes) / Decimal('60'), 'shifts'

    whs = list(user.resourcing_working_hours.filter(is_active=True))
    if whs:
        by_weekday = {}
        for wh in whs:
            mins = ((wh.end_time.hour * 60 + wh.end_time.minute)
                    - (wh.start_time.hour * 60 + wh.start_time.minute))
            if mins > 0:
                by_weekday[wh.weekday] = by_weekday.get(wh.weekday, 0) + mins
        minutes = sum(by_weekday.get(d.weekday(), 0) for d in days
                      if by_weekday.get(d.weekday()) and not _skip(d))
        return Decimal(minutes) / Decimal('60'), 'working_hours'

    bt = BillableTarget.objects.filter(user=user, is_active=True).first()
    if bt and bt.target_hours_per_week:
        weeks = Decimal(len(days)) / Decimal('7')
        return Decimal(str(bt.target_hours_per_week)) * weeks, 'billable_target'
    return None, None


def technician_utilization(start_date, end_date, organization=None, users=None):
    """
    Billable hours ÷ available hours per technician who logged time in the
    window (or each of `users`). `utilization_pct` is None when the
    technician has no shifts, working hours or billable target to measure
    against.

    Returns: list of {'tech_id', 'tech_username', 'hours',
    'billable_hours', 'available_hours', 'basis', 'utilization_pct'}.
    """
    qs = _time_entries(start_date, end_date, organization).filter(user__isnull=False)
    per = {}
    for te in qs:
        row = per.setdefault(te.user_id, {'user': te.user, 'minutes': 0, 'billable_minutes': 0})
        row['minutes'] += te.duration_minutes or 0
        if te.is_billable:
            row['billable_minutes'] += te.duration_minutes or 0
    for u in users or []:
        per.setdefault(u.pk, {'user': u, 'minutes': 0, 'billable_minutes': 0})

    out = []
    for uid, row in per.items():
        avail, basis = available_hours(row['user'], start_date, end_date)
        billable = Decimal(row['billable_minutes']) / Decimal('60')
        util = (round(float(billable / avail * 100), 1)
                if avail is not None and avail > 0 else None)
        out.append({
            'tech_id': uid,
            'tech_username': row['user'].username,
            'hours': round(row['minutes'] / 60.0, 2),
            'billable_hours': float(round(billable, 2)),
            'available_hours': float(round(avail, 2)) if avail is not None else None,
            'basis': basis,
            'utilization_pct': util,
        })
    return sorted(out, key=lambda r: r['tech_username'])


def profitability_by_tech(start_date, end_date, organization=None):
    """
    Per-tech profitability and utilization.

    Cost: each entry × the tech's cost rate on the day of the work.
    Attributed revenue: each billable entry × its bill rate (entry snapshot,
    else the covering contract's hourly / overage rate). Entries without a
    rate are counted in `unknown_cost_*` / `unknown_bill_*` instead of being
    priced at a default, and `margin` is None while either side is
    incomplete.
    Utilization: billable hours ÷ available hours (`technician_utilization`).

    Returns: list of {'tech_id', 'tech_username', 'hours',
    'billable_minutes', 'cost', 'attributed_revenue', 'margin',
    'margin_pct', 'utilization_pct', 'unknown_cost_hours',
    'unknown_cost_entries', 'unknown_bill_hours', 'unknown_bill_entries',
    'is_complete'} dicts, sorted by attributed_revenue desc.
    """
    from .costing import LaborTally, RateBook, entry_hours, margin_fields

    book = RateBook()
    tallies = {}
    users = {}
    for te in _time_entries(start_date, end_date, organization):
        if not te.user_id:
            continue
        users[te.user_id] = te.user
        tally = tallies.setdefault(te.user_id, LaborTally())
        hours = entry_hours(te)
        tally.add_cost(hours, book.entry_cost_rate(te))
        if te.is_billable:
            tally.add_revenue(hours, book.bill_rate_for(te), te.duration_minutes)

    util = {r['tech_id']: r for r in technician_utilization(
        start_date, end_date, organization, users=list(users.values()))}

    rows = []
    for uid, tally in tallies.items():
        c = tally.cost_fields()
        rv = tally.revenue_fields()
        row = {
            'tech_id': uid,
            'tech_username': users[uid].username,
            'hours': c['hours'],
            'billable_minutes': tally.billable_minutes,
            'cost': c['cost'],
            'attributed_revenue': rv['attributed_revenue'],
            'unknown_cost_hours': c['unknown_cost_hours'],
            'unknown_cost_entries': c['unknown_cost_entries'],
            'unknown_bill_hours': rv['unknown_bill_hours'],
            'unknown_bill_entries': rv['unknown_bill_entries'],
            'cost_complete': c['cost_complete'],
            'revenue_complete': rv['revenue_complete'],
            'utilization_pct': util.get(uid, {}).get('utilization_pct'),
            'utilization_basis': util.get(uid, {}).get('basis'),
        }
        row.update(margin_fields(rv['attributed_revenue'], c['cost'],
                                 cost_complete=tally.cost_complete,
                                 revenue_complete=tally.revenue_complete))
        rows.append(row)
    return sorted(rows, key=lambda r: r['attributed_revenue'], reverse=True)

# ---- Phase 3.3: Effective hourly rate + Revenue leakage --------------------

def effective_hourly_rate_by_client(start_date, end_date, organization=None):
    """
    Per-client effective hourly rate = revenue / billable_hours.

    Returns: list of {'client_id', 'client_name', 'revenue',
    'billable_hours', 'nonbillable_hours', 'effective_rate',
    'utilization_ratio'} dicts.
    `effective_rate` is 0.0 when billable_hours = 0 (no work logged).
    `utilization_ratio` = billable_minutes / total_minutes (signals giveaway).
    """
    rev = {r['client_id']: r for r in revenue_by_client(start_date, end_date, organization)}
    hrs = {r['client_id']: r for r in hours_minutes_by_client(start_date, end_date, organization)}
    client_ids = set(rev.keys()) | set(hrs.keys())

    out = []
    for cid in client_ids:
        r = rev.get(cid, {})
        h = hrs.get(cid, {})
        revenue = r.get('invoiced', 0.0)
        billable_min = h.get('billable_minutes', 0)
        nonbillable_min = h.get('nonbillable_minutes', 0)
        total_min = h.get('total_minutes', 0)
        billable_hours = billable_min / 60.0
        eff_rate = (revenue / billable_hours) if billable_hours else 0.0
        util_ratio = (billable_min / total_min) if total_min else 0.0
        out.append({
            'client_id': cid,
            'client_name': r.get('client_name') or h.get('client_name') or '?',
            'revenue': revenue,
            'billable_hours': round(billable_hours, 2),
            'nonbillable_hours': round(nonbillable_min / 60.0, 2),
            'effective_rate': round(eff_rate, 2),
            'utilization_ratio': round(util_ratio, 3),
        })
    return sorted(out, key=lambda r: r['effective_rate'], reverse=True)


def effective_hourly_rate_by_tech(start_date, end_date, organization=None):
    """
    Per-tech effective hourly rate = (attributed revenue) / billable_hours.

    Reuses `profitability_by_tech`. `cost_rate` is the tech's blended
    loaded rate over the window (known cost ÷ hours, each entry at the rate
    in effect on its day); realization_pct = effective_rate / cost_rate ×
    100 (target ≥ 200%).

    `effective_rate` is None when some billable hours have no bill rate;
    `cost_rate` and `realization_pct` are None when some hours have no cost
    rate. Unknown is reported as unknown, not as a default.

    Returns: list of {'tech_id', 'tech_username', 'attributed_revenue',
    'billable_hours', 'effective_rate', 'cost_rate', 'realization_pct',
    'unknown_cost_hours', 'unknown_bill_hours', 'is_complete'}.
    """
    rows = profitability_by_tech(start_date, end_date, organization=organization)

    out = []
    for r in rows:
        billable_hours = (r.get('billable_minutes', 0) or 0) / 60.0
        revenue = r.get('attributed_revenue', 0.0) or 0.0
        if not r['revenue_complete']:
            eff_rate = None
        else:
            eff_rate = round(revenue / billable_hours, 2) if billable_hours else 0.0
        hours = r.get('hours') or 0.0
        if r['cost_complete'] and hours:
            cost_rate = round(r['cost'] / hours, 2)
        else:
            cost_rate = None
        realization = (round(eff_rate / cost_rate * 100, 1)
                       if eff_rate is not None and cost_rate else None)
        out.append({
            'tech_id': r['tech_id'],
            'tech_username': r['tech_username'],
            'attributed_revenue': round(revenue, 2),
            'billable_hours': round(billable_hours, 2),
            'effective_rate': eff_rate,
            'cost_rate': cost_rate,
            'realization_pct': realization,
            'unknown_cost_hours': r['unknown_cost_hours'],
            'unknown_cost_entries': r['unknown_cost_entries'],
            'unknown_bill_hours': r['unknown_bill_hours'],
            'unknown_bill_entries': r['unknown_bill_entries'],
            'is_complete': r['is_complete'],
        })
    return sorted(out, key=lambda r: (r['effective_rate'] is not None, r['effective_rate'] or 0),
                  reverse=True)


def revenue_leakage(start_date, end_date, organization=None,
                    stale_days=30):
    """
    Three categories of leakage:
      1. **Stale unbilled time** — billable TicketTimeEntry rows ≥
         `stale_days` old that aren't on any invoice. TicketTimeEntry has
         no direct `invoice` FK; we use `InvoiceLineItem.source='time'` +
         `source_id=str(entry.pk)` as the heuristic linkage. An entry is
         considered "billed" if any non-void invoice line points at it.
      2. **Expired contract blocks** — Contract rows with `status='expired'`
         where `hours_used < total_hours` (paid for hours never used —
         these aren't recoverable but they signal client churn risk).
      3. **Stuck draft invoices** — `Invoice` rows in `draft` status whose
         `invoice_date` is older than 14 days. Money that should've been
         sent.

    `start_date` / `end_date` here are accepted for parity with sibling
    queries; for stale-unbilled the cutoff is `today - stale_days` (we
    look back FROM today, not at the bounded window). Expired blocks are
    not date-windowed — once expired they stay leaky regardless of when.
    Stuck drafts are bounded by the `start_date` lower bound to avoid
    showing ancient junk drafts.

    Returns dict:
      {
        'stale_unbilled': [...],
        'expired_blocks': [...],
        'stuck_drafts':   [...],
        'totals': {'stale': float, 'expired_blocks': float,
                   'stuck': float, 'grand_total': float,
                   'stale_hours_without_rate': float,
                   'stale_entries_without_rate': int,
                   'expired_blocks_without_rate': int,
                   'is_complete': bool},
        'stale_days': int,
      }

    Amounts are the known part only: time without a bill rate and expired
    blocks without an hourly rate are counted, not priced (`is_complete`).
    """
    from datetime import timedelta
    from django.utils import timezone
    from psa.models import TicketTimeEntry, Contract, Invoice, InvoiceLineItem

    today = timezone.localdate()
    stale_cutoff = today - timedelta(days=stale_days)
    stuck_cutoff = today - timedelta(days=14)

    # --- 1. Stale unbilled time ---------------------------------------------
    # TicketTimeEntry has no direct Invoice FK: an entry is billed when a
    # live invoice line (source='time', source_id=entry pk) points at it.
    # Each entry is valued at its own bill rate (reports.costing); entries
    # without one are counted in `hours_without_rate` and left out of the
    # amount instead of being priced at a made-up rate.
    from .costing import RateBook, entry_hours
    book = RateBook()
    billed_entry_ids = InvoiceLineItem.billed_source_ids('time')

    te_qs = TicketTimeEntry.objects.filter(
        is_billable=True,
        started_at__date__lte=stale_cutoff,
    ).select_related('ticket__organization', 'user')
    te_qs = scope_to_organizations(te_qs, 'ticket__organization', organization)

    stale_rows = {}
    for te in te_qs:
        if te.id in billed_entry_ids:
            continue  # already on an invoice
        client = te.ticket.organization
        if not client:
            continue
        row = stale_rows.setdefault(client.id, {
            'client_id': client.id, 'client_name': client.name,
            'oldest_at': te.started_at, 'entry_count': 0,
            'minutes': 0, 'amount': Decimal('0'),
            'unrated_hours': Decimal('0'), 'unrated_entries': 0,
        })
        row['entry_count'] += 1
        row['minutes'] += (te.duration_minutes or 0)
        hours = entry_hours(te)
        rate = book.bill_rate_for(te)
        if rate is None:
            if hours > 0:
                row['unrated_hours'] += hours
                row['unrated_entries'] += 1
        else:
            row['amount'] += hours * rate
        if te.started_at < row['oldest_at']:
            row['oldest_at'] = te.started_at

    stale_out = []
    for cid, row in stale_rows.items():
        stale_out.append({
            'client_id': row['client_id'],
            'client_name': row['client_name'],
            'oldest_at': row['oldest_at'].isoformat() if row['oldest_at'] else None,
            'entry_count': row['entry_count'],
            'hours_at_risk': round(row['minutes'] / 60.0, 2),
            'amount_at_risk': round(float(row['amount']), 2),
            'hours_without_rate': float(round(row['unrated_hours'], 2)),
            'entries_without_rate': row['unrated_entries'],
            'is_complete': row['unrated_entries'] == 0,
        })
    stale_out.sort(key=lambda r: r['amount_at_risk'], reverse=True)

    # --- 2. Expired contract blocks ----------------------------------------
    expired_qs = Contract.objects.filter(status='expired').select_related('client_org')
    expired_qs = scope_to_organizations(expired_qs, 'client_org', organization)
    expired_out = []
    for c in expired_qs:
        if not c.total_hours or c.hours_used >= float(c.total_hours):
            continue
        unused = float(c.total_hours) - c.hours_used
        rate = book.contract_bill_rate(c)
        expired_out.append({
            'client_id': c.client_org_id,
            'client_name': c.client_org.name if c.client_org else '?',
            'contract_id': c.id,
            'contract_name': c.name,
            'unused_hours': round(unused, 2),
            # None = the contract has no hourly rate to value the hours at.
            'unused_value': round(unused * float(rate), 2) if rate is not None else None,
        })
    expired_out.sort(key=lambda r: r['unused_value'] or 0, reverse=True)

    # --- 3. Stuck drafts ----------------------------------------------------
    stuck_qs = Invoice.objects.filter(
        status='draft', invoice_date__lte=stuck_cutoff,
    ).select_related('client_org')
    stuck_qs = scope_to_organizations(stuck_qs, 'client_org', organization)
    stuck_out = []
    for inv in stuck_qs:
        days_stuck = (today - inv.invoice_date).days
        stuck_out.append({
            'invoice_id': inv.id,
            'invoice_number': inv.invoice_number,
            'client_id': inv.client_org_id,
            'client_name': inv.client_org.name if inv.client_org else '?',
            'amount': float(inv.total or 0),
            'days_stuck': days_stuck,
        })
    stuck_out.sort(key=lambda r: r['amount'], reverse=True)

    totals = {
        'stale': round(sum(r['amount_at_risk'] for r in stale_out), 2),
        'expired_blocks': round(sum(r['unused_value'] or 0 for r in expired_out), 2),
        'stuck': round(sum(r['amount'] for r in stuck_out), 2),
        'stale_hours_without_rate': round(sum(r['hours_without_rate'] for r in stale_out), 2),
        'stale_entries_without_rate': sum(r['entries_without_rate'] for r in stale_out),
        'expired_blocks_without_rate': sum(1 for r in expired_out if r['unused_value'] is None),
    }
    totals['is_complete'] = (totals['stale_entries_without_rate'] == 0
                             and totals['expired_blocks_without_rate'] == 0)
    totals['grand_total'] = round(
        totals['stale'] + totals['expired_blocks'] + totals['stuck'], 2
    )

    return {
        'stale_unbilled': stale_out,
        'expired_blocks': expired_out,
        'stuck_drafts': stuck_out,
        'totals': totals,
        'stale_days': stale_days,
    }


# ---- Phase 3.4: SLA trends + Margin analytics by service line --------------

def sla_trend_by_priority(start_date, end_date, organization=None, bucket='week'):
    """
    Per-priority SLA breach rate over time.

    Buckets the period into ``bucket='day'|'week'|'month'`` slots. For each
    bucket × priority, computes:
      - tickets_in_bucket: # of tickets with created_at falling in bucket
      - response_breaches: # whose first_response_at > first_response_due_at
                           (or never responded + due has passed)
      - resolution_breaches: # closed tickets where closed_at >
                             resolution_due_at
      - response_breach_pct, resolution_breach_pct

    Returns chart-friendly parallel arrays keyed by priority code.
    """
    from django.utils import timezone
    from psa.models import Ticket

    # Build buckets: list of (label, start_date, end_date)
    buckets = []
    if bucket == 'day':
        cur = start_date
        while cur <= end_date:
            buckets.append((cur.strftime('%m/%d'), cur, cur))
            cur += timedelta(days=1)
    elif bucket == 'month':
        cur = start_date.replace(day=1)
        while cur <= end_date:
            if cur.month == 12:
                next_start = date(cur.year + 1, 1, 1)
            else:
                next_start = date(cur.year, cur.month + 1, 1)
            end = min(end_date, next_start - timedelta(days=1))
            label = cur.strftime('%Y-%m')
            buckets.append((label, max(cur, start_date), end))
            cur = next_start
    else:  # week (ISO Mon-Sun)
        cur = start_date - timedelta(days=start_date.weekday())  # Mon
        while cur <= end_date:
            week_end = cur + timedelta(days=6)
            label = cur.strftime('%m/%d')
            buckets.append((label, max(cur, start_date), min(week_end, end_date)))
            cur += timedelta(days=7)

    priorities = ['P1', 'P2', 'P3', 'P4', 'P5']
    now = timezone.now()
    series = {p: [] for p in priorities}
    totals = {p: {'tickets': 0, 'response_breaches': 0, 'resolution_breaches': 0}
              for p in priorities}

    for label, b_start, b_end in buckets:
        for p in priorities:
            qs = Ticket.objects.filter(
                priority__code=p,
                created_at__date__gte=b_start,
                created_at__date__lte=b_end,
            )
            qs = scope_to_organizations(qs, 'organization', organization)
            cnt = qs.count()

            # Response breaches: first_response_due_at exists, AND either
            #   first_response_at > first_response_due_at, OR no first_response
            #   yet AND now() > first_response_due_at
            resp_breach = qs.exclude(first_response_due_at__isnull=True).filter(
                Q(first_response_at__gt=F('first_response_due_at'))
                | Q(first_response_at__isnull=True,
                    first_response_due_at__lt=now)
            ).count()

            # Resolution breaches: only on tickets that have closed
            res_breach = qs.exclude(resolution_due_at__isnull=True).filter(
                closed_at__gt=F('resolution_due_at')
            ).count()

            row = {
                'bucket': label,
                'tickets': cnt,
                'response_breaches': resp_breach,
                'resolution_breaches': res_breach,
                'response_pct': round((resp_breach / cnt * 100), 1) if cnt else 0.0,
                'resolution_pct': round((res_breach / cnt * 100), 1) if cnt else 0.0,
            }
            series[p].append(row)
            totals[p]['tickets'] += cnt
            totals[p]['response_breaches'] += resp_breach
            totals[p]['resolution_breaches'] += res_breach

    # Compute summary pcts
    for p, t in totals.items():
        t['response_pct'] = round((t['response_breaches'] / t['tickets'] * 100), 1) if t['tickets'] else 0.0
        t['resolution_pct'] = round((t['resolution_breaches'] / t['tickets'] * 100), 1) if t['tickets'] else 0.0

    return {
        'buckets': [b[0] for b in buckets],
        'priorities': priorities,
        'series': series,
        'totals_by_priority': totals,
    }


def sla_trend_by_client(start_date, end_date, organization=None, top_n=10):
    """
    Per-client breach rate summary over the window. Returns top N clients
    by ticket volume so the chart doesn't blow up for installs with 100s.

    Returns: list of {'client_id', 'client_name', 'tickets',
    'response_breaches', 'resolution_breaches', 'response_pct',
    'resolution_pct'} sorted by tickets desc.
    """
    from django.utils import timezone
    from psa.models import Ticket
    qs = Ticket.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).select_related('organization')
    if organization is not None:
        qs = qs.filter(organization=organization)

    by_client = {}
    now = timezone.now()
    for t in qs:
        if not t.organization_id:
            continue
        row = by_client.setdefault(t.organization_id, {
            'client_id': t.organization_id,
            'client_name': t.organization.name,
            'tickets': 0,
            'response_breaches': 0,
            'resolution_breaches': 0,
        })
        row['tickets'] += 1
        if t.first_response_due_at:
            if (t.first_response_at and t.first_response_at > t.first_response_due_at) or \
               (not t.first_response_at and t.first_response_due_at < now):
                row['response_breaches'] += 1
        if t.resolution_due_at and t.closed_at and t.closed_at > t.resolution_due_at:
            row['resolution_breaches'] += 1

    rows = list(by_client.values())
    for r in rows:
        r['response_pct'] = round((r['response_breaches'] / r['tickets'] * 100), 1) if r['tickets'] else 0.0
        r['resolution_pct'] = round((r['resolution_breaches'] / r['tickets'] * 100), 1) if r['tickets'] else 0.0
    rows.sort(key=lambda r: r['tickets'], reverse=True)
    return rows[:top_n]


def margin_analytics_by_service_line(start_date, end_date, organization=None,
                                     dimension='ticket_type'):
    """
    Margin grouped by 'service line' — either Ticket.ticket_type,
    Ticket.closure_category, or Ticket.queue. Useful for seeing which
    buckets of work are profitable vs. which are loss leaders.

    Per TicketTimeEntry (rates from `reports.costing`):
      revenue = billable hours × the entry's bill rate (snapshot, else the
                covering contract's hourly / overage rate);
      cost    = hours (billable or not — unbilled work still costs) × the
                tech's cost rate on the day of the work.
    Entries without a rate are counted in `unknown_*` and `margin` is None
    for a group with any.

    dimension: 'ticket_type' | 'closure_category' | 'queue'
    """
    from .costing import LaborTally, RateBook, entry_hours, margin_fields

    book = RateBook()
    qs = _time_entries(start_date, end_date, organization).select_related(
        'ticket__ticket_type', 'ticket__queue',
    )

    out = {}
    for te in qs:
        ticket = te.ticket
        if dimension == 'ticket_type':
            key = ticket.ticket_type_id or 0
            label = ticket.ticket_type.name if ticket.ticket_type_id else '—'
        elif dimension == 'closure_category':
            key = ticket.closure_category or '_unset'
            label = ticket.get_closure_category_display() if ticket.closure_category else 'Unset'
        elif dimension == 'queue':
            key = ticket.queue_id or 0
            label = ticket.queue.name if ticket.queue_id else '—'
        else:
            key = '_unknown'
            label = 'Unknown'

        row = out.setdefault(key, {'key': str(key), 'label': label,
                                   'tickets': set(), 'tally': LaborTally()})
        row['tickets'].add(ticket.id)
        hours = entry_hours(te)
        row['tally'].add_cost(hours, book.entry_cost_rate(te))
        if te.is_billable:
            row['tally'].add_revenue(hours, book.bill_rate_for(te), te.duration_minutes)

    rows = []
    for r in out.values():
        t = r['tally']
        c = t.cost_fields()
        rv = t.revenue_fields()
        row = {
            'key': r['key'], 'label': r['label'],
            'tickets': len(r['tickets']),
            'hours': c['hours'],
            'billable_hours': rv['billable_hours'],
            'revenue': rv['attributed_revenue'],
            'cost': c['cost'],
            'unknown_cost_hours': c['unknown_cost_hours'],
            'unknown_cost_entries': c['unknown_cost_entries'],
            'unknown_bill_hours': rv['unknown_bill_hours'],
            'unknown_bill_entries': rv['unknown_bill_entries'],
        }
        row.update(margin_fields(row['revenue'], row['cost'],
                                 cost_complete=t.cost_complete,
                                 revenue_complete=t.revenue_complete))
        rows.append(row)
    rows.sort(key=lambda r: r['revenue'], reverse=True)
    return rows


# ---- Phase 3.6 wave B: Client-health score ---------------------------------

def client_health_score(client_org_id, ref_date=None):
    """
    Composite client-health score (0-100, higher = healthier). Returns dict
    with score, category, components, and explanatory metrics.

    Weighted components:
      - SLA hits           (30 pts) — (1 - resolution_breach_rate_30d) × 30
      - Ticket velocity    (20 pts) — opened ≤ closed → full; else scaled
      - Billing aging      (25 pts) — (1 - over_60d / total_outstanding) × 25
      - Engagement         (15 pts) — any tickets in 30d → full
      - NPS proxy          (10 pts) — neutral 7/10 default

    Categories:
      - Healthy   ≥ 80  (success / green)
      - At-risk   60-80 (warning / amber)
      - Trouble   < 60  (danger / red)
    """
    from django.utils import timezone
    from psa.models import Ticket, Invoice
    from core.models import Organization

    ref = ref_date or timezone.localdate()
    start_30 = ref - timedelta(days=29)

    org = Organization.objects.filter(pk=client_org_id).first()
    if not org:
        return None

    # --- SLA component ------------------------------------------------------
    tix = Ticket.objects.filter(
        organization_id=client_org_id,
        created_at__date__gte=start_30,
        created_at__date__lte=ref,
    )
    total_tix = tix.count()
    breaches = tix.filter(
        resolution_due_at__isnull=False,
        closed_at__isnull=False,
        closed_at__gt=F('resolution_due_at'),
    ).count()
    sla_rate = (1 - breaches / total_tix) if total_tix else 1.0
    sla_score = sla_rate * 30

    # --- Velocity component -------------------------------------------------
    opened = Ticket.objects.filter(
        organization_id=client_org_id,
        created_at__date__gte=start_30,
    ).count()
    closed = Ticket.objects.filter(
        organization_id=client_org_id,
        closed_at__date__gte=start_30,
    ).count()
    if opened == 0:
        velocity_score = 20
    elif closed >= opened:
        velocity_score = 20
    else:
        velocity_score = max(0, 20 * (closed / opened))

    # --- Billing aging component -------------------------------------------
    inv_qs = Invoice.objects.filter(
        client_org_id=client_org_id,
        status__in=['sent', 'partial', 'overdue'],
    )
    total_outstanding = sum(
        float((inv.total or 0) - (inv.amount_paid or 0)) for inv in inv_qs
    )
    over_60 = 0.0
    for inv in inv_qs:
        if inv.due_date and (ref - inv.due_date).days > 60:
            over_60 += float((inv.total or 0) - (inv.amount_paid or 0))
    if total_outstanding == 0:
        aging_score = 25
    else:
        aging_score = max(0, 25 * (1 - over_60 / total_outstanding))

    # --- Engagement component ----------------------------------------------
    if total_tix == 0:
        # No activity is itself a yellow flag — half credit.
        engagement_score = 7.5
    else:
        engagement_score = 15

    # --- NPS proxy component -----------------------------------------------
    # Neutral 7/10 default — placeholder until a real CSAT field is wired up.
    nps_raw = 7  # 0-10 scale
    nps_weighted = (nps_raw / 10.0) * 10  # → 7.0 of 10 max

    # --- Total + category --------------------------------------------------
    total = round(sla_score + velocity_score + aging_score
                  + engagement_score + nps_weighted)
    if total >= 80:
        category = 'healthy'
        color = 'success'
    elif total >= 60:
        category = 'at_risk'
        color = 'warning'
    else:
        category = 'trouble'
        color = 'danger'

    return {
        'client_id': client_org_id,
        'client_name': org.name,
        'score': total,
        'category': category,
        'color': color,
        'components': {
            'sla': round(sla_score, 1),
            'velocity': round(velocity_score, 1),
            'aging': round(aging_score, 1),
            'engagement': round(engagement_score, 1),
            'nps': round(nps_weighted, 1),
        },
        'metrics': {
            'total_tickets_30d': total_tix,
            'tickets_opened': opened,
            'tickets_closed': closed,
            'sla_breaches': breaches,
            'total_outstanding': round(total_outstanding, 2),
            'over_60_days': round(over_60, 2),
        },
    }


def client_health_scores_all(organization_filter=None):
    """Compute health score for every active client. Returns list sorted by
    score asc (worst clients first — most-actionable view)."""
    from core.models import Organization
    qs = Organization.objects.filter(is_active=True)
    qs = scope_to_organizations(qs, 'pk', organization_filter)
    rows = []
    for org in qs:
        s = client_health_score(org.pk)
        if s:
            rows.append(s)
    return sorted(rows, key=lambda r: r['score'])


# ---------------------------------------------------------------------------
# Phase 5.2 — CRM sales funnel
# ---------------------------------------------------------------------------

def sales_funnel(start_date, end_date, organization=None):
    """
    Sales funnel conversion rates across the period.

    Stages tracked:
      Leads created → Leads qualified → Opportunities created
      → Proposal stage → Closed Won

    Returns dict:
      {
        'stages': [
          {'name': 'Leads', 'count': N, 'value': 0},
          {'name': 'Qualified', 'count': N, 'value': 0},
          {'name': 'Opportunities', 'count': N, 'value': sum estimated_value},
          {'name': 'Proposal', 'count': N, 'value': sum},
          {'name': 'Closed Won', 'count': N, 'value': sum},
        ],
        'conversion_rates': {  # stage_to_stage percentages
          'lead_to_qualified': float,
          'qualified_to_opp': float,
          'opp_to_proposal': float,
          'proposal_to_closed_won': float,
          'lead_to_won': float,  # end-to-end
        },
        'total_won_value': float,
      }
    """
    from crm.models import Lead, Opportunity
    leads_qs = Lead.objects.filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date,
    )
    if organization is not None:
        leads_qs = leads_qs.filter(organization=organization)
    leads_n = leads_qs.count()
    qualified_n = leads_qs.filter(status__in=['qualified', 'converted']).count()

    opps_qs = Opportunity.objects.filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date,
    )
    if organization is not None:
        opps_qs = opps_qs.filter(organization=organization)
    opps_n = opps_qs.count()
    opps_value = float(sum((o.estimated_value or 0) for o in opps_qs))

    proposal_qs = opps_qs.filter(stage__in=['proposal', 'negotiation', 'closed_won'])
    proposal_n = proposal_qs.count()
    proposal_value = float(sum((o.estimated_value or 0) for o in proposal_qs))

    won_qs = opps_qs.filter(stage='closed_won')
    won_n = won_qs.count()
    won_value = float(sum((o.estimated_value or 0) for o in won_qs))

    def pct(num, den):
        return round((num / den * 100) if den else 0.0, 1)

    return {
        'stages': [
            {'name': 'Leads', 'count': leads_n, 'value': 0},
            {'name': 'Qualified', 'count': qualified_n, 'value': 0},
            {'name': 'Opportunities', 'count': opps_n, 'value': opps_value},
            {'name': 'Proposal', 'count': proposal_n, 'value': proposal_value},
            {'name': 'Closed Won', 'count': won_n, 'value': won_value},
        ],
        'conversion_rates': {
            'lead_to_qualified': pct(qualified_n, leads_n),
            'qualified_to_opp': pct(opps_n, qualified_n),
            'opp_to_proposal': pct(proposal_n, opps_n),
            'proposal_to_closed_won': pct(won_n, proposal_n),
            'lead_to_won': pct(won_n, leads_n),
        },
        'total_won_value': won_value,
    }


# ---------------------------------------------------------------------------
# Phase 9.4 — Security alert MTTA (Mean Time To Acknowledge)
# ---------------------------------------------------------------------------

def security_alert_mtta(start_date, end_date, organization=None):
    """
    Mean Time To Acknowledge for security alerts in the window.

    Returns: list of {'client_id', 'client_name', 'vendor',
    'count', 'avg_mtta_minutes', 'unack_count'} rows.
    """
    from security_alerts.models import SecurityAlert
    qs = SecurityAlert.objects.filter(
        seen_at__date__gte=start_date,
        seen_at__date__lte=end_date,
    ).select_related('client_org', 'connection')
    if organization is not None:
        qs = qs.filter(organization=organization)

    out = {}
    for a in qs:
        client_id = a.client_org_id or 0
        # SIEM-ingested alerts have no vendor connection.
        conn = a.connection
        provider = conn.provider if conn is not None else 'siem'
        key = (client_id, provider)
        row = out.setdefault(key, {
            'client_id': client_id,
            'client_name': a.client_org.name if a.client_org else '(unscoped)',
            'vendor': conn.get_provider_display() if conn is not None else 'SIEM',
            'count': 0, 'mtta_total': 0, 'mtta_count': 0, 'unack_count': 0,
        })
        row['count'] += 1
        if a.acknowledged_at:
            row['mtta_total'] += int((a.acknowledged_at - a.seen_at).total_seconds() / 60)
            row['mtta_count'] += 1
        else:
            row['unack_count'] += 1
    rows = []
    for r in out.values():
        rows.append({
            'client_id': r['client_id'], 'client_name': r['client_name'],
            'vendor': r['vendor'], 'count': r['count'],
            'avg_mtta_minutes': (r['mtta_total'] / r['mtta_count']) if r['mtta_count'] else None,
            'unack_count': r['unack_count'],
        })
    return sorted(rows, key=lambda r: r['count'], reverse=True)


# ---------------------------------------------------------------------------
# MSP-wide business metrics: recurring revenue, churn, service lines,
# utilization, unbilled time, upcoming expirations.
#
# One install serves one MSP; every Organization is one of its customers. These
# aggregate across all customers, or across `organization` (one customer or a
# list — pass reports.access.viewer_client_scope(user) so a technician with a
# limited client scope only adds up their customers). Contracts and invoices
# are scoped by `client_org` (the customer). Each function returns
# completeness flags for inputs it could not use, so a dashboard can show
# "incomplete" instead of a confident wrong number.
# ---------------------------------------------------------------------------

MONTHS_PER_PERIOD = {'monthly': Decimal('1'), 'quarterly': Decimal('3'), 'yearly': Decimal('12')}


def monthly_amount(contract):
    """A contract's recurring amount normalized to one month, or None when
    it has no recurring billing frequency or amount."""
    months = MONTHS_PER_PERIOD.get(contract.billing_frequency)
    if months is None:
        return None
    amount = contract.effective_recurring_amount
    if not amount or amount <= 0:
        return None
    return (Decimal(str(amount)) / months).quantize(Decimal('0.01'))


def _contracts_running_on(on_date, organization=None):
    """Non-draft contracts that were billing on `on_date`, plus the ones
    whose stop date is unknown (cancelled / expired with no end date)."""
    from django.utils import timezone
    from psa.models import Contract
    qs = Contract.objects.exclude(status='draft').filter(start_date__lte=on_date).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=on_date))
    qs = scope_to_organizations(qs, 'client_org', organization).select_related('client_org')
    today = timezone.localdate()
    running, undated = [], []
    for c in qs:
        if c.status == 'active':
            if on_date >= today and c.paused_at:
                continue  # paused contracts are not billing now
            running.append(c)
        elif c.end_date is None:
            undated.append(c)   # stopped, but we can't tell when
        elif on_date < today:
            running.append(c)   # ran until its end date
    return running, undated


def recurring_revenue(on_date=None, organization=None):
    """
    MRR / ARR on `on_date` (default today) from contracts' recurring
    amounts normalized by billing frequency (quarterly ÷ 3, yearly ÷ 12).

    Returns: {'as_of', 'mrr', 'arr', 'contract_count', 'contracts': [...],
    'contracts_without_amount', 'contracts_unknown_end', 'is_complete'}.
    `contracts_without_amount` counts running contracts whose recurring
    billing is off or has no amount (their revenue is not recurring here);
    `contracts_unknown_end` counts stopped contracts with no end date, which
    can't be placed in a past month.
    """
    from django.utils import timezone
    on_date = on_date or timezone.localdate()
    running, undated = _contracts_running_on(on_date, organization)
    rows = []
    without_amount = 0
    for c in running:
        m = monthly_amount(c)
        if m is None:
            without_amount += 1
            continue
        rows.append({'contract_id': c.id, 'contract_name': c.name,
                     'client_id': c.client_org_id, 'client_name': c.client_org.name,
                     'frequency': c.billing_frequency, 'mrr': float(m),
                     'next_billing_date': c.next_billing_date,
                     'end_date': c.end_date})
    rows.sort(key=lambda r: -r['mrr'])
    mrr = round(sum(r['mrr'] for r in rows), 2)
    unknown_end = len(undated) if on_date < timezone.localdate() else 0
    return {
        'as_of': on_date,
        'mrr': mrr,
        'arr': round(mrr * 12, 2),
        'contract_count': len(rows),
        'contracts': rows,
        'contracts_without_amount': without_amount,
        'contracts_unknown_end': unknown_end,
        'is_complete': unknown_end == 0,
    }


def _month_end(d):
    from calendar import monthrange
    return d.replace(day=monthrange(d.year, d.month)[1])


def mrr_trend(months=12, ref_date=None, organization=None):
    """
    MRR at the end of each of the last `months` months (the current month
    as of `ref_date`), with month-over-month growth.

    Returns: {'points': [{'month', 'mrr', 'growth', 'growth_pct',
    'is_complete'}], 'mom_growth', 'mom_growth_pct', 'is_complete'}.
    `growth_pct` is None when the prior month's MRR is zero.
    """
    from django.utils import timezone
    from dateutil.relativedelta import relativedelta
    ref = ref_date or timezone.localdate()
    points = []
    for i in range(months - 1, -1, -1):
        month_start = (ref.replace(day=1) - relativedelta(months=i))
        point_date = min(_month_end(month_start), ref)
        rr = recurring_revenue(point_date, organization)
        points.append({'month': month_start.strftime('%Y-%m'), 'as_of': point_date,
                       'mrr': rr['mrr'], 'is_complete': rr['is_complete']})
    prev = None
    for p in points:
        if prev is None:
            p['growth'] = None
            p['growth_pct'] = None
        else:
            p['growth'] = round(p['mrr'] - prev['mrr'], 2)
            p['growth_pct'] = (round((p['mrr'] - prev['mrr']) / prev['mrr'] * 100, 1)
                               if prev['mrr'] else None)
        prev = p
    last = points[-1] if points else {}
    return {
        'points': points,
        'mom_growth': last.get('growth'),
        'mom_growth_pct': last.get('growth_pct'),
        'is_complete': all(p['is_complete'] for p in points),
    }


def _was_renewed(contract, contracts_by_client):
    """A contract counts as renewed when a renewal points at it, or another
    non-draft contract for the same client starts within 31 days of its end
    and runs past it."""
    if contract.renewals.exclude(status='draft').exists():
        return True
    end = contract.end_date
    for other in contracts_by_client.get(contract.client_org_id, ()):
        if other.pk == contract.pk or other.status == 'draft':
            continue
        if other.start_date and other.start_date <= end + timedelta(days=31) \
                and (other.end_date is None or other.end_date > end) \
                and other.start_date >= contract.start_date:
            return True
    return False


def contract_churn(start_date, end_date, organization=None):
    """
    Contracts that ended (cancelled or expired, end date in the window)
    without a renewal.

    Returns: {'churned': [...], 'churned_count', 'churned_mrr',
    'starting_mrr', 'churn_rate_pct', 'undated_cancellations',
    'is_complete'}. `churn_rate_pct` = churned MRR ÷ MRR at the start of
    the window (None when that is zero). Cancelled / expired contracts with
    no end date can't be placed in a window; they are counted in
    `undated_cancellations` and make the result incomplete.
    """
    from psa.models import Contract
    ended = scope_to_organizations(
        Contract.objects.filter(status__in=('cancelled', 'expired')),
        'client_org', organization).select_related('client_org')
    in_window = [c for c in ended
                 if c.end_date and start_date <= c.end_date <= end_date]
    undated = sum(1 for c in ended if c.end_date is None)

    client_ids = {c.client_org_id for c in in_window}
    by_client = {}
    for c in Contract.objects.filter(client_org_id__in=client_ids):
        by_client.setdefault(c.client_org_id, []).append(c)

    churned = []
    for c in in_window:
        if _was_renewed(c, by_client):
            continue
        m = monthly_amount(c)
        churned.append({'contract_id': c.id, 'contract_name': c.name,
                        'client_id': c.client_org_id, 'client_name': c.client_org.name,
                        'status': c.status, 'end_date': c.end_date,
                        'mrr': float(m) if m is not None else None})
    churned_mrr = round(sum(r['mrr'] or 0 for r in churned), 2)
    starting = recurring_revenue(start_date, organization)
    rate = (round(churned_mrr / starting['mrr'] * 100, 1) if starting['mrr'] else None)
    return {
        'churned': churned,
        'churned_count': len(churned),
        'churned_mrr': churned_mrr,
        'starting_mrr': starting['mrr'],
        'churn_rate_pct': rate,
        'undated_cancellations': undated,
        'is_complete': undated == 0 and starting['is_complete'],
    }


def revenue_by_service_line(start_date, end_date, organization=None):
    """
    Invoiced revenue (sent / partial / paid / overdue) by service line:
    the contract type of the invoice's source contract, "Projects" for
    project invoices, "Ticket work" for ticket invoices, and "Unattributed"
    for anything else. `unattributed` is reported so a large share of
    unclassified revenue is visible.

    Returns: {'rows': [{'key', 'label', 'invoices', 'revenue'}],
    'total', 'unattributed', 'is_complete'}.
    """
    from psa.models import Contract, Invoice
    labels = dict(Contract.CONTRACT_TYPES)
    qs = Invoice.objects.filter(
        invoice_date__gte=start_date, invoice_date__lte=end_date,
        status__in=['sent', 'partial', 'paid', 'overdue'],
    ).select_related('source_contract')
    qs = scope_to_organizations(qs, 'client_org', organization)
    out = {}
    for inv in qs:
        if inv.source_contract_id:
            key = inv.source_contract.contract_type
            label = labels.get(key, key)
        elif getattr(inv, 'project_id', None):
            key, label = 'project', 'Projects'
        elif inv.source_ticket_id:
            key, label = 'ticket', 'Ticket work'
        else:
            key, label = 'unattributed', 'Unattributed'
        row = out.setdefault(key, {'key': key, 'label': label, 'invoices': 0,
                                   'revenue': Decimal('0')})
        row['invoices'] += 1
        row['revenue'] += inv.total or Decimal('0')
    rows = sorted(({**r, 'revenue': float(r['revenue'])} for r in out.values()),
                  key=lambda r: -r['revenue'])
    unattributed = out.get('unattributed', {}).get('revenue', Decimal('0'))
    return {
        'rows': rows,
        'total': round(sum(r['revenue'] for r in rows), 2),
        'unattributed': float(unattributed),
        'is_complete': not unattributed,
    }


def utilization_summary(start_date, end_date, organization=None):
    """Team utilization: billable hours ÷ available hours across the techs
    who have a basis to measure against. Techs without one are counted in
    `techs_without_basis` (and make the summary incomplete)."""
    rows = technician_utilization(start_date, end_date, organization)
    measured = [r for r in rows if r['available_hours']]
    billable = sum(r['billable_hours'] for r in measured)
    available = sum(r['available_hours'] for r in measured)
    without = len(rows) - len(measured)
    return {
        'rows': rows,
        'billable_hours': round(billable, 2),
        'available_hours': round(available, 2),
        'utilization_pct': round(billable / available * 100, 1) if available else None,
        'techs_measured': len(measured),
        'techs_without_basis': without,
        'is_complete': without == 0,
    }


def unbilled_time(start_date, end_date, organization=None):
    """
    Billable, finished time entries in the window that are not on any live
    invoice (`InvoiceLineItem.billed_source_ids`), valued at each entry's
    bill rate. Entries without a bill rate are counted, not priced.

    Returns: {'rows': [{'client_id', 'client_name', 'entries', 'hours',
    'amount', 'hours_without_rate'}], 'entries', 'hours', 'amount',
    'hours_without_rate', 'entries_without_rate', 'is_complete'}.
    """
    from psa.models import InvoiceLineItem
    from .costing import RateBook, entry_hours
    book = RateBook()
    qs = _time_entries(start_date, end_date, organization).filter(
        is_billable=True, ended_at__isnull=False, duration_minutes__gt=0)
    billed = InvoiceLineItem.billed_source_ids('time')
    per = {}
    for te in qs:
        if te.pk in billed:
            continue
        org = te.ticket.organization
        if not org:
            continue
        row = per.setdefault(org.id, {'client_id': org.id, 'client_name': org.name,
                                      'entries': 0, 'hours': Decimal('0'),
                                      'amount': Decimal('0'),
                                      'hours_without_rate': Decimal('0'),
                                      'entries_without_rate': 0})
        hours = entry_hours(te)
        row['entries'] += 1
        row['hours'] += hours
        rate = book.bill_rate_for(te)
        if rate is None:
            row['hours_without_rate'] += hours
            row['entries_without_rate'] += 1
        else:
            row['amount'] += hours * rate
    rows = []
    for r in per.values():
        rows.append({**r, 'hours': float(round(r['hours'], 2)),
                     'amount': float(r['amount'].quantize(Decimal('0.01'))),
                     'hours_without_rate': float(round(r['hours_without_rate'], 2))})
    rows.sort(key=lambda r: -r['amount'])
    without = sum(r['entries_without_rate'] for r in rows)
    return {
        'rows': rows,
        'entries': sum(r['entries'] for r in rows),
        'hours': round(sum(r['hours'] for r in rows), 2),
        'amount': round(sum(r['amount'] for r in rows), 2),
        'hours_without_rate': round(sum(r['hours_without_rate'] for r in rows), 2),
        'entries_without_rate': without,
        'is_complete': without == 0,
    }


def contracts_expiring(ref_date=None, organization=None, windows=(30, 60, 90)):
    """
    Active contracts whose end date falls within each window from
    `ref_date` (cumulative: the 60-day bucket includes the 30-day one).

    Returns: {'windows': {30: {'count', 'mrr', 'auto_renew', 'contracts'},
    ...}, 'contracts_without_amount': int, 'is_complete'}. `mrr` is the
    recurring revenue at stake; contracts without a recurring amount are
    listed but add nothing to it.
    """
    from django.utils import timezone
    from psa.models import Contract
    ref = ref_date or timezone.localdate()
    horizon = ref + timedelta(days=max(windows))
    qs = scope_to_organizations(
        Contract.objects.filter(status='active', end_date__isnull=False,
                                end_date__gte=ref, end_date__lte=horizon),
        'client_org', organization).select_related('client_org').order_by('end_date')
    contracts = list(qs)
    out = {}
    for w in windows:
        limit = ref + timedelta(days=w)
        rows = []
        for c in contracts:
            if c.end_date > limit:
                continue
            m = monthly_amount(c)
            rows.append({'contract_id': c.id, 'contract_name': c.name,
                         'client_id': c.client_org_id, 'client_name': c.client_org.name,
                         'end_date': c.end_date, 'auto_renew': c.auto_renew,
                         'days_left': (c.end_date - ref).days,
                         'mrr': float(m) if m is not None else None})
        out[w] = {'count': len(rows),
                  'mrr': round(sum(r['mrr'] or 0 for r in rows), 2),
                  'auto_renew': sum(1 for r in rows if r['auto_renew']),
                  'contracts': rows}
    without = sum(1 for c in contracts if monthly_amount(c) is None)
    return {'windows': out, 'contracts_without_amount': without,
            'is_complete': without == 0}


def msp_metrics(ref_date=None, organization=None, window_days=30):
    """All the MSP-wide metrics above for one dashboard, over the last
    `window_days` days ending `ref_date`."""
    from django.utils import timezone
    ref = ref_date or timezone.localdate()
    start = ref - timedelta(days=window_days - 1)
    return {
        'as_of': ref,
        'window_start': start,
        'recurring': recurring_revenue(ref, organization),
        'mrr_trend': mrr_trend(12, ref, organization),
        'churn': contract_churn(start, ref, organization),
        'service_lines': revenue_by_service_line(start, ref, organization),
        'utilization': utilization_summary(start, ref, organization),
        'unbilled': unbilled_time(start, ref, organization),
        'expiring': contracts_expiring(ref, organization),
    }
