"""
Dashboard views - Main application dashboard
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.conf import settings
from datetime import timedelta
from accounts.permission_utils import filter_by_org_perm
from core.middleware import get_request_organization
from core.models import SystemSetting
from vault.models import Password
from assets.models import Asset
from docs.models import Document
from monitoring.models import WebsiteMonitor
from core.dashboard_panels import get_schedule, get_tasks
from audit.models import AuditLog

# PSA integration imports (may not be available)
try:
    from integrations.models import PSACompany, PSATicket
    HAS_PSA_INTEGRATION = True
except ImportError:
    HAS_PSA_INTEGRATION = False


VARIANTS = ('modern', 'classic')


def dashboard_variant(request):
    """'modern' or 'classic': `?layout=` for this one view, else the user's
    saved choice (UserProfile.dashboard_variant, default modern)."""
    asked = (request.GET.get('layout') or '').strip().lower()
    if asked in VARIANTS:
        return asked
    profile = getattr(request.user, 'profile', None)
    saved = getattr(profile, 'dashboard_variant', '') if profile is not None else ''
    return saved if saved in VARIANTS else 'modern'


@login_required
def dashboard(request):
    """
    Main dashboard. Phase 67: the compact widget dashboard by default, the
    previous one as the "Classic dashboard" (per-user switch, `?layout=`).
    Routes to global dashboard if superuser and no org context.
    """
    # v3.17.681: straight after sign-in, the role's landing page (only when
    # this user may open it; see landing_for).
    target = take_landing_redirect(request)
    if target:
        return redirect(target)

    org = get_request_organization(request)

    # No customer selected: Global View for superusers and MSP staff
    # (v3.17.681: staff used to be sent to pick a customer).
    if not org and (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        return global_dashboard(request)

    # If no organization context, redirect to organization selection
    if not org:
        # Check if user has any memberships
        if hasattr(request.user, 'memberships'):
            memberships = request.user.memberships.filter(is_active=True)
            if memberships.count() > 1:
                # Multiple orgs - redirect to org list
                messages.info(request, 'Please select an organization to continue.')
                return redirect('accounts:organization_list')
            elif memberships.count() == 0:
                # No memberships - show error
                messages.error(request, 'You are not a member of any organization. Please contact your administrator.')
                return redirect('home')
        else:
            messages.error(request, 'Organization context not available.')
            return redirect('home')

    if dashboard_variant(request) == 'classic':
        return classic_dashboard(request, org)
    return modern_dashboard(request, org)


def classic_dashboard(request, org):
    """The dashboard as it was before Phase 67 (unchanged behaviour)."""
    system_settings = SystemSetting.get_settings()

    # Monitors live under /monitoring/ and follow its role flag.
    monitors_qs = filter_by_org_perm(
        WebsiteMonitor.objects.filter(organization=org), request.user, 'monitoring_view')

    # Stats cards
    stats = {
        # Gated by the same role flags as /vault/, /assets/ and /docs/.
        'passwords': filter_by_org_perm(
            Password.objects.for_organization(org), request.user, 'vault_view').count(),
        'assets': filter_by_org_perm(
            Asset.objects.for_organization(org), request.user, 'assets_view').count(),
        'documents': filter_by_org_perm(
            Document.objects.filter(organization=org, is_published=True),
            request.user, 'docs_view').count(),
        'monitors': monitors_qs.count(),
        'psa_companies': 0,
        'psa_tickets': 0,
    }

    # PSA integration stats
    if HAS_PSA_INTEGRATION:
        try:
            stats['psa_companies'] = filter_by_org_perm(
                PSACompany.objects.for_organization(org), request.user,
                'integrations_view').count()
            stats['psa_tickets'] = filter_by_org_perm(
                PSATicket.objects.for_organization(org), request.user,
                'integrations_view').filter(
                status__in=['new', 'in_progress']
            ).count()
        except Exception:
            pass  # Integrations app might not be available

    # Website monitor status summary (single aggregated query)
    monitor_counts = monitors_qs.aggregate(
        monitors_down=Count('id', filter=Q(status='down')),
        monitors_warning=Count('id', filter=Q(status='warning')),
        monitors_active=Count('id', filter=Q(status='active')),
    )
    monitors_down = monitor_counts['monitors_down']
    monitors_warning = monitor_counts['monitors_warning']
    monitors_active = monitor_counts['monitors_active']

    # Check if user has 2FA enabled or authenticated via Azure AD SSO
    has_2fa = False
    from accounts.sso_mfa import sso_counts_as_2fa
    if sso_counts_as_2fa(request):
        # Microsoft confirmed MFA for this sign-in (v3.17.660: no longer any
        # Microsoft sign-in)
        has_2fa = True
    elif hasattr(request.user, 'totpdevice_set'):
        has_2fa = request.user.totpdevice_set.filter(confirmed=True).exists()

    return render(request, 'core/dashboard_classic.html', {
        'current_organization': org,
        'stats': stats,
        # v3.17.524 — Schedule + Tasks replace My Recent, Recent Activity and
        # Expiring Soon. The audit-log tails and the three expiring_* querysets
        # that fed those panels are gone: get_tasks() covers the expiring items,
        # and nothing else in the codebase read any of those context keys.
        'schedule_days': get_schedule(request.user, org),
        'task_rows': get_tasks(request.user, org),
        'monitors_down': monitors_down,
        'monitors_warning': monitors_warning,
        'monitors_active': monitors_active,
        'has_2fa': has_2fa,
        'map_default_zoom': system_settings.map_default_zoom,
        'map_dragging_enabled': system_settings.map_dragging_enabled,
    })


@login_required
def global_dashboard(request):
    """
    Global View for MSP staff (no customer selected). v3.17.681: the widget
    dashboard with the all-clients widgets (core.dashboard_global), or the
    previous page (classic_global_dashboard) for users on the Classic
    dashboard. Customer users don't get either.
    """
    from django.core.exceptions import PermissionDenied
    if not (request.user.is_superuser or request.user.is_staff
            or getattr(request, 'is_staff_user', False)):
        raise PermissionDenied("MSP staff only")
    if get_request_organization(request) is None and dashboard_variant(request) == 'modern':
        from core import dashboard_widgets as dw
        if dw.is_global_view(request):
            return modern_dashboard(request, None)
    return classic_global_dashboard(request)


def classic_global_dashboard(request):
    """
    Global system dashboard for MSP staff: system-wide statistics across all
    customers, including every customer's name and the install-wide audit
    log, so customer users don't get it. (Access checked by global_dashboard.)
    """

    from core.models import Organization
    from accounts.models import Membership
    from django.contrib.auth.models import User
    from processes.models import Process, ProcessExecution

    # System-wide stats
    stats = {
        'organizations': Organization.objects.filter(is_active=True).count(),
        'users': User.objects.filter(is_active=True).count(),
        'total_passwords': filter_by_org_perm(
            Password.objects.all(), request.user, 'vault_view').count(),
        'total_assets': filter_by_org_perm(
            Asset.objects.all(), request.user, 'assets_view').count(),
        'total_documents': filter_by_org_perm(
            Document.objects.filter(is_published=True, is_archived=False),
            request.user, 'docs_view').count(),
        'total_processes': Process.objects.count(),
        'total_monitors': filter_by_org_perm(
            WebsiteMonitor.objects.all(), request.user, 'monitoring_view').count(),
    }

    # Organization stats (top 10 by member count)
    # IMPORTANT: Use distinct=True to avoid Cartesian product when counting multiple relations
    top_orgs = Organization.objects.filter(is_active=True).annotate(
        member_count=Count('memberships', filter=Q(memberships__is_active=True), distinct=True),
        asset_count=Count('assets', distinct=True),
        document_count=Count('documents', distinct=True),
    ).order_by('-member_count')[:10]

    # Recent global activity (last 20 actions). The install-wide audit log
    # is audit_view across every customer — not every technician's to read.
    from reports.access import has_msp_wide_perm
    if has_msp_wide_perm(request.user, 'audit_view', legacy='staff'):
        global_activity = AuditLog.objects.select_related(
            'user', 'organization'
        ).order_by('-timestamp')[:20]
    else:
        global_activity = AuditLog.objects.none()

    # System health indicators
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)

    health_stats = {
        'active_users_30d': AuditLog.objects.filter(
            timestamp__gte=thirty_days_ago
        ).values('user').distinct().count(),
        'new_orgs_30d': Organization.objects.filter(
            created_at__gte=thirty_days_ago
        ).count(),
        'active_processes': ProcessExecution.objects.filter(
            status='in_progress'
        ).count(),
        'monitors_down': filter_by_org_perm(
            WebsiteMonitor.objects.filter(status='down'), request.user,
            'monitoring_view').count(),
    }

    # Global processes stats
    process_stats = {
        'total': Process.objects.count(),
        'global': Process.objects.filter(is_global=True).count(),
        'org_specific': Process.objects.filter(is_global=False).count(),
        'active_executions': ProcessExecution.objects.filter(
            status__in=['not_started', 'in_progress']
        ).count(),
    }

    # Storage stats (approximate)
    from files.models import Attachment
    total_attachments = Attachment.objects.count()
    total_storage = Attachment.objects.aggregate(
        total=Count('id')
    )['total'] or 0

    return render(request, 'core/global_dashboard.html', {
        'stats': stats,
        'top_orgs': top_orgs,
        'global_activity': global_activity,
        'health_stats': health_stats,
        'process_stats': process_stats,
        'total_attachments': total_attachments,
        'total_storage': total_storage,
        'map_default_zoom': SystemSetting.get_settings().map_default_zoom,
        'map_dragging_enabled': SystemSetting.get_settings().map_dragging_enabled,
    })


# ---------------------------------------------------------------------------
# Phase 67: the compact widget dashboard (core/dashboard_widgets.py)
# ---------------------------------------------------------------------------

import json as _json
import logging as _logging

from django.http import Http404, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

_log = _logging.getLogger(__name__)


def _profile(user):
    from accounts.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def _build(request, widget, errors):
    """A widget's context, or None. A failing builder doesn't take the page
    down: the widget shows an error state and the failure is logged."""
    from core import dashboard_widgets as dw
    try:
        return dw.build_widget(request, widget)
    except Exception:
        if settings.DEBUG:
            raise
        _log.exception('dashboard widget %s failed', widget.key)
        errors.append(widget.key)
        return {'load_error': True}


def can_manage_role_defaults(user):
    """Role default layouts are installation-wide: superusers, and MSP staff
    whose global role grants roles_manage (the role editor's flag)."""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    from psa.visibility import is_msp_staff
    if not is_msp_staff(user):
        return False
    profile = getattr(user, 'profile', None)
    role = profile.get_global_permissions() if profile is not None else None
    return bool(role is not None and getattr(role, 'roles_manage', False))


def _quick_action_options(request):
    """Every quick action this user's checks allow, in their saved order,
    for the customize panel."""
    from core import dashboard_widgets as dw
    from core.quick_actions import (QUICK_ACTIONS_REGISTRY, DEFAULT_QUICK_ACTION_KEYS,
                                    action_allowed, clean_keys)
    ctx = dw._qa_context(request)
    profile = getattr(request.user, 'profile', None)
    saved = clean_keys(getattr(profile, 'quick_actions_config', None) or []) if profile else []
    chosen = saved or list(DEFAULT_QUICK_ACTION_KEYS)
    by_key = {a['key']: a for a in QUICK_ACTIONS_REGISTRY}
    order = chosen + [a['key'] for a in QUICK_ACTIONS_REGISTRY if a['key'] not in chosen]
    out = []
    for key in order:
        a = by_key[key]
        try:
            if not a['enabled'](ctx):
                continue
        except Exception:
            continue
        if a.get('requires_org') and ctx.get('current_organization') is None:
            continue
        if not action_allowed(a, request):
            continue
        if not dw.action_enabled(request, f'qa:{key}'):
            continue
        out.append({'key': key, 'label': a['label'], 'icon': a['icon'], 'on': key in chosen})
    return out


def modern_dashboard(request, org):
    from core import dashboard_widgets as dw

    layout, source, preset = dw.effective_layout(request)
    placed = dw.visible_widgets(request, layout)
    errors = []
    zones = {'banner': [], 'kpi': [], 'toolbar': [], 'grid': []}
    probe = _link_probe(request)
    for p in placed:
        p.link = _checked_link(probe, p.widget, org)
        if p.hidden:
            continue
        if p.widget.lazy:
            # Fetched after the page loads (a KPI shows a placeholder tile).
            p.ctx = None
        else:
            ctx = _build(request, p.widget, errors)
            if ctx is None:
                continue
            p.ctx = ctx
        zones[p.widget.zone].append(p)

    profile = _profile(request.user)
    customize = {
        'kpi': [p for p in placed if p.widget.zone == 'kpi'],
        'grid': [p for p in placed if p.widget.zone == 'grid'],
        'toolbar': [p for p in placed if p.widget.zone == 'toolbar'],
    }
    global_view = org is None
    # Role default layouts are per-customer presets; Global View has none.
    manage_defaults = can_manage_role_defaults(request.user) and not global_view
    return render(request, 'core/dashboard_modern.html', {
        'global_view': global_view,
        'current_organization': org,
        'greeting': dw.greeting(request.user),
        'header_actions': dw.header_actions(request),
        'banners': zones['banner'],
        'kpis': zones['kpi'],
        'toolbar': zones['toolbar'],
        'grid': zones['grid'],
        'widget_errors': errors,
        'customize': customize,
        'quick_action_options': _quick_action_options(request),
        'layout_source': source,
        'layout_preset': preset,
        'layout_preset_label': 'Global View' if global_view else dw.PRESET_LABELS.get(preset, preset),
        'preset_choices': list(dw.PRESET_LABELS.items()),
        'can_manage_role_defaults': manage_defaults,
        'ui_density': profile.ui_density or 'compact',
        'layout_json': _json.dumps(layout),
        'one_off_layout': (request.GET.get('layout') or '') in VARIANTS,
    })


def _link_probe(request):
    from core.navigation import _PermProbe, request_context
    return _PermProbe(request_context(request))


def _checked_link(probe, widget, org):
    """A widget's "View all" link, only when the server would open it for
    this user (the prefix rule and the view's role decorators), else its
    fallback page, else none."""
    for link in (widget.link_url(org), widget.link_url(org, fallback=True)):
        if link and probe.allows(link.split('?', 1)[0]):
            return link
    return ''


@login_required
def dashboard_widget(request, key):
    """One widget's body, for lazy loading, refresh and the expanded view.
    The widget's gate runs again here; a widget the user may not see is a
    404, the same answer as a key that doesn't exist."""
    from core import dashboard_widgets as dw
    widget = dw.get(key)
    if (widget is None or widget.zone not in ('grid', 'kpi')
            or not dw.widget_available(request, widget)):
        raise Http404('No such widget')
    org = get_request_organization(request)
    if (org is None and widget.scope == 'client') or (org is not None and widget.scope == 'global'):
        raise Http404('Not available here')
    errors = []
    ctx = _build(request, widget, errors)
    if ctx is None:
        raise Http404('Nothing to show')
    if errors:
        from django.http import HttpResponseServerError
        return HttpResponseServerError('This panel could not be loaded.')
    # The widget partials read only their own context (no csrf, no context
    # processor values), so they render without the context processors: each
    # of those costs queries on every lazy fetch and refresh.
    html = render_to_string(widget.template, {'w': ctx, 'widget': widget, 'request': request})
    from django.http import HttpResponse
    resp = HttpResponse(html)
    resp['Cache-Control'] = 'no-store'
    return resp


def _json_body(request):
    try:
        data = _json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


@login_required
@require_POST
def dashboard_layout_save(request):
    """Save the signed-in user's own dashboard layout, density and quick
    action order. There is no user id in the request: it only ever writes
    request.user's profile."""
    from core import dashboard_widgets as dw
    from core.quick_actions import clean_keys
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'errors': ['The request body must be a JSON object.']},
                            status=400)
    profile = _profile(request.user)
    fields = []
    errors = []
    # ?scope=global saves the Global View layout (MSP staff only), kept
    # apart from the per-customer one.
    attr = 'dashboard_layout'
    if request.GET.get('scope') == 'global':
        if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
            return JsonResponse({'ok': False, 'errors': ['Global View is for MSP staff.']},
                                status=403)
        attr = 'dashboard_global_layout'
    if data.get('action') == 'reset':
        setattr(profile, attr, {})
        fields.append(attr)
    elif 'layout' in data:
        layout, errors = dw.clean_layout(data.get('layout'))
        if errors:
            return JsonResponse({'ok': False, 'errors': errors}, status=400)
        setattr(profile, attr, layout)
        fields.append(attr)
    if 'density' in data:
        density = data.get('density')
        if density not in dict(profile.UI_DENSITY_CHOICES):
            return JsonResponse({'ok': False, 'errors': ['Density must be compact or comfortable.']},
                                status=400)
        profile.ui_density = density
        fields.append('ui_density')
    if 'quick_actions' in data:
        qa = data.get('quick_actions')
        if not isinstance(qa, list):
            return JsonResponse({'ok': False, 'errors': ['"quick_actions" must be a list.']},
                                status=400)
        profile.quick_actions_config = clean_keys(qa)
        fields.append('quick_actions_config')
    if not fields:
        return JsonResponse({'ok': False, 'errors': ['Nothing to save.']}, status=400)
    profile.save(update_fields=fields)
    return JsonResponse({'ok': True, 'layout': getattr(profile, attr),
                         'density': profile.ui_density,
                         'quick_actions': profile.quick_actions_config})


