"""Operational Security Overview (/security/overview/).

A read-only summary of what the existing security and monitoring pages
already show. Each widget follows the page its numbers come from:

* Security Alerts / Incidents: the alert and incident lists
  (``require_perm('security_alerts_view')``, every customer the role reaches
  through ``views._user_orgs``; the current client does not narrow them).
* RMM Security: the RMM alerts page (MSP staff, the /integrations/ section
  permission, the selected client and the clients below it; nothing in
  global view, exactly as that page).
* Monitoring: the website monitor, WAN and expiration lists (the
  ``monitoring_enabled`` module, the /monitoring/ section permission, the
  selected client, or every client in global view for MSP staff), narrowed
  further to the customers where the role grants ``monitoring_view``.
* Response Performance: alert MTTA / MTTR follow the MTTA report
  (``reports_view_sla`` across every customer); incident response times and
  aging come from the incident timestamps the incident pages show.

Rules: no invented metrics or scores, no actions. A source with nothing set
up says "Not configured"; a figure that cannot be derived says "No data"
(never a fake 0). Every drill-down link is drawn only when
``core.navigation._PermProbe`` says the server would open it.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

NOT_CONFIGURED = 'not_configured'
NO_DATA = 'no_data'
SELECT_CLIENT = 'select_client'

OPEN_ALERT = ('new', 'acknowledged')
OPEN_INCIDENT = ('open', 'investigating', 'contained')
SEVERITIES = ('critical', 'high', 'medium', 'low', 'info')
WINDOW_DAYS = 30
TREND_DAYS = 14


class _Links:
    """reverse() + the navigation's permission probe: '' when the server
    would refuse the page."""

    def __init__(self, request):
        from core import navigation
        self.ctx = navigation.request_context(request)
        self.probe = navigation._PermProbe(self.ctx)

    def __call__(self, name, *args, query=''):
        try:
            path = reverse(name, args=args)
        except NoReverseMatch:
            return ''
        if not self.probe.allows(path):
            return ''
        return f'{path}?{query}' if query else path


def _minutes(deltas):
    """Mean of timedeltas in minutes, or None when there are none."""
    vals = [d.total_seconds() / 60 for d in deltas if d is not None and d.total_seconds() >= 0]
    if not vals:
        return None
    return sum(vals) / len(vals)


def fmt_minutes(value):
    if value is None:
        return None
    if value < 90:
        return f'{value:.0f} min'
    if value < 60 * 48:
        return f'{value / 60:.1f} h'
    return f'{value / 1440:.1f} d'


def _conn_state(conn, now):
    """The state integrations.status.connection_status() gives a connection
    from its legacy fields, without reading its credentials (no error text
    is shown here, so nothing needs redacting)."""
    from integrations.status import (
        WORKING_FRESHNESS, _ERROR_STATUSES, _OK_STATUSES, _PARTIAL_STATUSES, _is_enabled,
    )
    if not _is_enabled(conn):
        return 'off'
    status = (getattr(conn, 'last_sync_status', '') or '').strip().lower()
    if status in _PARTIAL_STATUSES:
        return 'partial'
    if (getattr(conn, 'last_error', '') or '').strip() or status in _ERROR_STATUSES:
        return 'broken'
    if status in _OK_STATUSES:
        return 'working'
    last = getattr(conn, 'last_sync_at', None)
    if last and now - last < WORKING_FRESHNESS:
        return 'working'
    return 'unknown'


def _health(conns, now):
    counts = {'working': 0, 'partial': 0, 'broken': 0, 'unknown': 0, 'off': 0}
    rows = []
    for c in conns:
        state = _conn_state(c, now)
        counts[state] += 1
        rows.append({'name': c.name, 'state': state, 'last_sync_at': c.last_sync_at})
    return {'counts': counts, 'rows': rows, 'total': len(rows)}


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

def _collection_health(orgs, now, link):
    """Whether the alert sources are verified to be collecting (monitoring
    health contract, roadmap 82.9): a zero next to an unverified source is
    not "no threats". Kept separate from the alert severities."""
    from events import source_health as sh
    from events.source_health_store import summary_for
    try:
        ids = {o.pk for o in orgs}
        summary = summary_for(ids, kinds=('security', 'push'), now=now)
    except Exception:
        return None
    return {'summary': summary, 'statement': sh.visibility_statement(summary),
            'worst': summary['worst'], 'link': link('events:source_health')}


def _alerts_widget(orgs, link, now):
    from .models import SecurityAlert, SecurityVendorConnection, SIEMWebhookEndpoint

    alerts = SecurityAlert.objects.filter(organization__in=orgs)
    c = alerts.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status__in=OPEN_ALERT)),
        critical=Count('id', filter=Q(status__in=OPEN_ALERT, severity='critical')),
        high=Count('id', filter=Q(status__in=OPEN_ALERT, severity='high')),
        unacked=Count('id', filter=Q(status='new')),
        device=Count('id', filter=Q(status__in=OPEN_ALERT) & ~Q(asset_hint='')),
        last_24h=Count('id', filter=Q(seen_at__gte=now - timedelta(hours=24))),
    )
    vendors = list(SecurityVendorConnection.objects.filter(organization__in=orgs)
                   .only('name', 'is_active', 'sync_enabled', 'last_sync_at',
                         'last_sync_status', 'last_error').order_by('name')[:50])
    siem = SIEMWebhookEndpoint.objects.filter(organization__in=orgs).aggregate(
        total=Count('id'), active=Count('id', filter=Q(is_active=True)))
    configured = bool(vendors or siem['total'] or c['total'])
    base = link('security_alerts:alert_list')
    # SR-08: webhooks that still take posts without a signature (connections
    # made before v3.17.715 keep that until switched over).
    unsigned = (list(SecurityVendorConnection.objects.filter(organization__in=orgs, is_active=True,
                                                            require_signature=False)
                     .order_by('name').values_list('name', flat=True)[:20])
                + list(SIEMWebhookEndpoint.objects.filter(organization__in=orgs, is_active=True, require_hmac=False)
                       .order_by('name').values_list('name', flat=True)[:20]))
    return {
        'state': '' if configured else NOT_CONFIGURED,
        'counts': c,
        'collection': _collection_health(orgs, now, link),
        'unsigned': unsigned,
        'sources': _health(vendors, now),
        'siem': siem,
        'links': {
            'list': base,
            'unacked': link('security_alerts:alert_list', query='status=new'),
            'critical': link('security_alerts:alert_list', query='severity=critical'),
            'high': link('security_alerts:alert_list', query='severity=high'),
            'connections': link('security_alerts:connection_list'),
            'siem': link('security_alerts:siem_endpoint_list'),
            'threats': link('security_alerts:threat_overview'),
        },
    }


def _incidents_widget(orgs, link, now, alerts_configured):
    from .models import SecurityIncident, SecurityIncidentSLAPolicy

    incidents = SecurityIncident.objects.filter(organization__in=orgs)
    open_qs = incidents.filter(status__in=OPEN_INCIDENT)
    agg = {f'sev_{s}': Count('id', filter=Q(severity=s)) for s in SEVERITIES}
    agg.update(
        open=Count('id'),
        new=Count('id', filter=Q(status='open')),
        investigating=Count('id', filter=Q(status='investigating')),
        contained=Count('id', filter=Q(status='contained')),
        unassigned=Count('id', filter=Q(assigned_to__isnull=True)),
    )
    c = open_qs.aggregate(**agg)
    # Incidents come from correlated alerts (or are opened by hand): with no
    # alert source and no incident ever, there is nothing to count yet.
    configured = alerts_configured or bool(c['open']) or incidents.exists()
    # Incidents carry no escalation field; the escalation signal that exists
    # is the SLA-breach timeline event (models.evaluate_incident_breaches),
    # and only where an SLA policy is set up.
    has_policy = SecurityIncidentSLAPolicy.objects.filter(organization__in=orgs, is_active=True).exists()
    breached = (open_qs.filter(events__kind='sla_breach').values('pk').distinct().count()
                if has_policy else None)
    responders = list(
        open_qs.filter(assigned_to__isnull=False)
        .values('assigned_to', 'assigned_to__username', 'assigned_to__first_name', 'assigned_to__last_name')
        .annotate(n=Count('id')).order_by('-n', 'assigned_to__username')[:6])
    for r in responders:
        full = f"{r['assigned_to__first_name']} {r['assigned_to__last_name']}".strip()
        r['name'] = full or r['assigned_to__username']
    sev_links = {s: link('security_alerts:incident_list', query=f'severity={s}') for s in SEVERITIES}
    return {
        'state': '' if configured else NOT_CONFIGURED,
        'counts': c,
        'by_severity': [(s, c[f'sev_{s}'], sev_links[s]) for s in SEVERITIES],
        'has_policy': has_policy,
        'breached': breached,
        'responders': responders,
        'links': {
            'list': link('security_alerts:incident_list'),
            'new': link('security_alerts:incident_list', query='status=open'),
            'investigating': link('security_alerts:incident_list', query='status=investigating'),
            'contained': link('security_alerts:incident_list', query='status=contained'),
            'playbooks': link('security_alerts:playbook_list'),
            'threats': link('security_alerts:threat_overview'),
        },
    }


def _rmm_widget(request, link, alerts_counts, now):
    from psa.visibility import is_msp_staff
    alerts_url = link('integrations:rmm_alerts')
    if not is_msp_staff(request.user) or not alerts_url:
        return None
    from core.dashboard_widgets import _rmm_alerts_qs
    from integrations.models import RMMConnection
    from integrations.ownership import connection_queryset

    out = {
        'device_security_alerts': alerts_counts['device'],
        'links': {
            'alerts': alerts_url,
            'critical': link('integrations:rmm_alerts', query='status=active&severity=critical'),
            'devices': link('integrations:rmm_devices'),
            'integrations': link('integrations:integration_list'),
            'security_alerts': link('security_alerts:alert_list'),
        },
    }
    # The RMM alerts page's own empty-state test: any RMM connection at all.
    if not RMMConnection.objects.exists():
        out['state'] = NOT_CONFIGURED
        return out
    from core.middleware import get_request_organization
    org = get_request_organization(request)
    conns = list(connection_queryset(request, RMMConnection, 'read')
                 .only('name', 'is_active', 'sync_enabled', 'last_sync_at', 'last_sync_status', 'last_error')
                 .order_by('name')[:50])
    out['health'] = _health(conns, now)
    if org is None:
        # integrations.views.rmm_alerts lists nothing until a client is picked.
        out['state'] = SELECT_CLIENT
        return out
    qs = _rmm_alerts_qs(request, org)
    out['state'] = ''
    out['counts'] = qs.aggregate(
        active=Count('id'),
        critical=Count('id', filter=Q(severity='critical')),
        error=Count('id', filter=Q(severity='error')),
        warning=Count('id', filter=Q(severity='warning')),
    )
    recent = list(qs.select_related('device').order_by('-triggered_at')[:5])
    device_url = link('integrations:rmm_devices')
    out['recent'] = [{
        'alert': a,
        'device_url': reverse('integrations:rmm_device_detail', args=[a.device_id]) if device_url else '',
    } for a in recent]
    return out


def _monitoring_widget(request, link, now):
    ctx = link.ctx
    if not ctx.get('monitoring_enabled'):
        return None
    list_url = link('monitoring:website_monitor_list')
    if not list_url:
        return None
    from accounts.permission_utils import filter_by_org_perm
    from locations.models import WAN
    from monitoring.models import Expiration, WebsiteMonitor

    from core.middleware import get_request_organization
    user = request.user
    org = get_request_organization(request)
    staff_global = org is None and (user.is_superuser or getattr(request, 'is_staff_user', False))

    def scoped(qs, global_ok):
        # Each list page's own rule: the selected client, or every client
        # in global view; then only customers the role grants monitoring_view.
        if org is not None:
            qs = qs.filter(organization=org)
        elif not global_ok:
            return qs.none()
        return filter_by_org_perm(qs, user, 'monitoring_view')

    web = scoped(WebsiteMonitor.objects.all(), staff_global).aggregate(
        total=Count('id'),
        down=Count('id', filter=Q(status='down')),
        warning=Count('id', filter=Q(status='warning')),
        active=Count('id', filter=Q(status='active')),
        unknown=Count('id', filter=Q(status='unknown')),
        paused=Count('id', filter=Q(is_enabled=False)),
        ssl_soon=Count('id', filter=Q(ssl_expires_at__lte=now + timedelta(days=30))),
    )
    wan = scoped(WAN.objects.filter(monitoring_enabled=True), staff_global).aggregate(
        total=Count('id'),
        down=Count('id', filter=Q(status='down')),
        active=Count('id', filter=Q(status='active')),
        maintenance=Count('id', filter=Q(status='maintenance')),
    )
    # expiration_list's global view follows Django's is_staff, not the
    # MSP-staff profile type.
    exp_global = org is None and (user.is_superuser or user.is_staff)
    exp = scoped(Expiration.objects.all(), exp_global).aggregate(
        total=Count('id'),
        expired=Count('id', filter=Q(expires_at__lt=now)),
        soon=Count('id', filter=Q(expires_at__gte=now, expires_at__lte=now + timedelta(days=30))),
    )
    integrations = None
    integrations_url = link('integrations:integration_list')
    if integrations_url:
        from integrations.models import GrandstreamConnection, OmadaConnection, UnifiConnection
        from integrations.ownership import connection_queryset
        conns = []
        for model in (UnifiConnection, OmadaConnection, GrandstreamConnection):
            conns += list(connection_queryset(request, model, 'read')
                          .only('name', 'is_active', 'last_sync_at', 'last_sync_status', 'last_error')[:25])
        integrations = _health(conns, now)
    return {
        'scope': 'client' if org is not None else ('global' if staff_global else 'none'),
        'web': web, 'wan': wan, 'exp': exp, 'integrations': integrations,
        'links': {
            'web': list_url,
            'web_down': link('monitoring:website_monitor_list', query='status=down'),
            'web_warning': link('monitoring:website_monitor_list', query='status=warning'),
            'wan': link('monitoring:wan_monitor_list'),
            'wan_down': link('monitoring:wan_monitor_list', query='status=down'),
            'exp': link('monitoring:expiration_list'),
            'integrations': integrations_url,
            'policies': link('ticket_routing:alerts') if ctx.get('psa_enabled') else '',
        },
    }


def _response_widget(request, orgs, link, now):
    from reports.access import has_msp_wide_perm
    from .models import SecurityAlert, SecurityIncident

    since = now - timedelta(days=WINDOW_DAYS)
    out = {'window_days': WINDOW_DAYS, 'trend_days': TREND_DAYS}

    # Alert MTTA / MTTR: the MTTA report's figures (acknowledged_at - seen_at,
    # alerts seen in the window), behind the report's own permission.
    report_url = link('reports:security_alert_mtta')
    if has_msp_wide_perm(request.user, 'reports_view_sla'):
        rows = list(SecurityAlert.objects.filter(organization__in=orgs, seen_at__gte=since)
                    .values_list('seen_at', 'acknowledged_at', 'resolved_at'))
        out['alert'] = {
            'count': len(rows),
            'mtta': fmt_minutes(_minutes(a - s for s, a, _r in rows if a)),
            'mttr': fmt_minutes(_minutes(r - s for s, _a, r in rows if r)),
            'unacked': sum(1 for _s, a, _r in rows if not a),
            'report_url': report_url,
        }

    inc = list(SecurityIncident.objects.filter(organization__in=orgs, opened_at__gte=since)
               .values_list('opened_at', 'acknowledged_at', 'resolved_at'))
    out['incident'] = {
        'count': len(inc),
        'tta': fmt_minutes(_minutes(a - o for o, a, _r in inc if a)),
        'ttr': fmt_minutes(_minutes(r - o for o, _a, r in inc if r)),
    }

    opened = list(SecurityIncident.objects.filter(organization__in=orgs, status__in=OPEN_INCIDENT)
                  .values_list('opened_at', flat=True))
    ages = [now - o for o in opened]
    out['aging'] = {
        'total': len(ages),
        'lt_1d': sum(1 for a in ages if a < timedelta(days=1)),
        'd1_7': sum(1 for a in ages if timedelta(days=1) <= a < timedelta(days=7)),
        'gt_7d': sum(1 for a in ages if a >= timedelta(days=7)),
        'oldest': fmt_minutes(max(ages).total_seconds() / 60) if ages else None,
    }

    # Daily alert volume (seen_at), the same count Threat Overview's
    # week-over-week figure uses.
    start = (now - timedelta(days=TREND_DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    local = timezone.localtime
    days = {}
    for seen in (SecurityAlert.objects.filter(organization__in=orgs, seen_at__gte=start)
                 .values_list('seen_at', flat=True)):
        d = local(seen).date()
        days[d] = days.get(d, 0) + 1
    today = local(now).date()
    series = []
    for i in range(TREND_DAYS - 1, -1, -1):
        d = today - timedelta(days=i)
        series.append({'date': d, 'count': days.get(d, 0)})
    peak = max((s['count'] for s in series), default=0)
    for s in series:
        s['pct'] = round(100 * s['count'] / peak) if peak else 0
    week_a = sum(s['count'] for s in series[-7:])
    week_b = sum(s['count'] for s in series[:-7])
    out['trend'] = {
        'series': series, 'peak': peak, 'week_a': week_a, 'week_b': week_b,
        'wow_pct': round((week_a - week_b) / week_b * 100, 1) if week_b else None,
    }
    out['links'] = {
        'report': report_url,
        'incidents': link('security_alerts:incident_list'),
        'threats': link('security_alerts:threat_overview'),
    }
    return out


def build_overview(request):
    from .views import _user_orgs
    now = timezone.now()
    link = _Links(request)
    orgs = _user_orgs(request.user)
    alerts = _alerts_widget(orgs, link, now)
    from core.middleware import get_request_organization
    return {
        'now': now,
        'current_org': get_request_organization(request),
        'alerts': alerts,
        'incidents': _incidents_widget(orgs, link, now, alerts['state'] != NOT_CONFIGURED),
        'rmm': _rmm_widget(request, link, alerts['counts'], now),
        'monitoring': _monitoring_widget(request, link, now),
        'response': _response_widget(request, orgs, link, now),
    }
