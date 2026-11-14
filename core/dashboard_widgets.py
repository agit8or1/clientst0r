"""
Dashboard widget registry (Phase 67, compact dashboard).

Every widget on the new dashboard is one `Widget` here:

  * `gate(request) -> bool` runs on every render and on every lazy fetch
    (`/core/dashboard/widget/<key>/`). It mirrors the check of the page the
    widget's data comes from, so a widget never shows what that page would
    refuse. A saved layout or a role preset only decides order, size and
    visibility among widgets whose gate passes; it never grants anything.
  * `build(request, org) -> dict | None` computes the widget's context for
    the selected customer (`request.current_organization`) only. `None`
    means "nothing to show" (for example the PSA integration cards at 0,
    which the classic dashboard also hides). Hidden or gated widgets are
    never built.
  * `zone`: 'banner' (2FA warning), 'kpi' (the KPI row), 'toolbar' (quick
    actions) or 'grid' (the panels filling the rest of the viewport).
  * `size`: default column span in the 3-column grid (grid widgets only).
  * `lazy`: rendered as a placeholder and fetched after the page loads.

Which widgets a role sees by default is `_PRESETS` below (one ordered list
per built-in preset); `preset_for_user` picks the preset from the user's
real role (accounts.role_seeds seed keys, RMM tiers, the legacy built-in
templates). An administrator's saved DashboardRoleDefault replaces a
preset's list; a user's own layout replaces both.

The header's primary actions (`header_actions`) are fixed, not widgets:
each is drawn only when its page's own check would let the user in.

The classic dashboard (core/dashboard_views.py, templates/core/dashboard.html)
does not use this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Callable

from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

# ---------------------------------------------------------------------------
# Role presets
# ---------------------------------------------------------------------------

PRESET_ADMIN = 'admin'
PRESET_MANAGER = 'manager'
PRESET_L3 = 'tech_l3'
PRESET_L2 = 'tech_l2'
PRESET_L1 = 'tech_l1'
PRESET_SALES = 'sales'
PRESET_CUSTOMER = 'customer'

PRESET_LABELS = {
    PRESET_ADMIN: 'Owner / Administrator',
    PRESET_MANAGER: 'Service Manager',
    PRESET_L3: 'L3 technician',
    PRESET_L2: 'L2 technician',
    PRESET_L1: 'L1 technician',
    PRESET_SALES: 'Sales',
    PRESET_CUSTOMER: 'Customer',
}
PRESET_KEYS = tuple(PRESET_LABELS)

ALL = PRESET_KEYS
STAFF = (PRESET_ADMIN, PRESET_MANAGER, PRESET_L3, PRESET_L2, PRESET_L1, PRESET_SALES)
TECHS = (PRESET_ADMIN, PRESET_MANAGER, PRESET_L3, PRESET_L2, PRESET_L1)

MAX_LAYOUT_KEYS = 64
MAX_QUICK_ACTIONS = 16
SIZES = (1, 2, 3)


# ---------------------------------------------------------------------------
# Shared checks (each mirrors the page the data comes from)
# ---------------------------------------------------------------------------

def _memo(request, key, compute):
    cache = getattr(request, '_dashboard_gate_memo', None)
    if cache is None:
        cache = {}
        try:
            request._dashboard_gate_memo = cache
        except AttributeError:
            return compute()
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def current_org(request):
    from core.middleware import get_request_organization
    return get_request_organization(request)


def _user(request):
    return request.user


def is_staff(request):
    from psa.visibility import is_msp_staff
    return _memo(request, 'staff', lambda: bool(is_msp_staff(request.user)))


def section_ok(request, perm):
    """SectionPermissionMiddleware's decision for the section `perm` guards
    (/vault/ vault_view, /docs/ docs_view, /assets/ assets_view,
    /monitoring/ monitoring_view, /integrations/ integrations_view)."""
    from accounts.middleware import SectionPermissionMiddleware

    def compute():
        user = request.user
        return bool(user.is_authenticated
                    and SectionPermissionMiddleware.denial(request, user, perm) is None)
    return _memo(request, ('section', perm), compute)


def path_ok(request, path):
    """Would SectionPermissionMiddleware let this user open `path`?"""
    from accounts.middleware import SectionPermissionMiddleware as gate
    if (path.startswith(gate.STAFF_ONLY_PREFIXES)
            and not path.startswith(gate.STAFF_ONLY_EXEMPT) and not is_staff(request)):
        return False
    perm = gate._required_perm(gate, path)
    return perm is None or section_ok(request, perm)


def org_perm(request, perm):
    """`perm` in the selected customer (orgs_with_perm, as filter_by_org_perm)."""
    org = current_org(request)
    if org is None:
        return False

    def compute():
        from accounts.permission_utils import orgs_with_perm
        allowed = orgs_with_perm(request.user, perm)
        return allowed is None or org.pk in allowed
    return _memo(request, ('org_perm', perm), compute)


def psa_on(request):
    def compute():
        try:
            from psa.feature_flags import is_psa_enabled
            return bool(is_psa_enabled())
        except Exception:
            return False
    return _memo(request, 'psa_on', compute)


def _setting(request, name, default=True):
    def compute():
        from core.models import SystemSetting
        try:
            return bool(getattr(SystemSetting.get_settings(), name, default))
        except Exception:
            return default
    return _memo(request, ('setting', name), compute)


def write_ok(request):
    """core.decorators.require_write for the selected customer."""
    user = request.user
    if user.is_superuser or user.is_staff:
        return True
    org = current_org(request)
    if org is None:
        return False

    def compute():
        from core.decorators import get_user_membership
        m = get_user_membership(request, org.pk)
        return bool(m and m.can_write())
    return _memo(request, 'write', compute)


def admin_ok(request):
    """core.decorators.require_admin for the selected customer (the audit log
    pages use it)."""
    user = request.user
    if user.is_superuser or user.is_staff:
        return True
    org = current_org(request)
    if org is None:
        return False

    def compute():
        from core.decorators import get_user_membership
        m = get_user_membership(request, org.pk)
        return bool(m and m.can_admin())
    return _memo(request, 'admin', compute)


def url(name, *args, query=''):
    try:
        u = reverse(name, args=args)
    except NoReverseMatch:
        return ''
    return f'{u}?{query}' if query else u


def visible_tickets(request, org):
    """PSA tickets of the selected customer this user may see: tickets_view
    for the customer, shared tickets only for customer users, and only their
    own unless their role sees the whole organization's (the rule the
    classic dashboard's Schedule panel and the portal use)."""
    from accounts.permission_utils import filter_by_org_perm
    from psa.models import Ticket
    from psa.visibility import customer_ticket_q, customer_visible_tickets

    user = request.user
    qs = Ticket.objects.filter(organization=org)
    qs = filter_by_org_perm(customer_visible_tickets(qs, user), user, 'tickets_view')
    if not is_staff(request):
        qs = qs.filter(customer_ticket_q(
            user, user.memberships.filter(is_active=True, organization__is_active=True)
            .select_related('role_template')))
    return qs


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gate_org(request):
    return request.user.is_authenticated and current_org(request) is not None