@login_required
@require_POST
def dashboard_variant_save(request):
    """Switch between the new and the classic dashboard (saved per user)."""
    variant = request.POST.get('variant', '')
    if variant not in VARIANTS:
        messages.error(request, 'Unknown dashboard.')
        return redirect('core:dashboard')
    profile = _profile(request.user)
    profile.dashboard_variant = variant
    profile.save(update_fields=['dashboard_variant'])
    return redirect('core:dashboard')


@login_required
@require_POST
def dashboard_role_default_save(request):
    """Save or clear the default layout for one role preset."""
    from core import dashboard_widgets as dw
    from core.models import DashboardRoleDefault
    if not can_manage_role_defaults(request.user):
        return JsonResponse({'ok': False, 'errors': ['You may not change role defaults.']},
                            status=403)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'errors': ['The request body must be a JSON object.']},
                            status=400)
    preset = data.get('preset')
    if preset not in dw.PRESET_LABELS:
        return JsonResponse({'ok': False, 'errors': ['Unknown role.']}, status=400)
    if data.get('action') == 'clear':
        DashboardRoleDefault.objects.filter(preset=preset).delete()
        return JsonResponse({'ok': True, 'preset': preset, 'cleared': True})
    layout, errors = dw.clean_layout(data.get('layout'))
    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)
    DashboardRoleDefault.objects.update_or_create(
        preset=preset, defaults={'layout': layout, 'updated_by': request.user})
    try:
        AuditLog.objects.create(
            user=request.user, username=request.user.username, action='update',
            object_type='core.DashboardRoleDefault', object_repr=preset,
            description=f'Dashboard default layout saved for {dw.PRESET_LABELS[preset]}')
    except Exception:
        pass
    return JsonResponse({'ok': True, 'preset': preset, 'layout': layout})


