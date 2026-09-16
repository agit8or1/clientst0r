"""
Dashboard widget data sources.

Each entry:  data_source (str) → callable(params: dict) → result dict
Result shape depends on widget type but is always JSON-serializable.

For 'metric': {'value': float|str, 'unit': str, 'trend_pct': float|None,
               'trend_label': str, 'subtitle': str, 'icon': str, 'color': str}
For 'chart_line', 'chart_bar': {'labels': [str], 'series': [{'name', 'data': [num]}]}
For 'chart_pie': {'labels': [str], 'data': [num]}
For 'table', 'list': {'columns': [str], 'rows': [[any]]}
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import models


def _last_n_days(n=30):
    today = date.today()
    return today - timedelta(days=n - 1), today


# ---- Who is looking --------------------------------------------------------
#
# A widget puts the same numbers on screen as a report page does, so it has to
# answer the same two questions that page answers: may this user see this kind
# of data at all, and whose data are they entitled to see? Until v3.17.568 no
# widget asked either — every source aggregated across every client, and the
# only gate was `reports_view_dashboards`, which every role has by default. A
# read-only member of one client could open a shared dashboard and read the
# MSP's revenue and its other clients' names.
#
# `WIDGET_SPECS` states both answers per data source:
#   perm  — the permission the equivalent report page requires, or None when
#           any dashboard viewer may see it.
#   scope — SCOPE_ORG when the source honours `params['org_ids']`; SCOPE_MSP
#           when the underlying rows have no client to scope by (django-axes
#           attempts, the user table), which means the source may only be
#           shown to a viewer entitled to every client.

SCOPE_ORG = 'org'
SCOPE_MSP = 'msp'

WIDGET_SPECS = {
    # Money — same bar as the profitability / leakage report pages.
    'revenue_this_period': ('reports_view_financial', SCOPE_ORG),
    'top_clients_by_revenue': ('reports_view_financial', SCOPE_ORG),
    'revenue_trend_30d': ('reports_view_financial', SCOPE_ORG),
    'unbilled_hours': ('reports_view_financial', SCOPE_ORG),
    'hours_split_pie': ('reports_view_financial', SCOPE_ORG),
    # SLA — same bar as the SLA trends page.
    'sla_breach_trend': ('reports_view_sla', SCOPE_ORG),
    # Service desk.
    'open_tickets_count': (None, SCOPE_ORG),
    'overdue_tickets_count': (None, SCOPE_ORG),
    'avg_resolution_hours': (None, SCOPE_ORG),
    'tickets_by_priority': (None, SCOPE_ORG),
    'tickets_opened_30d': (None, SCOPE_ORG),
    'my_assigned_tickets': (None, SCOPE_ORG),
    'active_techs': (None, SCOPE_ORG),
    # Client health.
    'at_risk_clients': (None, SCOPE_ORG),
    'client_health_breakdown': (None, SCOPE_ORG),
    # Other modules — each behind its own module's view permission.
    'recent_sales_activity': ('crm_view', SCOPE_ORG),
    'low_stock_items': ('procurement_view', SCOPE_ORG),
    'security_alerts_24h': (None, SCOPE_ORG),
    'security_alerts_open_critical': (None, SCOPE_ORG),
    'alerts_by_severity': (None, SCOPE_ORG),
    'monitors_down': (None, SCOPE_ORG),
    'monitors_status_breakdown': (None, SCOPE_ORG),
    'ssl_expiring_soon': (None, SCOPE_ORG),
    'domain_expiring_soon': (None, SCOPE_ORG),
    'warranties_expiring_soon': (None, SCOPE_ORG),
    'vault_activity_24h': ('audit_view', SCOPE_ORG),
    # No client to scope these by, so they are MSP-wide or nothing.
    'recent_failed_logins': ('audit_view', SCOPE_MSP),
    'techs_logged_in': (None, SCOPE_MSP),
}

# An unregistered source is treated as the most sensitive thing it could be,
# so adding one to REGISTRY without a spec fails closed rather than leaking.
DEFAULT_SPEC = (None, SCOPE_MSP)

REQUIRED_PERMS = sorted({perm for perm, _ in WIDGET_SPECS.values() if perm})


def viewer_for(user, is_staff_user=False):
    """
    Build the viewer context `get_widget_data` needs, from a request's user.

    `org_ids` is None for someone entitled to every client (superuser or MSP
    staff) and a list of their active memberships' organization ids otherwise
    — the same rule `psa.views._scoped_ticket_qs` applies to tickets.
    """
    from accounts.permission_utils import user_has_perm

    if not user or not getattr(user, 'is_authenticated', False):
        return no_access_viewer()

    if user.is_superuser or is_staff_user:
        org_ids = None
    else:
        org_ids = list(
            user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        ) if hasattr(user, 'memberships') else []

    return {
        'user_id': user.id,
        'org_ids': org_ids,
        'perms': {p for p in REQUIRED_PERMS if user_has_perm(user, p)},
    }


def no_access_viewer():
    """A viewer entitled to nothing — the default when a caller supplies none."""
    return {'user_id': None, 'org_ids': [], 'perms': set()}


def msp_wide_viewer():
    """A viewer entitled to everything — for system callers with no request."""
    return {'user_id': None, 'org_ids': None, 'perms': set(REQUIRED_PERMS)}


def _org_ids(params):
    """The client orgs this render is limited to, or None for all of them."""
    return (params or {}).get('org_ids')


def _scoped(qs, params, field='organization_id'):
    """Limit a queryset to the viewer's client orgs."""
    ids = _org_ids(params)
    if ids is None:
        return qs
    return qs.filter(**{f'{field}__in': ids})