def gate_tickets(request):
    # /psa/ pages need PSA on (require_psa_enabled) and tickets_view for the
    # customer; the ticket list shows nothing else.
    return gate_org(request) and psa_on(request) and org_perm(request, 'tickets_view')


def gate_assets(request):
    return gate_org(request) and section_ok(request, 'assets_view')


def gate_docs(request):
    return gate_org(request) and section_ok(request, 'docs_view')


def gate_vault(request):
    return gate_org(request) and section_ok(request, 'vault_view')


def gate_monitoring(request):
    return gate_org(request) and section_ok(request, 'monitoring_view')


def gate_rmm(request):
    # integrations.views.rmm_staff_only + the /integrations/rmm/ staff-only
    # prefix + the integrations_view section flag.
    return (gate_org(request) and is_staff(request)
            and path_ok(request, url('integrations:rmm_alerts') or '/integrations/rmm/alerts/'))


def gate_psa_integration(request):
    # /integrations/ follows integrations_view (the classic cards used the
    # same flag for their counts).
    return gate_org(request) and section_ok(request, 'integrations_view')


def gate_audit(request):
    return gate_org(request) and admin_ok(request)


def gate_superuser(request):
    return request.user.is_authenticated and request.user.is_superuser


def gate_2fa_warning(request):
    if not request.user.is_authenticated:
        return False
    return not _has_2fa(request)


def gate_quick_actions(request):
    return request.user.is_authenticated


def _has_2fa(request):
    from accounts.azure_auth import azure_sso_counts_as_2fa
    if azure_sso_counts_as_2fa(request):
        return True
    if hasattr(request.user, 'totpdevice_set'):
        return request.user.totpdevice_set.filter(confirmed=True).exists()
    return False


# ---------------------------------------------------------------------------
# Builders (selected customer only)
# ---------------------------------------------------------------------------

def _kpi(value, label, icon, href='', tone='primary', sub='', sub_tone=''):
    return {'value': value, 'label': label, 'icon': icon, 'href': href,
            'tone': tone, 'sub': sub, 'sub_tone': sub_tone}


def build_kpi_tickets(request, org):
    n = visible_tickets(request, org).exclude(status__is_terminal=True).count()
    return _kpi(n, 'Open tickets', 'fa-ticket', url('psa:ticket_list', query=f'client={org.pk}'),
                tone='danger' if n else 'primary')


def build_kpi_assets(request, org):
    from accounts.permission_utils import filter_by_org_perm
    from assets.models import Asset
    n = filter_by_org_perm(Asset.objects.for_organization(org), request.user, 'assets_view').count()
    return _kpi(n, 'Assets', 'fa-box', url('assets:asset_list'), tone='success')


def build_kpi_documents(request, org):
    from accounts.permission_utils import filter_by_org_perm
    from docs.models import Document
    n = filter_by_org_perm(Document.objects.filter(organization=org, is_published=True),
                           request.user, 'docs_view').count()
    return _kpi(n, 'Documents', 'fa-file-alt', url('docs:document_list'), tone='info')


def build_kpi_passwords(request, org):
    from accounts.permission_utils import filter_by_org_perm
    from vault.models import Password
    n = filter_by_org_perm(Password.objects.for_organization(org), request.user, 'vault_view').count()
    return _kpi(n, 'Passwords', 'fa-key', url('vault:password_list'), tone='primary')


def _monitor_counts(request, org):
    from accounts.permission_utils import filter_by_org_perm
    from monitoring.models import WebsiteMonitor

    def compute():
        qs = filter_by_org_perm(WebsiteMonitor.objects.filter(organization=org),
                                request.user, 'monitoring_view')
        return qs.aggregate(
            total=Count('id'),
            down=Count('id', filter=Q(status='down')),
            warning=Count('id', filter=Q(status='warning')),
            active=Count('id', filter=Q(status='active')),
            unknown=Count('id', filter=Q(status='unknown')),
        )
    return _memo(request, ('monitors', org.pk), compute)


def build_kpi_monitors(request, org):
    c = _monitor_counts(request, org)
    sub, tone = '', ''
    if c['down']:
        sub, tone = f"{c['down']} down", 'danger'
    elif c['warning']:
        sub, tone = f"{c['warning']} warning", 'warning'
    return _kpi(c['total'], 'Monitors', 'fa-globe', url('monitoring:website_monitor_list'),
                tone='warning', sub=sub, sub_tone=tone)


def _rmm_alerts_qs(request, org):
    # integrations.views.rmm_alerts: the device's customer (and the
    # customers below it), resolved ownership only.
    from core.utils import descendant_org_ids
    from integrations.models import RMMAlert, RMMDevice
    return RMMAlert.objects.filter(
        device__organization_id__in=descendant_org_ids(org),
        device__ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
        status='active',
    )


def build_kpi_rmm_alerts(request, org):
    counts = _rmm_alerts_qs(request, org).aggregate(
        total=Count('id'), critical=Count('id', filter=Q(severity='critical')))
    sub = f"{counts['critical']} critical" if counts['critical'] else ''
    return _kpi(counts['total'], 'RMM alerts', 'fa-triangle-exclamation',
                url('integrations:rmm_alerts'),
                tone='danger' if counts['critical'] else 'secondary',
                sub=sub, sub_tone='danger' if sub else '')


def _my_open_tasks(request, org):
    from core.dashboard_panels import OPEN_TASK_STATUSES
    from scheduling.models import ScheduledTask
    return ScheduledTask.objects.filter(
        organization=org, status__in=OPEN_TASK_STATUSES, assigned_to=request.user).distinct()


def build_kpi_tasks(request, org):
    qs = _my_open_tasks(request, org)
    n = qs.count()
    overdue = qs.filter(due_date__lt=timezone.now()).count()
    return _kpi(n, 'My open tasks', 'fa-list-check', url('scheduling:scheduling_dashboard'),
                tone='secondary', sub=f'{overdue} overdue' if overdue else '',
                sub_tone='danger' if overdue else '')


def build_kpi_psa_companies(request, org):
    try:
        from accounts.permission_utils import filter_by_org_perm
        from integrations.models import PSACompany
    except ImportError:
        return None
    n = filter_by_org_perm(PSACompany.objects.for_organization(org), request.user,
                           'integrations_view').count()
    if not n:
        return None  # the classic dashboard hides the card at 0 as well
    return _kpi(n, 'PSA companies', 'fa-building', url('integrations:psa_companies'),
                tone='secondary')


def build_kpi_psa_tickets(request, org):
    try:
        from accounts.permission_utils import filter_by_org_perm
        from integrations.models import PSATicket
    except ImportError:
        return None
    n = filter_by_org_perm(PSATicket.objects.for_organization(org), request.user,
                           'integrations_view').filter(status__in=['new', 'in_progress']).count()
    if not n:
        return None
    return _kpi(n, 'Active PSA tickets', 'fa-ticket-alt', url('integrations:psa_tickets'),
                tone='danger')


def build_schedule(request, org):
    from core.dashboard_panels import get_schedule
    return {'schedule_days': get_schedule(request.user, org),
            'more_url': url('scheduling:scheduling_dashboard')}


