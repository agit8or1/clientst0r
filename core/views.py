"""
Core views - Documentation and About pages
"""
import logging
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.core.cache import cache
from django_ratelimit.decorators import ratelimit
from config.version import get_version, get_full_version
from .updater import UpdateService
from audit.models import AuditLog

logger = logging.getLogger(__name__)


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


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
    Fast-loading with minimal database queries.
    """
    from assets.models import Vendor, EquipmentModel

    # Get equipment catalog statistics (cached for 1 hour - fast DB query)
    stats_cache_key = 'about_page_equipment_stats'
    equipment_stats = cache.get(stats_cache_key)
    if equipment_stats is None:
        equipment_stats = {
            'vendor_count': Vendor.objects.filter(is_active=True).count(),
            'model_count': EquipmentModel.objects.filter(is_active=True).count(),
        }
        cache.set(stats_cache_key, equipment_stats, 3600)  # Cache for 1 hour

    # Security scan and dependencies moved to System Status page for performance
    # These operations are slow (pip-audit takes 1-2 seconds) and not critical for About page

    return render(request, 'core/about.html', {
        'version': get_version(),
        'full_version': get_full_version(),
        'equipment_stats': equipment_stats,
    })


@login_required
@user_passes_test(is_superuser)
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

    # Check if passwordless sudo is configured (for web-based updates)
    sudo_configured = updater._check_passwordless_sudo()

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

    # Add debug info if there's an error
    debug_info = None
    if update_info.get('error'):
        debug_info = {
            'error': update_info.get('error'),
            'github_api_url': f'https://api.github.com/repos/{updater.repo_owner}/{updater.repo_name}/tags',
            'current_version': get_version(),
        }

    return render(request, 'core/system_updates.html', {
        'version': get_version(),
        'update_info': update_info,
        'git_status': git_status,
        'sudo_configured': sudo_configured,
        'recent_updates': recent_updates,
        'current_changelog': current_changelog,
        'newer_changelogs': newer_changelogs,
        'debug_info': debug_info,
    })


@login_required
@user_passes_test(is_superuser)
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


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def apply_update(request):
    """
    Apply system update with real-time progress tracking.
    Staff-only access.
    """
    from core.update_progress import UpdateProgress
    import threading

    updater = UpdateService()
    progress = UpdateProgress()
    progress.start()

    # Clear update cache IMMEDIATELY to prevent stale data during update
    cache.delete('system_update_check')

    def run_update():
        """Run update in background thread."""
        try:
            result = updater.perform_update(user=request.user, progress_tracker=progress)
            if result['success']:
                # Clear update cache again after success
                cache.delete('system_update_check')
        except Exception as e:
            progress.finish(success=False, error=str(e))
            # Clear cache even on failure to force fresh check
            cache.delete('system_update_check')

    # Start update in background thread
    thread = threading.Thread(target=run_update)
    thread.daemon = True
    thread.start()

    # Return immediately - progress will be polled via AJAX
    return JsonResponse({
        'status': 'started',
        'message': 'Update started. Polling for progress...'
    })


@login_required
@user_passes_test(is_superuser)
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
        cache.set(cache_key, update_info, 300)  # Cache for 5 minutes (consistent with system_updates view)

    return JsonResponse(update_info)


@login_required
@user_passes_test(is_superuser)
def update_progress_api(request):
    """
    API endpoint for checking update progress (for AJAX polling).
    Staff-only access.
    """
    from core.update_progress import UpdateProgress
    progress = UpdateProgress()
    return JsonResponse(progress.get_progress())


@login_required
@ratelimit(key='user', rate='5/h', method='POST', block=True)
def report_bug(request):
    """
    Bug reporting endpoint - creates GitHub issues using system credentials.
    Rate limited to 5 reports per user per hour to prevent abuse.
    """
    from django.http import JsonResponse
    from .github_api import GitHubIssueCreator, format_bug_report_body, GitHubAPIError
    from .models import SystemSetting
    import sys
    import platform
    from datetime import datetime
    from config.version import VERSION
    
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        }, status=405)

    # Check if rate limited
    if getattr(request, 'limited', False):
        logger.warning(f"Bug report rate limit exceeded for user {request.user.username}")
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_rate_limited',
            resource_type='bug_report',
            details=f'User exceeded rate limit (5 reports per hour)'
        )
        return JsonResponse({
            'success': False,
            'message': 'Rate limit exceeded. You can only submit 5 bug reports per hour. Please wait before submitting another report.'
        }, status=429)

    # Get form data
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    steps_to_reproduce = request.POST.get('steps_to_reproduce', '').strip()
    screenshot = request.FILES.get('screenshot')

    # Validate required fields
    if not title or not description:
        return JsonResponse({
            'success': False,
            'message': 'Title and description are required'
        }, status=400)

    # Get system GitHub PAT (only option for security)
    system_settings = SystemSetting.get_settings()
    token = system_settings.github_pat
    if not token:
        return JsonResponse({
            'success': False,
            'message': 'System GitHub PAT is not configured. Please contact your administrator to configure bug reporting.'
        }, status=400)




    
    # Collect system information
    system_info = {
        'version': VERSION,
        'django_version': f"{'.'.join(map(str, __import__('django').VERSION[:3]))}",
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'browser': request.META.get('HTTP_USER_AGENT', 'Unknown'),
        'os': platform.platform(),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    }
    
    # Collect reporter information
    reporter_info = {
        'username': request.user.username,
        'email': request.user.email if request.user.email else None,
        'organization': request.current_organization.name if hasattr(request, 'current_organization') and request.current_organization else None
    }
    
    # Format issue body
    issue_body = format_bug_report_body(
        description=description,
        steps_to_reproduce=steps_to_reproduce,
        system_info=system_info,
        reporter_info=reporter_info
    )
    
    # Create GitHub issue
    try:
        github_client = GitHubIssueCreator(token)
        
        # Validate token first
        if not github_client.validate_token():
            return JsonResponse({
                'success': False,
                'message': 'Invalid GitHub token or insufficient permissions. Please ensure your token has "public_repo" scope.'
            }, status=400)
        
        # Create the issue
        issue = github_client.create_issue(
            title=title,
            body=issue_body,
            labels=['bug', 'user-reported']
        )
        
        issue_number = issue['number']
        issue_url = issue['html_url']
        
        # Upload screenshot if provided
        if screenshot:
            # Validate file size (max 5MB)
            if screenshot.size > 5 * 1024 * 1024:
                return JsonResponse({
                    'success': False,
                    'message': 'Screenshot file size must be less than 5MB'
                }, status=400)
            
            # Validate file type
            allowed_extensions = ['png', 'jpg', 'jpeg', 'gif', 'webp']
            file_extension = screenshot.name.lower().split('.')[-1]
            if file_extension not in allowed_extensions:
                return JsonResponse({
                    'success': False,
                    'message': f'Invalid file type. Allowed types: {", ".join(allowed_extensions)}'
                }, status=400)
            
            try:
                github_client.upload_image_to_issue(
                    issue_number=issue_number,
                    image_data=screenshot.read(),
                    filename=screenshot.name
                )
            except GitHubAPIError as e:
                # Issue was created but screenshot upload failed - still return success
                logger.warning(f"Screenshot upload failed for bug report: {e}")
                pass

        # Log successful bug report submission
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_submitted',
            resource_type='bug_report',
            details=f'GitHub Issue #{issue_number} created: {title}'
        )
        logger.info(f"Bug report submitted by {request.user.username}: Issue #{issue_number}")

        return JsonResponse({
            'success': True,
            'message': f'Bug report submitted successfully! Issue #{issue_number} created.',
            'issue_number': issue_number,
            'issue_url': issue_url
        })

    except GitHubAPIError as e:
        logger.error(f"GitHub API error in bug report: {e}")
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_failed',
            resource_type='bug_report',
            details=f'GitHub API error: {str(e)}'
        )
        return JsonResponse({
            'success': False,
            'message': f'Failed to create GitHub issue: {str(e)}'
        }, status=500)
    except Exception as e:
        logger.error(f"Unexpected error in report_bug: {e}")
        import traceback
        logger.error(traceback.format_exc())
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_error',
            resource_type='bug_report',
            details=f'Unexpected error: {str(e)}'
        )
        return JsonResponse({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}'
        }, status=500)