def _scoped_rows(rows, params, key='client_id'):
    """Same idea for the per-client row lists `reports.queries` returns."""
    ids = _org_ids(params)
    if ids is None:
        return rows
    allowed = set(ids)
    return [r for r in rows if r.get(key) in allowed]


def _restricted(message):
    """The payload a widget renders when the viewer may not see its data.

    Both the dashboard and wallboard templates already render `error` as a
    warning tile, so a restricted widget shows the reason in place of numbers
    rather than showing a plausible-looking zero.
    """
    return {'error': message, 'restricted': True}


# ---- METRIC widgets --------------------------------------------------------

def revenue_this_period(params):
    from reports.queries import revenue_by_client
    days = int(params.get('days', 30))
    start, end = _last_n_days(days)
    # `revenue_by_client` groups by the invoice's client_org, so filtering its
    # rows is what limits this to the viewer's own clients.
    rows = _scoped_rows(revenue_by_client(start, end), params)
    total = sum(r['invoiced'] for r in rows)
    return {
        'value': f'${total:,.0f}',
        'subtitle': f'Revenue invoiced (last {days}d)',
        'icon': 'fa-dollar-sign',
        'color': 'success',
    }


def open_tickets_count(params):
    from psa.models import Ticket
    from django.utils import timezone
    qs = _scoped(Ticket.objects.filter(status__is_terminal=False), params)
    cat = (params or {}).get('category') or 'all'
    label = 'Open tickets'
    if cat == 'unassigned':
        qs = qs.filter(assigned_to__isnull=True)
        label = 'Open tickets — unassigned'
    elif cat == 'overdue':
        qs = qs.filter(resolution_due_at__lt=timezone.now())
        label = 'Open tickets — SLA overdue'
    elif cat == 'priority_high':
        qs = qs.filter(priority__code__in=['P1', 'P2'])
        label = 'Open tickets — P1/P2'
    n = qs.count()
    return {
        'value': str(n),
        'subtitle': label,
        'icon': 'fa-ticket',
        'color': 'info' if n < 50 else 'warning' if n < 100 else 'danger',
    }


def overdue_tickets_count(params):
    from psa.models import Ticket
    from django.utils import timezone
    n = _scoped(Ticket.objects.filter(
        status__is_terminal=False,
        resolution_due_at__lt=timezone.now(),
    ), params).count()
    return {
        'value': str(n),
        'subtitle': 'SLA overdue',
        'icon': 'fa-triangle-exclamation',
        'color': 'success' if n == 0 else 'warning' if n < 5 else 'danger',
    }


def unbilled_hours(params):
    """Stale (>30d) billable time not yet invoiced."""
    from reports.queries import revenue_leakage
    leak = revenue_leakage(date.today() - timedelta(days=365), date.today(),
                           organization=_org_ids(params))
    stale = leak['totals']['stale']
    return {
        'value': f'${stale:,.0f}',
        'subtitle': 'Stale unbilled time at risk',
        'icon': 'fa-faucet-drip',
        'color': 'danger' if stale > 5000 else 'warning' if stale > 0 else 'success',
    }


def active_techs(params):
    """Distinct techs who logged time in last 30 days."""
    from psa.models import TicketTimeEntry
    start, _ = _last_n_days(30)
    n = _scoped(
        TicketTimeEntry.objects.filter(started_at__date__gte=start),
        params, 'ticket__organization_id',
    ).values('user_id').distinct().count()
    return {
        'value': str(n),
        'subtitle': 'Active techs (30d)',
        'icon': 'fa-users-gear',
        'color': 'primary',
    }


def avg_resolution_hours(params):
    """Average resolution time in hours over last 30d closed tickets."""
    from psa.models import Ticket
    from django.utils import timezone
    from datetime import timedelta as td
    cutoff = timezone.now() - td(days=30)
    closed = _scoped(Ticket.objects.filter(
        closed_at__gte=cutoff, status__is_terminal=True,
    ), params).exclude(closed_at__isnull=True).exclude(created_at__isnull=True)
    total = 0
    cnt = 0
    for t in closed:
        delta = (t.closed_at - t.created_at).total_seconds() / 3600
        if delta > 0:
            total += delta
            cnt += 1
    avg = (total / cnt) if cnt else 0.0
    return {
        'value': f'{avg:.1f}h',
        'subtitle': 'Avg time-to-resolve (30d)',
        'icon': 'fa-clock',
        'color': 'info',
    }


# ---- TABLE widgets ---------------------------------------------------------

