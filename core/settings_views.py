"""
Admin Settings Views
Superuser-only views for managing system configuration.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import connection
from django.conf import settings as django_settings
from .models import SystemSetting, ScheduledTask
import platform
import sys
import os
import shutil
import psutil
import django
from datetime import datetime, timedelta


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def settings_general(request):
    """General system settings."""
    settings = SystemSetting.get_settings()

    if request.method == 'POST':
        # Update general settings
        settings.site_name = request.POST.get('site_name', settings.site_name)
        settings.site_url = request.POST.get('site_url', settings.site_url)
        settings.default_timezone = request.POST.get('default_timezone', settings.default_timezone)

        settings.updated_by = request.user
        settings.save()

        messages.success(request, 'General settings updated successfully.')
        return redirect('core:settings_general')

    # Timezone choices
    import pytz
    timezone_choices = [(tz, tz) for tz in pytz.common_timezones]

    return render(request, 'core/settings_general.html', {
        'settings': settings,
        'timezone_choices': timezone_choices,
        'current_tab': 'general',
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

    # Read current values from .env file
    env_path = Path('/home/administrator/.env')
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

    if request.method == 'POST':
        # Update .env file with new values
        anthropic_key = request.POST.get('anthropic_api_key', '').strip()
        claude_model = request.POST.get('claude_model', 'claude-sonnet-4-5-20250929')
        google_maps_key = request.POST.get('google_maps_api_key', '').strip()

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
        'current_tab': 'ai',
    })