def build_tasks(request, org):
    from core.dashboard_panels import get_tasks
    return {'task_rows': get_tasks(request.user, org),
            'more_url': url('scheduling:scheduling_dashboard')}


def build_monitors(request, org):
    c = _monitor_counts(request, org)
    base = url('monitoring:website_monitor_list')
    return {'counts': c, 'more_url': base,
            'rows': [
                ('active', 'Healthy', 'fa-check-circle', 'success', c['active']),
                ('warning', 'Warning', 'fa-exclamation-triangle', 'warning', c['warning']),
                ('down', 'Down', 'fa-times-circle', 'danger', c['down']),
                ('unknown', 'Not checked yet', 'fa-circle-question', 'secondary', c['unknown']),
            ]}


def build_map(request, org):
    from core.models import SystemSetting
    s = SystemSetting.get_settings()
    devices = is_staff(request) and path_ok(
        request, url('integrations:rmm_device_map_data') or '/integrations/rmm/')
    return {
        'map_default_zoom': s.map_default_zoom,
        'map_dragging_enabled': s.map_dragging_enabled,
        'locations_url': url('locations:location_map_data'),
        'devices_url': url('integrations:rmm_device_map_data') if devices else '',
        'more_url': url('locations:location_list'),
    }


def build_ticket_status(request, org):
    from psa.models import TicketStatus
    qs = visible_tickets(request, org).exclude(status__is_terminal=True)
    rows = list(qs.values('status_id').annotate(n=Count('id')).order_by('-n'))
    names = dict(TicketStatus.objects.filter(pk__in=[r['status_id'] for r in rows])
                 .values_list('pk', 'name'))
    base = url('psa:ticket_list')
    total = sum(r['n'] for r in rows)
    out = []
    for r in rows:
        out.append({'name': names.get(r['status_id'], '?'), 'count': r['n'],
                    'pct': round(100 * r['n'] / total) if total else 0,
                    'href': f"{base}?client={org.pk}&status={r['status_id']}" if base else ''})
    return {'rows': out, 'total': total,
            'more_url': f'{base}?client={org.pk}' if base else ''}


ACTIVITY_DAYS = 14


def build_ticket_activity(request, org):
    today = timezone.localdate()
    start = today - timedelta(days=ACTIVITY_DAYS - 1)
    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    qs = visible_tickets(request, org)
    opened = {}
    for dt in qs.filter(created_at__gte=start_dt).values_list('created_at', flat=True):
        d = timezone.localtime(dt).date()
        opened[d] = opened.get(d, 0) + 1
    resolved = {}
    for r, c in qs.filter(Q(resolved_at__gte=start_dt) | Q(closed_at__gte=start_dt)).values_list(
            'resolved_at', 'closed_at'):
        # Resolved first, else closed: whichever falls in the window.
        dt = r if r is not None and r >= start_dt else c
        if dt is None or dt < start_dt:
            continue
        d = timezone.localtime(dt).date()
        resolved[d] = resolved.get(d, 0) + 1
    days = []
    peak = 1
    for i in range(ACTIVITY_DAYS):
        d = start + timedelta(days=i)
        o, r = opened.get(d, 0), resolved.get(d, 0)
        peak = max(peak, o, r)
        days.append({'day': d, 'opened': o, 'resolved': r})
    for row in days:
        row['opened_pct'] = round(100 * row['opened'] / peak)
        row['resolved_pct'] = round(100 * row['resolved'] / peak)
    half = ACTIVITY_DAYS // 2
    this_week = sum(r['opened'] for r in days[half:])
    last_week = sum(r['opened'] for r in days[:half])
    return {
        'days': days,
        'opened_total': sum(opened.values()),
        'resolved_total': sum(resolved.values()),
        'this_week': this_week, 'last_week': last_week,
        'trend': this_week - last_week,
        'trend_abs': abs(this_week - last_week),
        'window': ACTIVITY_DAYS,
        'more_url': url('psa:ticket_list', query=f'client={org.pk}'),
    }


def build_recent_activity(request, org):
    from audit.models import AuditLog
    logs = list(AuditLog.objects.filter(organization=org).select_related('user')
                .order_by('-timestamp')[:15])
    return {'logs': logs, 'more_url': url('audit:audit_log_list')}


def build_system_status(request, org):
    import shutil

    from django.db import connection

    from config.version import get_version
    from core.models import SystemSetting

    s = SystemSetting.get_settings()
    current = get_version()
    latest = (getattr(s, 'latest_release_version', '') or '').strip()
    update = ''
    if latest:
        try:
            from packaging import version
            if version.parse(latest) > version.parse(current):
                update = latest
        except Exception:
            update = ''
    db_ok = True
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception:
        db_ok = False
    disk = None
    try:
        u = shutil.disk_usage('/')
        disk = round(100 * u.used / u.total, 1)
    except Exception:
        disk = None
    mem = None
    try:
        import psutil
        mem = psutil.virtual_memory().percent
    except Exception:
        mem = None
    return {
        'version': current, 'update': update,
        'last_check': getattr(s, 'latest_release_checked_at', None),
        'db_ok': db_ok, 'db_engine': connection.vendor,
        'disk': disk, 'mem': mem,
        'status_url': url('core:system_status'),
        'updates_url': url('core:system_updates'),
    }


def build_rmm_alerts(request, org):
    order = {'critical': 0, 'error': 1, 'warning': 2, 'info': 3}
    alerts = list(_rmm_alerts_qs(request, org).select_related('device')
                  .order_by('-triggered_at')[:40])
    alerts.sort(key=lambda a: (order.get(a.severity, 9), -a.triggered_at.timestamp()))
    return {'alerts': alerts[:12], 'more_url': url('integrations:rmm_alerts')}


def build_2fa_warning(request, org):
    return {'setup_url': url('two_factor:setup')}


def build_quick_actions(request, org):
    from core.quick_actions import resolve_for_user
    return {'actions': resolve_for_user(request.user, _qa_context(request), request=request),
            'edit_url': url('accounts:quick_actions_edit')}


def _qa_context(request):
    from core.models import SystemSetting
    try:
        s = SystemSetting.get_settings()
        flags = {
            'psa_enabled': bool(getattr(s, 'psa_enabled', False)),
            'vehicles_enabled': bool(getattr(s, 'vehicles_enabled', True)),
            'reports_enabled': getattr(s, 'reports_enabled', True),
        }
    except Exception:
        flags = {'psa_enabled': False, 'vehicles_enabled': True, 'reports_enabled': True}
    flags['current_organization'] = current_org(request)
    return flags


# ---------------------------------------------------------------------------
# Service desk figures (selected customer, ticket-list scoping)
# ---------------------------------------------------------------------------
#
# Every figure starts from `visible_tickets` (the selected customer, the
# user's tickets_view, customer users' shared-and-own rule) narrowed to open
# tickets with psa.my_work.open_q, the definition behind the ticket list's
# `?queue=open` filter and My Work. The SLA deadline is the one My Work and
# the ticket list sort by: first response until one is made, then
# resolution. Tickets in a status that pauses the SLA clock are not counted
# as late or at risk.
#
#   Overdue      open, clock running, deadline passed
#   SLA at risk  open, clock running, deadline within core.workspace.SLA_SOON
#   Due today    open, clock running, deadline between now and midnight
#
# The ticket list has no SLA filter, so those tiles open `?queue=open` for
# the customer, which the list orders soonest deadline first.