# ---------------------------------------------------------------------------
# v3.17.681: role landing page and role dashboard configuration
# ---------------------------------------------------------------------------

LANDING_SESSION_KEY = 'dash_landing_at'
LANDING_MAX_AGE = 300  # seconds between sign-in and the first dashboard view
# Never offered as a landing page (removed program; and pages that make no
# sense as a start page).
LANDING_EXCLUDED_NAMES = frozenset({
    'core:beta_test_signup', 'core:beta_test_admin', 'core:beta_test_upstream',
    'core:dashboard', 'home', 'accounts:logout', 'two_factor:login',
})


def note_sign_in(sender, request, user, **kwargs):
    """user_logged_in: remember that the next dashboard view is the one
    straight after sign-in, unless the sign-in was sent somewhere else
    (?next=/some/page/)."""
    if request is None or not hasattr(request, 'session'):
        return
    nxt = (request.POST.get('next') or request.GET.get('next') or '').strip() \
        if hasattr(request, 'POST') else ''
    if nxt and nxt.split('?', 1)[0] not in ('/', '/core/dashboard/'):
        request.session.pop(LANDING_SESSION_KEY, None)
        return
    import time
    request.session[LANDING_SESSION_KEY] = int(time.time())


def _landing_view_name(path):
    from django.urls import Resolver404, resolve
    try:
        return resolve(path).view_name
    except Resolver404:
        return None