def top_clients_by_revenue(params):
    from reports.queries import revenue_by_client
    days = int(params.get('days', 30))
    limit = int(params.get('limit', 5))
    start, end = _last_n_days(days)
    rows = _scoped_rows(revenue_by_client(start, end), params)[:limit]
    return {
        'columns': ['Client', 'Invoiced', 'Outstanding'],
        'rows': [
            [r['client_name'], f'${r["invoiced"]:,.2f}', f'${r["outstanding"]:,.2f}']
            for r in rows
        ],
    }


def tickets_by_priority(params):
    """Open-ticket breakdown — grouping is category-driven (priority,
    queue, or assigned tech). Name kept for backwards-compat with
    saved widgets; column header changes per category."""
    from psa.models import Ticket
    from django.db.models import Count
    cat = (params or {}).get('category') or 'priority'
    base = _scoped(Ticket.objects.filter(status__is_terminal=False), params)
    if cat == 'queue':
        agg = base.values('queue__name').annotate(n=Count('id')).order_by('-n')[:8]
        rows = [[r['queue__name'] or '—', str(r['n'])] for r in agg]
        return {'columns': ['Queue', 'Open'], 'rows': rows or [['—', '0']]}
    if cat == 'assigned_tech':
        agg = base.values('assigned_to__username').annotate(n=Count('id')).order_by('-n')[:8]
        rows = [[r['assigned_to__username'] or 'Unassigned', str(r['n'])] for r in agg]
        return {'columns': ['Tech', 'Open'], 'rows': rows or [['—', '0']]}
    rows = []
    for code in ['P1', 'P2', 'P3', 'P4', 'P5']:
        n = base.filter(priority__code=code).count()
        rows.append([code, str(n)])
    return {'columns': ['Priority', 'Open'], 'rows': rows}


def my_assigned_tickets(params):
    """Caller-aware: filtered to params['user_id']."""
    from psa.models import Ticket
    uid = params.get('user_id')
    if not uid:
        return {'columns': ['Ticket', 'Subject', 'Priority'], 'rows': []}
    qs = _scoped(Ticket.objects.filter(
        assigned_to_id=uid, status__is_terminal=False,
    ), params).select_related('priority').order_by('-resolution_due_at')[:8]
    rows = [
        [t.ticket_number, t.subject[:60], t.priority.code if t.priority_id else '']
        for t in qs
    ]
    return {'columns': ['Ticket', 'Subject', 'Priority'], 'rows': rows}


# ---- CHART widgets ---------------------------------------------------------

def revenue_trend_30d(params):
    """30-day revenue trend. Category-aware (daily / weekly / cumulative)."""
    from psa.models import Invoice
    today = date.today()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    by_day = {d: 0.0 for d in days}
    invs = _scoped(Invoice.objects.filter(
        invoice_date__gte=days[0], invoice_date__lte=today,
        status__in=['sent', 'partial', 'paid', 'overdue'],
    ), params, 'client_org_id')
    for inv in invs:
        if inv.invoice_date in by_day:
            by_day[inv.invoice_date] += float(inv.total or 0)

    cat = (params or {}).get('category') or 'daily'
    if cat == 'weekly':
        # Group into 5 buckets of ~6 days. Labels = end date of bucket.
        buckets = []
        labels = []
        chunk = 6
        for i in range(0, len(days), chunk):
            window = days[i:i + chunk]
            if not window:
                continue
            buckets.append(round(sum(by_day[d] for d in window), 2))
            labels.append(window[-1].strftime('%m/%d'))
        return {'labels': labels, 'series': [{'name': 'Invoiced (weekly)', 'data': buckets}]}
    if cat == 'cumulative':
        running = 0.0
        cum = []
        for d in days:
            running += by_day[d]
            cum.append(round(running, 2))
        return {
            'labels': [d.strftime('%m/%d') for d in days],
            'series': [{'name': 'Invoiced (running total)', 'data': cum}],
        }
    # daily — original behavior
    labels = [d.strftime('%m/%d') for d in days]
    series = [{'name': 'Invoiced', 'data': [round(by_day[d], 2) for d in days]}]
    return {'labels': labels, 'series': series}


def tickets_opened_30d(params):
    """30-day ticket trend. Category-aware (opened / closed / net)."""
    from psa.models import Ticket
    today = date.today()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    labels = [d.strftime('%m/%d') for d in days]
    cat = (params or {}).get('category') or 'opened'
    base = _scoped(Ticket.objects.all(), params)
    if cat == 'closed':
        counts = [
            base.filter(closed_at__date=d).count()
            for d in days
        ]
        return {'labels': labels, 'series': [{'name': 'Closed', 'data': counts}]}
    if cat == 'net':
        opened = [base.filter(created_at__date=d).count() for d in days]
        closed = [base.filter(closed_at__date=d).count() for d in days]
        net = [o - c for o, c in zip(opened, closed)]
        return {
            'labels': labels,
            'series': [
                {'name': 'Opened', 'data': opened},
                {'name': 'Closed', 'data': closed},
                {'name': 'Net (backlog Δ)', 'data': net},
            ],
        }
    counts = [base.filter(created_at__date=d).count() for d in days]
    return {'labels': labels, 'series': [{'name': 'Opened', 'data': counts}]}


