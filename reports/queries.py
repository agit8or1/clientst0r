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
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

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
    if organization is not None:
        qs = qs.filter(organization=organization)

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
        contract_qs = contract_qs.filter(organization=organization)
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
        inv_qs = inv_qs.filter(organization=organization)
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
        qs = qs.filter(organization=organization)

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

# Canonical default loaded-rate per tech ($/hr). Per-tech rates from
# `resourcing.TechCostRate` win when present; this is the ultimate fallback.
DEFAULT_LOADED_RATE = Decimal('60')


def cost_for_period(user, minutes, period_midpoint):
    """
    Decimal cost for `user` × `minutes` of work, using the active
    `TechCostRate` on `period_midpoint` (or DEFAULT_LOADED_RATE when no
    rate is configured).

    `minutes` can be int or Decimal; `period_midpoint` is a date.
    """
    from resourcing.models import TechCostRate
    rate = TechCostRate.rate_for(user, period_midpoint) if user else Decimal(str(DEFAULT_LOADED_RATE))
    hours = Decimal(str(minutes or 0)) / Decimal('60')
    return (hours * Decimal(str(rate))).quantize(Decimal('0.01'))


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


def cost_estimate_by_client(start_date, end_date, organization=None,
                            default_loaded_rate=None):
    """
    Cost-of-delivery estimate per client. Now uses **per-tech**
    `TechCostRate.rate_for(user, midpoint)` × the user's minutes on tickets
    for that client. Falls back to `default_loaded_rate` (or
    DEFAULT_LOADED_RATE) when no per-tech rate is configured.

    Returns: list of {'client_id', 'client_name', 'hours', 'cost'} dicts.
    """
    from psa.models import TicketTimeEntry
    from resourcing.models import TechCostRate

    fallback_rate = Decimal(str(default_loaded_rate or DEFAULT_LOADED_RATE))
    midpoint = _period_midpoint(start_date, end_date)

    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('user', 'ticket__organization')
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    out = {}
    for te in qs:
        org = te.ticket.organization
        if not org:
            continue
        # Per-tech rate (with fallback to the param-or-default)
        if te.user_id:
            rate = TechCostRate.rate_for(te.user, midpoint)
            # `rate_for` falls back to DEFAULT_LOADED_RATE when no rows
            # exist; if the caller passed a custom default_loaded_rate
            # AND there's still no row, prefer the caller's value.
            if rate == DEFAULT_LOADED_RATE and default_loaded_rate is not None:
                rate = fallback_rate
        else:
            rate = fallback_rate
        mins = te.duration_minutes or 0
        hours = Decimal(mins) / Decimal('60')
        row = out.setdefault(org.id, {
            'client_id': org.id, 'client_name': org.name,
            'hours': Decimal('0'), 'cost': Decimal('0'),
        })
        row['hours'] += hours
        row['cost'] += hours * Decimal(str(rate))

    for r in out.values():
        r['hours'] = float(r['hours'])
        r['cost'] = float(r['cost'])
    return sorted(out.values(), key=lambda r: r['cost'], reverse=True)


def cost_estimate_by_contract(start_date, end_date, organization=None,
                              default_loaded_rate=None):
    """Per-contract cost estimate using per-tech rates, mirroring
    `cost_estimate_by_client` but grouped by `Contract.for_ticket`."""
    from psa.models import TicketTimeEntry, Contract
    from resourcing.models import TechCostRate

    fallback_rate = Decimal(str(default_loaded_rate or DEFAULT_LOADED_RATE))
    midpoint = _period_midpoint(start_date, end_date)

    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('user', 'ticket__organization')
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    out = {}
    for te in qs:
        contract = Contract.for_ticket(te.ticket)
        if contract is None:
            continue
        if te.user_id:
            rate = TechCostRate.rate_for(te.user, midpoint)
            if rate == DEFAULT_LOADED_RATE and default_loaded_rate is not None:
                rate = fallback_rate
        else:
            rate = fallback_rate
        mins = te.duration_minutes or 0
        hours = Decimal(mins) / Decimal('60')
        row = out.setdefault(contract.id, {
            'contract_id': contract.id,
            'contract_name': contract.name,
            'client_id': contract.client_org_id,
            'client_name': contract.client_org.name if contract.client_org else '',
            'hours': Decimal('0'),
            'cost': Decimal('0'),
        })
        row['hours'] += hours
        row['cost'] += hours * Decimal(str(rate))

    for r in out.values():
        r['hours'] = float(r['hours'])
        r['cost'] = float(r['cost'])
    return sorted(out.values(), key=lambda r: r['cost'], reverse=True)


