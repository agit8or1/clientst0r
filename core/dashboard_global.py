"""Global View widgets for the new dashboard (v3.17.681).

Global View is the dashboard with no customer selected. These widgets show
figures across every customer the signed-in MSP staff member reaches, and
only those:

    reach              core.tenancy.accessible_org_ids (the staff client
                       scope, or memberships), intersected with
    the page's flag    accounts.permission_utils.orgs_with_perm for the flag
                       the source page checks (tickets_view, monitoring_view,
                       integrations_view)

`None` from both means every customer (superusers and unrestricted staff);
Organization.objects.all() is never used otherwise. Every gate starts with
gate_global: signed in, MSP staff, and no customer selected, so none of
these appear for customer users or inside a customer.
"""
from __future__ import annotations

from django.db.models import Count, Q

TOP_CLIENTS = 8
LIST_ROWS = 12


def _dw():
    from core import dashboard_widgets as dw
    return dw


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------

def reach(request):
    """Customer ids this request reaches (None = every customer); memoised."""
    def compute():
        from core.tenancy import accessible_org_ids
        return accessible_org_ids(request)
    return _dw()._memo(request, 'g_reach', compute)


def org_ids_for(request, perm):
    """Customers reached AND holding `perm` (None = every customer)."""
    def compute():
        from accounts.permission_utils import orgs_with_perm
        a, b = reach(request), orgs_with_perm(request.user, perm)
        if a is None:
            return None if b is None else set(b)
        return set(a) if b is None else set(a) & set(b)
    return _dw()._memo(request, ('g_perm', perm), compute)


def scoped(qs, request, perm, field='organization'):
    ids = org_ids_for(request, perm)
    qs = qs.filter(**{f'{field}__is_active': True})
    return qs if ids is None else qs.filter(**{f'{field}_id__in': ids})


def unrestricted(request):
    return reach(request) is None


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gate_global(request):
    dw = _dw()
    return (request.user.is_authenticated and dw.current_org(request) is None
            and (request.user.is_superuser or dw.is_staff(request)))


def gate_g_tickets(request):
    # /psa/ (require_psa_enabled; tickets_view per customer).
    dw = _dw()
    return (gate_global(request) and dw.psa_on(request)
            and dw.path_ok(request, dw.url('psa:ticket_list') or '/psa/')
            and org_ids_for(request, 'tickets_view') != set())


def gate_g_monitoring(request):
    dw = _dw()
    return (gate_global(request)
            and dw.path_ok(request, dw.url('monitoring:website_monitor_list') or '/monitoring/')
            and org_ids_for(request, 'monitoring_view') != set())


def gate_g_rmm(request):
    dw = _dw()
    return (gate_global(request)
            and dw.path_ok(request, dw.url('integrations:rmm_alerts') or '/integrations/rmm/alerts/')
            and org_ids_for(request, 'integrations_view') != set())


def gate_g_clients(request):
    return gate_global(request) and reach(request) != set()


def gate_g_audit(request):
    # The old Global View's rule for the install-wide audit log.
    from reports.access import has_msp_wide_perm
    return gate_global(request) and has_msp_wide_perm(request.user, 'audit_view', legacy='staff')


def gate_g_system(request):
    return gate_global(request) and request.user.is_superuser


def gate_g_map(request):
    # locations.views.global_location_map_data returns every customer's
    # locations, so the map is offered only to users who reach every
    # customer, and only when the global map is switched on.
    if not (gate_global(request) and unrestricted(request)):
        return False
    from core.models import SystemSetting
    try:
        return bool(SystemSetting.get_settings().global_locations_map_enabled)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Builders (org is always None here)
# ---------------------------------------------------------------------------

def open_tickets(request):
    def compute():
        from psa.models import Ticket
        from psa.my_work import open_q
        return scoped(Ticket.objects.all(), request, 'tickets_view').filter(open_q())
    return _dw()._memo(request, 'g_open_qs', compute)


def ticket_counts(request):
    def compute():
        dw = _dw()
        from psa.my_work import sla_bucket_qs
        now, _soon, _end = dw._sla_window()
        b = sla_bucket_qs('dash_due', now)
        return dw._with_deadline(open_tickets(request)).aggregate(
            open=Count('id'),
            unassigned=Count('id', filter=Q(assigned_to__isnull=True)),
            at_risk=Count('id', filter=b['at_risk']),
            breached=Count('id', filter=b['breached']),
        )
    return _dw()._memo(request, 'g_ticket_counts', compute)


def _list(**params):
    from urllib.parse import urlencode
    return _dw().url('psa:ticket_list', query=urlencode(params))


def build_g_kpi_open(request, org):
    n = ticket_counts(request)['open']
    return _dw()._kpi(n, 'Open tickets', 'fa-ticket', _list(queue='open'),
                      tone='primary', sub='all clients')


def build_g_kpi_unassigned(request, org):
    n = ticket_counts(request)['unassigned']
    return _dw()._kpi(n, 'Unassigned tickets', 'fa-inbox', _list(view='unassigned'),
                      tone='warning' if n else 'secondary')