def hours_split_pie(params):
    """Billable vs non-billable hours (last 30d)."""
    from reports.queries import hours_minutes_by_client
    start, end = _last_n_days(30)
    rows = hours_minutes_by_client(start, end, organization=_org_ids(params))
    bill = sum(r['billable_minutes'] for r in rows) / 60.0
    nonbill = sum(r['nonbillable_minutes'] for r in rows) / 60.0
    return {'labels': ['Billable', 'Non-billable'], 'data': [round(bill, 1), round(nonbill, 1)]}


def sla_breach_trend(params):
    """30d response-breach trend per priority (line chart, top 3 priorities only)."""
    from reports.queries import sla_trend_by_priority
    end = date.today()
    start = end - timedelta(days=29)
    data = sla_trend_by_priority(start, end, organization=_org_ids(params),
                                 bucket='day')
    labels = data['buckets']
    series = []
    for p in ['P1', 'P2', 'P3']:  # only top 3 priorities for the widget
        rows = data['series'].get(p, [])
        series.append({'name': p, 'data': [r['response_pct'] for r in rows]})
    return {'labels': labels, 'series': series}


# ---- v3.17.147 — Client-health widgets -------------------------------------

def at_risk_clients(params):
    """Client health table — category filters which slice to show.

    `worst` (default): top 5 by lowest score regardless of category.
    `trouble_only`: only clients in the Trouble bucket.
    `at_risk_only`: only clients in the At-Risk bucket.
    """
    from reports.queries import client_health_scores_all
    cat = (params or {}).get('category') or 'worst'
    rows = client_health_scores_all(organization_filter=_org_ids(params))
    if cat == 'trouble_only':
        rows = [r for r in rows if r['category'] == 'trouble'][:8]
    elif cat == 'at_risk_only':
        rows = [r for r in rows if r['category'] == 'at_risk'][:8]
    else:
        rows = rows[:5]
    table_rows = [
        [r['client_name'], r['score'], r['category'].replace('_', ' ').title()]
        for r in rows
    ]
    return {'columns': ['Client', 'Health', 'Status'], 'rows': table_rows or [['—', '', '']]}


def client_health_breakdown(params):
    """Pie chart: Healthy / At-Risk / Trouble counts."""
    from reports.queries import client_health_scores_all
    rows = client_health_scores_all(organization_filter=_org_ids(params))
    counts = {'Healthy': 0, 'At-Risk': 0, 'Trouble': 0}
    for r in rows:
        if r['category'] == 'healthy':
            counts['Healthy'] += 1
        elif r['category'] == 'at_risk':
            counts['At-Risk'] += 1
        else:
            counts['Trouble'] += 1
    return {'labels': list(counts.keys()), 'data': list(counts.values())}


# ---- Phase 5.3 — Recent sales activity -----------------------------------

def recent_sales_activity(params):
    """Last 10 sales activities across the entire MSP. Useful for sales mgr dashboard."""
    try:
        from crm.models import SalesActivity
        rows = []
        for a in _scoped(SalesActivity.objects.all(), params).select_related(
            'lead', 'opportunity', 'client_org', 'user',
        ).order_by('-occurred_at')[:10]:
            target = (
                a.lead.company_name if a.lead_id else (
                    a.opportunity.name if a.opportunity_id else (
                        a.client_org.name if a.client_org_id else '?'
                    )
                )
            )
            rows.append([
                a.occurred_at.strftime('%m/%d %H:%M'),
                a.get_activity_type_display(),
                target[:30],
                (a.user.username if a.user_id else 'anon'),
            ])
        return {'columns': ['When', 'Type', 'Target', 'Who'], 'rows': rows}
    except Exception:
        return {'columns': [], 'rows': []}


# ---- Phase 4.3 — Auto-replenish ------------------------------------------

def low_stock_items(params):
    """Top N items below minimum stock — grouped by name only."""
    rows = []
    try:
        from inventory.models import InventoryItem
        for it in _scoped(InventoryItem.objects.filter(
            quantity__lte=models.F('min_quantity')
        ), params).exclude(min_quantity=0)[:10]:
            rows.append([str(it), str(it.quantity), str(it.min_quantity)])
    except Exception:
        pass
    return {'columns': ['Item', 'In stock', 'Minimum'], 'rows': rows}


# ---- Phase 9 security alerts ----------------------------------------------

def security_alerts_24h(params):
    """Count of new security alerts in the last 24h, broken down by severity."""
    from datetime import timedelta
    from django.utils import timezone
    try:
        from security_alerts.models import SecurityAlert
        cutoff = timezone.now() - timedelta(hours=24)
        rows = []
        alerts = _scoped(SecurityAlert.objects.all(), params)
        for sev in ['critical', 'high', 'medium', 'low', 'info']:
            n = alerts.filter(severity=sev, status='new', seen_at__gte=cutoff).count()
            if n:
                rows.append([sev.upper(), str(n)])
        return {'columns': ['Severity', 'New (24h)'], 'rows': rows or [['—', '0']]}
    except Exception:
        return {'columns': [], 'rows': []}


