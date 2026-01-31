"""
Admin Settings Views
Superuser-only views for managing system configuration.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db import connection
from django.conf import settings as django_settings
from django.utils import timezone
from .models import SystemSetting, ScheduledTask, Organization
import platform
import sys
import os
import shutil
import psutil
import django
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('core')


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def security_dashboard(request):
    """Security dashboard showing overview of all security features."""
    from core.models import SnykScan
    from django.db.models import Count, Q, Sum

    # Get Snyk scan statistics
    total_scans = SnykScan.objects.count()
    recent_scans = SnykScan.objects.filter(
        started_at__gte=timezone.now() - timedelta(days=7)
    ).count()

    latest_scan = SnykScan.objects.filter(status='completed').first()

    # Get vulnerability statistics
    if latest_scan:
        total_vulnerabilities = latest_scan.total_vulnerabilities
        critical_vulns = latest_scan.critical_count
        high_vulns = latest_scan.high_count
        medium_vulns = latest_scan.medium_count
        low_vulns = latest_scan.low_count
    else:
        total_vulnerabilities = 0
        critical_vulns = 0
        high_vulns = 0
        medium_vulns = 0
        low_vulns = 0

    # Get scan history for chart (last 30 days)
    scan_history = SnykScan.objects.filter(
        status='completed',
        started_at__gte=timezone.now() - timedelta(days=30)
    ).order_by('-started_at')[:10]

    # Calculate trend
    if scan_history.count() >= 2:
        latest_total = scan_history[0].total_vulnerabilities
        previous_total = scan_history[1].total_vulnerabilities

        if previous_total > 0:
            trend_percent = ((latest_total - previous_total) / previous_total) * 100
        else:
            trend_percent = 0

        trend_direction = 'up' if trend_percent > 0 else 'down' if trend_percent < 0 else 'stable'
    else:
        trend_percent = 0
        trend_direction = 'stable'

    # Get Snyk settings
    settings = SystemSetting.get_settings()

    context = {
        'total_scans': total_scans,
        'recent_scans': recent_scans,
        'latest_scan': latest_scan,
        'total_vulnerabilities': total_vulnerabilities,
        'critical_vulns': critical_vulns,
        'high_vulns': high_vulns,
        'medium_vulns': medium_vulns,
        'low_vulns': low_vulns,
        'scan_history': scan_history,
        'trend_percent': abs(trend_percent),
        'trend_direction': trend_direction,
        'snyk_enabled': settings.snyk_enabled,
        'snyk_configured': bool(settings.snyk_api_token),
    }

    return render(request, 'core/security_dashboard.html', context)


@login_required
@user_passes_test(is_superuser)
def settings_general(request):
    """General system settings."""
    from pathlib import Path
    from django.conf import settings as django_settings

    settings = SystemSetting.get_settings()

    # Read current values from .env file for map settings
    env_path = django_settings.BASE_DIR / '.env'
    env_values = {}
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_values[key] = value

    map_default_zoom = env_values.get('MAP_DEFAULT_ZOOM', '4')
    map_dragging_enabled = env_values.get('MAP_DRAGGING_ENABLED', 'true').lower() == 'true'

    if request.method == 'POST':
        # Update general settings
        settings.site_name = request.POST.get('site_name', settings.site_name)
        settings.site_url = request.POST.get('site_url', settings.site_url)
        settings.default_timezone = request.POST.get('default_timezone', settings.default_timezone)

        # Update whitelabeling settings
        settings.custom_company_name = request.POST.get('custom_company_name', '').strip()
        settings.custom_logo_height = int(request.POST.get('custom_logo_height', 30))

        # Handle logo upload
        if 'custom_logo' in request.FILES:
            settings.custom_logo = request.FILES['custom_logo']
        elif request.POST.get('clear_logo') == 'on':
            settings.custom_logo = None

        # Issue #59: UI/UX Settings
        settings.stay_on_page_after_org_switch = request.POST.get('stay_on_page_after_org_switch') == 'on'

        settings.updated_by = request.user
        settings.save()

        # Update map settings in .env
        map_default_zoom_new = request.POST.get('map_default_zoom', '4')
        map_dragging_enabled_new = 'true' if request.POST.get('map_dragging_enabled') == 'on' else 'false'

        # Read all lines from .env
        lines = []
        if env_path.exists():
            with open(env_path, 'r') as f:
                lines = f.readlines()

        # Update or add the keys
        keys_to_update = {
            'MAP_DEFAULT_ZOOM': map_default_zoom_new,
            'MAP_DRAGGING_ENABLED': map_dragging_enabled_new,
        }

        for key, value in keys_to_update.items():
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f'{key}='):
                    lines[i] = f'{key}={value}\n'
                    found = True
                    break
            if not found:
                # Add new key
                lines.append(f'{key}={value}\n')

        # Write back to .env
        env_path.parent.mkdir(parents=True, exist_ok=True)
        with open(env_path, 'w') as f:
            f.writelines(lines)

        messages.success(request, 'General settings updated successfully.')
        return redirect('core:settings_general')

    # Timezone choices
    import pytz
    timezone_choices = [(tz, tz) for tz in pytz.common_timezones]

    return render(request, 'core/settings_general.html', {
        'settings': settings,
        'timezone_choices': timezone_choices,
        'current_tab': 'general',
        'map_default_zoom': map_default_zoom,
        'map_dragging_enabled': map_dragging_enabled,
    })


@login_required
@user_passes_test(is_superuser)
def settings_security(request):
    """Security and authentication settings."""
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        # Update security settings
        settings.session_timeout_minutes = int(request.POST.get('session_timeout_minutes', settings.session_timeout_minutes))
        settings.require_2fa = request.POST.get('require_2fa') == 'on'
        settings.password_min_length = int(request.POST.get('password_min_length', settings.password_min_length))
        settings.password_require_special = request.POST.get('password_require_special') == 'on'
        settings.failed_login_attempts = int(request.POST.get('failed_login_attempts', settings.failed_login_attempts))
        settings.lockout_duration_minutes = int(request.POST.get('lockout_duration_minutes', settings.lockout_duration_minutes))

        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'Security settings updated successfully.')
        return redirect('core:settings_security')

    return render(request, 'core/settings_security.html', {
        'settings': settings,
        'current_tab': 'security',
    })


@login_required
@user_passes_test(is_superuser)
def settings_features(request):
    """Feature toggles - enable/disable major system features."""
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        # Update feature toggles
        settings.monitoring_enabled = request.POST.get('monitoring_enabled') == 'on'
        settings.global_kb_enabled = request.POST.get('global_kb_enabled') == 'on'
        settings.workflows_enabled = request.POST.get('workflows_enabled') == 'on'

        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'Feature toggles updated successfully.')
        return redirect('core:settings_features')

    return render(request, 'core/settings_features.html', {
        'settings': settings,
        'current_tab': 'features',
    })


@login_required
@user_passes_test(is_superuser)
def settings_smtp(request):
    """SMTP and email notification settings."""
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        # Update SMTP settings
        settings.smtp_enabled = request.POST.get('smtp_enabled') == 'on'
        settings.smtp_host = request.POST.get('smtp_host', settings.smtp_host)
        settings.smtp_port = int(request.POST.get('smtp_port', settings.smtp_port))
        settings.smtp_username = request.POST.get('smtp_username', settings.smtp_username)

        # Only update password if provided
        smtp_password = request.POST.get('smtp_password', '').strip()
        if smtp_password:
            # Encrypt password before storing
            from vault.encryption import encrypt
            settings.smtp_password = encrypt(smtp_password)

        settings.smtp_use_tls = request.POST.get('smtp_use_tls') == 'on'
        settings.smtp_use_ssl = request.POST.get('smtp_use_ssl') == 'on'
        settings.smtp_from_email = request.POST.get('smtp_from_email', settings.smtp_from_email)
        settings.smtp_from_name = request.POST.get('smtp_from_name', settings.smtp_from_name)

        # Notification settings
        settings.notify_on_user_created = request.POST.get('notify_on_user_created') == 'on'
        settings.notify_on_ssl_expiry = request.POST.get('notify_on_ssl_expiry') == 'on'
        settings.notify_on_domain_expiry = request.POST.get('notify_on_domain_expiry') == 'on'
        settings.ssl_expiry_warning_days = int(request.POST.get('ssl_expiry_warning_days', settings.ssl_expiry_warning_days))
        settings.domain_expiry_warning_days = int(request.POST.get('domain_expiry_warning_days', settings.domain_expiry_warning_days))

        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'SMTP settings updated successfully.')
        return redirect('core:settings_smtp')

    return render(request, 'core/settings_smtp.html', {
        'settings': settings,
        'current_tab': 'smtp',
    })


@login_required
@user_passes_test(is_superuser)
@require_POST
def test_smtp_email(request):
    """
    Send a test email to verify SMTP configuration (Issue #58).
    """
    from django.core.mail import send_mail
    from django.core.mail import get_connection
    from django.core.mail.backends.smtp import EmailBackend

    test_email = request.POST.get('test_email', '').strip()

    if not test_email:
        messages.error(request, 'Please provide an email address for the test.')
        return redirect('core:settings_smtp')

    # Get SMTP settings
    settings = SystemSetting.get_settings()

    if not settings.smtp_enabled:
        messages.error(request, 'SMTP is not enabled. Please enable and configure SMTP settings first.')
        return redirect('core:settings_smtp')

    # Decrypt password if set
    smtp_password = ''
    if settings.smtp_password:
        try:
            from vault.encryption import decrypt
            smtp_password = decrypt(settings.smtp_password)
        except Exception as e:
            logger.error(f"Failed to decrypt SMTP password: {e}")
            messages.error(request, 'Failed to decrypt SMTP password.')
            return redirect('core:settings_smtp')

    try:
        # Configure email backend
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=smtp_password,
            use_tls=settings.smtp_use_tls,
            use_ssl=settings.smtp_use_ssl,
            timeout=10,
        )

        # Send test email
        subject = 'HuduGlue SMTP Test Email'
        message = f"""This is a test email from HuduGlue.

Your SMTP configuration is working correctly!

Configuration Details:
- SMTP Host: {settings.smtp_host}
- SMTP Port: {settings.smtp_port}
- Use TLS: {'Yes' if settings.smtp_use_tls else 'No'}
- Use SSL: {'Yes' if settings.smtp_use_ssl else 'No'}
- From Address: {settings.smtp_from_email}
- From Name: {settings.smtp_from_name}

This email was sent at: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} UTC