def valid_landing(value):
    """A local path that resolves to a page (no scheme, no host)."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value.startswith('/') or value.startswith('//') or '\\' in value or len(value) > 300:
        return False
    from django.utils.http import url_has_allowed_host_and_scheme
    if not url_has_allowed_host_and_scheme(value, allowed_hosts=None):
        return False
    name = _landing_view_name(value.split('?', 1)[0])
    return bool(name) and name not in LANDING_EXCLUDED_NAMES


def landing_for(request):
    """The role's landing page if this user may open it right now (the
    sidebar's gates: core.navigation.destinations_for, and the server's URL
    and view-decorator rules: _PermProbe), else ''."""
    from core import dashboard_widgets as dw
    landing = dw.role_config(request)['landing']
    if not landing or not valid_landing(landing):
        return ''
    from core.navigation import _PermProbe, destinations_for, request_context
    ctx = request_context(request)
    path = landing.split('?', 1)[0]
    hrefs = {d['href'] for d in destinations_for(ctx)}
    if landing not in hrefs and path not in {h.split('?', 1)[0] for h in hrefs}:
        return ''
    if not _PermProbe(ctx).allows(path):
        return ''
    return landing


def take_landing_redirect(request):
    """Once per sign-in: the landing page to send this user to instead of
    the dashboard, or ''."""
    import time
    session = getattr(request, 'session', None)
    if session is None:
        return ''
    at = session.pop(LANDING_SESSION_KEY, None)
    if not at or request.GET:
        return ''
    try:
        if time.time() - int(at) > LANDING_MAX_AGE:
            return ''
    except (TypeError, ValueError):
        return ''
    try:
        return landing_for(request)
    except Exception:
        _log.exception('role landing check failed')
        return ''


def role_ui_defaults(request):
    """Context processor: {'role_ui_defaults': {'sidebar_mode', 'landing'}}
    for base.html / app_nav.js. sidebar_mode is '', 'expanded' or 'rail' (a
    default only: the user's own stored choice wins). Lazy: nothing is
    queried unless a template reads it."""
    from django.utils.functional import SimpleLazyObject

    def compute():
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return {'sidebar_mode': '', 'landing': ''}
        from core import dashboard_widgets as dw
        try:
            cfg = dw.role_config(request)
        except Exception:
            return {'sidebar_mode': '', 'landing': ''}
        return {'sidebar_mode': cfg['sidebar_mode'], 'landing': cfg['landing']}
    return {'role_ui_defaults': SimpleLazyObject(compute)}


def _landing_choices(request):
    """Pages offered as landing pages: the administrator's own sidebar
    destinations (entries and tabs). Whether a given user may open the page
    is checked again when they sign in."""
    from core.navigation import destinations_for, request_context
    out, seen = [], set()
    for d in destinations_for(request_context(request)):
        if d['kind'] not in ('entry', 'tab'):
            continue
        href = d['href']
        if href in seen or not valid_landing(href):
            continue
        seen.add(href)
        out.append({'href': href, 'label': d['label'], 'group': d['group'], 'section': d['section']})
    return out


def _mappable_roles():
    from accounts.models import RoleTemplate
    return (RoleTemplate.objects.filter(organization__isnull=True, is_archived=False)
            .exclude(audience='customer').order_by('name'))


@login_required
def dashboard_role_settings(request):
    """Settings → Users & Access → Role Dashboards: per role preset the
    default layout, widgets that are switched off, actions removed, landing
    page and sidebar mode; and which preset each MSP role uses. Same
    permission as saving a role default from the Customize panel."""
    from django.core.exceptions import PermissionDenied
    from core import dashboard_widgets as dw
    from core.models import DashboardRoleDefault, DashboardRoleMapping
    if not can_manage_role_defaults(request.user):
        raise PermissionDenied('You may not change role dashboards.')

    landing_choices = _landing_choices(request)
    preset = request.POST.get('preset') or request.GET.get('preset') or dw.PRESET_ADMIN
    if preset not in dw.PRESET_LABELS:
        preset = dw.PRESET_ADMIN

    if request.method == 'POST':
        what = request.POST.get('form')
        if what == 'preset':
            row, _ = DashboardRoleDefault.objects.get_or_create(preset=preset)
            enabled = set(request.POST.getlist('widget'))
            row.disabled_widgets = dw.clean_disabled_widgets(
                [w.key for w in dw.WIDGETS if w.hideable and w.key not in enabled])
            on_actions = set(request.POST.getlist('action'))
            row.disabled_actions = dw.clean_disabled_actions(
                [k for k, _l in dw.action_keys() if k not in on_actions])
            landing = (request.POST.get('landing') or '').strip()
            if landing and landing not in {c['href'] for c in landing_choices}:
                messages.error(request, 'Choose a landing page from the list.')
                return redirect(f"{request.path}?preset={preset}")
            row.landing = landing
            mode = request.POST.get('sidebar_mode') or ''
            row.sidebar_mode = mode if mode in dw.SIDEBAR_MODES else ''
            if request.POST.get('reset_layout'):
                row.layout = {}
            row.updated_by = request.user
            row.save()
            _audit_role(request, f'Role dashboard settings saved for {dw.PRESET_LABELS[preset]}',
                        preset)
            messages.success(request, f'Saved the {dw.PRESET_LABELS[preset]} dashboard settings.')
            return redirect(f"{request.path}?preset={preset}")
        if what == 'mappings':
            changed = 0
            for role in _mappable_roles():
                val = request.POST.get(f'role_{role.pk}', '')
                current = DashboardRoleMapping.objects.filter(role_template=role).first()
                if val in dw.PRESET_LABELS and val != dw.PRESET_CUSTOMER:
                    if current is None or current.preset != val:
                        DashboardRoleMapping.objects.update_or_create(
                            role_template=role, defaults={'preset': val, 'updated_by': request.user})
                        changed += 1
                elif current is not None:
                    current.delete()
                    changed += 1
            if changed:
                _audit_role(request, f'Dashboard role mappings changed ({changed})', 'mappings')
            messages.success(request, 'Saved the role mappings.')
            return redirect(f"{request.path}?preset={preset}")
        messages.error(request, 'Unknown form.')
        return redirect(request.path)

    row = DashboardRoleDefault.objects.filter(preset=preset).first()
    disabled_w = set(dw.clean_disabled_widgets(getattr(row, 'disabled_widgets', None)))
    disabled_a = set(getattr(row, 'disabled_actions', None) or ())
    layout = dw.role_default(preset, row) or dw.preset_layout(preset)
    shown = [k for k in layout['order'] if k not in set(layout['hidden'])]
    zones = (('kpi', 'Key figures'), ('grid', 'Panels'), ('toolbar', 'Quick actions row'))
    widget_groups = []
    for zone, label in zones:
        items = [{'w': w, 'on': w.key not in disabled_w, 'default': w.key in shown,
                  'msp_only': w.key in dw.MSP_ONLY}
                 for w in dw.WIDGETS if w.zone == zone and w.hideable and w.scope != 'global']
        widget_groups.append({'label': label, 'items': items})
    global_shown = set(dw.preset_layout(dw.PRESET_GLOBAL)['order'][:len(dw._PRESETS[dw.PRESET_GLOBAL])])
    widget_groups.append({'label': 'Global View (no client selected)', 'items': [
        {'w': w, 'on': w.key not in disabled_w, 'default': w.key in global_shown, 'msp_only': True}
        for w in dw.WIDGETS if w.scope == 'global']})
    actions = [{'key': k, 'label': lbl, 'on': k not in disabled_a,
                'header': k.startswith('header:')} for k, lbl in dw.action_keys()]
    mapped = dict(DashboardRoleMapping.objects.values_list('role_template_id', 'preset'))
    roles = []
    for role in _mappable_roles():
        roles.append({'role': role, 'mapped': mapped.get(role.pk, ''),
                      'builtin': _builtin_preset_label(role)})
    return render(request, 'core/dashboard_role_settings.html', {
        'preset': preset, 'preset_label': dw.PRESET_LABELS[preset],
        'preset_choices': list(dw.PRESET_LABELS.items()),
        'row': row, 'layout_source': 'saved' if dw.role_default(preset, row) else 'built-in',
        'widget_groups': widget_groups, 'actions': actions,
        'landing_choices': landing_choices, 'landing': getattr(row, 'landing', '') or '',
        'landing_valid': not getattr(row, 'landing', '') or
        getattr(row, 'landing', '') in {c['href'] for c in landing_choices},
        'sidebar_mode': getattr(row, 'sidebar_mode', '') or '',
        'roles': roles,
    })


def _builtin_preset_label(role):
    """What the built-in rules give a technician holding `role` (no mapping)."""
    from core import dashboard_widgets as dw
    return dw.PRESET_LABELS[dw.builtin_preset_for_role(role) or dw.PRESET_L2]


def _audit_role(request, description, repr_):
    try:
        AuditLog.objects.create(
            user=request.user, username=request.user.username, action='update',
            object_type='core.DashboardRoleDefault', object_repr=repr_, description=description)
    except Exception:
        pass
