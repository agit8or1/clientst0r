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
    org = get_request_organization(request)

    # If superuser and explicitly accessing dashboard without org context, show global dashboard
    if request.user.is_superuser and not org:
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
    from accounts.azure_auth import azure_sso_counts_as_2fa
    if azure_sso_counts_as_2fa(request):
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
    Global system dashboard for MSP staff: system-wide statistics across all
    customers, including every customer's name and the install-wide audit
    log, so customer users don't get it.
    """
    from django.core.exceptions import PermissionDenied
    if not (request.user.is_superuser or request.user.is_staff
            or getattr(request, 'is_staff_user', False)):
        raise PermissionDenied("MSP staff only")

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
        out.append({'key': key, 'label': a['label'], 'icon': a['icon'], 'on': key in chosen})
    return out


def modern_dashboard(request, org):
    from core import dashboard_widgets as dw

    layout, source, preset = dw.effective_layout(request)
    placed = dw.visible_widgets(request, layout)
    errors = []
    zones = {'banner': [], 'kpi': [], 'toolbar': [], 'grid': []}
    for p in placed:
        p.link = p.widget.link_url(org)
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
    manage_defaults = can_manage_role_defaults(request.user)
    return render(request, 'core/dashboard_modern.html', {
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
        'layout_preset_label': dw.PRESET_LABELS.get(preset, preset),
        'preset_choices': list(dw.PRESET_LABELS.items()),
        'can_manage_role_defaults': manage_defaults,
        'ui_density': profile.ui_density or 'compact',
        'layout_json': _json.dumps(layout),
        'one_off_layout': (request.GET.get('layout') or '') in VARIANTS,
    })


@login_required
def dashboard_widget(request, key):
    """One widget's body, for lazy loading, refresh and the expanded view.
    The widget's gate runs again here; a widget the user may not see is a
    404, the same answer as a key that doesn't exist."""
    from core import dashboard_widgets as dw
    widget = dw.get(key)
    if widget is None or widget.zone not in ('grid', 'kpi') or not widget.allowed(request):
        raise Http404('No such widget')
    if get_request_organization(request) is None:
        raise Http404('Select a customer first')
    errors = []
    ctx = _build(request, widget, errors)
    if ctx is None:
        raise Http404('Nothing to show')
    if errors:
        from django.http import HttpResponseServerError
        return HttpResponseServerError('This panel could not be loaded.')
    html = render_to_string(widget.template, {'w': ctx, 'widget': widget, 'request': request},
                            request=request)
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
    if data.get('action') == 'reset':
        profile.dashboard_layout = {}
        fields.append('dashboard_layout')
    elif 'layout' in data:
        layout, errors = dw.clean_layout(data.get('layout'))
        if errors:
            return JsonResponse({'ok': False, 'errors': errors}, status=400)
        profile.dashboard_layout = layout
        fields.append('dashboard_layout')
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
    return JsonResponse({'ok': True, 'layout': profile.dashboard_layout,
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