def cost_estimate_by_project(start_date, end_date, organization=None,
                             default_loaded_rate=None):
    """Per-project cost estimate using per-tech rates."""
    from psa.models import TicketTimeEntry
    from resourcing.models import TechCostRate

    fallback_rate = Decimal(str(default_loaded_rate or DEFAULT_LOADED_RATE))
    midpoint = _period_midpoint(start_date, end_date)

    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
        ticket__project__isnull=False,
    ).select_related('user', 'ticket__project',
                     'ticket__project__client_org',
                     'ticket__organization')
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    out = {}
    for te in qs:
        project = te.ticket.project
        if not project:
            continue
        if te.user_id:
            rate = TechCostRate.rate_for(te.user, midpoint)
            if rate == DEFAULT_LOADED_RATE and default_loaded_rate is not None:
                rate = fallback_rate
        else:
            rate = fallback_rate
        mins = te.duration_minutes or 0
        hours = Decimal(mins) / Decimal('60')
        client = project.client_org or te.ticket.organization
        row = out.setdefault(project.id, {
            'project_id': project.id,
            'project_name': project.name,
            'client_id': client.id if client else None,
            'client_name': client.name if client else '',
            'hours': Decimal('0'),
            'cost': Decimal('0'),
        })
        row['hours'] += hours
        row['cost'] += hours * Decimal(str(rate))

    for r in out.values():
        r['hours'] = float(r['hours'])
        r['cost'] = float(r['cost'])
    return sorted(out.values(), key=lambda r: r['cost'], reverse=True)


# ---- Profitability ---------------------------------------------------------

def profitability_by_client(start_date, end_date, organization=None,
                            default_loaded_rate=None):
    """
    Combine revenue + cost into per-client profitability rows.
    Returns: list of {'client_id', 'client_name', 'revenue', 'cost',
    'margin', 'margin_pct', 'hours'} dicts, sorted by revenue desc.
    """
    rev = {r['client_id']: r for r in revenue_by_client(start_date, end_date, organization)}
    cost = {r['client_id']: r for r in cost_estimate_by_client(start_date, end_date, organization, default_loaded_rate)}
    client_ids = set(rev.keys()) | set(cost.keys())

    rows = []
    for cid in client_ids:
        r = rev.get(cid, {})
        c = cost.get(cid, {})
        revenue = r.get('invoiced', 0.0)
        cost_v = c.get('cost', 0.0)
        margin = revenue - cost_v
        margin_pct = (margin / revenue * 100) if revenue else 0.0
        rows.append({
            'client_id': cid,
            'client_name': r.get('client_name') or c.get('client_name') or '?',
            'revenue': revenue,
            'cost': cost_v,
            'margin': margin,
            'margin_pct': round(margin_pct, 1),
            'hours': c.get('hours', 0.0),
        })
    return sorted(rows, key=lambda r: r['revenue'], reverse=True)


def profitability_by_contract(start_date, end_date, organization=None,
                              default_loaded_rate=None):
    """Per-contract profitability. Same shape as `profitability_by_client`
    but pivoted on Contract."""
    rev = {r['contract_id']: r for r in revenue_by_contract(start_date, end_date, organization)}
    cost = {r['contract_id']: r for r in cost_estimate_by_contract(start_date, end_date, organization, default_loaded_rate)}
    ids = set(rev.keys()) | set(cost.keys())

    rows = []
    for cid in ids:
        r = rev.get(cid, {})
        c = cost.get(cid, {})
        revenue = r.get('revenue', 0.0)
        cost_v = c.get('cost', 0.0)
        margin = revenue - cost_v
        margin_pct = (margin / revenue * 100) if revenue else 0.0
        rows.append({
            'contract_id': cid,
            'contract_name': r.get('contract_name') or c.get('contract_name') or '?',
            'client_id': r.get('client_id') or c.get('client_id'),
            'client_name': r.get('client_name') or c.get('client_name') or '',
            'revenue': revenue,
            'cost': cost_v,
            'margin': margin,
            'margin_pct': round(margin_pct, 1),
            'hours': c.get('hours', 0.0),
        })
    return sorted(rows, key=lambda r: r['revenue'], reverse=True)


