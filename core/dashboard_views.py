"""
Dashboard views - Main application dashboard
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta
from core.middleware import get_request_organization
from vault.models import Password
from assets.models import Asset
from docs.models import Document
from monitoring.models import WebsiteMonitor, Expiration
from audit.models import AuditLog


@login_required
def dashboard(request):
    """
    Main dashboard with widgets and stats.
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

    # Stats cards
    stats = {
        'passwords': Password.objects.for_organization(org).count(),
        'assets': Asset.objects.for_organization(org).count(),
        'documents': Document.objects.filter(organization=org, is_published=True).count(),
        'monitors': WebsiteMonitor.objects.filter(organization=org).count(),
    }

    # Recent items (last 10 unique items accessed/modified)
    # Get all recent read logs, then deduplicate by object
    all_recent = AuditLog.objects.filter(
        organization=org,
        user=request.user,
        action='read'
    ).exclude(
        object_type=''
    ).order_by('-timestamp')[:50]  # Get more to ensure we have 10 unique

    # Deduplicate by object_type + object_id
    seen = set()
    recent_logs = []
    for log in all_recent:
        key = (log.object_type, log.object_id)
        if key not in seen and len(recent_logs) < 10:
            seen.add(key)
            recent_logs.append(log)

    # Expiring soon (next 30 days)
    now = timezone.now()
    thirty_days = now + timedelta(days=30)

    expiring_passwords = Password.objects.for_organization(org).filter(
        expires_at__gte=now,
        expires_at__lte=thirty_days
    ).order_by('expires_at')[:5]

    expiring_items = Expiration.objects.filter(
        organization=org,
        expires_at__gte=now,
        expires_at__lte=thirty_days
    ).order_by('expires_at')[:5]

    expiring_ssl = WebsiteMonitor.objects.filter(
        organization=org,
        ssl_enabled=True,
        ssl_expires_at__gte=now,
        ssl_expires_at__lte=thirty_days
    ).order_by('ssl_expires_at')[:5]

    # Website monitor status summary
    monitors_down = WebsiteMonitor.objects.filter(organization=org, status='down').count()
    monitors_warning = WebsiteMonitor.objects.filter(organization=org, status='warning').count()
    monitors_active = WebsiteMonitor.objects.filter(organization=org, status='active').count()

    # Recent activity feed (last 15 actions)
    activity_feed = AuditLog.objects.filter(
        organization=org
    ).select_related('user').order_by('-timestamp')[:15]

    # Check if user has 2FA enabled
    has_2fa = False
    if hasattr(request.user, 'totpdevice_set'):
        has_2fa = request.user.totpdevice_set.filter(confirmed=True).exists()

    return render(request, 'core/dashboard.html', {
        'current_organization': org,
        'stats': stats,
        'recent_logs': recent_logs,
        'expiring_passwords': expiring_passwords,
        'expiring_items': expiring_items,
        'expiring_ssl': expiring_ssl,
        'monitors_down': monitors_down,
        'monitors_warning': monitors_warning,
        'monitors_active': monitors_active,
        'activity_feed': activity_feed,
        'has_2fa': has_2fa,
    })


@login_required
def global_dashboard(request):
    """
    Global system dashboard - superuser only.
    Shows system-wide statistics across all organizations.
    """
    # Only accessible to superusers
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access the global dashboard.')
        return redirect('core:dashboard')

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
        'total_documents': Document.objects.filter(is_published=True).count(),
        'total_processes': Process.objects.count(),
        'total_monitors': WebsiteMonitor.objects.count(),
    }

    # Organization stats (top 10 by member count)
    top_orgs = Organization.objects.filter(is_active=True).annotate(
        member_count=Count('memberships', filter=Q(memberships__is_active=True)),
        asset_count=Count('assets'),
        document_count=Count('documents'),
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
    })
