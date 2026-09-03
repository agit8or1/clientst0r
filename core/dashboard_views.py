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


@login_required
def dashboard(request):
    """
    Main dashboard with widgets and stats.
    Routes to global dashboard if superuser and no org context.
    """
    org = get_request_organization(request)
    system_settings = SystemSetting.get_settings()

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

    # Stats cards
    stats = {
        'passwords': Password.objects.for_organization(org).count(),
        'assets': Asset.objects.for_organization(org).count(),
        'documents': Document.objects.filter(organization=org, is_published=True).count(),
        'monitors': WebsiteMonitor.objects.filter(organization=org).count(),
        'psa_companies': 0,
        'psa_tickets': 0,
    }

    # PSA integration stats
    if HAS_PSA_INTEGRATION:
        try:
            stats['psa_companies'] = PSACompany.objects.for_organization(org).count()
            stats['psa_tickets'] = PSATicket.objects.for_organization(org).filter(
                status__in=['new', 'in_progress']
            ).count()
        except Exception:
            pass  # Integrations app might not be available

    # Website monitor status summary (single aggregated query)
    monitor_counts = WebsiteMonitor.objects.filter(organization=org).aggregate(
        monitors_down=Count('id', filter=Q(status='down')),
        monitors_warning=Count('id', filter=Q(status='warning')),
        monitors_active=Count('id', filter=Q(status='active')),
    )
    monitors_down = monitor_counts['monitors_down']
    monitors_warning = monitor_counts['monitors_warning']
    monitors_active = monitor_counts['monitors_active']

    # Check if user has 2FA enabled or authenticated via Azure AD SSO
    has_2fa = False
    if request.session.get('azure_ad_authenticated', False):
        # Azure AD SSO users don't need 2FA (handled by Azure)
        has_2fa = True
    elif hasattr(request.user, 'totpdevice_set'):
        has_2fa = request.user.totpdevice_set.filter(confirmed=True).exists()

    return render(request, 'core/dashboard.html', {
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
    Global system dashboard - accessible to all authenticated users.
    Shows system-wide statistics across all organizations.
    """
    # Accessible to all authenticated users
    # Previously restricted to superusers and staff only

    from core.models import Organization
    from accounts.models import Membership
    from django.contrib.auth.models import User
    from processes.models import Process, ProcessExecution

    # System-wide stats
    stats = {
        'organizations': Organization.objects.filter(is_active=True).count(),
        'users': User.objects.filter(is_active=True).count(),
        'total_passwords': Password.objects.count(),
        'total_assets': Asset.objects.count(),
        'total_documents': Document.objects.filter(is_published=True, is_archived=False).count(),
        'total_processes': Process.objects.count(),
        'total_monitors': WebsiteMonitor.objects.count(),
    }

    # Organization stats (top 10 by member count)
    # IMPORTANT: Use distinct=True to avoid Cartesian product when counting multiple relations
    top_orgs = Organization.objects.filter(is_active=True).annotate(
        member_count=Count('memberships', filter=Q(memberships__is_active=True), distinct=True),
        asset_count=Count('assets', distinct=True),
        document_count=Count('documents', distinct=True),
    ).order_by('-member_count')[:10]

    # Recent global activity (last 20 actions)
    global_activity = AuditLog.objects.select_related(
        'user', 'organization'
    ).order_by('-timestamp')[:20]

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
        'monitors_down': WebsiteMonitor.objects.filter(status='down').count(),
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