def gate_staff_tickets(request):
    """Ticket figures that only make sense for MSP technicians (assigned to
    me, unassigned, workload). Customer users never get them."""
    return gate_tickets(request) and is_staff(request)


def gate_dispatch(request):
    # psa.views.dispatch_board / dispatch_heatmap: PSA on, MSP staff
    # (_staff_or_403).
    return gate_org(request) and psa_on(request) and is_staff(request)


def gate_approvals(request):
    # psa.views.approval_decide: MSP staff, @require_write, PSA on. The
    # count is My Work's approval queues (psa.views._my_work_approvals).
    return gate_dispatch(request) and write_ok(request)


def gate_my_time(request):
    # psa.views.my_timesheet: PSA on; time is logged by technicians.
    return gate_dispatch(request)


def gate_crm(request):
    # crm.views: /crm/ is MSP staff only (SectionPermissionMiddleware),
    # @require_perm('crm_view'); the navigation offers CRM only when the
    # module is on (SystemSetting.crm_enabled).
    if not (gate_org(request) and _setting(request, 'crm_enabled', False)):
        return False
    if not path_ok(request, url('crm:home') or '/crm/'):
        return False
    from accounts.permission_utils import user_has_perm
    return _memo(request, 'crm_view', lambda: bool(user_has_perm(request.user, 'crm_view')))


def _open_tickets(request, org):
    from psa.my_work import open_q
    return visible_tickets(request, org).filter(open_q())


def _with_deadline(qs):
    from django.db.models import Case, DateTimeField, F, When
    return qs.annotate(dash_due=Case(
        When(first_response_at__isnull=True, first_response_due_at__isnull=False,
             then=F('first_response_due_at')),
        default=F('resolution_due_at'),
        output_field=DateTimeField(),
    ))


def _sla_window():
    from core.workspace import SLA_SOON
    now = timezone.now()
    end_today = timezone.make_aware(datetime.combine(timezone.localdate(), time.max))
    return now, now + SLA_SOON, end_today


def sla_counts(request, org):
    def compute():
        now, soon, end_today = _sla_window()
        qs = _with_deadline(_open_tickets(request, org))
        running = ~Q(status__pauses_sla=True)
        return qs.aggregate(
            open=Count('id'),
            paused=Count('id', filter=Q(status__pauses_sla=True)),
            overdue=Count('id', filter=running & Q(dash_due__lt=now)),
            at_risk=Count('id', filter=running & Q(dash_due__gte=now, dash_due__lte=soon)),
            due_today=Count('id', filter=running & Q(dash_due__gte=now, dash_due__lte=end_today)),
            on_track=Count('id', filter=running & Q(dash_due__gt=soon)),
            no_sla=Count('id', filter=running & Q(dash_due__isnull=True)),
        )
    return _memo(request, ('sla_counts', org.pk), compute)


def _ticket_list(org, **params):
    """The ticket list filtered by its own query parameters
    (psa.views.ticket_list: client, assigned, queue)."""
    from urllib.parse import urlencode
    return url('psa:ticket_list', query=urlencode(dict(client=org.pk, **params)))


def build_kpi_my_open(request, org):
    n = _open_tickets(request, org).filter(assigned_to=request.user).count()
    return _kpi(n, 'My open tickets', 'fa-user-check', _ticket_list(org, assigned='me', queue='open'),
                tone='primary')


def build_kpi_sla_risk(request, org):
    n = sla_counts(request, org)['at_risk']
    return _kpi(n, 'SLA at risk', 'fa-hourglass-half', _ticket_list(org, queue='open'),
                tone='warning' if n else 'secondary')


def build_kpi_overdue(request, org):
    n = sla_counts(request, org)['overdue']
    return _kpi(n, 'Overdue tickets', 'fa-circle-exclamation', _ticket_list(org, queue='open'),
                tone='danger' if n else 'secondary')


def build_kpi_unassigned(request, org):
    n = _open_tickets(request, org).filter(assigned_to__isnull=True).count()
    return _kpi(n, 'Unassigned tickets', 'fa-inbox',
                _ticket_list(org, assigned='unassigned', queue='open'),
                tone='warning' if n else 'secondary')


def build_kpi_due_today(request, org):
    n = sla_counts(request, org)['due_today']
    return _kpi(n, 'Due today', 'fa-calendar-day', _ticket_list(org, queue='open'),
                tone='info' if n else 'secondary')


def _approval_queues(request):
    from psa.views import _my_work_approvals
    return _memo(request, 'approval_queues', lambda: _my_work_approvals(request))


def build_kpi_approvals(request, org):
    queues = [q for q in _approval_queues(request) if q['count']]
    n = sum(q['count'] for q in queues)
    # One waiting queue: open it; several (or none): My Work lists them all.
    href = queues[0]['url'] if len(queues) == 1 else url('psa:my_work')
    sub = ', '.join(f"{q['count']} {q['label'].lower()}" for q in queues[:2]) if len(queues) > 1 else ''
    return _kpi(n, 'Pending approvals', 'fa-circle-check', href,
                tone='warning' if n else 'secondary', sub=sub)


QUEUE_LIMIT = 25


def _queue_rows(qs):
    from django.db.models import F
    from psa.sla import status_chip
    now = timezone.now()
    rows = []
    qs = _with_deadline(qs).select_related('status', 'priority', 'organization', 'assigned_to')
    # Clock running first (soonest deadline first), then paused ones.
    order = ('status__pauses_sla', F('dash_due').asc(nulls_last=True), 'created_at')
    for t in qs.order_by(*order)[:QUEUE_LIMIT]:
        chip = status_chip(t, now=now)
        rows.append({
            'number': t.ticket_number, 'subject': t.subject,
            'status': t.status.name if t.status_id else '',
            'priority': t.priority.code if t.priority_id else '',
            'assignee': (t.assigned_to.get_full_name() or t.assigned_to.get_username())
            if t.assigned_to_id else '',
            'due': t.dash_due,
            'due_in': _short_delta(t.dash_due - now) if t.dash_due else '',
            'late': bool(t.dash_due and t.dash_due < now and not t.status.pauses_sla),
            'sla_kind': chip.get('kind', ''),
            'sla_label': chip.get('label', ''),
            'url': url('psa:ticket_detail', t.ticket_number),
        })
    return rows