def profitability_by_project(start_date, end_date, organization=None,
                             default_loaded_rate=None):
    """Per-project profitability. Same shape pivoted on Project."""
    rev = {r['project_id']: r for r in revenue_by_project(start_date, end_date, organization)}
    cost = {r['project_id']: r for r in cost_estimate_by_project(start_date, end_date, organization, default_loaded_rate)}
    ids = set(rev.keys()) | set(cost.keys())

    rows = []
    for pid in ids:
        r = rev.get(pid, {})
        c = cost.get(pid, {})
        revenue = r.get('revenue', 0.0)
        cost_v = c.get('cost', 0.0)
        margin = revenue - cost_v
        margin_pct = (margin / revenue * 100) if revenue else 0.0
        rows.append({
            'project_id': pid,
            'project_name': r.get('project_name') or c.get('project_name') or '?',
            'client_id': r.get('client_id') or c.get('client_id'),
            'client_name': r.get('client_name') or c.get('client_name') or '',
            'revenue': revenue,
            'cost': cost_v,
            'margin': margin,
            'margin_pct': round(margin_pct, 1),
            'hours': c.get('hours', 0.0),
        })
    return sorted(rows, key=lambda r: r['revenue'], reverse=True)


def profitability_by_tech(start_date, end_date, organization=None,
                          default_loaded_rate=None):
    """
    Per-tech profitability and utilization.

    Cost: hours × the tech's `TechCostRate` (or DEFAULT_LOADED_RATE).
    Attributed revenue: per-tech billable hours × the active contract's
    `hourly_rate` (best-effort approximation — exact per-entry billing rates
    arrive in Phase 3.4).
    Utilization: actual_hours / target_hours_per_week × weeks_in_period × 100.

    Returns: list of {'tech_id', 'tech_username', 'hours',
    'billable_minutes', 'cost', 'attributed_revenue', 'margin',
    'margin_pct', 'utilization_pct'} dicts, sorted by attributed_revenue
    desc.
    """
    from decimal import Decimal as _D
    from psa.models import TicketTimeEntry, Contract
    from resourcing.models import TechCostRate, BillableTarget

    fallback_rate = _D(str(default_loaded_rate or DEFAULT_LOADED_RATE))
    midpoint = _period_midpoint(start_date, end_date)

    qs = TicketTimeEntry.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related('user', 'ticket', 'ticket__organization')
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    # Cache per-ticket contract lookups
    contract_cache = {}

    out = {}
    for te in qs:
        if not te.user_id:
            continue
        # Cost rate
        rate = TechCostRate.rate_for(te.user, midpoint)
        if rate == DEFAULT_LOADED_RATE and default_loaded_rate is not None:
            rate = fallback_rate
        mins = te.duration_minutes or 0
        hours = _D(mins) / _D('60')
        # Attributed revenue: billable minutes × contract hourly_rate.
        # NOTE: exact per-entry billing rates arrive in Phase 3.4 — this
        # approximates revenue using the active contract's hourly_rate
        # (or `default_loaded_rate` fallback as a stand-in for retail).
        contract = contract_cache.get(te.ticket_id)
        if te.ticket_id not in contract_cache:
            contract = Contract.for_ticket(te.ticket)
            contract_cache[te.ticket_id] = contract
        if te.is_billable:
            billable_hours = hours
        else:
            billable_hours = _D('0')
        if contract and contract.hourly_rate:
            billing_rate = _D(str(contract.hourly_rate))
        else:
            billing_rate = fallback_rate
        attr_rev = billable_hours * billing_rate

        row = out.setdefault(te.user_id, {
            'tech_id': te.user_id,
            'tech_username': te.user.username,
            'hours': _D('0'),
            'billable_minutes': 0,
            'cost': _D('0'),
            'attributed_revenue': _D('0'),
        })
        row['hours'] += hours
        if te.is_billable:
            row['billable_minutes'] += mins
        row['cost'] += hours * _D(str(rate))
        row['attributed_revenue'] += attr_rev

    # Utilization: pull each tech's BillableTarget once.
    bt_by_user = {
        bt.user_id: bt for bt in BillableTarget.objects.filter(user_id__in=list(out.keys()))
    }
    days_in_period = ((end_date - start_date).days + 1) if end_date and start_date else 0
    weeks_in_period = _D(str(max(days_in_period, 1))) / _D('7')

    rows = []
    for uid, row in out.items():
        revenue = float(row['attributed_revenue'])
        cost_v = float(row['cost'])
        margin = revenue - cost_v
        margin_pct = (margin / revenue * 100) if revenue else 0.0

        bt = bt_by_user.get(uid)
        target_per_week = (
            _D(str(bt.target_hours_per_week)) if bt and bt.is_active
            else _D('32')
        )
        target_hours = target_per_week * weeks_in_period
        actual_hours = row['hours']
        util = float((actual_hours / target_hours) * 100) if target_hours else 0.0

        rows.append({
            'tech_id': row['tech_id'],
            'tech_username': row['tech_username'],
            'hours': float(round(actual_hours, 2)),
            'billable_minutes': row['billable_minutes'],
            'cost': cost_v,
            'attributed_revenue': revenue,
            'margin': margin,
            'margin_pct': round(margin_pct, 1),
            'utilization_pct': round(util, 1),
        })
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

    Reuses `profitability_by_tech` which already computes attributed revenue
    + billable minutes per tech. Looks up each tech's TechCostRate at the
    period midpoint to compute realization %.

    Returns: list of {'tech_id', 'tech_username', 'attributed_revenue',
    'billable_hours', 'effective_rate', 'cost_rate', 'realization_pct'}
    where realization_pct = effective_rate / cost_rate × 100 (target ≥ 200%).
    """
    from resourcing.models import TechCostRate

    rows = profitability_by_tech(start_date, end_date, organization=organization)
    midpoint = _period_midpoint(start_date, end_date)

    out = []
    for r in rows:
        billable_min = r.get('billable_minutes', 0) or 0
        billable_hours = billable_min / 60.0
        revenue = r.get('attributed_revenue', 0.0) or 0.0
        eff_rate = (revenue / billable_hours) if billable_hours else 0.0

        # Cost rate via TechCostRate; falls back to DEFAULT_LOADED_RATE
        try:
            user = User.objects.get(pk=r['tech_id'])
            cost_rate = float(TechCostRate.rate_for(user, midpoint))
        except User.DoesNotExist:
            cost_rate = float(DEFAULT_LOADED_RATE)

        realization = (eff_rate / cost_rate * 100) if cost_rate else 0.0
        out.append({
            'tech_id': r['tech_id'],
            'tech_username': r['tech_username'],
            'attributed_revenue': round(revenue, 2),
            'billable_hours': round(billable_hours, 2),
            'effective_rate': round(eff_rate, 2),
            'cost_rate': round(cost_rate, 2),
            'realization_pct': round(realization, 1),
        })
    return sorted(out, key=lambda r: r['effective_rate'], reverse=True)


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
                   'stuck': float, 'grand_total': float},
        'stale_days': int,
      }
    """
    from datetime import timedelta
    from django.utils import timezone
    from psa.models import TicketTimeEntry, Contract, Invoice, InvoiceLineItem

    today = timezone.now().date()
    stale_cutoff = today - timedelta(days=stale_days)
    stuck_cutoff = today - timedelta(days=14)

    # --- 1. Stale unbilled time ---------------------------------------------
    # TicketTimeEntry has no direct Invoice FK. We use the heuristic
    # InvoiceLineItem.source='time' + source_id=str(entry.pk), filtering
    # out void invoices.
    billed_entry_ids = set(
        int(sid) for sid in InvoiceLineItem.objects.filter(
            source='time',
        ).exclude(invoice__status='void').values_list('source_id', flat=True)
        if sid and str(sid).isdigit()
    )

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
            'minutes': 0,
        })
        row['entry_count'] += 1
        row['minutes'] += (te.duration_minutes or 0)
        if te.started_at < row['oldest_at']:
            row['oldest_at'] = te.started_at

    DEFAULT_BILL_RATE = Decimal('150')
    stale_out = []
    for cid, row in stale_rows.items():
        # Best-effort representative rate: active contract's hourly_rate
        contract = Contract.objects.filter(
            client_org_id=cid, status='active',
        ).first()
        rate = (contract.hourly_rate
                if contract and contract.hourly_rate
                else DEFAULT_BILL_RATE) or DEFAULT_BILL_RATE
        amount = float(Decimal(str(row['minutes'])) / Decimal('60') * Decimal(str(rate)))
        stale_out.append({
            'client_id': row['client_id'],
            'client_name': row['client_name'],
            'oldest_at': row['oldest_at'].isoformat() if row['oldest_at'] else None,
            'entry_count': row['entry_count'],
            'hours_at_risk': round(row['minutes'] / 60.0, 2),
            'amount_at_risk': round(amount, 2),
        })
    stale_out.sort(key=lambda r: r['amount_at_risk'], reverse=True)

    # --- 2. Expired contract blocks ----------------------------------------
    expired_qs = Contract.objects.filter(status='expired').select_related('client_org')
    expired_qs = scope_to_organizations(expired_qs, 'organization', organization)
    expired_out = []
    for c in expired_qs:
        if not c.total_hours or c.hours_used >= float(c.total_hours):
            continue
        unused = float(c.total_hours) - c.hours_used
        rate = float(c.hourly_rate or 0)
        expired_out.append({
            'client_id': c.client_org_id,
            'client_name': c.client_org.name if c.client_org else '?',
            'contract_id': c.id,
            'contract_name': c.name,
            'unused_hours': round(unused, 2),
            'unused_value': round(unused * rate, 2),
        })
    expired_out.sort(key=lambda r: r['unused_value'], reverse=True)

    # --- 3. Stuck drafts ----------------------------------------------------
    stuck_qs = Invoice.objects.filter(
        status='draft', invoice_date__lte=stuck_cutoff,
    ).select_related('client_org')
    stuck_qs = scope_to_organizations(stuck_qs, 'organization', organization)
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
        'expired_blocks': round(sum(r['unused_value'] for r in expired_out), 2),
        'stuck': round(sum(r['amount'] for r in stuck_out), 2),
    }
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

    Revenue attribution per TicketTimeEntry:
      `billable_minutes / 60 × ticket.contract.hourly_rate`
      (or DEFAULT_BILL_RATE = $150 if no active contract).
    Cost = billable_minutes / 60 × TechCostRate.rate_for(user, midpoint).

    dimension: 'ticket_type' | 'closure_category' | 'queue'
    """
    from psa.models import TicketTimeEntry, Contract
    from resourcing.models import TechCostRate

    DEFAULT_BILL_RATE = Decimal('150')
    midpoint = _period_midpoint(start_date, end_date)

    qs = TicketTimeEntry.objects.filter(
        is_billable=True,
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    ).select_related(
        'ticket__ticket_type', 'ticket__queue',
        'ticket__organization', 'user',
    )
    if organization is not None:
        qs = qs.filter(ticket__organization=organization)

    out = {}
    contract_cache = {}
    rate_cache = {}

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

        # Resolve revenue rate — active contract on ticket org
        org_id = ticket.organization_id
        if org_id not in contract_cache:
            c = Contract.objects.filter(
                client_org_id=org_id, status='active',
            ).first()
            contract_cache[org_id] = c.hourly_rate if c and c.hourly_rate else None
        rev_rate = contract_cache.get(org_id) or DEFAULT_BILL_RATE

        # Cost rate per tech (cached)
        if te.user_id not in rate_cache:
            try:
                rate_cache[te.user_id] = float(TechCostRate.rate_for(te.user, midpoint)) if te.user_id else 0.0
            except Exception:
                rate_cache[te.user_id] = 0.0
        cost_rate = rate_cache[te.user_id]

        hours = Decimal(te.duration_minutes or 0) / Decimal(60)
        revenue = float(hours * Decimal(str(rev_rate)))
        cost = float(hours * Decimal(str(cost_rate)))

        row = out.setdefault(key, {
            'key': str(key), 'label': label,
            'tickets': set(), 'hours': 0.0,
            'revenue': 0.0, 'cost': 0.0,
        })
        row['tickets'].add(ticket.id)
        row['hours'] += float(hours)
        row['revenue'] += revenue
        row['cost'] += cost

    rows = []
    for r in out.values():
        ticket_count = len(r['tickets'])
        margin = r['revenue'] - r['cost']
        margin_pct = (margin / r['revenue'] * 100) if r['revenue'] else 0.0
        rows.append({
            'key': r['key'], 'label': r['label'],
            'tickets': ticket_count,
            'hours': round(r['hours'], 2),
            'revenue': round(r['revenue'], 2),
            'cost': round(r['cost'], 2),
            'margin': round(margin, 2),
            'margin_pct': round(margin_pct, 1),
        })
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

    ref = ref_date or timezone.now().date()
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
        key = (client_id, a.connection.provider)
        row = out.setdefault(key, {
            'client_id': client_id,
            'client_name': a.client_org.name if a.client_org else '(unscoped)',
            'vendor': a.connection.get_provider_display(),
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