def security_alerts_open_critical(params):
    """Single metric: count of open security alerts. Category-aware."""
    try:
        from security_alerts.models import SecurityAlert
        from datetime import timedelta
        from django.utils import timezone
        cat = (params or {}).get('category') or 'critical_high'
        qs = _scoped(SecurityAlert.objects.all(), params)
        label = 'Open critical / high security alerts'
        if cat == 'critical_high':
            qs = qs.filter(severity__in=['critical', 'high'], status='new')
        elif cat == 'critical_only':
            qs = qs.filter(severity='critical', status='new')
            label = 'Open critical alerts'
        elif cat == 'all_open':
            qs = qs.filter(status='new')
            label = 'All open alerts'
        elif cat == 'last_24h':
            qs = qs.filter(seen_at__gte=timezone.now() - timedelta(hours=24))
            label = 'Alerts seen (last 24h)'
        else:
            qs = qs.filter(severity__in=['critical', 'high'], status='new')
        n = qs.count()
        return {
            'value': str(n),
            'subtitle': label,
            'icon': 'fa-shield-halved',
            'color': 'danger' if n > 0 else 'success',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'Security', 'icon': 'fa-shield-halved', 'color': 'secondary'}


# ---- v3.17.224 — operations / monitoring widgets ---------------------------

def techs_logged_in(params):
    """Distinct users with last_login within the last N hours (default 8)."""
    from django.contrib.auth.models import User
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    hours = int((params or {}).get('hours', 8))
    cutoff = _tz.now() - _td(hours=hours)
    n = User.objects.filter(last_login__gte=cutoff, is_active=True).count()
    return {
        'value': str(n),
        'subtitle': f'Users logged in (last {hours}h)',
        'icon': 'fa-user-clock',
        'color': 'primary',
    }


def monitors_down(params):
    """Count of WebsiteMonitors currently in `down` or `error` state."""
    try:
        from monitoring.models import WebsiteMonitor
        n = _scoped(WebsiteMonitor.objects.filter(
            is_enabled=True, status__in=['down', 'error'],
        ), params).count()
        return {
            'value': str(n),
            'subtitle': 'Monitors currently down',
            'icon': 'fa-link-slash',
            'color': 'success' if n == 0 else 'danger',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'Monitors', 'icon': 'fa-link-slash', 'color': 'secondary'}


def ssl_expiring_soon(params):
    """SSL certificates expiring within N days (default 30)."""
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    days = int((params or {}).get('days', 30))
    try:
        from monitoring.models import WebsiteMonitor
        cutoff = _tz.now() + _td(days=days)
        n = _scoped(WebsiteMonitor.objects.filter(
            is_enabled=True, ssl_enabled=True,
            ssl_expires_at__isnull=False,
            ssl_expires_at__lte=cutoff,
        ), params).count()
        return {
            'value': str(n),
            'subtitle': f'SSL certs expiring in {days}d',
            'icon': 'fa-shield-alt',
            'color': 'success' if n == 0 else 'warning' if n < 5 else 'danger',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'SSL', 'icon': 'fa-shield-alt', 'color': 'secondary'}


def domain_expiring_soon(params):
    """Domain registrations expiring within N days (default 60)."""
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    days = int((params or {}).get('days', 60))
    try:
        from monitoring.models import WebsiteMonitor
        cutoff = _tz.now() + _td(days=days)
        n = _scoped(WebsiteMonitor.objects.filter(
            is_enabled=True,
            domain_expires_at__isnull=False,
            domain_expires_at__lte=cutoff,
        ), params).count()
        return {
            'value': str(n),
            'subtitle': f'Domains expiring in {days}d',
            'icon': 'fa-globe',
            'color': 'success' if n == 0 else 'warning' if n < 5 else 'danger',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'Domains', 'icon': 'fa-globe', 'color': 'secondary'}


def warranties_expiring_soon(params):
    """Assets with warranty_expiry within N days (default 90)."""
    from datetime import date as _date, timedelta as _td
    days = int((params or {}).get('days', 90))
    try:
        from assets.models import Asset
        cutoff = _date.today() + _td(days=days)
        n = _scoped(Asset.objects.filter(
            warranty_expiry__isnull=False,
            warranty_expiry__lte=cutoff,
            warranty_expiry__gte=_date.today(),
        ), params).count()
        return {
            'value': str(n),
            'subtitle': f'Assets warranty expiring in {days}d',
            'icon': 'fa-clock-rotate-left',
            'color': 'success' if n == 0 else 'warning' if n < 5 else 'danger',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'Warranties', 'icon': 'fa-clock-rotate-left', 'color': 'secondary'}


def recent_failed_logins(params):
    """Failed login attempts in the last N hours (default 24, via django-axes)."""
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    hours = int((params or {}).get('hours', 24))
    try:
        from axes.models import AccessAttempt
        cutoff = _tz.now() - _td(hours=hours)
        n = AccessAttempt.objects.filter(attempt_time__gte=cutoff).count()
        return {
            'value': str(n),
            'subtitle': f'Failed logins (last {hours}h)',
            'icon': 'fa-user-slash',
            'color': 'success' if n < 5 else 'warning' if n < 25 else 'danger',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'Failed logins', 'icon': 'fa-user-slash', 'color': 'secondary'}