def _short_delta(delta):
    """'3d 4h', '4h 48m', '12m' (a deadline in the future)."""
    mins = max(0, int(delta.total_seconds() // 60))
    d, rem = divmod(mins, 1440)
    h, m = divmod(rem, 60)
    if d:
        return f'{d}d {h}h'
    if h:
        return f'{h}h {m:02d}m'
    return f'{m}m'


def build_my_queue(request, org):
    qs = _open_tickets(request, org).filter(assigned_to=request.user)
    return {'rows': _queue_rows(qs), 'total': qs.count(), 'show_assignee': False,
            'empty': 'Nothing assigned to you at this customer.',
            'more_url': _ticket_list(org, assigned='me', queue='open')}


def build_unassigned_queue(request, org):
    qs = _open_tickets(request, org).filter(assigned_to__isnull=True)
    return {'rows': _queue_rows(qs), 'total': qs.count(), 'show_assignee': False,
            'empty': 'Every open ticket has someone on it.',
            'more_url': _ticket_list(org, assigned='unassigned', queue='open')}


def build_sla_overview(request, org):
    c = sla_counts(request, org)
    rows = [
        ('Overdue', 'danger', c['overdue']),
        ('At risk (next 2 h)', 'warning', c['at_risk']),
        ('On track', 'success', c['on_track']),
        ('Paused (waiting)', 'secondary', c['paused']),
        ('No SLA', 'secondary', c['no_sla']),
    ]
    total = c['open'] or 0
    out = [{'label': label, 'tone': tone, 'count': n,
            'pct': round(100 * n / total) if total else 0} for label, tone, n in rows]
    timed = c['open'] - c['paused'] - c['no_sla']
    compliance = round(100 * (timed - c['overdue']) / timed) if timed > 0 else None
    return {'rows': out, 'total': total, 'compliance': compliance,
            'more_url': _ticket_list(org, queue='open')}


def build_workload(request, org):
    from django.contrib.auth import get_user_model
    now = timezone.now()
    qs = _with_deadline(_open_tickets(request, org))
    rows = list(qs.values('assigned_to').annotate(
        n=Count('id'),
        late=Count('id', filter=~Q(status__pauses_sla=True) & Q(dash_due__lt=now)),
    ).order_by('-n')[:30])
    ids = [r['assigned_to'] for r in rows if r['assigned_to']]
    users = {u.pk: (u.get_full_name() or u.get_username())
             for u in get_user_model().objects.filter(pk__in=ids)}
    peak = max([r['n'] for r in rows] or [1])
    base = url('psa:ticket_list')
    out = []
    for r in rows:
        uid = r['assigned_to']
        out.append({
            'name': users.get(uid, '?') if uid else 'Unassigned',
            'unassigned': uid is None,
            'count': r['n'], 'late': r['late'],
            'pct': round(100 * r['n'] / peak),
            'href': _ticket_list(org, assigned=uid if uid else 'unassigned', queue='open')
            if base else '',
        })
    out.sort(key=lambda r: (r['unassigned'] is False, -r['count']))
    return {'rows': out, 'more_url': url('psa:dispatch_board'),
            'heatmap_url': url('psa:dispatch_heatmap')}


def build_ticket_recent(request, org):
    qs = (visible_tickets(request, org).select_related('status')
          .order_by('-updated_at')[:12])
    return {'rows': [{'number': t.ticket_number, 'subject': t.subject,
                      'status': t.status.name if t.status_id else '',
                      'when': t.updated_at,
                      'url': url('psa:ticket_detail', t.ticket_number)} for t in qs],
            'more_url': _ticket_list(org)}


def build_my_time(request, org):
    """The signed-in user's own logged time this week (every customer:
    a timesheet is one per person), as psa:my_timesheet shows it."""
    from psa.models import TicketTimeEntry
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    start = timezone.make_aware(datetime.combine(monday, time.min))
    entries = list(TicketTimeEntry.objects.filter(user=request.user, started_at__gte=start)
                   .values_list('started_at', 'duration_minutes', 'is_billable', 'ended_at'))
    days = [{'day': monday + timedelta(days=i), 'minutes': 0} for i in range(7)]
    total = billable = running = 0
    for started, minutes, is_billable, ended in entries:
        if ended is None:
            running += 1
            continue
        d = (timezone.localtime(started).date() - monday).days
        if 0 <= d < 7:
            days[d]['minutes'] += minutes or 0
        total += minutes or 0
        if is_billable:
            billable += minutes or 0
    peak = max([d['minutes'] for d in days] + [1])
    for d in days:
        d['pct'] = round(100 * d['minutes'] / peak)
        d['is_today'] = d['day'] == today
        d['hours'] = f"{d['minutes'] / 60:.1f}"
    today_min = days[today.weekday()]['minutes']
    return {'days': days, 'total': f'{total / 60:.1f}', 'billable': f'{billable / 60:.1f}',
            'today': f'{today_min / 60:.1f}', 'running': running,
            'more_url': url('psa:my_timesheet')}


# ---------------------------------------------------------------------------
# Sales (CRM)
# ---------------------------------------------------------------------------

def _crm_scope(request, qs):
    # crm.views._scope_qs: superusers see every tenant, everyone else the
    # selected one.
    from crm.views import _scope_qs
    return _scope_qs(request, qs)


OPEN_STAGES = ('discovery', 'qualified', 'proposal', 'negotiation')


def build_kpi_crm_open(request, org):
    from crm.models import Opportunity
    qs = _crm_scope(request, Opportunity.objects.filter(stage__in=OPEN_STAGES))
    n = qs.count()
    return _kpi(n, 'Open opportunities', 'fa-handshake', url('crm:pipeline'), tone='primary')


def build_kpi_crm_leads(request, org):
    from crm.models import Lead
    n = _crm_scope(request, Lead.objects.filter(status__in=('new', 'contacted', 'qualified'))).count()
    return _kpi(n, 'Active leads', 'fa-user-plus', url('crm:lead_list'), tone='info')


def build_crm_pipeline(request, org):
    from django.db.models import Sum
    from crm.models import Opportunity
    labels = dict(Opportunity.STAGE_CHOICES)
    qs = _crm_scope(request, Opportunity.objects.filter(stage__in=OPEN_STAGES))
    agg = {r['stage']: r for r in qs.values('stage').annotate(n=Count('id'),
                                                              value=Sum('estimated_value'))}
    peak = max([r['n'] for r in agg.values()] + [1])
    rows = []
    for stage in OPEN_STAGES:
        r = agg.get(stage, {'n': 0, 'value': 0})
        rows.append({'label': labels.get(stage, stage), 'count': r['n'],
                     'value': r['value'] or 0, 'pct': round(100 * r['n'] / peak)})
    return {'rows': rows, 'total': sum(r['count'] for r in rows),
            'value': sum((r['value'] for r in rows), 0), 'more_url': url('crm:pipeline')}


def build_crm_closing(request, org):
    from crm.models import Opportunity
    today = timezone.localdate()
    qs = (_crm_scope(request, Opportunity.objects.filter(stage__in=OPEN_STAGES,
                                                         expected_close_date__isnull=False,
                                                         expected_close_date__lte=today + timedelta(days=30)))
          .select_related('client_org').order_by('expected_close_date')[:12])
    return {'rows': [{'name': o.name, 'client': o.client_org.name if o.client_org_id else '',
                      'stage': o.get_stage_display(), 'date': o.expected_close_date,
                      'overdue': o.expected_close_date < today,
                      'url': url('crm:opportunity_detail', o.pk)} for o in qs],
            'more_url': url('crm:opportunity_list')}


# ---------------------------------------------------------------------------
# Header actions (fixed, permission-gated; not customisable widgets)
# ---------------------------------------------------------------------------

def _can_new_ticket(request):
    from core.quick_actions import _can_ticket
    return psa_on(request) and _can_ticket(request)


def _can_add_client(request):
    # accounts.views.organization_create turns customer (portal) users away.
    from accounts.delegation import is_customer_actor
    return not is_customer_actor(request.user)


def _can_create_project(request):
    # psa.views.project_form: @require_write, @require_psa_enabled.
    return psa_on(request) and write_ok(request)


HEADER_ACTIONS = (
    # (key, label, icon, url name, check)
    ('new_ticket', 'New Ticket', 'fa-plus', 'psa:ticket_create', _can_new_ticket),
    ('log_time', 'Log Time', 'fa-clock', 'psa:my_timesheet', gate_my_time),
    ('add_client', 'Add Client', 'fa-building', 'accounts:organization_create', _can_add_client),
    ('create_project', 'Create Project', 'fa-diagram-project', 'psa:project_create',
     _can_create_project),
    ('dispatch_board', 'Dispatch Board', 'fa-table-list', 'psa:dispatch_board', gate_dispatch),
)


def header_actions(request):
    """The header's primary actions this user's checks allow (fails closed)."""
    out = []
    for key, label, icon, name, check in HEADER_ACTIONS:
        try:
            ok = bool(check(request))
        except Exception:
            ok = False
        href = url(name) if ok else ''
        if href:
            out.append({'key': key, 'label': label, 'icon': icon, 'url': href,
                        'primary': key == 'new_ticket'})
    return out


def greeting(user):
    hour = timezone.localtime().hour
    part = 'morning' if hour < 12 else 'afternoon' if hour < 18 else 'evening'
    name = (user.first_name or user.get_username()) if user.is_authenticated else ''
    return f'Good {part}, {name}' if name else f'Good {part}'


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Widget:
    key: str
    label: str
    icon: str
    gate: Callable
    build: Callable
    template: str
    zone: str = 'grid'
    size: int = 1
    lazy: bool = False
    hideable: bool = True
    expandable: bool = True
    description: str = ''
    link: str = ''            # url name of the page behind the widget
    link_client: bool = False  # add ?client=<selected customer> (PSA lists)
    link_query: str = ''       # further ticket-list filters (assigned, queue)

    def link_url(self, org):
        if not self.link:
            return ''
        parts = []
        if self.link_client and org is not None:
            parts.append(f'client={org.pk}')
        if self.link_query:
            parts.append(self.link_query)
        return url(self.link, query='&'.join(parts))

    def allowed(self, request) -> bool:
        try:
            return bool(self.gate(request))
        except Exception:
            # Fail closed: an error in a check never shows the widget.
            return False


_KPI_TPL = 'core/dashboard/_kpi.html'
_QUEUE_TPL = 'core/dashboard/_w_ticket_queue.html'

WIDGETS = (
    Widget('security_2fa', 'Two-factor warning', 'fa-shield-alt', gate_2fa_warning,
           build_2fa_warning, 'core/dashboard/_w_2fa.html', zone='banner', hideable=False,
           expandable=False, description='Shown until two-factor authentication is on.'),

    # Service desk figures (MSP staff; see "Service desk figures" above).
    Widget('kpi_my_open', 'My open tickets', 'fa-user-check', gate_staff_tickets,
           build_kpi_my_open, _KPI_TPL, zone='kpi', expandable=False,
           description='Open tickets assigned to you at this customer.'),
    Widget('kpi_sla_risk', 'SLA at risk', 'fa-hourglass-half', gate_staff_tickets,
           build_kpi_sla_risk, _KPI_TPL, zone='kpi', expandable=False,
           description='Open tickets whose next SLA deadline is within two hours.'),
    Widget('kpi_overdue', 'Overdue tickets', 'fa-circle-exclamation', gate_staff_tickets,
           build_kpi_overdue, _KPI_TPL, zone='kpi', expandable=False,
           description='Open tickets past their SLA deadline (paused ones excluded).'),
    Widget('kpi_unassigned', 'Unassigned tickets', 'fa-inbox', gate_staff_tickets,
           build_kpi_unassigned, _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_approvals', 'Pending approvals', 'fa-circle-check', gate_approvals,
           build_kpi_approvals, _KPI_TPL, zone='kpi', lazy=True, expandable=False,
           description='The approval queues on My Work you can act on.'),
    Widget('kpi_due_today', 'Due today', 'fa-calendar-day', gate_staff_tickets,
           build_kpi_due_today, _KPI_TPL, zone='kpi', expandable=False,
           description='Open tickets whose SLA deadline falls later today.'),
    Widget('kpi_crm_open', 'Open opportunities', 'fa-handshake', gate_crm, build_kpi_crm_open,
           _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_crm_leads', 'Active leads', 'fa-user-plus', gate_crm, build_kpi_crm_leads,
           _KPI_TPL, zone='kpi', expandable=False),

    Widget('kpi_tickets', 'Open tickets', 'fa-ticket', gate_tickets, build_kpi_tickets,
           _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_rmm_alerts', 'RMM alerts', 'fa-triangle-exclamation', gate_rmm,
           build_kpi_rmm_alerts, _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_tasks', 'My open tasks', 'fa-list-check', gate_org, build_kpi_tasks,
           _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_assets', 'Assets', 'fa-box', gate_assets, build_kpi_assets, _KPI_TPL,
           zone='kpi', expandable=False),
    Widget('kpi_documents', 'Documents', 'fa-file-alt', gate_docs, build_kpi_documents,
           _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_passwords', 'Passwords', 'fa-key', gate_vault, build_kpi_passwords,
           _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_monitors', 'Monitors', 'fa-globe', gate_monitoring, build_kpi_monitors,
           _KPI_TPL, zone='kpi', expandable=False),
    Widget('kpi_psa_companies', 'PSA companies', 'fa-building', gate_psa_integration,
           build_kpi_psa_companies, _KPI_TPL, zone='kpi', expandable=False,
           description='Synced PSA companies; shown when there are any.'),
    Widget('kpi_psa_tickets', 'Active PSA tickets', 'fa-ticket-alt', gate_psa_integration,
           build_kpi_psa_tickets, _KPI_TPL, zone='kpi', expandable=False,
           description='New and in-progress synced PSA tickets; shown when there are any.'),

    Widget('quick_actions', 'Quick actions', 'fa-bolt', gate_quick_actions,
           build_quick_actions, 'core/dashboard/_w_quick_actions.html', zone='toolbar',
           expandable=False,
           description='Your own shortcut row (the header keeps the main actions).'),

    # Main and secondary panels.
    Widget('my_queue', 'My ticket queue', 'fa-user-check', gate_staff_tickets, build_my_queue,
           _QUEUE_TPL, size=2, link='psa:ticket_list', link_client=True,
           link_query='assigned=me&queue=open',
           description='Your open tickets at this customer, soonest SLA deadline first.'),
    Widget('unassigned_queue', 'Unassigned tickets', 'fa-inbox', gate_staff_tickets,
           build_unassigned_queue, _QUEUE_TPL, size=2, link='psa:ticket_list', link_client=True,
           link_query='assigned=unassigned&queue=open',
           description='Open tickets nobody has picked up, soonest SLA deadline first.'),
    Widget('sla_overview', 'SLA overview', 'fa-stopwatch', gate_staff_tickets,
           build_sla_overview, 'core/dashboard/_w_sla_overview.html', lazy=True,
           link='psa:ticket_list', link_client=True, link_query='queue=open'),
    Widget('workload', 'Technician workload', 'fa-people-group', gate_dispatch, build_workload,
           'core/dashboard/_w_workload.html', lazy=True, link='psa:dispatch_board',
           description='Open tickets per technician at this customer.'),
    Widget('ticket_recent', 'Recently updated tickets', 'fa-clock-rotate-left', gate_tickets,
           build_ticket_recent, 'core/dashboard/_w_ticket_recent.html', lazy=True,
           link='psa:ticket_list', link_client=True),
    Widget('crm_pipeline', 'Sales pipeline', 'fa-filter-circle-dollar', gate_crm,
           build_crm_pipeline, 'core/dashboard/_w_crm_pipeline.html', lazy=True,
           link='crm:pipeline'),
    Widget('crm_closing', 'Opportunities closing soon', 'fa-calendar-check', gate_crm,
           build_crm_closing, 'core/dashboard/_w_crm_closing.html', lazy=True,
           link='crm:opportunity_list',
           description='Open opportunities expected to close within 30 days (or overdue).'),
    Widget('my_time', 'My time this week', 'fa-clock', gate_my_time, build_my_time,
           'core/dashboard/_w_my_time.html', lazy=True, link='psa:my_timesheet'),

    Widget('schedule', 'Schedule (next 7 days)', 'fa-calendar-days', gate_org, build_schedule,
           'core/dashboard/_w_schedule.html', link='scheduling:scheduling_dashboard'),
    Widget('tasks', 'Upcoming tasks', 'fa-list-check', gate_org, build_tasks,
           'core/dashboard/_w_tasks.html', link='scheduling:scheduling_dashboard'),
    Widget('ticket_status', 'Open tickets by status', 'fa-chart-bar', gate_tickets,
           build_ticket_status, 'core/dashboard/_w_ticket_status.html',
           link='psa:ticket_list', link_client=True),
    Widget('rmm_alerts', 'RMM alerts', 'fa-triangle-exclamation', gate_rmm, build_rmm_alerts,
           'core/dashboard/_w_rmm_alerts.html', link='integrations:rmm_alerts'),
    Widget('monitors', 'Service health', 'fa-globe', gate_monitoring, build_monitors,
           'core/dashboard/_w_monitors.html', link='monitoring:website_monitor_list',
           description='Website and service monitors of this customer.'),
    Widget('ticket_activity', 'Ticket trends', 'fa-chart-column', gate_tickets,
           build_ticket_activity, 'core/dashboard/_w_ticket_activity.html', size=2, lazy=True,
           link='psa:ticket_list', link_client=True),
    Widget('map', 'Location map', 'fa-map-marked-alt', gate_org, build_map,
           'core/dashboard/_w_map.html', size=2, lazy=True, link='locations:location_list'),
    Widget('recent_activity', 'Recent activity', 'fa-clock-rotate-left', gate_audit,
           build_recent_activity, 'core/dashboard/_w_recent_activity.html', lazy=True,
           link='audit:audit_log_list', description='The audit log of this customer.'),
    Widget('system_status', 'System status', 'fa-server', gate_superuser, build_system_status,
           'core/dashboard/_w_system_status.html', lazy=True, link='core:system_status'),
)

BY_KEY = {w.key: w for w in WIDGETS}
KEYS = tuple(BY_KEY)
CUSTOMIZABLE_KEYS = tuple(w.key for w in WIDGETS if w.hideable)


def get(key):
    return BY_KEY.get(key)


# ---------------------------------------------------------------------------
# Built-in role presets
# ---------------------------------------------------------------------------
#
# Each preset is the ordered list of widgets shown by default; every other
# widget starts hidden (the Customize panel lists it). Widgets a user's
# permissions refuse drop out whatever the list says, so a preset can name
# a widget only some of its users can open (Recent activity needs admin
# rights at the customer, System status a superuser, and so on).
#
# Sized so the default dashboard fits a 1366x768 window: at most seven
# figures, and panels filling two rows of the three-column grid.

_SERVICE_KPIS = ('kpi_my_open', 'kpi_sla_risk', 'kpi_overdue', 'kpi_unassigned',
                 'kpi_approvals', 'kpi_due_today')

_PRESETS = {
    # Owner / administrator: the service desk figures, the queue, how the
    # team and the SLAs are doing, and the installation's health.
    PRESET_ADMIN: _SERVICE_KPIS + ('kpi_rmm_alerts',) + (
        'my_queue', 'sla_overview', 'workload', 'recent_activity', 'system_status'),
    # Service manager / dispatcher (also Billing / Finance and Auditor, the
    # other oversight roles): unassigned work first, workload, SLA
    # compliance, approvals, trends.
    PRESET_MANAGER: ('kpi_unassigned', 'kpi_sla_risk', 'kpi_overdue', 'kpi_due_today',
                     'kpi_approvals', 'kpi_my_open') + (
        'unassigned_queue', 'workload', 'sla_overview', 'ticket_activity'),
    # L3: escalated / advanced work, infrastructure and RMM.
    PRESET_L3: ('kpi_my_open', 'kpi_sla_risk', 'kpi_overdue', 'kpi_due_today', 'kpi_rmm_alerts',
                'kpi_tasks') + (
        'my_queue', 'sla_overview', 'rmm_alerts', 'monitors', 'tasks'),
    # L2: own queue, SLA warnings, tasks, RMM alerts.
    PRESET_L2: ('kpi_my_open', 'kpi_sla_risk', 'kpi_overdue', 'kpi_due_today', 'kpi_unassigned',
                'kpi_tasks') + (
        'my_queue', 'sla_overview', 'tasks', 'rmm_alerts', 'ticket_recent'),
    # L1: own queue, SLA warnings, tasks, own time.
    PRESET_L1: ('kpi_my_open', 'kpi_sla_risk', 'kpi_overdue', 'kpi_due_today', 'kpi_tasks') + (
        'my_queue', 'sla_overview', 'tasks', 'ticket_recent', 'my_time'),
    # Sales: pipeline, leads, deals closing, follow-up tasks.
    PRESET_SALES: ('kpi_crm_open', 'kpi_crm_leads', 'kpi_tasks', 'kpi_approvals') + (
        'crm_pipeline', 'crm_closing', 'tasks', 'schedule', 'ticket_activity'),
    # Customer users: customer-facing widgets only (each also gated).
    PRESET_CUSTOMER: ('kpi_tickets', 'kpi_assets', 'kpi_documents', 'kpi_passwords',
                      'kpi_monitors') + (
        'ticket_status', 'tasks', 'schedule', 'monitors', 'map'),
}

# Widgets that are never in a customer's built-in layout, whatever an
# administrator saves for the customer preset: MSP-only data. Their gates
# refuse customer users anyway; this keeps the preset honest.
MSP_ONLY = frozenset({
    'kpi_my_open', 'kpi_sla_risk', 'kpi_overdue', 'kpi_unassigned', 'kpi_approvals',
    'kpi_due_today', 'kpi_crm_open', 'kpi_crm_leads', 'kpi_rmm_alerts', 'kpi_psa_companies',
    'kpi_psa_tickets', 'my_queue', 'unassigned_queue', 'sla_overview', 'workload', 'crm_pipeline',
    'crm_closing', 'my_time', 'rmm_alerts', 'system_status',
})

_PRESET_SIZES = {
    PRESET_CUSTOMER: {'map': 1},
}


def preset_layout(preset):
    """The built-in layout for a preset key (unknown keys fall back to L2)."""
    if preset not in PRESET_LABELS:
        preset = PRESET_L2
    shown = [k for k in _PRESETS.get(preset, ()) if k in BY_KEY]
    order = shown + [k for k in KEYS if k not in shown]
    hidden = [w.key for w in WIDGETS if w.hideable and w.key not in shown]
    return {'order': order, 'hidden': hidden, 'sizes': dict(_PRESET_SIZES.get(preset, {}))}


# The legacy built-in role templates (accounts.models.RoleTemplate
# .create_default_templates) carry no seed key; they are matched by name
# only while they are still system templates.
_LEGACY_TEMPLATES = {
    'Full Admin': PRESET_ADMIN,
    'Tech Manager': PRESET_MANAGER,
    'Office Manager': PRESET_MANAGER,
    'Technician': PRESET_L2,
}


def preset_for_user(user, organization=None):
    """Which built-in preset suits this user's actual role."""
    if user.is_superuser:
        return PRESET_ADMIN
    from psa.visibility import is_msp_staff
    profile = getattr(user, 'profile', None)
    if is_msp_staff(user):
        role = getattr(profile, 'global_role_template', None) if profile is not None else None
        if role is not None:
            seed = (role.seed_key or '').strip()
            tier = (getattr(role, 'rmm_tier', '') or '').strip()
            if seed in ('org_owner', 'org_admin') or tier == 'platform_admin':
                return PRESET_ADMIN
            if seed in ('service_manager', 'billing_finance', 'auditor'):
                return PRESET_MANAGER
            if seed in ('sales_rep', 'sales_manager'):
                return PRESET_SALES
            if seed in ('tech_l1', 'tech_l2', 'tech_l3'):
                return {'tech_l1': PRESET_L1, 'tech_l2': PRESET_L2, 'tech_l3': PRESET_L3}[seed]
            if tier in ('l1', 'l2', 'l3'):
                return {'l1': PRESET_L1, 'l2': PRESET_L2, 'l3': PRESET_L3}[tier]
            if not seed and getattr(role, 'is_system_template', False):
                legacy = _LEGACY_TEMPLATES.get(role.name)
                if legacy:
                    return legacy
        if user.is_staff and (profile is None or not profile.is_staff_user()):
            return PRESET_ADMIN  # Django staff without a role: full reach
        return PRESET_L2
    return PRESET_CUSTOMER



# ---------------------------------------------------------------------------
# Layout validation and resolution
# ---------------------------------------------------------------------------

def clean_layout(raw):
    """Validate a posted or stored layout. Unknown keys are dropped, lists
    de-duplicated and capped, sizes limited to 1-3. Returns (layout, errors)."""
    errors = []
    if not isinstance(raw, dict):
        return {'order': [], 'hidden': [], 'sizes': {}}, ['Layout must be an object.']

    def keys(value, name):
        if value is None:
            return []
        if not isinstance(value, list):
            errors.append(f'"{name}" must be a list.')
            return []
        out, seen = [], set()
        for k in value[:MAX_LAYOUT_KEYS * 2]:
            if isinstance(k, str) and k in BY_KEY and k not in seen:
                seen.add(k)
                out.append(k)
        return out[:MAX_LAYOUT_KEYS]

    order = keys(raw.get('order'), 'order')
    hidden = [k for k in keys(raw.get('hidden'), 'hidden') if BY_KEY[k].hideable]
    sizes = {}
    raw_sizes = raw.get('sizes') or {}
    if not isinstance(raw_sizes, dict):
        errors.append('"sizes" must be an object.')
        raw_sizes = {}
    for k, v in list(raw_sizes.items())[:MAX_LAYOUT_KEYS * 2]:
        w = BY_KEY.get(k) if isinstance(k, str) else None
        if w is None or w.zone != 'grid':
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        sizes[k] = min(max(n, 1), 3)
    return {'order': order, 'hidden': hidden, 'sizes': sizes}, errors


def role_default(preset):
    try:
        from core.models import DashboardRoleDefault
        row = DashboardRoleDefault.objects.filter(preset=preset).first()
    except Exception:
        return None
    if row is None or not row.layout:
        return None
    return clean_layout(row.layout)[0]


def effective_layout(request):
    """(layout, source, preset): the user's own layout, else the role default
    an administrator saved for their preset, else the built-in preset."""
    user = request.user
    preset = preset_for_user(user, current_org(request))
    profile = getattr(user, 'profile', None)
    own = getattr(profile, 'dashboard_layout', None) if profile is not None else None
    base = preset_layout(preset)
    if own:
        layout, source = clean_layout(own)[0], 'personal'
    else:
        layout = role_default(preset)
        source = 'role' if layout else 'preset'
        layout = layout or base
        if source == 'role' and preset == PRESET_CUSTOMER:
            # A customer default never lists MSP-only panels, whatever was saved.
            layout['hidden'] = list(dict.fromkeys(
                list(layout['hidden']) + [k for k in layout['order'] if k in MSP_ONLY]))
    # Widgets added after the layout was saved go to the end, visible as the
    # preset would have them.
    order = list(layout['order'])
    for k in base['order']:
        if k not in order:
            order.append(k)
            if k in base['hidden'] and k not in layout['hidden']:
                layout['hidden'].append(k)
    layout['order'] = order
    return layout, source, preset


@dataclass
class Placed:
    widget: Widget
    size: int
    hidden: bool
    ctx: dict = field(default_factory=dict)
    link: str = ''

    @property
    def key(self):
        return self.widget.key


def visible_widgets(request, layout=None):
    """Gate-passing widgets in layout order. Hidden ones are listed (for the
    customize panel) but never built."""
    if layout is None:
        layout = effective_layout(request)[0]
    hidden = set(layout.get('hidden', []))
    sizes = layout.get('sizes', {})
    out = []
    for key in layout['order']:
        w = BY_KEY.get(key)
        if w is None or not w.allowed(request):
            continue
        out.append(Placed(widget=w, size=sizes.get(key, w.size),
                          hidden=w.hideable and key in hidden))
    return out


def build_widget(request, widget):
    """The widget's context for the selected customer, or None."""
    org = current_org(request)
    if widget.zone != 'banner' and widget.key != 'quick_actions' and org is None:
        return None
    return widget.build(request, org)
