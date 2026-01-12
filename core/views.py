"""
Core views - Documentation and About pages
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.core.cache import cache
from config.version import get_version, get_full_version
from .updater import UpdateService
from audit.models import AuditLog


@login_required
def documentation(request):
    """
    Platform documentation page.
    """
    return render(request, 'core/documentation.html', {
        'version': get_version(),
    })


@login_required
def about(request):
    """
    About page with version and system information.
    """
    from .security_scan import run_vulnerability_scan, get_dependency_versions
    from assets.models import Vendor, EquipmentModel

    # Run security scan
    scan_results = run_vulnerability_scan()

    # Get dependency versions
    dependencies = get_dependency_versions()

    # Get equipment catalog statistics
    equipment_stats = {
        'vendor_count': Vendor.objects.filter(is_active=True).count(),
        'model_count': EquipmentModel.objects.filter(is_active=True).count(),
    }

    return render(request, 'core/about.html', {
        'version': get_version(),
        'full_version': get_full_version(),
        'scan_results': scan_results,
        'dependencies': dependencies,
        'equipment_stats': equipment_stats,
    })


@staff_member_required
def system_updates(request):
    """
    System updates page - check for and apply updates.
    Staff-only access.
    """
    updater = UpdateService()

    # Get cached update check or perform new check
    cache_key = 'system_update_check'
    update_info = cache.get(cache_key)

    if not update_info:
        update_info = updater.check_for_updates()
        cache.set(cache_key, update_info, 300)  # Cache for 5 minutes

    # Get git status
    git_status = updater.get_git_status()

    # Get recent update logs
    recent_updates = AuditLog.objects.filter(
        action__in=['system_update', 'system_update_failed', 'update_check']
    ).order_by('-timestamp')[:10]

    # Get changelog for current version
    current_version = get_version()
    current_changelog = updater.get_changelog_for_version(current_version)

    # Get changelogs for newer versions (if update available)
    newer_changelogs = {}
    if update_info.get('update_available') and update_info.get('latest_version'):
        newer_changelogs = updater.get_changelog_between_versions(
            current_version,
            update_info['latest_version']
        )

    return render(request, 'core/system_updates.html', {
        'version': get_version(),
        'update_info': update_info,
        'git_status': git_status,
        'recent_updates': recent_updates,
        'current_changelog': current_changelog,
        'newer_changelogs': newer_changelogs,
    })


@staff_member_required
@require_http_methods(["POST"])
def check_updates_now(request):
    """
    Force check for updates (bypass cache).
    Staff-only access.
    """
    updater = UpdateService()
    update_info = updater.check_for_updates()

    # Update cache
    cache.set('system_update_check', update_info, 300)  # Cache for 5 minutes

    # Log the check
    AuditLog.objects.create(
        action='update_check',
        description=f'Manual update check by {request.user.username}',
        user=request.user,
        username=request.user.username,
        extra_data=update_info
    )

    if update_info.get('error'):
        messages.error(request, f"Failed to check for updates: {update_info['error']}")
    elif update_info['update_available']:
        messages.success(
            request,
            f"Update available: v{update_info['latest_version']}"
        )
    else:
        messages.info(request, "System is up to date")

    return redirect('core:system_updates')


@staff_member_required
@require_http_methods(["POST"])
def apply_update(request):
    """
    Apply system update.
    Staff-only access.
    """
    updater = UpdateService()

    # Perform update
    result = updater.perform_update(user=request.user)

    if result['success']:
        messages.success(
            request,
            "Update completed successfully! The system will restart shortly."
        )
        # Clear update cache
        cache.delete('system_update_check')
    else:
        messages.error(
            request,
            f"Update failed: {result.get('error', 'Unknown error')}"
        )

    return redirect('core:system_updates')


@staff_member_required
def update_status_api(request):
    """
    API endpoint for checking update status (for AJAX polling).
    Staff-only access.
    """
    cache_key = 'system_update_check'
    update_info = cache.get(cache_key)

    if not update_info:
        updater = UpdateService()
        update_info = updater.check_for_updates()
        cache.set(cache_key, update_info, 3600)

    return JsonResponse(update_info)