def vault_activity_24h(params):
    """Vault password access events (read/update/create/delete) in the last 24h."""
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    try:
        from audit.models import AuditLog
        cutoff = _tz.now() - _td(hours=24)
        n = _scoped(AuditLog.objects.filter(
            object_type__iexact='password',
            timestamp__gte=cutoff,
        ), params).count()
        return {
            'value': str(n),
            'subtitle': 'Vault events (24h)',
            'icon': 'fa-key',
            'color': 'info',
        }
    except Exception:
        return {'value': '0', 'subtitle': 'Vault', 'icon': 'fa-key', 'color': 'secondary'}


def alerts_by_severity(params):
    """Open security alerts grouped by severity (table, all severities listed)."""
    try:
        from security_alerts.models import SecurityAlert
        rows = []
        alerts = _scoped(SecurityAlert.objects.all(), params)
        for sev in ['critical', 'high', 'medium', 'low', 'info']:
            n = alerts.filter(severity=sev, status='new').count()
            rows.append([sev.upper(), str(n)])
        return {'columns': ['Severity', 'Open'], 'rows': rows}
    except Exception:
        return {'columns': [], 'rows': []}


def monitors_status_breakdown(params):
    """Pie: monitor status counts (active vs warning vs down vs unknown)."""
    try:
        from monitoring.models import WebsiteMonitor
        labels = ['Active', 'Warning', 'Down', 'Unknown']
        keys = ['active', 'warning', 'down', 'unknown']
        data = []
        monitors = _scoped(WebsiteMonitor.objects.filter(is_enabled=True), params)
        for k in keys:
            data.append(monitors.filter(status=k).count())
        return {'labels': labels, 'data': data}
    except Exception:
        return {'labels': [], 'data': []}


# ---- Registry --------------------------------------------------------------

REGISTRY = {
    # metric
    'revenue_this_period': revenue_this_period,
    'open_tickets_count': open_tickets_count,
    'overdue_tickets_count': overdue_tickets_count,
    'unbilled_hours': unbilled_hours,
    'active_techs': active_techs,
    'avg_resolution_hours': avg_resolution_hours,
    # table
    'top_clients_by_revenue': top_clients_by_revenue,
    'tickets_by_priority': tickets_by_priority,
    'my_assigned_tickets': my_assigned_tickets,
    'at_risk_clients': at_risk_clients,
    # chart
    'revenue_trend_30d': revenue_trend_30d,
    'tickets_opened_30d': tickets_opened_30d,
    'hours_split_pie': hours_split_pie,
    'sla_breach_trend': sla_breach_trend,
    'client_health_breakdown': client_health_breakdown,
    # phase 4.3
    'low_stock_items': low_stock_items,
    # phase 5.3
    'recent_sales_activity': recent_sales_activity,
    # phase 9
    'security_alerts_24h': security_alerts_24h,
    'security_alerts_open_critical': security_alerts_open_critical,
    # v3.17.224 — operations / monitoring
    'techs_logged_in': techs_logged_in,
    'monitors_down': monitors_down,
    'ssl_expiring_soon': ssl_expiring_soon,
    'domain_expiring_soon': domain_expiring_soon,
    'warranties_expiring_soon': warranties_expiring_soon,
    'recent_failed_logins': recent_failed_logins,
    'vault_activity_24h': vault_activity_24h,
    'alerts_by_severity': alerts_by_severity,
    'monitors_status_breakdown': monitors_status_breakdown,
}

DATA_SOURCE_CHOICES = [
    # (key, label, default widget_type)
    ('revenue_this_period', 'Revenue this period (metric)', 'metric'),
    ('open_tickets_count', 'Open tickets count (metric)', 'metric'),
    ('overdue_tickets_count', 'SLA-overdue tickets (metric)', 'metric'),
    ('unbilled_hours', 'Unbilled hours at risk (metric)', 'metric'),
    ('active_techs', 'Active techs in 30d (metric)', 'metric'),
    ('avg_resolution_hours', 'Avg time to resolve (metric)', 'metric'),
    ('top_clients_by_revenue', 'Top clients by revenue (table)', 'table'),
    ('tickets_by_priority', 'Open tickets by priority (table)', 'table'),
    ('my_assigned_tickets', 'My assigned tickets (table)', 'table'),
    ('at_risk_clients', 'At-risk clients (table)', 'table'),
    ('revenue_trend_30d', 'Revenue trend 30d (bar chart)', 'chart_bar'),
    ('tickets_opened_30d', 'Tickets opened 30d (line chart)', 'chart_line'),
    ('hours_split_pie', 'Billable vs non-billable (pie chart)', 'chart_pie'),
    ('sla_breach_trend', 'SLA breach trend 30d (line chart)', 'chart_line'),
    ('client_health_breakdown', 'Client health breakdown (pie)', 'chart_pie'),
    ('low_stock_items', 'Low stock items (table)', 'table'),
    ('recent_sales_activity', 'Recent sales activity (table)', 'table'),
    ('security_alerts_24h', 'Security alerts last 24h by severity (table)', 'table'),
    ('security_alerts_open_critical', 'Open critical/high alerts (metric)', 'metric'),
    # v3.17.224 — operations / monitoring widgets
    ('techs_logged_in', 'Techs logged in (last 8h) (metric)', 'metric'),
    ('monitors_down', 'Monitors currently down (metric)', 'metric'),
    ('ssl_expiring_soon', 'SSL certs expiring soon (metric)', 'metric'),
    ('domain_expiring_soon', 'Domains expiring soon (metric)', 'metric'),
    ('warranties_expiring_soon', 'Warranties expiring soon (metric)', 'metric'),
    ('recent_failed_logins', 'Failed logins last 24h (metric)', 'metric'),
    ('vault_activity_24h', 'Vault events last 24h (metric)', 'metric'),
    ('alerts_by_severity', 'Open alerts by severity (table)', 'table'),
    ('monitors_status_breakdown', 'Monitor status breakdown (pie)', 'chart_pie'),
]