def build_g_kpi_sla_risk(request, org):
    n = ticket_counts(request)['at_risk']
    return _dw()._kpi(n, 'SLA at risk', 'fa-hourglass-half', _list(view='sla', sla='at_risk'),
                      tone='warning' if n else 'secondary')


def build_g_kpi_breached(request, org):
    n = ticket_counts(request)['breached']
    return _dw()._kpi(n, 'SLA breached', 'fa-circle-exclamation', _list(view='sla', sla='breached'),
                      tone='danger' if n else 'secondary')


def _rmm_alerts(request):
    from integrations.models import RMMAlert, RMMDevice
    return scoped(RMMAlert.objects.filter(device__ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
                                          status='active'),
                  request, 'integrations_view', field='device__organization')


def build_g_kpi_rmm(request, org):
    c = _rmm_alerts(request).aggregate(total=Count('id'),
                                       critical=Count('id', filter=Q(severity='critical')))
    sub = f"{c['critical']} critical" if c['critical'] else ''
    return _dw()._kpi(c['total'], 'Active RMM alerts', 'fa-triangle-exclamation',
                      _dw().url('integrations:rmm_alerts'),
                      tone='danger' if c['critical'] else 'secondary',
                      sub=sub, sub_tone='danger' if sub else '')


def _monitors(request):
    from monitoring.models import WebsiteMonitor
    return scoped(WebsiteMonitor.objects.all(), request, 'monitoring_view')


def build_g_kpi_monitors_down(request, org):
    c = _monitors(request).aggregate(total=Count('id'), down=Count('id', filter=Q(status='down')))
    return _dw()._kpi(c['down'], 'Monitors down', 'fa-globe',
                      _dw().url('monitoring:website_monitor_list'),
                      tone='danger' if c['down'] else 'secondary', sub=f"of {c['total']}")


def _clients(request):
    from core.models import Organization
    qs = Organization.objects.filter(is_active=True)
    ids = reach(request)
    return qs if ids is None else qs.filter(pk__in=ids)


def build_g_kpi_clients(request, org):
    n = _clients(request).count()
    return _dw()._kpi(n, 'Active clients', 'fa-building', _dw().url('accounts:organization_list'),
                      tone='primary')


def build_g_top_clients(request, org):
    dw = _dw()
    from core.models import Organization
    rows = list(open_tickets(request).values('organization_id')
                .annotate(n=Count('id')).order_by('-n', 'organization_id')[:TOP_CLIENTS])
    names = dict(Organization.objects.filter(pk__in=[r['organization_id'] for r in rows])
                 .values_list('pk', 'name'))
    peak = max([r['n'] for r in rows] or [1])
    out = []
    for r in rows:
        pk = r['organization_id']
        out.append({'name': names.get(pk, '?'), 'count': r['n'],
                    'pct': round(100 * r['n'] / peak),
                    'url': dw.url('accounts:organization_detail', pk),
                    'tickets_url': dw.url('psa:ticket_list', query=f'client={pk}&queue=open')})
    return {'rows': out, 'more_url': dw.url('accounts:organization_list')}


def build_g_monitors_down(request, org):
    dw = _dw()
    qs = _monitors(request)
    down = list(qs.filter(status='down').select_related('organization')
                .order_by('organization__name', 'name')[:LIST_ROWS])
    c = qs.aggregate(total=Count('id'), down=Count('id', filter=Q(status='down')),
                     warning=Count('id', filter=Q(status='warning')))
    return {'rows': down, 'counts': c, 'more_url': dw.url('monitoring:website_monitor_list')}


def build_g_rmm_alerts(request, org):
    order = {'critical': 0, 'error': 1, 'warning': 2, 'info': 3}
    alerts = list(_rmm_alerts(request).select_related('device', 'device__organization')
                  .order_by('-triggered_at')[:40])
    alerts.sort(key=lambda a: (order.get(a.severity, 9), -a.triggered_at.timestamp()))
    return {'alerts': alerts[:LIST_ROWS], 'more_url': _dw().url('integrations:rmm_alerts'),
            'rmm_configured': bool(alerts) or _dw().rmm_configured()}


def build_g_audit(request, org):
    from audit.models import AuditLog
    qs = AuditLog.objects.select_related('user', 'organization')
    ids = reach(request)
    if ids is not None:
        # A scoped technician sees only their customers' rows (no
        # install-wide rows without a customer).
        qs = qs.filter(organization_id__in=ids)
    return {'logs': list(qs.order_by('-timestamp')[:15]),
            'more_url': _dw().url('audit:audit_log_list')}


def build_g_map(request, org):
    dw = _dw()
    from core.models import SystemSetting
    s = SystemSetting.get_settings()
    return {
        'map_default_zoom': s.map_default_zoom,
        'map_dragging_enabled': s.map_dragging_enabled,
        'locations_url': dw.url('locations:global_location_map_data'),
        'devices_url': '',
        'more_url': dw.url('locations:location_list'),
    }
