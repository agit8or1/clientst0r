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
from django.utils import timezone
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
    Start system update using UpdateService with proper progress tracking.
    """
    from core.updater import UpdateService
    from core.update_progress import UpdateProgress

    try:
        # Clear cache
        cache.delete('system_update_check')

        # Initialize progress tracker
        progress = UpdateProgress()
        progress.start()

        # Start update in background thread
        import threading
        updater = UpdateService()

        def run_update():
            try:
                updater.perform_update(user=request.user, progress_tracker=progress)
            except Exception as e:
                logger.error(f"Update failed: {e}")
                progress.fail(str(e))

        update_thread = threading.Thread(target=run_update)
        update_thread.daemon = True
        update_thread.start()

        # Log the action
        AuditLog.objects.create(
            action='system_update',
            description=f'Update triggered by {request.user.username}',
            user=request.user,
            username=request.user.username
        )

        return JsonResponse({
            'status': 'started',
            'message': 'Update in progress...'
        })

    except Exception as e:
        messages.error(request, f"Failed to start update: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


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
@user_passes_test(is_superuser)
def version_diagnostic(request):
    """
    Diagnostic endpoint to debug version mismatch issues.
    Shows: file content vs Python import vs worker reports
    """
    import subprocess
    import os
    from django.conf import settings

    diagnostics = {}

    # 1. Read version.py file directly
    version_file = os.path.join(settings.BASE_DIR, 'config', 'version.py')
    try:
        with open(version_file, 'r') as f:
            content = f.read()
            for line in content.split('\n'):
                if line.strip().startswith('VERSION ='):
                    diagnostics['file_content'] = line.strip()
                    break
    except Exception as e:
        diagnostics['file_content'] = f"Error reading file: {e}"

    # 2. Python import (current process)
    try:
        from config.version import VERSION
        diagnostics['python_import'] = f"VERSION = '{VERSION}'"
    except Exception as e:
        diagnostics['python_import'] = f"Error importing: {e}"

    # 3. Force reload and check again
    try:
        import importlib
        import config.version
        importlib.reload(config.version)
        diagnostics['python_reload'] = f"VERSION = '{config.version.VERSION}'"
    except Exception as e:
        diagnostics['python_reload'] = f"Error reloading: {e}"

    # 4. UpdateService reports
    try:
        updater = UpdateService()
        diagnostics['update_service'] = f"VERSION = '{updater.current_version}'"
    except Exception as e:
        diagnostics['update_service'] = f"Error: {e}"

    # 5. Git info
    try:
        result = subprocess.run(['git', 'log', '-1', '--oneline'],
                               capture_output=True, text=True, cwd=settings.BASE_DIR)
        diagnostics['git_commit'] = result.stdout.strip()
    except Exception as e:
        diagnostics['git_commit'] = f"Error: {e}"

    # 6. Check for .pyc files
    try:
        pyc_path = os.path.join(settings.BASE_DIR, 'config', '__pycache__', 'version.cpython-312.pyc')
        if os.path.exists(pyc_path):
            import time
            mtime = os.path.getmtime(pyc_path)
            diagnostics['pyc_file'] = f"Exists (modified: {time.ctime(mtime)})"
        else:
            diagnostics['pyc_file'] = "Not found"
    except Exception as e:
        diagnostics['pyc_file'] = f"Error: {e}"

    return JsonResponse(diagnostics, json_dumps_params={'indent': 2})


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def force_restart_services(request):
    """
    Force restart all services and clear cache.
    Use this when Update Now completes but version doesn't change.
    This is a bootstrap fix for when old buggy UpdateService is running.
    """
    import subprocess
    import logging

    logger = logging.getLogger(__name__)

    try:
        # Clear Django cache first
        cache.delete('system_update_check')
        logger.info("Cleared Django cache")

        # Detect which gunicorn service exists
        service_names = ['clientst0r-gunicorn.service', 'clientst0r-gunicorn.service', 'itdocs-gunicorn.service']
        gunicorn_service = None

        for service in service_names:
            result = subprocess.run(
                ['systemctl', 'list-unit-files', service],
                capture_output=True,
                text=True
            )
            if service in result.stdout:
                gunicorn_service = service
                logger.info(f"Found service: {gunicorn_service}")
                break

        if not gunicorn_service:
            return JsonResponse({
                'success': False,
                'error': 'No gunicorn service found'
            }, status=500)

        # Stop service
        subprocess.run(['sudo', 'systemctl', 'stop', gunicorn_service], check=False)
        logger.info(f"Stopped {gunicorn_service}")

        # Kill any lingering processes
        subprocess.run(['sudo', 'pkill', '-9', '-f', 'gunicorn'], check=False)
        logger.info("Killed lingering gunicorn processes")

        # Wait a moment
        import time
        time.sleep(2)

        # Clear Python bytecode cache
        import os
        import shutil
        from django.conf import settings

        for root, dirs, files in os.walk(settings.BASE_DIR):
            if 'venv' in root or 'node_modules' in root:
                continue
            if '__pycache__' in dirs:
                cache_dir = os.path.join(root, '__pycache__')
                shutil.rmtree(cache_dir, ignore_errors=True)

        logger.info("Cleared Python bytecode cache")

        # Start service
        subprocess.run(['sudo', 'systemctl', 'start', gunicorn_service], check=True)
        logger.info(f"Started {gunicorn_service}")

        # Wait for service to start
        time.sleep(3)

        # Check if service is running
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', gunicorn_service],
            capture_output=True,
            text=True
        )

        if result.stdout.strip() == 'active':
            messages.success(request, 'Services restarted successfully! Refresh page to see new version.')
            return JsonResponse({
                'success': True,
                'message': 'Services restarted successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Service failed to start'
            }, status=500)

    except Exception as e:
        logger.error(f"Force restart failed: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def emergency_restart_webhook(request):
    """
    Emergency restart webhook - no authentication required but needs secret key.
    This endpoint can be called remotely to force restart stuck servers.

    Usage: POST /emergency-restart/?secret=YOUR_SECRET_KEY

    Secret key can be set in settings.EMERGENCY_RESTART_SECRET or defaults to a hash.
    """
    from django.conf import settings
    import hashlib
    import subprocess

    # Get secret from settings or generate default from SECRET_KEY
    expected_secret = getattr(settings, 'EMERGENCY_RESTART_SECRET',
                             hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest()[:32])

    # Check secret
    provided_secret = request.GET.get('secret') or request.POST.get('secret')
    if not provided_secret or provided_secret != expected_secret:
        return JsonResponse({'error': 'Invalid secret'}, status=403)

    # Run auto-heal command
    try:
        result = subprocess.run(
            ['python', 'manage.py', 'auto_heal_version'],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )

        return JsonResponse({
            'success': result.returncode == 0,
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@ratelimit(key='user', rate='10/h', method='POST', block=False)
def report_bug(request):
    """
    Bug reporting endpoint - generates pre-filled GitHub issue URL.
    Users submit with their own GitHub account.
    Rate limited to 10 reports per user per hour.
    """
    from django.http import JsonResponse
    from .github_api import format_bug_report_body, generate_github_issue_url
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
            object_type='bug_report',
            description=f'User exceeded rate limit (10 reports per hour)'
        )
        return JsonResponse({
            'success': False,
            'message': 'Rate limit exceeded. You can only submit 10 bug reports per hour. Please wait before submitting another report.'
        }, status=429)

    # Get form data
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    steps_to_reproduce = request.POST.get('steps_to_reproduce', '').strip()

    # Validate required fields
    if not title or not description:
        return JsonResponse({
            'success': False,
            'message': 'Title and description are required'
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

    # Generate pre-filled GitHub issue URL
    try:
        github_url = generate_github_issue_url(
            title=title,
            body=issue_body,
            labels=['bug', 'user-reported']
        )

        # Log bug report initiation
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_initiated',
            object_type='bug_report',
            description=f'Bug report URL generated: {title}'
        )
        logger.info(f"Bug report URL generated for {request.user.username}: {title}")

        return JsonResponse({
            'success': True,
            'message': 'Opening GitHub to submit your bug report...',
            'github_url': github_url
        })

    except Exception as e:
        logger.error(f"Unexpected error in report_bug: {e}")
        import traceback
        logger.error(traceback.format_exc())
        AuditLog.objects.create(
            user=request.user,
            action='bug_report_error',
            object_type='bug_report',
            description=f'Unexpected error: {str(e)}'
        )
        return JsonResponse({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}'
        }, status=500)


@login_required
def download_mobile_app(request, app_type):
    """
    Serve mobile app downloads or auto-build if not available.
    Automatically triggers build process when apps don't exist.
    """
    import os
    import json
    import subprocess
    import threading
    import time
    from django.conf import settings
    from django.http import FileResponse, Http404, HttpResponse
    from django.shortcuts import redirect, render

    # Define mobile app paths
    MOBILE_APP_DIR = os.path.join(settings.BASE_DIR, 'mobile-app', 'builds')
    os.makedirs(MOBILE_APP_DIR, exist_ok=True)

    if app_type == 'android':
        apk_path = os.path.join(MOBILE_APP_DIR, 'clientst0r.apk')
        status_file = os.path.join(MOBILE_APP_DIR, 'android_build_status.json')

        # Check if APK exists
        if os.path.exists(apk_path):
            # Serve the APK file
            response = FileResponse(
                open(apk_path, 'rb'),
                content_type='application/vnd.android.package-archive'
            )
            response['Content-Disposition'] = 'attachment; filename="Client St0r.apk"'

            # Log download
            AuditLog.objects.create(
                user=request.user,
                action='mobile_app_download',
                object_type='mobile_app',
                description=f'Downloaded Android APK'
            )

            return response

        # Check if build is in progress
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status_data = json.load(f)

            if status_data['status'] == 'building':
                # Read build log for real-time progress
                log_file = os.path.join(MOBILE_APP_DIR, f'{app_type}_build.log')
                build_log = ''
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        build_log = f.read()
                        # Filter log: show only major steps and current command
                        log_lines = []
                        for line in build_log.split('\n'):
                            # Skip verbose output
                            skip_patterns = ['npm warn', 'warning', '[10:', 'cleared', 'created', 'added', 'removed', '✔', '✓', '-', '›']
                            if any(pattern in line.lower() for pattern in skip_patterns):
                                continue
                            # Keep only major markers
                            if any(marker in line for marker in ['===', 'Started at:', '> npx', '> ./gradlew', 'Step', 'Building', 'Installing', 'Error:', 'failed', 'complete']):
                                log_lines.append(line)
                        # Show last 20 lines (major steps only)
                        build_log = '\n'.join(log_lines[-20:]) if len(log_lines) > 20 else '\n'.join(log_lines)
                        if not build_log.strip():
                            build_log = 'Build in progress... (details filtered for clarity)'

                # Build in progress - show status page with live log
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Building Android App - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <meta http-equiv="refresh" content="5">
                        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 1200px; margin: 30px auto; padding: 20px; }}
                            .spinner {{ border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }}
                            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #58a6ff; }}
                            .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }}
                            .log-container::-webkit-scrollbar {{ width: 10px; }}
                            .log-container::-webkit-scrollbar-track {{ background: #161b22; }}
                            .log-container::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 5px; }}
                            .status-header {{ display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }}
                            .progress-bar-container {{ width: 100%; height: 8px; background: #30363d; border-radius: 4px; overflow: hidden; margin: 20px 0; }}
                            .progress-bar {{ height: 100%; background: linear-gradient(90deg, #58a6ff, #79c0ff, #58a6ff); background-size: 200% 100%; animation: progressSlide 2s linear infinite; }}
                            @keyframes progressSlide {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
                        </style>
                        <script>
                            // Auto-scroll to bottom of log
                            window.onload = function() {{
                                var logContainer = document.getElementById('log-container');
                                if (logContainer) {{
                                    logContainer.scrollTop = logContainer.scrollHeight;
                                }}
                            }};
                        </script>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <div class="status-header">
                                    <div class="spinner"></div>
                                    <h1 style="margin: 0;">Building Android App...</h1>
                                </div>
                                <p class="lead text-center"><strong>Status:</strong> {status_data['message']}</p>
                                <div class="progress-bar-container">
                                    <div class="progress-bar"></div>
                                </div>
                                <p class="text-center"><strong>Elapsed Time:</strong> <span id="elapsed-time" style="color: #58a6ff; font-size: 1.2em;">Calculating...</span></p>
                                <p class="text-center text-muted"><small>Page refreshes in <span id="refresh-countdown">5</span> seconds • You can close this tab</small></p>
                            </div>

                            <div class="card">
                                <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                                <div id="log-container" class="log-container">
                                    <pre style="margin: 0; color: #c9d1d9;">{build_log if build_log else 'Waiting for build to start...'}</pre>
                                </div>
                                <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Showing last 100 lines of build output</small></p>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'complete':
                # Build complete but file not downloaded yet
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Android App Build Complete - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 800px; margin: 50px auto; padding: 40px; }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #3fb950; }}
                            code {{ background: #30363d; padding: 2px 6px; border-radius: 3px; color: #ffa657; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <h1>&#x2705; Android App Build Complete!</h1>
                                <p class="lead">{status_data['message']}</p>
                                <hr>
                                <h5>Next Steps:</h5>
                                <ol class="text-start">
                                    <li>Download the APK from the URL above</li>
                                    <li>Place it at: <code>~/clientst0r/mobile-app/builds/clientst0r.apk</code></li>
                                    <li>Refresh this page to download</li>
                                </ol>
                                <hr>
                                <a href="javascript:history.back()" class="btn btn-secondary">&larr; Go Back</a>
                                <a href="javascript:location.reload()" class="btn btn-primary">Refresh Page</a>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'failed':
                # Build failed - allow retry
                if request.GET.get('retry') == '1':
                    # Clear status and trigger new build
                    os.remove(status_file)
                    # Fall through to trigger build below
                else:
                    # Delete failed status file so we show clean state
                    try:
                        os.remove(status_file)
                    except:
                        pass

                    # Show friendly "not created yet" page instead of error
                    return HttpResponse(f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <title>Android App - Client St0r</title>
                            <meta charset="UTF-8">
                            <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                            <meta http-equiv="Pragma" content="no-cache">
                            <meta http-equiv="Expires" content="0">
                            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                            <style>
                                body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                                .container {{ max-width: 800px; margin: 50px auto; padding: 40px; text-align: center; }}
                                .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 40px; }}
                                h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                                p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                                strong {{ color: #ffffff; }}
                                .text-muted {{ color: #8b949e !important; }}
                                h1 {{ color: #58a6ff; margin-bottom: 20px; }}
                                .info-icon {{ font-size: 64px; margin-bottom: 20px; }}
                                .btn-build {{ background: #238636; border: 1px solid #2ea043; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; }}
                                .btn-build:hover {{ background: #2ea043; color: white; }}
                                .btn-secondary {{ background: #30363d; border: 1px solid #484f58; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; margin-left: 10px; }}
                                .btn-secondary:hover {{ background: #484f58; color: white; }}
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="card">
                                    <div class="info-icon">📱</div>
                                    <h1>Android App Not Created Yet</h1>
                                    <p class="lead">The mobile app hasn't been built yet.</p>
                                    <p class="text-muted">Click the button below to start building the Android app. This process takes about 10-15 minutes.</p>
                                    <div class="mt-4">
                                        <a href="?build=1" class="btn-build">Build Android App</a>
                                        <a href="javascript:history.back()" class="btn-secondary">Go Back</a>
                                    </div>
                                </div>
                            </div>
                        </body>
                        </html>
                    """, content_type='text/html; charset=utf-8')

        # No APK and no build in progress - start build
        def build_app_background():
            import logging
            logger = logging.getLogger(__name__)
            try:
                venv_python = os.path.join(settings.BASE_DIR, 'venv', 'bin', 'python')
                result = subprocess.run(
                    [venv_python, 'manage.py', 'build_mobile_app', 'android'],
                    cwd=settings.BASE_DIR,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    logger.error(f'Build failed: {result.stderr}')
            except Exception as e:
                logger.error(f'Build exception: {str(e)}')

        # Start build in background thread
        build_thread = threading.Thread(target=build_app_background)
        build_thread.daemon = True
        build_thread.start()

        # Log build initiation
        AuditLog.objects.create(
            user=request.user,
            action='mobile_app_build_started',
            object_type='mobile_app',
            description=f'Started Android APK build'
        )

        # Return building status page with log viewer
        current_time = time.time()
        return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Building Android App - Client St0r</title>
                <meta charset="UTF-8">
                <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                <meta http-equiv="Pragma" content="no-cache">
                <meta http-equiv="Expires" content="0">
                <meta http-equiv="refresh" content="5">
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                <style>
                    body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                    .container {{ max-width: 1200px; margin: 30px auto; padding: 20px; }}
                    .spinner {{ border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }}
                    @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }}
                    h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                    p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                    strong {{ color: #ffffff; }}
                    .text-muted {{ color: #8b949e !important; }}
                    h1 {{ color: #58a6ff; }}
                    .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }}
                    .log-container::-webkit-scrollbar {{ width: 10px; }}
                    .log-container::-webkit-scrollbar-track {{ background: #161b22; }}
                    .log-container::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 5px; }}
                    .status-header {{ display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }}
                    .progress-bar-container {{ width: 100%; height: 8px; background: #30363d; border-radius: 4px; overflow: hidden; margin: 20px 0; }}
                    .progress-bar {{ height: 100%; background: linear-gradient(90deg, #58a6ff, #79c0ff, #58a6ff); background-size: 200% 100%; animation: progressSlide 2s linear infinite; }}
                    @keyframes progressSlide {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
                </style>
                <script>
                    window.onload = function() {{
                        var logContainer = document.getElementById('log-container');
                        if (logContainer) {{
                            logContainer.scrollTop = logContainer.scrollHeight;
                        }}

                        // Show elapsed time with live updates
                        var startTime = {current_time} * 1000;
                        console.log('Build start time:', new Date(startTime));
                        console.log('Current time:', new Date());

                        function updateElapsedTime() {{
                            var elapsed = Math.floor((Date.now() - startTime) / 1000);
                            if (elapsed < 0) elapsed = 0;
                            var minutes = Math.floor(elapsed / 60);
                            var seconds = elapsed % 60;
                            var elapsedText = minutes + 'm ' + (seconds < 10 ? '0' : '') + seconds + 's';
                            var elapsedElement = document.getElementById('elapsed-time');
                            if (elapsedElement) {{
                                elapsedElement.textContent = elapsedText;
                                elapsedElement.style.color = '#58a6ff';  // Ensure visibility
                            }}
                        }}

                        // Start immediately and update every second
                        updateElapsedTime();
                        setInterval(updateElapsedTime, 1000);

                        // Also show page refresh countdown
                        var refreshIn = 5;
                        setInterval(function() {{
                            refreshIn--;
                            if (refreshIn <= 0) refreshIn = 5;
                            var refreshElement = document.getElementById('refresh-countdown');
                            if (refreshElement) refreshElement.textContent = refreshIn;
                        }}, 1000);
                    }};
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="status-header">
                            <div class="spinner"></div>
                            <h1 style="margin: 0;">Building Android App...</h1>
                        </div>
                        <p class="lead text-center"><strong>Status:</strong> Build started! Initializing...</p>
                        <div class="progress-bar-container">
                            <div class="progress-bar"></div>
                        </div>
                        <p class="text-center"><strong>Elapsed Time:</strong> <span id="elapsed-time" style="color: #58a6ff; font-size: 1.2em;">Calculating...</span></p>
                        <p class="text-center text-muted"><small>Page refreshes in <span id="refresh-countdown">5</span> seconds • You can close this tab</small></p>
                    </div>

                    <div class="card">
                        <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                        <div id="log-container" class="log-container">
                            <pre style="margin: 0; color: #c9d1d9;">Build initializing... Log will appear shortly.</pre>
                        </div>
                        <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Real-time build output will display here</small></p>
                    </div>
                </div>
            </body>
            </html>
        """, content_type='text/html; charset=utf-8')

    elif app_type == 'ios':
        ipa_path = os.path.join(MOBILE_APP_DIR, 'clientst0r.ipa')
        status_file = os.path.join(MOBILE_APP_DIR, 'ios_build_status.json')

        # Check if IPA exists
        if os.path.exists(ipa_path):
            # Serve the IPA file
            response = FileResponse(
                open(ipa_path, 'rb'),
                content_type='application/octet-stream'
            )
            response['Content-Disposition'] = 'attachment; filename="Client St0r.ipa"'

            # Log download
            AuditLog.objects.create(
                user=request.user,
                action='mobile_app_download',
                object_type='mobile_app',
                description=f'Downloaded iOS IPA'
            )

            return response

        # Check if build is in progress
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status_data = json.load(f)

            if status_data['status'] == 'building':
                # Read build log for real-time progress
                log_file = os.path.join(MOBILE_APP_DIR, f'{app_type}_build.log')
                build_log = ''
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        build_log = f.read()
                        # Filter log: show only major steps and current command
                        log_lines = []
                        for line in build_log.split('\n'):
                            # Skip verbose output
                            skip_patterns = ['npm warn', 'warning', '[10:', 'cleared', 'created', 'added', 'removed', '✔', '✓', '-', '›']
                            if any(pattern in line.lower() for pattern in skip_patterns):
                                continue
                            # Keep only major markers
                            if any(marker in line for marker in ['===', 'Started at:', '> npx', '> ./gradlew', 'Step', 'Building', 'Installing', 'Error:', 'failed', 'complete']):
                                log_lines.append(line)
                        # Show last 20 lines (major steps only)
                        build_log = '\n'.join(log_lines[-20:]) if len(log_lines) > 20 else '\n'.join(log_lines)
                        if not build_log.strip():
                            build_log = 'Build in progress... (details filtered for clarity)'

                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Building iOS App - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <meta http-equiv="refresh" content="5">
                        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 1200px; margin: 30px auto; padding: 20px; }}
                            .spinner {{ border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }}
                            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #58a6ff; }}
                            .log-container {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }}
                            .log-container::-webkit-scrollbar {{ width: 10px; }}
                            .log-container::-webkit-scrollbar-track {{ background: #161b22; }}
                            .log-container::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 5px; }}
                            .status-header {{ display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }}
                            .progress-bar-container {{ width: 100%; height: 8px; background: #30363d; border-radius: 4px; overflow: hidden; margin: 20px 0; }}
                            .progress-bar {{ height: 100%; background: linear-gradient(90deg, #58a6ff, #79c0ff, #58a6ff); background-size: 200% 100%; animation: progressSlide 2s linear infinite; }}
                            @keyframes progressSlide {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
                        </style>
                        <script>
                            // Auto-scroll to bottom of log
                            window.onload = function() {{
                                var logContainer = document.getElementById('log-container');
                                if (logContainer) {{
                                    logContainer.scrollTop = logContainer.scrollHeight;
                                }}
                            }};
                        </script>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <div class="status-header">
                                    <div class="spinner"></div>
                                    <h1 style="margin: 0;">Building iOS App...</h1>
                                </div>
                                <p class="lead text-center"><strong>Status:</strong> {status_data['message']}</p>
                                <div class="progress-bar-container">
                                    <div class="progress-bar"></div>
                                </div>
                                <p class="text-center"><strong>Elapsed Time:</strong> <span id="elapsed-time" style="color: #58a6ff; font-size: 1.2em;">Calculating...</span></p>
                                <p class="text-center text-muted"><small>Page refreshes in <span id="refresh-countdown">5</span> seconds • You can close this tab</small></p>
                            </div>

                            <div class="card">
                                <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                                <div id="log-container" class="log-container">
                                    <pre style="margin: 0; color: #c9d1d9;">{build_log if build_log else 'Waiting for build to start...'}</pre>
                                </div>
                                <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Showing last 100 lines of build output</small></p>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'complete':
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>iOS App Build Complete - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 800px; margin: 50px auto; padding: 40px; }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #3fb950; }}
                            code {{ background: #30363d; padding: 2px 6px; border-radius: 3px; color: #ffa657; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <h1>&#x2705; iOS App Build Complete!</h1>
                                <p class="lead">{status_data['message']}</p>
                                <hr>
                                <h5>Next Steps:</h5>
                                <ol class="text-start">
                                    <li>Download the IPA from the URL above</li>
                                    <li>Place it at: <code>~/clientst0r/mobile-app/builds/clientst0r.ipa</code></li>
                                    <li>Refresh this page to download</li>
                                </ol>
                                <p class="alert alert-warning">IPA files require TestFlight, enterprise distribution, or App Store for installation.</p>
                                <hr>
                                <a href="javascript:history.back()" class="btn btn-secondary">&larr; Go Back</a>
                                <a href="javascript:location.reload()" class="btn btn-primary">Refresh Page</a>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

            elif status_data['status'] == 'failed':
                # Delete failed status file so we show clean state
                try:
                    os.remove(status_file)
                except:
                    pass

                # Show friendly "not created yet" page instead of error
                return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>iOS App - Client St0r</title>
                        <meta charset="UTF-8">
                        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                        <meta http-equiv="Pragma" content="no-cache">
                        <meta http-equiv="Expires" content="0">
                        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                        <style>
                            body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                            .container {{ max-width: 800px; margin: 50px auto; padding: 40px; text-align: center; }}
                            .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 40px; }}
                            h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                            p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                            strong {{ color: #ffffff; }}
                            .text-muted {{ color: #8b949e !important; }}
                            h1 {{ color: #58a6ff; margin-bottom: 20px; }}
                            .info-icon {{ font-size: 64px; margin-bottom: 20px; }}
                            .btn-build {{ background: #238636; border: 1px solid #2ea043; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; }}
                            .btn-build:hover {{ background: #2ea043; color: white; }}
                            .btn-secondary {{ background: #30363d; border: 1px solid #484f58; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; margin-left: 10px; }}
                            .btn-secondary:hover {{ background: #484f58; color: white; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="card">
                                <div class="info-icon">📱</div>
                                <h1>iOS App Not Available</h1>
                                <p class="lead">iOS app builds are not currently supported.</p>
                                <p class="text-muted">Building iOS apps requires a macOS system with Xcode. Consider using the Android app or web interface instead.</p>
                                <div class="mt-4">
                                    <a href="javascript:history.back()" class="btn-secondary">Go Back</a>
                                </div>
                            </div>
                        </div>
                    </body>
                    </html>
                """, content_type='text/html; charset=utf-8')

        # No IPA and no build in progress - show friendly message
        # iOS builds require macOS with Xcode, so we don't support them
        return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>iOS App - Client St0r</title>
                <meta charset="UTF-8">
                <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                <meta http-equiv="Pragma" content="no-cache">
                <meta http-equiv="Expires" content="0">
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                <style>
                    body {{ background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                    .container {{ max-width: 800px; margin: 50px auto; padding: 40px; text-align: center; }}
                    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 40px; }}
                    h1, h2, h3, h4, h5 {{ color: #ffffff !important; }}
                    p, .lead {{ color: #ffffff !important; font-size: 1.1rem; }}
                    strong {{ color: #ffffff; }}
                    .text-muted {{ color: #8b949e !important; }}
                    h1 {{ color: #58a6ff; margin-bottom: 20px; }}
                    .info-icon {{ font-size: 64px; margin-bottom: 20px; }}
                    .btn-secondary {{ background: #30363d; border: 1px solid #484f58; color: white; padding: 12px 32px; font-size: 16px; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 20px; }}
                    .btn-secondary:hover {{ background: #484f58; color: white; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="info-icon">📱</div>
                        <h1>iOS App Not Available</h1>
                        <p class="lead">iOS app builds are not currently supported.</p>
                        <p class="text-muted">Building iOS apps requires a macOS system with Xcode installed. This Linux server cannot build iOS apps.</p>
                        <p class="text-muted">Consider using the Android app or accessing Client St0r through your web browser instead.</p>
                        <div class="mt-4">
                            <a href="javascript:history.back()" class="btn-secondary">Go Back</a>
                        </div>
                    </div>
                </div>
            </body>
            </html>
        """, content_type='text/html; charset=utf-8')

        AuditLog.objects.create(
            user=request.user,
            action='mobile_app_build_started',
            object_type='mobile_app',
            description=f'Started iOS IPA build'
        )

        return HttpResponse("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Building iOS App - Client St0r</title>
                <meta charset="UTF-8">
                <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
                <meta http-equiv="Pragma" content="no-cache">
                <meta http-equiv="Expires" content="0">
                <meta http-equiv="refresh" content="5">
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                <style>
                    body { background: #0d1117; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
                    .container { max-width: 1200px; margin: 30px auto; padding: 20px; }
                    .spinner { border: 5px solid #30363d; border-top: 5px solid #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.3); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 15px; }
                    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                    .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; margin-bottom: 20px; }
                    h1, h2, h3, h4, h5 { color: #ffffff !important; }
                    p, .lead { color: #ffffff !important; font-size: 1.1rem; }
                    strong { color: #ffffff; }
                    .text-muted { color: #8b949e !important; }
                    h1 { color: #58a6ff; }
                    .log-container { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 20px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5; color: #c9d1d9; }
                    .log-container::-webkit-scrollbar { width: 10px; }
                    .log-container::-webkit-scrollbar-track { background: #161b22; }
                    .log-container::-webkit-scrollbar-thumb { background: #30363d; border-radius: 5px; }
                    .status-header { display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }
                </style>
                <script>
                    window.onload = function() {{
                        var logContainer = document.getElementById('log-container');
                        if (logContainer) {{
                            logContainer.scrollTop = logContainer.scrollHeight;
                        }}

                        // Show elapsed time with live updates
                        var startTime = {status_data.get('timestamp', time.time())} * 1000;
                        console.log('Build start time:', new Date(startTime));
                        console.log('Current time:', new Date());

                        function updateElapsedTime() {{
                            var elapsed = Math.floor((Date.now() - startTime) / 1000);
                            if (elapsed < 0) elapsed = 0;
                            var minutes = Math.floor(elapsed / 60);
                            var seconds = elapsed % 60;
                            var elapsedText = minutes + 'm ' + (seconds < 10 ? '0' : '') + seconds + 's';
                            var elapsedElement = document.getElementById('elapsed-time');
                            if (elapsedElement) {{
                                elapsedElement.textContent = elapsedText;
                                elapsedElement.style.color = '#58a6ff';  // Ensure visibility
                            }}
                        }}

                        // Start immediately and update every second
                        updateElapsedTime();
                        setInterval(updateElapsedTime, 1000);

                        // Also show page refresh countdown
                        var refreshIn = 5;
                        setInterval(function() {{
                            refreshIn--;
                            if (refreshIn <= 0) refreshIn = 5;
                            var refreshElement = document.getElementById('refresh-countdown');
                            if (refreshElement) refreshElement.textContent = refreshIn;
                        }}, 1000);
                    }};
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="status-header">
                            <div class="spinner"></div>
                            <h1 style="margin: 0;">Building iOS App...</h1>
                        </div>
                        <p class="lead text-center"><strong>Status:</strong> Build started! Initializing...</p>
                        <p class="text-center text-muted"><small>Page refreshes every 5 seconds. You can close this tab and come back later.</small></p>
                    </div>

                    <div class="card">
                        <h3 style="margin-bottom: 15px;">&#x1F4DD; Build Progress Log</h3>
                        <div id="log-container" class="log-container">
                            <pre style="margin: 0; color: #c9d1d9;">Build initializing... Log will appear shortly.</pre>
                        </div>
                        <p class="text-muted text-center" style="margin-top: 15px; margin-bottom: 0;"><small>Real-time build output will display here</small></p>
                    </div>
                </div>
            </body>
            </html>
        """, content_type='text/html; charset=utf-8')

    else:
        raise Http404("Invalid app type")