# v3.17.217: per-widget selectable categories. Each entry maps a
# data_source key to a list of {value, label, default?} items the wallboard
# template renders as a dropdown next to the widget title; the chosen value
# is passed to the source as `params['category']` and the source branches.
CATEGORIES = {
    'open_tickets_count': [
        {'value': 'all', 'label': 'All open', 'default': True},
        {'value': 'unassigned', 'label': 'Unassigned'},
        {'value': 'overdue', 'label': 'SLA overdue'},
        {'value': 'priority_high', 'label': 'P1 / P2 only'},
    ],
    'security_alerts_open_critical': [
        {'value': 'critical_high', 'label': 'Critical + High', 'default': True},
        {'value': 'critical_only', 'label': 'Critical only'},
        {'value': 'all_open', 'label': 'All open'},
        {'value': 'last_24h', 'label': 'Last 24h'},
    ],
    'tickets_by_priority': [
        {'value': 'priority', 'label': 'By priority', 'default': True},
        {'value': 'queue', 'label': 'By queue'},
        {'value': 'assigned_tech', 'label': 'By tech'},
    ],
    'tickets_opened_30d': [
        {'value': 'opened', 'label': 'Opened', 'default': True},
        {'value': 'closed', 'label': 'Closed'},
        {'value': 'net', 'label': 'Opened vs closed (net Δ)'},
    ],
    'revenue_trend_30d': [
        {'value': 'daily', 'label': 'Daily', 'default': True},
        {'value': 'weekly', 'label': 'Weekly buckets'},
        {'value': 'cumulative', 'label': 'Cumulative (running total)'},
    ],
    'at_risk_clients': [
        {'value': 'worst', 'label': 'Top 5 worst', 'default': True},
        {'value': 'trouble_only', 'label': 'Trouble only'},
        {'value': 'at_risk_only', 'label': 'At-Risk only'},
    ],
}


def get_categories(data_source):
    return CATEGORIES.get(data_source)


def is_valid_category(data_source, value):
    cats = CATEGORIES.get(data_source) or []
    return any(c['value'] == value for c in cats)


def default_category(data_source):
    cats = CATEGORIES.get(data_source) or []
    for c in cats:
        if c.get('default'):
            return c['value']
    return cats[0]['value'] if cats else None


