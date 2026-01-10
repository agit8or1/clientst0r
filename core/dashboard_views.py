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
    """
    org = get_request_organization(request)

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

    # Recent items (last 10 items accessed/modified)
    recent_logs = AuditLog.objects.filter(
        organization=org,
        user=request.user,
        action='read'
    ).exclude(
        object_type=''
    ).order_by('-timestamp')[:10]

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
    })