---
HuduGlue - IT Documentation Platform
"""

        from_email = f'{settings.smtp_from_name} <{settings.smtp_from_email}>' if settings.smtp_from_name else settings.smtp_from_email

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[test_email],
            connection=connection,
            fail_silently=False,
        )

        messages.success(request, f'Test email sent successfully to {test_email}. Please check your inbox.')
        logger.info(f"Test email sent to {test_email} by {request.user.username}")

    except Exception as e:
        logger.error(f"Failed to send test email: {e}")
        messages.error(request, f'Failed to send test email: {str(e)}')

    return redirect('core:settings_smtp')


@login_required
@user_passes_test(is_superuser)
def settings_scheduler(request):
    """Task scheduler settings - manage scheduled tasks."""
    # Ensure default tasks exist
    ScheduledTask.get_or_create_defaults()

    tasks = ScheduledTask.objects.all()

    if request.method == 'POST':
        # Update task schedules
        for task in tasks:
            enabled = request.POST.get(f'task_{task.id}_enabled') == 'on'
            interval = int(request.POST.get(f'task_{task.id}_interval', task.interval_minutes))

            task.enabled = enabled
            task.interval_minutes = interval
            task.save()

        messages.success(request, 'Scheduler settings updated successfully.')
        return redirect('core:settings_scheduler')

    return render(request, 'core/settings_scheduler.html', {
        'tasks': tasks,
        'current_tab': 'scheduler',
    })


@login_required
@user_passes_test(is_superuser)
def settings_directory(request):
    """Directory services settings - LDAP and Azure AD."""
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        # LDAP Settings
        settings.ldap_enabled = request.POST.get('ldap_enabled') == 'on'
        settings.ldap_server_uri = request.POST.get('ldap_server_uri', settings.ldap_server_uri)
        settings.ldap_bind_dn = request.POST.get('ldap_bind_dn', settings.ldap_bind_dn)

        # Only update password if provided
        ldap_password = request.POST.get('ldap_bind_password', '').strip()
        if ldap_password:
            # TODO: Encrypt password before storing
            settings.ldap_bind_password = ldap_password

        settings.ldap_user_search_base = request.POST.get('ldap_user_search_base', settings.ldap_user_search_base)
        settings.ldap_user_search_filter = request.POST.get('ldap_user_search_filter', settings.ldap_user_search_filter)
        settings.ldap_group_search_base = request.POST.get('ldap_group_search_base', settings.ldap_group_search_base)
        settings.ldap_require_group = request.POST.get('ldap_require_group', settings.ldap_require_group)
        settings.ldap_start_tls = request.POST.get('ldap_start_tls') == 'on'

        # Azure AD Settings
        settings.azure_ad_enabled = request.POST.get('azure_ad_enabled') == 'on'
        settings.azure_ad_tenant_id = request.POST.get('azure_ad_tenant_id', settings.azure_ad_tenant_id)
        settings.azure_ad_client_id = request.POST.get('azure_ad_client_id', settings.azure_ad_client_id)

        # Only update client secret if provided
        azure_secret = request.POST.get('azure_ad_client_secret', '').strip()
        if azure_secret:
            # TODO: Encrypt secret before storing
            settings.azure_ad_client_secret = azure_secret

        settings.azure_ad_redirect_uri = request.POST.get('azure_ad_redirect_uri', settings.azure_ad_redirect_uri)
        settings.azure_ad_auto_create_users = request.POST.get('azure_ad_auto_create_users') == 'on'
        settings.azure_ad_sync_groups = request.POST.get('azure_ad_sync_groups') == 'on'

        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'Directory services settings updated successfully.')
        return redirect('core:settings_directory')

    return render(request, 'core/settings_directory.html', {
        'settings': settings,
        'current_tab': 'directory',
    })


@login_required
@user_passes_test(is_superuser)
def system_status(request):
    """System status and health check page."""
    from config.version import get_full_version

    # System information
    system_info = {
        'os': platform.system(),
        'os_version': platform.release(),
        'platform': platform.platform(),
        'python_version': sys.version.split()[0],
        'django_version': django.get_version(),
        'huduglue_version': get_full_version(),
        'hostname': platform.node(),
    }

    # Database information
    db_info = {}
    try:
        db_engine = connection.settings_dict['ENGINE']
        db_info['engine'] = db_engine.split('.')[-1]

        with connection.cursor() as cursor:
            # Test connection
            cursor.execute("SELECT 1")
            db_info['connected'] = True

            # Get database version based on engine
            if 'mysql' in db_engine:
                cursor.execute("SELECT VERSION()")
                db_info['version'] = cursor.fetchone()[0]

                # Get database size for MySQL
                cursor.execute("SELECT SUM(data_length + index_length) / 1024 / 1024 AS size_mb FROM information_schema.tables WHERE table_schema = DATABASE()")
                size_result = cursor.fetchone()
                db_info['size_mb'] = round(size_result[0], 2) if size_result[0] else 0
            elif 'postgresql' in db_engine:
                cursor.execute("SELECT version()")
                db_info['version'] = cursor.fetchone()[0].split(',')[0]

                # Get database size for PostgreSQL
                cursor.execute("SELECT pg_database_size(current_database()) / 1024.0 / 1024.0")
                db_info['size_mb'] = round(cursor.fetchone()[0], 2)
            elif 'sqlite' in db_engine:
                cursor.execute("SELECT sqlite_version()")
                db_info['version'] = f"SQLite {cursor.fetchone()[0]}"

                # Get database size for SQLite
                db_path = connection.settings_dict['NAME']
                if os.path.exists(db_path):
                    db_info['size_mb'] = round(os.path.getsize(db_path) / 1024 / 1024, 2)
                else:
                    db_info['size_mb'] = 0
            else:
                db_info['version'] = 'Unknown'
                db_info['size_mb'] = 0
    except Exception as e:
        db_info['connected'] = False
        db_info['error'] = str(e)

    # Disk space
    disk_usage = {}
    try:
        usage = shutil.disk_usage('/')
        disk_usage['total_gb'] = round(usage.total / (1024**3), 2)
        disk_usage['used_gb'] = round(usage.used / (1024**3), 2)
        disk_usage['free_gb'] = round(usage.free / (1024**3), 2)
        disk_usage['percent'] = round((usage.used / usage.total) * 100, 1)
    except Exception as e:
        disk_usage['error'] = str(e)

    # Memory information
    memory_info = {}
    try:
        mem = psutil.virtual_memory()
        memory_info['total_gb'] = round(mem.total / (1024**3), 2)
        memory_info['available_gb'] = round(mem.available / (1024**3), 2)
        memory_info['used_gb'] = round(mem.used / (1024**3), 2)
        memory_info['percent'] = mem.percent
    except Exception as e:
        memory_info['error'] = str(e)

    # CPU information
    cpu_info = {}
    try:
        cpu_info['count'] = psutil.cpu_count()
        cpu_info['percent'] = psutil.cpu_percent(interval=1)
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0)
        cpu_info['load_1'] = round(load_avg[0], 2)
        cpu_info['load_5'] = round(load_avg[1], 2)
        cpu_info['load_15'] = round(load_avg[2], 2)
    except Exception as e:
        cpu_info['error'] = str(e)

    # Upload directory status
    upload_info = {}
    try:
        upload_root = getattr(django_settings, 'UPLOAD_ROOT', '/var/lib/itdocs/uploads')
        if os.path.exists(upload_root):
            usage = shutil.disk_usage(upload_root)
            upload_info['path'] = upload_root
            upload_info['exists'] = True
            upload_info['writable'] = os.access(upload_root, os.W_OK)
            upload_info['size_mb'] = round(sum(f.stat().st_size for f in os.scandir(upload_root) if f.is_file()) / (1024**2), 2)
        else:
            upload_info['exists'] = False
            upload_info['path'] = upload_root
    except Exception as e:
        upload_info['error'] = str(e)

    # Scheduled tasks status
    tasks_status = []
    for task in ScheduledTask.objects.all():
        tasks_status.append({
            'name': task.get_task_type_display(),
            'enabled': task.enabled,
            'last_run': task.last_run_at,
            'next_run': task.next_run_at,
            'status': task.last_status,
        })

    # Services status (check if systemd services are running)
    services_status = {}
    try:
        import subprocess
        # Check Gunicorn
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', 'huduglue-gunicorn'],
                              capture_output=True, text=True, timeout=5)
        services_status['gunicorn'] = result.stdout.strip() == 'active'

        # Check PSA Sync timer
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', 'huduglue-psa-sync.timer'],
                              capture_output=True, text=True, timeout=5)
        services_status['psa_sync'] = result.stdout.strip() == 'active'

        # Check Monitor timer
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', 'huduglue-monitor.timer'],
                              capture_output=True, text=True, timeout=5)
        services_status['monitor'] = result.stdout.strip() == 'active'
    except Exception as e:
        services_status['error'] = str(e)

    # Calculate projected capacity
    capacity = {}
    try:
        from core.models import Organization
        from django.contrib.auth import get_user_model
        from vault.models import Password
        from assets.models import Asset
        from docs.models import Document

        User = get_user_model()

        # Current usage counts
        capacity['organizations'] = Organization.objects.count()
        capacity['users'] = User.objects.count()
        capacity['passwords'] = Password.objects.count()
        capacity['assets'] = Asset.objects.count()
        capacity['documents'] = Document.objects.count()

        # Resource-based capacity estimates
        # These are conservative estimates based on typical usage patterns

        # Memory-based capacity (assume 50MB per active user session)
        if memory_info.get('available_gb'):
            capacity['estimated_concurrent_users'] = int(memory_info['available_gb'] * 1024 / 50)
        else:
            capacity['estimated_concurrent_users'] = 0

        # Database size-based capacity (warn at 80% of typical limits)
        if db_info.get('size_mb'):
            db_size_gb = db_info['size_mb'] / 1024
            # SQLite: warn at 140GB (max 2TB theoretical)
            # MySQL/PostgreSQL: warn at 800GB (typical deployment)
            if 'sqlite' in db_info.get('engine', ''):
                max_recommended_gb = 140
            else:
                max_recommended_gb = 800

            capacity['db_size_gb'] = round(db_size_gb, 2)
            capacity['db_max_recommended_gb'] = max_recommended_gb
            capacity['db_percent_used'] = round((db_size_gb / max_recommended_gb) * 100, 1)
        else:
            capacity['db_size_gb'] = 0
            capacity['db_percent_used'] = 0

        # CPU-based capacity (estimate users per core)
        if cpu_info.get('count'):
            # Assume 10 concurrent users per CPU core at normal load
            users_per_core = 10
            capacity['estimated_users_per_core'] = users_per_core
            capacity['max_recommended_users'] = cpu_info['count'] * users_per_core

        # Disk space-based capacity
        if disk_usage.get('free_gb'):
            # Estimate file uploads: average 100MB per organization
            capacity['estimated_orgs_disk_capacity'] = int(disk_usage['free_gb'] * 1024 / 100)

        # Overall capacity score (0-100)
        # Weight different factors
        scores = []

        # CPU score (load average vs cores)
        if cpu_info.get('load_5') is not None and cpu_info.get('count'):
            cpu_score = max(0, 100 - (cpu_info['load_5'] / cpu_info['count'] * 50))
            scores.append(('cpu', cpu_score))

        # Memory score
        if memory_info.get('percent') is not None:
            memory_score = 100 - memory_info['percent']
            scores.append(('memory', memory_score))

        # Disk score
        if disk_usage.get('percent') is not None:
            disk_score = 100 - disk_usage['percent']
            scores.append(('disk', disk_score))

        # Database score
        if capacity.get('db_percent_used') is not None:
            db_score = 100 - capacity['db_percent_used']
            scores.append(('database', db_score))

        # Calculate weighted average
        if scores:
            total_score = sum(score for _, score in scores)
            capacity['overall_score'] = round(total_score / len(scores), 1)
            capacity['score_breakdown'] = scores

            # Capacity status
            if capacity['overall_score'] >= 70:
                capacity['status'] = 'healthy'
                capacity['status_text'] = 'System has ample capacity'
            elif capacity['overall_score'] >= 50:
                capacity['status'] = 'moderate'
                capacity['status_text'] = 'System capacity is adequate'
            elif capacity['overall_score'] >= 30:
                capacity['status'] = 'limited'
                capacity['status_text'] = 'System capacity is limited'
            else:
                capacity['status'] = 'critical'
                capacity['status_text'] = 'System capacity is critical'
        else:
            capacity['overall_score'] = 0
            capacity['status'] = 'unknown'
            capacity['status_text'] = 'Unable to calculate capacity'

    except Exception as e:
        capacity['error'] = str(e)

    return render(request, 'core/system_status.html', {
        'system_info': system_info,
        'db_info': db_info,
        'disk_usage': disk_usage,
        'memory_info': memory_info,
        'cpu_info': cpu_info,
        'upload_info': upload_info,
        'tasks_status': tasks_status,
        'services_status': services_status,
        'capacity': capacity,
        'current_tab': 'system_status',
    })


@login_required
@user_passes_test(is_superuser)
def maintenance(request):
    """System maintenance page - database cleanup, cache management, etc."""
    from audit.models import AuditLog
    from core.models import Organization
    from django.contrib.auth.models import User
    from django.contrib.sessions.models import Session

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'clear_expired_sessions':
            # Clear expired sessions
            Session.objects.filter(expire_date__lt=datetime.now()).delete()
            messages.success(request, 'Expired sessions cleared successfully.')

        elif action == 'cleanup_audit_logs':
            # Clean up audit logs older than specified days
            days = int(request.POST.get('days', 90))
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_count = AuditLog.objects.filter(timestamp__lt=cutoff_date).delete()[0]
            messages.success(request, f'Deleted {deleted_count} audit log entries older than {days} days.')

        elif action == 'optimize_database':
            # Optimize database tables
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    tables = [row[0] for row in cursor.fetchall()]
                    for table in tables:
                        # Use proper SQL identifier quoting to prevent SQL injection
                        quoted_table = connection.ops.quote_name(table)
                        cursor.execute(f"OPTIMIZE TABLE {quoted_table}")
                messages.success(request, f'Optimized {len(tables)} database tables successfully.')
            except Exception as e:
                messages.error(request, f'Database optimization failed: {e}')

        elif action == 'vacuum_database':
            # Analyze tables for query optimization
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    tables = [row[0] for row in cursor.fetchall()]
                    for table in tables:
                        # Use proper SQL identifier quoting to prevent SQL injection
                        quoted_table = connection.ops.quote_name(table)
                        cursor.execute(f"ANALYZE TABLE {quoted_table}")
                messages.success(request, f'Analyzed {len(tables)} database tables successfully.')
            except Exception as e:
                messages.error(request, f'Database analysis failed: {e}')

        return redirect('core:maintenance')

    # Gather statistics
    stats = {
        'total_users': User.objects.count(),
        'active_users': User.objects.filter(is_active=True).count(),
        'total_orgs': Organization.objects.count(),
        'active_orgs': Organization.objects.filter(is_active=True).count(),
        'audit_logs_count': AuditLog.objects.count(),
        'audit_logs_30d': AuditLog.objects.filter(timestamp__gte=datetime.now() - timedelta(days=30)).count(),
        'audit_logs_90d': AuditLog.objects.filter(timestamp__gte=datetime.now() - timedelta(days=90)).count(),
        'audit_logs_older_90d': AuditLog.objects.filter(timestamp__lt=datetime.now() - timedelta(days=90)).count(),
        'active_sessions': Session.objects.filter(expire_date__gte=datetime.now()).count(),
        'expired_sessions': Session.objects.filter(expire_date__lt=datetime.now()).count(),
    }

    # Database table sizes
    table_sizes = []
    try:
        db_engine = connection.settings_dict['ENGINE']

        if 'mysql' in db_engine:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT table_name,
                           ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb,
                           table_rows
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    ORDER BY (data_length + index_length) DESC
                    LIMIT 20
                """)
                for row in cursor.fetchall():
                    table_sizes.append({
                        'name': row[0],
                        'size_mb': row[1],
                        'rows': row[2],
                    })
        elif 'postgresql' in db_engine:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT tablename,
                           ROUND(pg_total_relation_size(schemaname||'.'||tablename) / 1024.0 / 1024.0, 2) AS size_mb,
                           NULL as rows
                    FROM pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                    LIMIT 20
                """)
                for row in cursor.fetchall():
                    table_sizes.append({
                        'name': row[0],
                        'size_mb': row[1],
                        'rows': row[2],
                    })
        elif 'sqlite' in db_engine:
            # For SQLite, get list of tables and their row counts
            with connection.cursor() as cursor:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = cursor.fetchall()

                for table_row in tables:
                    table_name = table_row[0]
                    # Skip SQLite system tables
                    if table_name.startswith('sqlite_'):
                        continue

                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        row_count = cursor.fetchone()[0]
                        table_sizes.append({
                            'name': table_name,
                            'size_mb': None,  # SQLite doesn't provide per-table sizes easily
                            'rows': row_count,
                        })
                    except Exception:
                        continue

                # Sort by row count
                table_sizes.sort(key=lambda x: x['rows'] or 0, reverse=True)
                table_sizes = table_sizes[:20]
    except Exception as e:
        messages.warning(request, f'Could not fetch table sizes: {e}')

    return render(request, 'core/maintenance.html', {
        'stats': stats,
        'table_sizes': table_sizes,
        'current_tab': 'maintenance',
    })


@login_required
@user_passes_test(is_superuser)
def settings_ai(request):
    """AI and LLM settings - Anthropic, OpenAI, etc."""
    import os
    from pathlib import Path
    from django.conf import settings as django_settings

    # Read current values from .env file (located in project root)
    env_path = django_settings.BASE_DIR / '.env'
    env_values = {}
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_values[key] = value

    current_anthropic_key = env_values.get('ANTHROPIC_API_KEY', '')
    current_claude_model = env_values.get('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929')
    current_google_maps_key = env_values.get('GOOGLE_MAPS_API_KEY', '')
    current_regrid_key = env_values.get('REGRID_API_KEY', '')
    current_attom_key = env_values.get('ATTOM_API_KEY', '')

    if request.method == 'POST':
        # Update .env file with new values
        anthropic_key = request.POST.get('anthropic_api_key', '').strip()
        claude_model = request.POST.get('claude_model', 'claude-sonnet-4-5-20250929')
        google_maps_key = request.POST.get('google_maps_api_key', '').strip()
        regrid_key = request.POST.get('regrid_api_key', '').strip()
        attom_key = request.POST.get('attom_api_key', '').strip()

        # Read all lines from .env
        lines = []
        if env_path.exists():
            with open(env_path, 'r') as f:
                lines = f.readlines()

        # Update or add the keys
        keys_to_update = {
            'ANTHROPIC_API_KEY': anthropic_key,
            'CLAUDE_MODEL': claude_model,
            'GOOGLE_MAPS_API_KEY': google_maps_key,
            'REGRID_API_KEY': regrid_key,
            'ATTOM_API_KEY': attom_key,
        }

        for key, value in keys_to_update.items():
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f'{key}='):
                    lines[i] = f'{key}={value}\n'
                    found = True
                    break
            if not found:
                # Add new key
                lines.append(f'{key}={value}\n')

        # Write back to .env (create parent directory if needed)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        with open(env_path, 'w') as f:
            f.writelines(lines)

        # Automatically reload Gunicorn to apply changes (using HUP signal)
        try:
            import subprocess
            import signal

            # Find Gunicorn master process
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            gunicorn_pid = None
            for line in result.stdout.split('\n'):
                if 'gunicorn' in line and 'master' in line:
                    parts = line.split()
                    if len(parts) > 1:
                        gunicorn_pid = int(parts[1])
                        break

            if gunicorn_pid:
                # Send HUP signal to reload workers (doesn't require sudo)
                os.kill(gunicorn_pid, signal.SIGHUP)
                messages.success(request, 'AI settings updated successfully. Application reloaded automatically.')
            else:
                messages.warning(request, 'AI settings updated. The application will restart shortly. Please refresh the page if needed.')

        except PermissionError:
            # If we don't have permission to send signal, try systemctl restart with sudo
            try:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', 'huduglue-gunicorn'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    messages.success(request, 'AI settings updated successfully. Application restarted automatically.')
                else:
                    messages.warning(request, 'AI settings updated. The application will restart shortly. Please refresh the page if needed.')
            except Exception:
                messages.warning(request, 'AI settings updated. The application will restart shortly. Please refresh the page if needed.')

        except Exception as e:
            messages.warning(request, 'AI settings updated. The application will restart shortly. Please refresh the page if needed.')

        return redirect('core:settings_ai')

    return render(request, 'core/settings_ai.html', {
        'current_anthropic_key': current_anthropic_key,
        'current_claude_model': current_claude_model,
        'current_google_maps_key': current_google_maps_key,
        'current_regrid_key': current_regrid_key,
        'current_attom_key': current_attom_key,
        'current_tab': 'ai',
    })


@login_required
@user_passes_test(is_superuser)
def settings_snyk(request):
    """Snyk security scanning settings."""
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        # Snyk Settings
        settings.snyk_enabled = request.POST.get('snyk_enabled') == 'on'

        # Only update API token if provided
        snyk_token = request.POST.get('snyk_api_token', '').strip()
        if snyk_token:
            settings.snyk_api_token = snyk_token

        settings.snyk_org_id = request.POST.get('snyk_org_id', '').strip()
        settings.snyk_severity_threshold = request.POST.get('snyk_severity_threshold', 'high')
        settings.snyk_scan_frequency = request.POST.get('snyk_scan_frequency', 'daily')

        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'Snyk security settings updated successfully.')
        return redirect('core:settings_snyk')

    # Check if API token is configured
    has_token = bool(settings.snyk_api_token)

    return render(request, 'core/settings_snyk.html', {
        'settings': settings,
        'current_tab': 'snyk',
        'has_token': has_token,
    })


@login_required
@user_passes_test(is_superuser)
def check_snyk_version(request):
    """Check current and latest Snyk CLI version."""
    from django.http import JsonResponse
    import subprocess
    import re
    import os

    def find_command(cmd):
        """Find command in common locations."""
        import glob

        # Check nvm installations (any node version)
        nvm_pattern = f'/home/administrator/.nvm/versions/node/*/bin/{cmd}'
        nvm_matches = glob.glob(nvm_pattern)
        if nvm_matches:
            # Use the first match (or could sort and use latest version)
            for path in nvm_matches:
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    return path

        # Common paths to check
        paths = [
            f'/usr/local/bin/{cmd}',
            f'/usr/bin/{cmd}',
            f'/home/administrator/.local/bin/{cmd}',
            f'/opt/homebrew/bin/{cmd}',  # macOS homebrew
        ]

        # Also check PATH
        path_env = os.environ.get('PATH', '')
        for path_dir in path_env.split(':'):
            if path_dir:  # Skip empty strings
                full_path = os.path.join(path_dir, cmd)
                if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    return full_path

        # Check our predefined paths
        for path in paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        return None

    try:
        # Find npm and snyk binaries
        snyk_path = find_command('snyk')
        npm_path = find_command('npm')

        # Check current installed version
        current_version = None
        snyk_error = None
        if snyk_path:
            try:
                # Set up environment with nvm node bin directory in PATH
                env = os.environ.copy()
                node_bin_dir = os.path.dirname(snyk_path)  # Get the bin directory
                system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                existing_path = env.get('PATH', '')
                env['PATH'] = f"{node_bin_dir}:{system_paths}:{existing_path}"

                result = subprocess.run(
                    [snyk_path, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env
                )
                if result.returncode == 0:
                    # Parse version from output (e.g., "1.1234.0")
                    version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
                    current_version = version_match.group(1) if version_match else result.stdout.strip()
                else:
                    snyk_error = f"Exit code {result.returncode}: {result.stderr}"
            except Exception as e:
                snyk_error = str(e)

        # Check latest version from npm
        latest_version = None
        npm_error = None
        if npm_path:
            try:
                # Set up environment with nvm node bin directory in PATH
                env = os.environ.copy()
                node_bin_dir = os.path.dirname(npm_path)  # Get the bin directory
                system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                existing_path = env.get('PATH', '')
                env['PATH'] = f"{node_bin_dir}:{system_paths}:{existing_path}"

                result = subprocess.run(
                    [npm_path, 'view', 'snyk', 'version'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env
                )
                if result.returncode == 0:
                    latest_version = result.stdout.strip()
                else:
                    npm_error = f"Exit code {result.returncode}: {result.stderr}"
            except Exception as e:
                npm_error = str(e)

        # Determine if update is available
        update_available = False
        if current_version and latest_version:
            try:
                from packaging import version
                update_available = version.parse(latest_version) > version.parse(current_version)
            except:
                # Fallback to string comparison if packaging module not available
                update_available = latest_version != current_version

        # Debug info
        import glob
        nvm_snyk_matches = glob.glob('/home/administrator/.nvm/versions/node/*/bin/snyk')
        nvm_npm_matches = glob.glob('/home/administrator/.nvm/versions/node/*/bin/npm')

        return JsonResponse({
            'success': True,
            'current_version': current_version,
            'latest_version': latest_version,
            'update_available': update_available,
            'snyk_path': snyk_path,
            'npm_path': npm_path,
            'debug': {
                'nvm_snyk_matches': nvm_snyk_matches,
                'nvm_npm_matches': nvm_npm_matches,
                'snyk_exists': os.path.exists(snyk_path) if snyk_path else False,
                'npm_exists': os.path.exists(npm_path) if npm_path else False,
                'snyk_error': snyk_error,
                'npm_error': npm_error,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_superuser)
@require_POST
def upgrade_snyk_cli(request):
    """Upgrade Snyk CLI to the latest version."""
    from django.http import JsonResponse
    import subprocess
    import os

    def find_command(cmd):
        """Find command in common locations."""
        import glob

        # Check nvm installations (any node version)
        nvm_pattern = f'/home/administrator/.nvm/versions/node/*/bin/{cmd}'
        nvm_matches = glob.glob(nvm_pattern)
        if nvm_matches:
            # Use the first match (or could sort and use latest version)
            for path in nvm_matches:
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    return path

        # Common paths to check
        paths = [
            f'/usr/local/bin/{cmd}',
            f'/usr/bin/{cmd}',
            f'/home/administrator/.local/bin/{cmd}',
            f'/opt/homebrew/bin/{cmd}',  # macOS homebrew
        ]

        # Also check PATH
        path_env = os.environ.get('PATH', '')
        for path_dir in path_env.split(':'):
            if path_dir:  # Skip empty strings
                full_path = os.path.join(path_dir, cmd)
                if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    return full_path

        # Check our predefined paths
        for path in paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        return None

    try:
        # Find npm and snyk binaries
        npm_path = find_command('npm')
        snyk_path = find_command('snyk')

        if not npm_path:
            return JsonResponse({
                'success': False,
                'message': 'npm command not found. Please ensure Node.js and npm are installed.'
            })

        # Set up environment with nvm node bin directory in PATH
        # Also include common system paths for shell utilities
        env = os.environ.copy()
        node_bin_dir = os.path.dirname(npm_path)  # Get the bin directory

        # Ensure essential system paths are included
        system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        existing_path = env.get('PATH', '')
        env['PATH'] = f"{node_bin_dir}:{system_paths}:{existing_path}"

        # Run npm install -g snyk@latest
        result = subprocess.run(
            [npm_path, 'install', '-g', 'snyk@latest'],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            env=env
        )

        if result.returncode == 0:
            # Get new version - refresh the snyk path in case it changed
            snyk_path = find_command('snyk')
            if snyk_path:
                # Set up environment with nvm node bin directory in PATH
                version_env = os.environ.copy()
                version_node_bin_dir = os.path.dirname(snyk_path)
                system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                existing_path = version_env.get('PATH', '')
                version_env['PATH'] = f"{version_node_bin_dir}:{system_paths}:{existing_path}"

                version_result = subprocess.run(
                    [snyk_path, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=version_env
                )

                import re
                version_match = re.search(r'(\d+\.\d+\.\d+)', version_result.stdout)
                new_version = version_match.group(1) if version_match else 'latest'
            else:
                new_version = 'latest'

            return JsonResponse({
                'success': True,
                'message': 'Snyk CLI upgraded successfully',
                'new_version': new_version,
                'output': result.stdout + result.stderr
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Failed to upgrade Snyk CLI',
                'output': result.stdout + result.stderr
            })

    except subprocess.TimeoutExpired:
        return JsonResponse({
            'success': False,
            'message': 'Upgrade timed out after 2 minutes'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_superuser)
@require_POST
def install_nodejs_npm(request):
    """Install Node.js and npm via nvm for Snyk CLI."""
    from django.http import JsonResponse
    import subprocess
    import os

    try:
        # Check if nvm is installed
        nvm_dir = '/home/administrator/.nvm'

        if not os.path.exists(nvm_dir):
            # Install nvm first
            install_nvm_script = """
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
"""
            result = subprocess.run(
                ['/bin/bash', '-c', install_nvm_script],
                capture_output=True,
                text=True,
                timeout=60,
                cwd='/home/administrator'
            )

            if result.returncode != 0:
                return JsonResponse({
                    'success': False,
                    'message': 'Failed to install nvm',
                    'output': result.stdout + result.stderr
                })

        # Install Node.js LTS via nvm
        install_node_script = """
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install --lts
nvm use --lts
npm install -g npm@latest
"""

        result = subprocess.run(
            ['/bin/bash', '-c', install_node_script],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes
            cwd='/home/administrator'
        )

        if result.returncode == 0:
            return JsonResponse({
                'success': True,
                'message': 'Node.js and npm installed successfully',
                'output': result.stdout + result.stderr
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Failed to install Node.js',
                'output': result.stdout + result.stderr
            })

    except subprocess.TimeoutExpired:
        return JsonResponse({
            'success': False,
            'message': 'Installation timed out after 5 minutes'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_superuser)
def test_snyk_connection(request):
    """Test Snyk API connection."""
    import requests
    from django.http import JsonResponse

    settings = SystemSetting.get_settings()

    if not settings.snyk_api_token:
        return JsonResponse({
            'success': False,
            'message': 'No Snyk API token configured'
        })

    try:
        # Test the Snyk API with the v1 user endpoint
        headers = {
            'Authorization': f'token {settings.snyk_api_token}',
        }

        response = requests.get(
            'https://api.snyk.io/v1/user/me',
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            return JsonResponse({
                'success': True,
                'message': 'Connection successful!',
                'user': data.get('username', 'Unknown')
            })
        elif response.status_code == 401:
            return JsonResponse({
                'success': False,
                'message': 'Invalid API token - authentication failed'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'API returned error: {response.status_code}'
            })

    except requests.exceptions.Timeout:
        return JsonResponse({
            'success': False,
            'message': 'Connection timeout - unable to reach Snyk API'
        })
    except requests.exceptions.RequestException as e:
        return JsonResponse({
            'success': False,
            'message': f'Connection error: {str(e)}'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        })


@login_required
@user_passes_test(is_superuser)
def snyk_scans(request):
    """List all Snyk scans."""
    from core.models import SnykScan
    
    scans = SnykScan.objects.all()[:50]  # Latest 50 scans
    
    # Get latest scan for dashboard
    latest_scan = scans.first() if scans else None
    
    return render(request, 'core/snyk_scans.html', {
        'scans': scans,
        'latest_scan': latest_scan,
        'current_tab': 'snyk',
    })


@login_required
@user_passes_test(is_superuser)
def snyk_scan_detail(request, scan_id):
    """View details of a specific Snyk scan."""
    from core.models import SnykScan
    from django.shortcuts import get_object_or_404

    scan = get_object_or_404(SnykScan, id=scan_id)

    # Parse vulnerabilities for display
    vulnerabilities = scan.vulnerabilities.get('vulnerabilities', [])

    # Check if there are any fixable vulnerabilities
    has_fixable_vulns = any(
        vuln.get('fixedIn') or vuln.get('upgradePath')
        for vuln in vulnerabilities
    )

    return render(request, 'core/snyk_scan_detail.html', {
        'scan': scan,
        'vulnerabilities': vulnerabilities,
        'has_fixable_vulns': has_fixable_vulns,
        'current_tab': 'snyk',
    })


@login_required
@user_passes_test(is_superuser)
def run_snyk_scan(request):
    """Trigger a manual Snyk scan."""
    from django.http import JsonResponse
    from django.core.management import call_command
    import threading
    import uuid
    
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })
    
    settings = SystemSetting.get_settings()
    
    if not settings.snyk_enabled:
        return JsonResponse({
            'success': False,
            'message': 'Snyk scanning is not enabled'
        })
    
    if not settings.snyk_api_token:
        return JsonResponse({
            'success': False,
            'message': 'Snyk API token is not configured'
        })
    
    # Generate scan ID
    scan_id = f"manual-{uuid.uuid4().hex[:8]}"
    
    # Run scan in background thread
    def run_scan():
        try:
            call_command('run_snyk_scan', scan_id=scan_id, user_id=request.user.id)
        except Exception as e:
            print(f"Scan error: {e}")
    
    thread = threading.Thread(target=run_scan)
    thread.daemon = True
    thread.start()
    
    return JsonResponse({
        'success': True,
        'message': 'Scan started successfully',
        'scan_id': scan_id
    })


@login_required
@user_passes_test(is_superuser)
def snyk_scan_status(request, scan_id):
    """Get status of a running scan."""
    from django.http import JsonResponse
    from core.models import SnykScan
    
    try:
        scan = SnykScan.objects.get(scan_id=scan_id)
        return JsonResponse({
            'success': True,
            'status': scan.status,
            'total_vulnerabilities': scan.total_vulnerabilities,
            'critical_count': scan.critical_count,
            'high_count': scan.high_count,
            'medium_count': scan.medium_count,
            'low_count': scan.low_count,
            'completed': scan.status in ['completed', 'failed', 'cancelled', 'timeout'],
            'error_message': scan.error_message if scan.status in ['failed', 'timeout'] else None,
        })
    except SnykScan.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Scan not found'
        })


@login_required
@user_passes_test(is_superuser)
def apply_snyk_remediation(request):
    """Apply Snyk vulnerability remediation by upgrading a package."""
    from django.http import JsonResponse
    import subprocess
    import os
    import re

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })

    package = request.POST.get('package')
    version = request.POST.get('version')

    if not package or not version:
        return JsonResponse({
            'success': False,
            'message': 'Package and version are required'
        })

    # Validate package name (prevent command injection)
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', package):
        return JsonResponse({
            'success': False,
            'message': 'Invalid package name'
        })

    # Validate version (prevent command injection)
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', version):
        return JsonResponse({
            'success': False,
            'message': 'Invalid version format'
        })

    try:
        # Get virtualenv path
        venv_path = '/home/administrator/venv'
        pip_path = os.path.join(venv_path, 'bin', 'pip')

        if not os.path.exists(pip_path):
            return JsonResponse({
                'success': False,
                'message': 'Virtual environment not found'
            })

        # Run pip install with specific version
        cmd = [pip_path, 'install', f'{package}=={version}']

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            cwd='/home/administrator'
        )

        # Check if successful
        if result.returncode == 0:
            return JsonResponse({
                'success': True,
                'message': f'Successfully upgraded {package} to version {version}',
                'output': result.stdout + result.stderr
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'Failed to upgrade {package}',
                'output': result.stdout + result.stderr
            })

    except subprocess.TimeoutExpired:
        return JsonResponse({
            'success': False,
            'message': 'Upgrade timed out after 2 minutes'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_superuser)
@require_POST
def fix_all_snyk_vulnerabilities(request):
    """Apply fixes for all fixable Snyk vulnerabilities in batch."""
    from django.http import JsonResponse
    import subprocess
    import os
    import re
    import json

    vulnerabilities_json = request.POST.get('vulnerabilities')

    if not vulnerabilities_json:
        return JsonResponse({
            'success': False,
            'message': 'No vulnerabilities provided'
        })

    try:
        vulnerabilities = json.loads(vulnerabilities_json)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid vulnerabilities data'
        })

    if not vulnerabilities or not isinstance(vulnerabilities, list):
        return JsonResponse({
            'success': False,
            'message': 'Vulnerabilities must be a non-empty list'
        })

    # Get virtualenv path
    venv_path = '/home/administrator/venv'
    pip_path = os.path.join(venv_path, 'bin', 'pip')

    if not os.path.exists(pip_path):
        return JsonResponse({
            'success': False,
            'message': 'Virtual environment not found'
        })

    results = []

    for vuln in vulnerabilities:
        package = vuln.get('package')
        version = vuln.get('version')

        if not package or not version:
            results.append({
                'success': False,
                'package': package or 'Unknown',
                'message': 'Missing package or version'
            })
            continue

        # Validate package name (prevent command injection)
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', package):
            results.append({
                'success': False,
                'package': package,
                'message': 'Invalid package name'
            })
            continue

        # Validate version (prevent command injection)
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', version):
            results.append({
                'success': False,
                'package': package,
                'message': 'Invalid version format'
            })
            continue

        try:
            # Run pip install with specific version
            cmd = [pip_path, 'install', f'{package}=={version}']

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute per package
                cwd='/home/administrator'
            )

            # Check if successful
            if result.returncode == 0:
                results.append({
                    'success': True,
                    'package': package,
                    'message': f'Upgraded to {version}'
                })
            else:
                results.append({
                    'success': False,
                    'package': package,
                    'message': f'Failed: {result.stderr[:200]}'
                })

        except subprocess.TimeoutExpired:
            results.append({
                'success': False,
                'package': package,
                'message': 'Upgrade timed out'
            })
        except Exception as e:
            results.append({
                'success': False,
                'package': package,
                'message': str(e)
            })

    # Count successes
    success_count = sum(1 for r in results if r['success'])

    return JsonResponse({
        'success': True,
        'message': f'Processed {len(vulnerabilities)} vulnerabilities',
        'results': results,
        'success_count': success_count,
        'total_count': len(vulnerabilities)
    })


@login_required
@user_passes_test(is_superuser)
def cancel_snyk_scan(request, scan_id):
    """Cancel a running Snyk scan."""
    from django.http import JsonResponse
    from core.models import SnykScan

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })

    try:
        scan = SnykScan.objects.get(scan_id=scan_id)

        if scan.status not in ['pending', 'running']:
            return JsonResponse({
                'success': False,
                'message': f'Cannot cancel scan in {scan.status} state'
            })

        # Mark scan as cancelled
        scan.cancel_requested = True
        scan.status = 'cancelled'
        scan.completed_at = timezone.now()
        scan.error_message = 'Scan cancelled by user'

        if scan.started_at:
            duration = (timezone.now() - scan.started_at).total_seconds()
            scan.duration_seconds = int(duration)

        scan.save()

        return JsonResponse({
            'success': True,
            'message': 'Scan cancelled successfully'
        })

    except SnykScan.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Scan not found'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_superuser)
def restart_application(request):
    """Restart the Gunicorn application service."""
    from django.http import JsonResponse
    import subprocess

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })

    try:
        # Restart Gunicorn service using sudo (full path)
        result = subprocess.run(
            ['/usr/bin/sudo', '/bin/systemctl', 'restart', 'huduglue-gunicorn.service'],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return JsonResponse({
                'success': True,
                'message': 'Application is restarting. Please refresh the page in a few seconds.'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'Failed to restart application: {result.stderr}'
            })

    except subprocess.TimeoutExpired:
        return JsonResponse({
            'success': False,
            'message': 'Restart command timed out'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@user_passes_test(is_superuser)
def cleanup_old_snyk_scans(request):
    """Cleanup old Snyk scans, keeping only the last 30."""
    from django.http import JsonResponse
    from core.models import SnykScan

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })

    try:
        # First, clean up stuck scans (mark as timeout)
        stuck_count = SnykScan.cleanup_stuck_scans(timeout_hours=2)

        # Get all scans ordered by completion time (newest first)
        all_scans = SnykScan.objects.all().order_by('-completed_at', '-started_at')
        total_count = all_scans.count()

        if total_count <= 30:
            if stuck_count > 0:
                return JsonResponse({
                    'success': True,
                    'message': f'Marked {stuck_count} stuck scan(s) as timed out. No old scans to delete (only {total_count} exist).',
                    'deleted_count': 0,
                    'stuck_count': stuck_count,
                    'remaining_count': total_count
                })
            return JsonResponse({
                'success': True,
                'message': f'No cleanup needed. Only {total_count} scans exist.',
                'deleted_count': 0,
                'stuck_count': 0,
                'remaining_count': total_count
            })

        # Get scans to keep (last 30)
        scans_to_keep = list(all_scans[:30].values_list('id', flat=True))

        # Delete old scans
        deleted = SnykScan.objects.exclude(id__in=scans_to_keep).delete()
        deleted_count = deleted[0]  # First element is count of deleted objects

        message = f'Cleanup complete. Deleted {deleted_count} old scan(s).'
        if stuck_count > 0:
            message += f' Marked {stuck_count} stuck scan(s) as timed out.'

        return JsonResponse({
            'success': True,
            'message': message,
            'deleted_count': deleted_count,
            'stuck_count': stuck_count,
            'remaining_count': 30
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Cleanup failed: {str(e)}'
        })


@login_required
@user_passes_test(is_superuser)
@ensure_csrf_cookie
def settings_kb_import(request):
    """Knowledge Base article import settings and management."""
    from docs.models import Document, DocumentCategory
    from django.core.management import call_command
    from io import StringIO

    # Get current statistics
    total_articles = Document.objects.count()
    global_articles = Document.objects.filter(organization__isnull=True).count()
    categories = DocumentCategory.objects.all().order_by('name')

    # Get category statistics
    category_stats = []
    for category in categories:
        count = Document.objects.filter(
            category=category,
            organization__isnull=True
        ).count()
        category_stats.append({
            'name': category.name,
            'count': count
        })

    context = {
        'current_tab': 'kb_import',
        'total_articles': total_articles,
        'global_articles': global_articles,
        'category_stats': category_stats,
        'categories_count': categories.count(),
    }

    return render(request, 'core/settings_kb_import.html', context)


@require_POST
@login_required
@user_passes_test(is_superuser)
def import_kb_articles(request):
    """Import KB articles from seed command."""
    from django.http import JsonResponse
    from django.core.management import call_command
    from io import StringIO
    import time

    source = request.POST.get('source', 'local')  # 'local' or 'github'
    delete_existing = request.POST.get('delete_existing') == 'true'

    try:
        # Capture command output
        out = StringIO()

        # Start time tracking
        start_time = time.time()

        if source == 'github':
            # Import from GitHub (which internally calls seed_professional_kb)
            call_command('fetch_kb_from_github', delete=delete_existing, stdout=out)
        else:
            # Import locally generated professional articles
            call_command('seed_professional_kb', stdout=out)

        # Calculate duration
        duration = time.time() - start_time

        # Get updated statistics
        from docs.models import Document
        total_articles = Document.objects.count()
        global_articles = Document.objects.filter(organization__isnull=True).count()

        return JsonResponse({
            'success': True,
            'message': f'Successfully imported KB articles from {source}',
            'output': out.getvalue(),
            'duration': round(duration, 2),
            'total_articles': total_articles,
            'global_articles': global_articles,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Import failed: {str(e)}'
        })


@require_POST
@login_required
@user_passes_test(is_superuser)
def delete_global_kb_articles(request):
    """Delete all global KB articles."""
    from django.http import JsonResponse
    from docs.models import Document

    try:
        # Delete only global articles (not organization-specific ones)
        deleted_count, _ = Document.objects.filter(organization__isnull=True).delete()

        return JsonResponse({
            'success': True,
            'message': f'Deleted {deleted_count} global KB articles',
            'deleted_count': deleted_count
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Delete failed: {str(e)}'
        })


@login_required
@user_passes_test(is_superuser)
def settings_data_export(request):
    """Data export settings and options."""
    from django.db.models import Count
    from assets.models import Asset, Contact
    from docs.models import Document
    from vault.models import Password

    # Get statistics for current organization
    # Note: For superuser, we could show all orgs or let them select
    stats = {
        'assets': Asset.objects.count(),
        'contacts': Contact.objects.count(),
        'documents': Document.objects.count(),
        'passwords': Password.objects.count(),
    }

    context = {
        'current_tab': 'data_export',
        'stats': stats,
    }

    return render(request, 'core/settings_data_export.html', context)


@login_required
@user_passes_test(is_superuser)
def export_data(request):
    """Export data in specified format."""
    from django.http import JsonResponse, HttpResponse
    import json
    from datetime import datetime

    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})

    export_format = request.POST.get('format', 'json')  # 'json', 'hudu', 'itglue'
    export_type = request.POST.get('type', 'all')  # 'all', 'assets', 'contacts', 'docs', 'passwords'

    try:
        # Build export data based on type
        export_data = {}

        if export_type in ['all', 'assets']:
            from assets.models import Asset
            assets = Asset.objects.all().select_related('equipment_model', 'primary_contact')
            export_data['assets'] = [_serialize_asset(asset, export_format) for asset in assets]

        if export_type in ['all', 'contacts']:
            from assets.models import Contact
            contacts = Contact.objects.all()
            export_data['contacts'] = [_serialize_contact(contact, export_format) for contact in contacts]

        if export_type in ['all', 'documents']:
            from docs.models import Document
            documents = Document.objects.all()
            export_data['documents'] = [_serialize_document(doc, export_format) for doc in documents]

        # Note: Passwords require special handling for security
        if export_type == 'passwords':
            from vault.models import Password
            passwords = Password.objects.all()
            export_data['passwords'] = [_serialize_password(pwd, export_format) for pwd in passwords]

        # Format the export based on target system
        if export_format == 'hudu':
            formatted_data = _format_for_hudu(export_data)
        elif export_format == 'itglue':
            formatted_data = _format_for_itglue(export_data)
        else:
            formatted_data = export_data

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'huduglue_export_{export_type}_{timestamp}.json'

        # Return as downloadable file
        response = HttpResponse(
            json.dumps(formatted_data, indent=2, default=str),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        return response

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Export failed: {str(e)}'
        })


def _serialize_asset(asset, format_type):
    """Serialize asset to dictionary."""
    data = {
        'id': asset.id,
        'name': asset.name,
        'asset_type': asset.asset_type,
        'manufacturer': asset.manufacturer,
        'model': asset.model,
        'serial_number': asset.serial_number,
        'asset_tag': asset.asset_tag,
        'hostname': asset.hostname,
        'ip_address': asset.ip_address,
        'mac_address': asset.mac_address,
        'location': asset.location,
        'status': asset.status,
        'purchase_date': asset.purchase_date,
        'warranty_expiry': asset.warranty_expiry,
        'notes': asset.notes,
        'custom_fields': asset.custom_fields,
    }

    if asset.equipment_model:
        data['equipment_model'] = asset.equipment_model.model_name
        data['equipment_vendor'] = asset.equipment_model.vendor.name

    return data




def _serialize_contact(contact, format_type):
    """Serialize contact to dictionary."""
    return {
        'id': contact.id,
        'first_name': contact.first_name,
        'last_name': contact.last_name,
        'email': contact.email,
        'phone': contact.phone,
        'title': contact.title,
        'notes': contact.notes,
    }


def _serialize_document(doc, format_type):
    """Serialize document to dictionary."""
    return {
        'id': doc.id,
        'title': doc.title,
        'content': doc.content,
        'category': doc.category.name if doc.category else None,
        'tags': [tag.name for tag in doc.tags.all()],
        'is_global': doc.organization is None,
        'created_at': doc.created_at,
        'updated_at': doc.updated_at,
    }


def _serialize_password(pwd, format_type):
    """Serialize password to dictionary (encrypted value only)."""
    return {
        'id': pwd.id,
        'title': pwd.title,
        'username': pwd.username,
        'url': pwd.url,
        'password_type': pwd.password_type,
        'notes': pwd.notes,
        # Do NOT export decrypted password for security
        'password_encrypted': pwd.password_encrypted,
    }


def _format_for_hudu(data):
    """Format data for Hudu API compatibility."""
    # Hudu API structure
    formatted = {
        'export_info': {
            'source': 'HuduGlue',
            'format': 'hudu',
            'version': '1.0',
        },
        'data': {}
    }

    # Map to Hudu structure
    if 'assets' in data:
        formatted['data']['assets'] = [
            {
                'asset_type': asset['asset_type'],
                'name': asset['name'],
                'serial_number': asset.get('serial_number', ''),
                'asset_tag': asset.get('asset_tag', ''),
                'manufacturer': asset.get('manufacturer', ''),
                'model': asset.get('model', ''),
                'notes': asset.get('notes', ''),
                'fields': asset.get('custom_fields', {}),
            }
            for asset in data['assets']
        ]

    if 'documents' in data:
        formatted['data']['kb_articles'] = [
            {
                'name': doc['title'],
                'content': doc['content'],
                'category': doc.get('category', ''),
            }
            for doc in data['documents']
        ]

    return formatted


def _format_for_itglue(data):
    """Format data for IT Glue API compatibility."""
    # IT Glue API structure
    formatted = {
        'export_info': {
            'source': 'HuduGlue',
            'format': 'itglue',
            'version': '1.0',
        },
        'data': {
            'type': 'export',
            'attributes': {}
        }
    }

    # Map to IT Glue structure
    if 'assets' in data:
        formatted['data']['attributes']['configurations'] = [
            {
                'type': 'configurations',
                'attributes': {
                    'name': asset['name'],
                    'configuration_type_name': asset['asset_type'],
                    'manufacturer_name': asset.get('manufacturer', ''),
                    'model_name': asset.get('model', ''),
                    'serial_number': asset.get('serial_number', ''),
                    'asset_tag': asset.get('asset_tag', ''),
                    'notes': asset.get('notes', ''),
                }
            }
            for asset in data['assets']
        ]

    if 'contacts' in data:
        formatted['data']['attributes']['contacts'] = [
            {
                'type': 'contacts',
                'attributes': {
                    'first_name': contact['first_name'],
                    'last_name': contact['last_name'],
                    'contact_emails': [{'value': contact['email']}] if contact.get('email') else [],
                    'contact_phones': [{'value': contact['phone']}] if contact.get('phone') else [],
                    'title': contact.get('title', ''),
                    'notes': contact.get('notes', ''),
                }
            }
            for contact in data['contacts']
        ]

    return formatted


@login_required
@user_passes_test(is_superuser)
def import_demo_data(request):
    """Import Acme Corporation demo data - automatically creates 'Acme Corporation' org."""
    from django.http import JsonResponse
    from django.core.management import call_command
    from accounts.models import Membership
    import io
    from contextlib import redirect_stdout, redirect_stderr

    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })

    # Wrap entire function in try/except to ensure we always return JSON
    try:
        logger.info(f"Demo data import requested by user: {request.user.username}")

        # Auto-generate APP_MASTER_KEY if not configured
        import os
        import base64
        from pathlib import Path
        from django.conf import settings

        master_key = os.getenv('APP_MASTER_KEY', '').strip()
        settings_key = getattr(settings, 'APP_MASTER_KEY', '').strip() if hasattr(settings, 'APP_MASTER_KEY') else ''

        # Log what we found for debugging
        logger.info(f"APP_MASTER_KEY from os.environ: {'SET' if master_key else 'NOT SET'} (len={len(master_key)})")
        logger.info(f"APP_MASTER_KEY from settings: {'SET' if settings_key else 'NOT SET'} (len={len(settings_key)})")

        # Use whichever is set and valid, and try to validate it
        candidate_key = settings_key if settings_key and len(settings_key) >= 40 else master_key

        # If we have a candidate key, validate it before using
        if candidate_key and len(candidate_key) >= 40:
            logger.info("Found candidate APP_MASTER_KEY, validating...")
            try:
                # Try to decode it to check if it's valid base64
                decoded = base64.b64decode(candidate_key)
                if len(decoded) == 32:
                    logger.info("✓ APP_MASTER_KEY is valid, using it")
                    master_key = candidate_key
                else:
                    logger.error(f"✗ APP_MASTER_KEY decoded to {len(decoded)} bytes, expected 32. Will regenerate.")
                    master_key = ''  # Force regeneration
            except Exception as e:
                logger.error(f"✗ APP_MASTER_KEY validation failed: {e}. Will regenerate.")
                master_key = ''  # Force regeneration
        else:
            master_key = candidate_key

        if not master_key or len(master_key) < 40:
            logger.warning("APP_MASTER_KEY not configured, auto-generating...")

            # Generate a secure 32-byte key
            new_key = base64.b64encode(os.urandom(32)).decode()

            # Validate the key we just generated (sanity check)
            try:
                test_decode = base64.b64decode(new_key)
                if len(test_decode) != 32:
                    raise ValueError(f"Generated key decoded to {len(test_decode)} bytes, expected 32")
            except Exception as e:
                logger.error(f"Generated invalid key: {e}")
                return JsonResponse({
                    'success': False,
                    'message': f'✗ Failed to generate valid encryption key: {str(e)}'
                })

            logger.info(f"Generated new APP_MASTER_KEY: {new_key[:10]}... ({len(new_key)} chars)")

            # Try to write to .env file
            env_path = Path(settings.BASE_DIR) / '.env'
            try:
                import re

                # Read existing .env content
                env_content = ''
                if env_path.exists():
                    with open(env_path, 'r') as f:
                        env_content = f.read()

                    # Debug: Check if there's an existing APP_MASTER_KEY line
                    existing_keys = re.findall(r'^#?\s*APP_MASTER_KEY=(.*)$', env_content, re.MULTILINE)
                    if existing_keys:
                        logger.info(f"Found {len(existing_keys)} existing APP_MASTER_KEY line(s) in .env")
                        for idx, key in enumerate(existing_keys):
                            key_value = key.strip()
                            key_preview = key_value[:10] + '...' if len(key_value) > 10 else key_value if key_value else '(empty)'
                            logger.info(f"  Line {idx+1}: APP_MASTER_KEY='{key_preview}' (len={len(key_value)})")

                # Remove any existing APP_MASTER_KEY lines (including comments and empty values)
                env_content = re.sub(
                    r'^#?\s*APP_MASTER_KEY=.*$\n?',
                    '',
                    env_content,
                    flags=re.MULTILINE
                )

                # Remove any trailing whitespace and ensure single newline at end
                env_content = env_content.rstrip()
                if env_content:
                    env_content += '\n'

                # Add new APP_MASTER_KEY at the end
                env_content += f'\n# Auto-generated encryption key for passwords and sensitive data\n'
                env_content += f'# WARNING: Never change this key after data is encrypted!\n'
                env_content += f'APP_MASTER_KEY={new_key}\n'

                # Write back to .env
                with open(env_path, 'w') as f:
                    f.write(env_content)

                # Set in current process environment AND Django settings
                os.environ['APP_MASTER_KEY'] = new_key
                settings.APP_MASTER_KEY = new_key  # Update Django settings for current process

                # Verify it was set correctly
                verify_key = getattr(settings, 'APP_MASTER_KEY', None)
                if verify_key != new_key:
                    logger.error(f"Failed to update settings.APP_MASTER_KEY! Got: {verify_key[:10] if verify_key else 'None'}...")
                    return JsonResponse({
                        'success': False,
                        'message': '✗ Failed to update APP_MASTER_KEY in Django settings. Please restart the application and try again.'
                    })

                logger.info(f"✓ Auto-generated and saved APP_MASTER_KEY to {env_path}")
                logger.info(f"✓ Verified settings.APP_MASTER_KEY = {verify_key[:10]}... ({len(verify_key)} chars)")
                logger.warning("IMPORTANT: Restart the application to ensure the key is loaded on next startup")

            except Exception as e:
                logger.error(f"Failed to write APP_MASTER_KEY to .env: {e}")
                return JsonResponse({
                    'success': False,
                    'message': f'✗ Failed to auto-generate APP_MASTER_KEY: {str(e)}\n\nPlease check file permissions on .env file.'
                })

        # Validate that encryption actually works before proceeding
        logger.info("Validating encryption functionality...")
        try:
            from vault.encryption_v2 import encrypt_v2, decrypt_v2
            test_data = "test-encryption-validation-12345"
            encrypted = encrypt_v2(test_data)
            decrypted = decrypt_v2(encrypted)
            if decrypted != test_data:
                raise ValueError("Decrypted data doesn't match original")
            logger.info("✓ Encryption validation passed")
        except Exception as e:
            logger.error(f"Encryption validation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return JsonResponse({
                'success': False,
                'message': f'✗ Encryption validation failed: {str(e)}\n\nThe APP_MASTER_KEY may be invalid. Please check server logs.',
                'error': str(e)
            })

        # Get or create Acme Corporation organization
        organization, created = Organization.objects.get_or_create(
            name='Acme Corporation',
            defaults={
                'description': 'Demo company with sample data for testing and demonstration',
                'is_active': True,
            }
        )

        if created:
            logger.info(f"Created new 'Acme Corporation' organization (ID: {organization.id})")
        else:
            logger.info(f"Using existing 'Acme Corporation' organization (ID: {organization.id})")

        # Add current user to the organization if not already a member
        membership_created = False
        if not Membership.objects.filter(
            user=request.user,
            organization=organization
        ).exists():
            Membership.objects.create(
                user=request.user,
                organization=organization,
                role='admin'
            )
            membership_created = True
            logger.info(f"Added user {request.user.username} as admin to Acme Corporation")
        else:
            logger.info(f"User {request.user.username} already member of Acme Corporation")

        # Run import synchronously (it's fast enough) for better error handling and feedback
        logger.info(f"Starting demo data import for organization ID {organization.id}")
        try:
            # Capture stdout and stderr from management command
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()

            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                call_command(
                    'import_demo_data',
                    organization=str(organization.id),
                    user=request.user.username,
                    force=True  # Always force when importing from web UI
                )

            logger.info(f"✓ Demo data import completed successfully for organization ID {organization.id}")

            # Update session to automatically switch to Acme Corporation
            request.session['current_organization_id'] = organization.id
            request.session.modified = True

            action = 'created' if created else 'using existing'
            membership_msg = ' Added you as admin to the organization.' if membership_created else ''

            return JsonResponse({
                'success': True,
                'message': f'✓ Demo data imported successfully! {action.capitalize()} "Acme Corporation" organization.{membership_msg} Automatically switched to Acme Corporation - refresh the page to see: equipment catalog (22+ vendors), 5 documents, 3 diagrams, 10 assets, 5 passwords, and 5 workflows.',
                'organization_id': organization.id,
                'organization_name': organization.name,
                'auto_switched': True
            })

        except Exception as e:
            logger.error(f"✗ Demo data import FAILED for organization ID {organization.id}: {e}")
            import traceback
            logger.error(traceback.format_exc())

            return JsonResponse({
                'success': False,
                'message': f'Demo data import failed: {str(e)}. Check logs for details.',
                'error': str(e)
            })

    except Exception as e:
        # Catch-all exception handler for any unhandled errors
        logger.error(f"✗ CRITICAL ERROR in demo data import: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return JsonResponse({
            'success': False,
            'message': f'Critical error during demo data import: {str(e)}. Check server logs for details.',
            'error': str(e),
            'traceback': traceback.format_exc()
        })


@login_required
@user_passes_test(is_superuser)
def settings_sms(request):
    """SMS provider settings for sending navigation links and notifications."""
    settings_obj = SystemSetting.get_settings()

    if request.method == 'POST':
        # Update SMS settings
        settings_obj.sms_enabled = request.POST.get('sms_enabled') == 'on'
        settings_obj.sms_provider = request.POST.get('sms_provider', settings_obj.sms_provider)
        settings_obj.sms_account_sid = request.POST.get('sms_account_sid', settings_obj.sms_account_sid)
        settings_obj.sms_from_number = request.POST.get('sms_from_number', settings_obj.sms_from_number)

        # Only update auth token if provided
        sms_auth_token = request.POST.get('sms_auth_token', '').strip()
        if sms_auth_token:
            # Encrypt auth token before storing
            from vault.encryption import encrypt
            settings_obj.sms_auth_token = encrypt(sms_auth_token)

        settings_obj.updated_by = request.user
        settings_obj.save()

        messages.success(request, 'SMS settings updated successfully.')
        return redirect('core:settings_sms')

    return render(request, 'core/settings_sms.html', {
        'settings': settings_obj,
        'current_tab': 'sms',
    })


@login_required
@user_passes_test(is_superuser)
def vault_import(request):
    """
    Vault import page - wrapper for Bitwarden import in admin section.
    Delegates to vault.views.bitwarden_import.
    """
    from vault.views import bitwarden_import
    return bitwarden_import(request)


# ============================================================================
# API Key Validation Endpoints
# ============================================================================

@login_required
@user_passes_test(is_superuser)
@require_POST
def validate_anthropic_key(request):
    """Validate Anthropic API key via AJAX."""
    from django.http import JsonResponse
    from .services.api_key_validator import APIKeyValidator
    import json

    try:
        data = json.loads(request.body)
        api_key = data.get('api_key', '')

        success, message, details = APIKeyValidator.validate_anthropic(api_key)

        return JsonResponse({
            'success': success,
            'message': message,
            'details': details
        })

    except Exception as e:
        logger.error(f"Error validating Anthropic key: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Validation error: {str(e)}',
            'details': {}
        }, status=500)


@login_required
@user_passes_test(is_superuser)
@require_POST
def validate_google_maps_key(request):
    """Validate Google Maps API key via AJAX."""
    from django.http import JsonResponse
    from .services.api_key_validator import APIKeyValidator
    import json

    try:
        data = json.loads(request.body)
        api_key = data.get('api_key', '')

        success, message, details = APIKeyValidator.validate_google_maps(api_key)

        return JsonResponse({
            'success': success,
            'message': message,
            'details': details
        })

    except Exception as e:
        logger.error(f"Error validating Google Maps key: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Validation error: {str(e)}',
            'details': {}
        }, status=500)


@login_required
@user_passes_test(is_superuser)
@require_POST
def validate_twilio_credentials(request):
    """Validate Twilio credentials via AJAX."""
    from django.http import JsonResponse
    from .services.api_key_validator import APIKeyValidator
    import json

    try:
        data = json.loads(request.body)
        account_sid = data.get('account_sid', '')
        auth_token = data.get('auth_token', '')

        success, message, details = APIKeyValidator.validate_twilio(account_sid, auth_token)

        return JsonResponse({
            'success': success,
            'message': message,
            'details': details
        })

    except Exception as e:
        logger.error(f"Error validating Twilio credentials: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Validation error: {str(e)}',
            'details': {}
        }, status=500)


@login_required
@user_passes_test(is_superuser)
@require_POST
def validate_vonage_credentials(request):
    """Validate Vonage credentials via AJAX."""
    from django.http import JsonResponse
    from .services.api_key_validator import APIKeyValidator
    import json

    try:
        data = json.loads(request.body)
        api_key = data.get('api_key', '')
        api_secret = data.get('api_secret', '')

        success, message, details = APIKeyValidator.validate_vonage(api_key, api_secret)

        return JsonResponse({
            'success': success,
            'message': message,
            'details': details
        })

    except Exception as e:
        logger.error(f"Error validating Vonage credentials: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Validation error: {str(e)}',
            'details': {}
        }, status=500)