# v3.17.220: wallboard-type templates. Each template defines a starter set
# of widgets; selecting one on the Create form pre-populates the new board
# so the user lands on a useful screen instead of an empty grid.
#
# Each item:
#   key (str)            — internal id; passed in the create form POST
#   label (str)          — human-readable
#   description (str)    — one-liner shown next to the option
#   widgets (list)       — list of {data_source, title, widget_type}
WALLBOARD_TEMPLATES = [
    {
        'key': 'custom',
        'label': 'Custom (empty)',
        'description': 'Start with no widgets — add them yourself.',
        'widgets': [],
    },
    {
        'key': 'operations',
        'label': 'Operations overview',
        'description': 'Open tickets, overdue, security alerts, ticket trend — the all-purpose NOC TV.',
        'widgets': [
            {'data_source': 'open_tickets_count', 'title': 'Open tickets', 'widget_type': 'metric'},
            {'data_source': 'overdue_tickets_count', 'title': 'SLA overdue', 'widget_type': 'metric'},
            {'data_source': 'security_alerts_open_critical', 'title': 'Security alerts', 'widget_type': 'metric'},
            {'data_source': 'active_techs', 'title': 'Active techs (30d)', 'widget_type': 'metric'},
            {'data_source': 'tickets_opened_30d', 'title': 'Tickets opened — 30d', 'widget_type': 'chart_line'},
            {'data_source': 'tickets_by_priority', 'title': 'Open tickets by priority', 'widget_type': 'table'},
        ],
    },
    {
        'key': 'tickets',
        'label': 'Tickets / Service Desk',
        'description': 'Service-desk-focused — queue load, dispatch view, ticket flow.',
        'widgets': [
            {'data_source': 'open_tickets_count', 'title': 'Open tickets', 'widget_type': 'metric'},
            {'data_source': 'overdue_tickets_count', 'title': 'SLA overdue', 'widget_type': 'metric'},
            {'data_source': 'avg_resolution_hours', 'title': 'Avg resolution time', 'widget_type': 'metric'},
            {'data_source': 'tickets_by_priority', 'title': 'Open tickets by priority', 'widget_type': 'table'},
            {'data_source': 'tickets_opened_30d', 'title': 'Opened vs closed (30d)', 'widget_type': 'chart_line'},
            {'data_source': 'sla_breach_trend', 'title': 'SLA breach trend', 'widget_type': 'chart_line'},
        ],
    },
    {
        'key': 'alerts',
        'label': 'Security & Alerts',
        'description': 'Critical alerts, recent fires, vulnerable surface area.',
        'widgets': [
            {'data_source': 'security_alerts_open_critical', 'title': 'Open critical alerts', 'widget_type': 'metric'},
            {'data_source': 'security_alerts_24h', 'title': 'New alerts (24h) by severity', 'widget_type': 'table'},
            {'data_source': 'recent_failed_logins', 'title': 'Failed logins (24h)', 'widget_type': 'metric'},
            {'data_source': 'alerts_by_severity', 'title': 'All open alerts by severity', 'widget_type': 'table'},
            {'data_source': 'vault_activity_24h', 'title': 'Vault events (24h)', 'widget_type': 'metric'},
        ],
    },
    {
        'key': 'monitoring',
        'label': 'Monitoring & Infrastructure',
        'description': 'Sites up, SSL/domain expirations, warranty cliffs.',
        'widgets': [
            {'data_source': 'monitors_down', 'title': 'Monitors down', 'widget_type': 'metric'},
            {'data_source': 'ssl_expiring_soon', 'title': 'SSL expiring (30d)', 'widget_type': 'metric'},
            {'data_source': 'domain_expiring_soon', 'title': 'Domains expiring (60d)', 'widget_type': 'metric'},
            {'data_source': 'warranties_expiring_soon', 'title': 'Warranties expiring (90d)', 'widget_type': 'metric'},
            {'data_source': 'monitors_status_breakdown', 'title': 'Monitor status', 'widget_type': 'chart_pie'},
        ],
    },
    {
        'key': 'sales',
        'label': 'Sales / Revenue',
        'description': 'Revenue this period, 30d trend, recent activity.',
        'widgets': [
            {'data_source': 'revenue_this_period', 'title': 'Revenue this period', 'widget_type': 'metric'},
            {'data_source': 'unbilled_hours', 'title': 'Unbilled hours at risk', 'widget_type': 'metric'},
            {'data_source': 'revenue_trend_30d', 'title': 'Revenue trend (30d)', 'widget_type': 'chart_bar'},
            {'data_source': 'top_clients_by_revenue', 'title': 'Top clients by revenue', 'widget_type': 'table'},
            {'data_source': 'recent_sales_activity', 'title': 'Recent sales activity', 'widget_type': 'table'},
        ],
    },
    {
        'key': 'health',
        'label': 'Client health',
        'description': 'At-risk clients + health breakdown + SLA pressure.',
        'widgets': [
            {'data_source': 'client_health_breakdown', 'title': 'Client health (pie)', 'widget_type': 'chart_pie'},
            {'data_source': 'at_risk_clients', 'title': 'At-risk clients', 'widget_type': 'table'},
            {'data_source': 'sla_breach_trend', 'title': 'SLA breach trend', 'widget_type': 'chart_line'},
        ],
    },
]


def get_template(key):
    for t in WALLBOARD_TEMPLATES:
        if t['key'] == key:
            return t
    return None


def get_widget_data(data_source: str, params: dict, viewer: dict = None) -> dict:
    """
    Look the source up, check the viewer may see it, and execute it.

    `viewer` comes from `viewer_for(request.user, request.is_staff_user)`.
    Omitting it means no access at all, not full access: a caller that forgets
    to pass one renders visibly empty tiles instead of quietly handing every
    client's data to whoever asked.

    Returns {'error': str} if the data source is unknown, the viewer may not
    see it, or the callable raises (so one bad widget can't take the whole
    dashboard down with it).
    """
    fn = REGISTRY.get(data_source)
    if fn is None:
        return {'error': f'Unknown data source: {data_source}'}

    viewer = no_access_viewer() if viewer is None else viewer
    perm, scope = WIDGET_SPECS.get(data_source, DEFAULT_SPEC)
    org_ids = viewer.get('org_ids')

    if perm and perm not in (viewer.get('perms') or ()):
        return _restricted(f'Restricted — needs the {perm} permission')
    if scope == SCOPE_MSP and org_ids is not None:
        return _restricted('Restricted — this widget reports across every client')

    params = dict(params or {})
    params['org_ids'] = org_ids
    if viewer.get('user_id') is not None:
        params['user_id'] = viewer['user_id']

    try:
        return fn(params)
    except Exception as exc:
        import logging
        logging.getLogger('reports.widgets').exception('widget %s failed', data_source)
        return {'error': str(exc)[:200]}
