"""
Management command to run the task scheduler.
This command should be called every minute by systemd timer or cron.
It checks all scheduled tasks and runs them if they're due.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import ScheduledTask


class Command(BaseCommand):
    help = 'Run the task scheduler - checks and executes due scheduled tasks'

    def handle(self, *args, **options):
        self.stdout.write(f"[{timezone.now()}] Task Scheduler starting...")

        # Get all tasks that should run
        tasks = ScheduledTask.objects.all()
        ran_count = 0
        skipped_count = 0

        for task in tasks:
            if task.should_run():
                self.stdout.write(f"  Running: {task.get_task_type_display()}")
                try:
                    task.mark_started()
                    self.run_task(task)
                    task.mark_completed()
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Completed: {task.get_task_type_display()}"))
                    ran_count += 1
                except Exception as e:
                    task.mark_completed(error=str(e))
                    self.stdout.write(self.style.ERROR(f"  ✗ Failed: {task.get_task_type_display()} - {e}"))
            else:
                skipped_count += 1
                if not task.enabled:
                    reason = "disabled"
                elif task.last_status == 'running':
                    reason = "already running"
                elif task.next_run_at:
                    reason = f"not due until {task.next_run_at.strftime('%H:%M:%S')}"
                else:
                    reason = "unknown"
                self.stdout.write(f"  Skipped: {task.get_task_type_display()} ({reason})")

        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduler completed: {ran_count} tasks run, {skipped_count} tasks skipped"
            )
        )

    def run_task(self, task):
        """Execute the actual task based on its type."""
        if task.task_type == 'website_monitoring':
            self.run_website_monitoring()
        elif task.task_type == 'psa_sync':
            self.run_psa_sync()
        elif task.task_type == 'accounting_sync':
            self.run_accounting_sync()
        elif task.task_type == 'password_breach_scan':
            self.run_password_breach_scan()
        elif task.task_type == 'equipment_catalog_update':
            self.run_equipment_catalog_update()
        elif task.task_type == 'ssl_expiry_check':
            self.run_ssl_expiry_check()
        elif task.task_type == 'domain_expiry_check':
            self.run_domain_expiry_check()
        elif task.task_type == 'update_check':
            self.run_update_check()
        elif task.task_type == 'cleanup_stuck_scans':
            self.run_cleanup_stuck_scans()
        elif task.task_type == 'scheduling_alerts':
            self.run_scheduling_alerts()
        elif task.task_type == 'security_scan':
            self.run_security_scan()
        elif task.task_type == 'asset_age_check':
            self.run_asset_age_check()
        elif task.task_type == 'firmware_check':
            self.run_firmware_check()
        elif task.task_type == 'warranty_check':
            self.run_warranty_check()
        elif task.task_type == 'vault_password_expiry':
            self.run_vault_password_expiry()
        elif task.task_type == 'python_dep_scan':
            self.run_python_dep_scan()
        elif task.task_type == 'system_warnings_digest':
            self.run_system_warnings_digest()
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

    def run_website_monitoring(self):
        """Run website monitoring checks."""
        from django.core.management import call_command
        call_command('check_websites', verbosity=0)

    def run_psa_sync(self):
        """Run PSA synchronization."""
        from django.core.management import call_command
        try:
            call_command('sync_psa', verbosity=0)
        except Exception as e:
            # PSA sync might not be configured, that's okay
            self.stdout.write(f"    PSA sync not available: {e}")

    def run_accounting_sync(self):
        """Phase 44.3 (v3.17.530): two-way accounting sync.

        Delegates to the management command so the systemd timer and the in-app
        scheduler run exactly the same code path.
        """
        from django.core.management import call_command
        call_command('accounting_sync', verbosity=0)

    def run_password_breach_scan(self):
        """Check all passwords against HaveIBeenPwned breach database."""
        from django.core.management import call_command
        try:
            call_command('check_password_breaches', verbosity=1)
        except Exception as e:
            self.stdout.write(f"    Password breach scan failed: {e}")

    def run_equipment_catalog_update(self):
        """Update equipment catalog with new hardware releases."""
        from django.core.management import call_command
        try:
            call_command('update_equipment_catalog', verbosity=1)
        except Exception as e:
            self.stdout.write(f"    Equipment catalog update failed: {e}")

    def run_ssl_expiry_check(self):
        """Check for expiring SSL certificates and send notifications."""
        from monitoring.models import WebsiteMonitor
        from core.models import SystemSetting
        from django.utils import timezone
        from datetime import timedelta

        settings = SystemSetting.get_settings()
        if not settings.notify_on_ssl_expiry:
            return

        warning_days = settings.ssl_expiry_warning_days
        threshold = timezone.now() + timedelta(days=warning_days)

        expiring = WebsiteMonitor.objects.filter(
            ssl_enabled=True,
            ssl_expires_at__lte=threshold,
            ssl_expires_at__gte=timezone.now()
        )

        count = expiring.count()
        if count > 0:
            self.stdout.write(f"    Found {count} expiring SSL certificates")
            # TODO: Send email notifications
        else:
            self.stdout.write(f"    No expiring SSL certificates found")

    def run_domain_expiry_check(self):
        """Check for expiring domains and send notifications."""
        from monitoring.models import Expiration
        from core.models import SystemSetting
        from django.utils import timezone
        from datetime import timedelta

        settings = SystemSetting.get_settings()
        if not settings.notify_on_domain_expiry:
            return

        warning_days = settings.domain_expiry_warning_days
        threshold = timezone.now() + timedelta(days=warning_days)

        expiring = Expiration.objects.filter(
            expiration_type='domain',
            expires_at__lte=threshold,
            expires_at__gte=timezone.now()
        )

        count = expiring.count()
        if count > 0:
            self.stdout.write(f"    Found {count} expiring domains")
            # TODO: Send email notifications
        else:
            self.stdout.write(f"    No expiring domains found")

    def run_vault_password_expiry(self):
        """Check for expiring vault passwords and send email notifications."""
        from vault.models import Password
        from core.models import SystemSetting
        from django.utils import timezone
        from django.db import models
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.core.mail import send_mail, get_connection

        settings = SystemSetting.get_settings()
        if not settings.notify_on_password_expiry:
            self.stdout.write('    Vault password expiry notifications disabled — skipping')
            return

        if not settings.smtp_enabled or not settings.smtp_host:
            self.stdout.write('    SMTP not configured — skipping vault password expiry emails')
            return

        warning_days = settings.password_expiry_warning_days
        now = timezone.now()
        threshold = now + timedelta(days=warning_days)

        # Passwords expiring within the warning window (not yet notified)
        expiring = Password.objects.filter(
            expires_at__isnull=False,
            expires_at__gte=now,
            expires_at__lte=threshold,
            expiry_notification_sent=False,
        ).select_related('organization')

        # Passwords already expired but not yet notified
        expired = Password.objects.filter(
            expires_at__isnull=False,
            expires_at__lt=now,
            expiry_notification_sent=False,
        ).select_related('organization')

        all_due = list(expiring) + list(expired)

        if not all_due:
            self.stdout.write('    No vault passwords need expiry notifications')
            return

        self.stdout.write(f'    Found {len(all_due)} vault password(s) needing expiry notification')

        # Get SMTP connection
        try:
            from vault.encryption import decrypt
            smtp_password = decrypt(settings.smtp_password) if settings.smtp_password else ''
        except Exception:
            smtp_password = settings.smtp_password or ''

        try:
            connection = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=smtp_password,
                use_tls=settings.smtp_use_tls,
                use_ssl=settings.smtp_use_ssl,
                timeout=15,
            )
        except Exception as e:
            self.stdout.write(f'    SMTP connection failed: {e}')
            return

        User = get_user_model()
        site_url = (settings.site_url or '').rstrip('/')
        from_email = f'{settings.smtp_from_name} <{settings.smtp_from_email}>' if settings.smtp_from_email else settings.smtp_username

        # Group passwords by organisation so we can notify org-specific admins
        from collections import defaultdict
        by_org = defaultdict(list)
        for pw in all_due:
            by_org[pw.organization_id].append(pw)

        notified_count = 0
        for org_id, passwords in by_org.items():
            # Find recipients: superusers + org staff
            if org_id:
                recipients = list(
                    User.objects.filter(
                        is_active=True, email__gt='',
                    ).filter(
                        models.Q(is_superuser=True) | models.Q(organization_memberships__organization_id=org_id, organization_memberships__role__in=['admin', 'owner'])
                    ).values_list('email', flat=True).distinct()
                )
            else:
                recipients = list(
                    User.objects.filter(is_active=True, is_superuser=True, email__gt='').values_list('email', flat=True)
                )

            if not recipients:
                self.stdout.write(f'    No recipients for org {org_id} — marking as notified anyway')
                Password.objects.filter(pk__in=[p.pk for p in passwords]).update(expiry_notification_sent=True)
                continue

            # Build email body
            lines = []
            for pw in passwords:
                if pw.expires_at < now:
                    status = 'EXPIRED'
                else:
                    days = (pw.expires_at - now).days
                    status = f'expires in {days} day{"s" if days != 1 else ""}'
                detail_url = f'{site_url}/vault/{pw.pk}/' if site_url else f'/vault/{pw.pk}/'
                lines.append(f'  • {pw.title} ({status}): {detail_url}')

            org_name = passwords[0].organization.name if passwords[0].organization else 'Global'
            subject = f'[{settings.custom_company_name or settings.site_name or "Client St0r"}] Vault password expiry alert — {org_name}'
            body = (
                f'The following vault password{"s" if len(passwords) > 1 else ""} '
                f'{"are" if len(passwords) > 1 else "is"} expiring or have expired:\n\n'
                + '\n'.join(lines)
                + f'\n\nLog in to review and update: {site_url}/vault/'
            )

            sent = 0
            for email in recipients:
                try:
                    send_mail(
                        subject=subject,
                        message=body,
                        from_email=from_email,
                        recipient_list=[email],
                        connection=connection,
                        fail_silently=False,
                    )
                    sent += 1
                except Exception as e:
                    self.stdout.write(f'    Email to {email} failed: {e}')

            if sent > 0:
                Password.objects.filter(pk__in=[p.pk for p in passwords]).update(expiry_notification_sent=True)
                notified_count += len(passwords)
                self.stdout.write(f'    Notified {sent} recipient(s) about {len(passwords)} password(s) for {org_name}')

        self.stdout.write(f'    Vault password expiry check complete — {notified_count} password(s) notified')

    def run_python_dep_scan(self):
        """Scan installed Python packages for known CVEs (pip-audit)."""
        from django.core.management import call_command
        try:
            call_command('scan_python_packages', '--save', verbosity=0)
            self.stdout.write('    Python dep scan complete')
        except Exception as e:
            self.stdout.write(f"    Python dep scan failed: {e}")

    def run_system_warnings_digest(self):
        """Email superusers a digest of unresolved system warnings."""
        from core.models import SystemSetting, SystemWarningNotification
        from core.system_warnings import collect_system_warnings, severity_summary, worst_severity
        from django.contrib.auth import get_user_model
        from django.core.mail import send_mail, get_connection

        settings = SystemSetting.get_settings()
        if not settings.smtp_enabled or not settings.smtp_host:
            self.stdout.write('    SMTP not configured — skipping system warnings digest')
            return

        # Pull all warnings at info+ severity
        all_warnings = collect_system_warnings(min_severity='info')
        if not all_warnings:
            self.stdout.write('    No system warnings — nothing to send')
            return

        # Filter out warnings already notified (by stable warning_id)
        already_notified_ids = set(
            SystemWarningNotification.objects.values_list('warning_id', flat=True)
        )
        new_warnings = [w for w in all_warnings if w['id'] not in already_notified_ids]
        if not new_warnings:
            self.stdout.write(f'    All {len(all_warnings)} warning(s) already notified — nothing new')
            return

        # Recipients: active superusers with email
        User = get_user_model()
        recipients = list(
            User.objects.filter(is_active=True, is_superuser=True, email__gt='')
            .values_list('email', flat=True).distinct()
        )
        if not recipients:
            self.stdout.write('    No superuser recipients — marking warnings as notified anyway')
            for w in new_warnings:
                SystemWarningNotification.objects.update_or_create(
                    warning_id=w['id'],
                    defaults={'severity': w['severity'], 'title': w['title'], 'recipients_count': 0},
                )
            return

        try:
            from vault.encryption import decrypt
            smtp_password = decrypt(settings.smtp_password) if settings.smtp_password else ''
        except Exception:
            smtp_password = settings.smtp_password or ''

        try:
            connection = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=smtp_password,
                use_tls=settings.smtp_use_tls,
                use_ssl=settings.smtp_use_ssl,
                timeout=15,
            )
        except Exception as e:
            self.stdout.write(f'    SMTP connection failed: {e}')
            return

        from_email = (
            f'{settings.smtp_from_name} <{settings.smtp_from_email}>'
            if settings.smtp_from_email else settings.smtp_username
        )
        site_url = (settings.site_url or '').rstrip('/')
        brand = settings.custom_company_name or settings.site_name or 'Client St0r'
        worst = worst_severity(new_warnings) or 'info'
        summary = severity_summary(new_warnings)

        subject = f'[{brand}] System warnings digest — {len(new_warnings)} new ({worst})'

        body_lines = [
            f'New system warnings detected on {brand}.',
            '',
            f'Summary: {summary["critical"]} critical, {summary["high"]} high, '
            f'{summary["medium"]} medium, {summary["low"]} low, {summary["info"]} info.',
            '',
            'Warnings:',
        ]
        for w in new_warnings:
            url = (site_url + w['action_url']) if (site_url and w['action_url']) else w['action_url']
            body_lines.append(f'  • [{w["severity"].upper()}] {w["title"]}')
            body_lines.append(f'      {w["detail"]}')
            if url:
                body_lines.append(f'      → {url}')
            body_lines.append('')
        body_lines.append(f'Review all warnings: {site_url}/core/security/')
        body = '\n'.join(body_lines)

        sent_to = 0
        for email in recipients:
            try:
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=from_email,
                    recipient_list=[email],
                    connection=connection,
                    fail_silently=False,
                )
                sent_to += 1
            except Exception as e:
                self.stdout.write(f'    Email to {email} failed: {e}')

        if sent_to > 0:
            for w in new_warnings:
                SystemWarningNotification.objects.update_or_create(
                    warning_id=w['id'],
                    defaults={
                        'severity': w['severity'],
                        'title': w['title'][:500],
                        'recipients_count': sent_to,
                    },
                )
            self.stdout.write(
                f'    System warnings digest sent to {sent_to} recipient(s) '
                f'covering {len(new_warnings)} new warning(s)'
            )
        else:
            self.stdout.write('    Digest not delivered — no recipients accepted the message')

    def run_update_check(self):
        """Check for system updates from GitHub."""
        from django.core.management import call_command
        try:
            call_command('check_updates', verbosity=1)
        except Exception as e:
            self.stdout.write(f"    Update check failed: {e}")

    def run_cleanup_stuck_scans(self):
        """Cleanup stuck security scans (Snyk scans running > 2 hours)."""
        from django.core.management import call_command
        try:
            call_command('cleanup_stuck_scans', verbosity=1)
        except Exception as e:
            self.stdout.write(f"    Cleanup stuck scans failed: {e}")

    def run_scheduling_alerts(self):
        """Send email/SMS alerts for upcoming and overdue scheduled tasks."""
        from django.core.management import call_command
        try:
            call_command('check_scheduled_task_alerts', verbosity=1)
        except Exception as e:
            self.stdout.write(f"    Scheduling alerts failed: {e}")

    def run_security_scan(self):
        """Run automated security scan and alert superusers on findings."""
        from django.core.management import call_command
        try:
            call_command('run_security_scan', verbosity=1)
        except Exception as e:
            self.stdout.write(f"    Security scan failed: {e}")

    def run_asset_age_check(self):
        """Evaluate asset age warnings against configured thresholds."""
        from core.models import SystemSetting
        settings = SystemSetting.get_settings()
        if not settings.asset_age_warnings_enabled:
            self.stdout.write("    Asset age warnings disabled — skipping")
            return
        from assets.health import AssetAgeService
        counts = AssetAgeService(settings).check_all()
        self.stdout.write(f"    Asset age check: {counts['warning']} warning, {counts['critical']} critical")

    def run_firmware_check(self):
        """Check for firmware updates on network devices."""
        from core.models import SystemSetting
        settings = SystemSetting.get_settings()
        if not settings.firmware_checks_enabled:
            self.stdout.write("    Firmware checks disabled — skipping")
            return
        from assets.health import FirmwareCheckService
        updated = FirmwareCheckService(settings).check_all()
        self.stdout.write(f"    Firmware check: {updated} assets updated")

    def run_warranty_check(self):
        """Check warranty expiry for PCs and servers via vendor APIs."""
        from core.models import SystemSetting
        settings = SystemSetting.get_settings()
        if not settings.warranty_checks_enabled:
            self.stdout.write("    Warranty checks disabled — skipping")
            return
        from assets.health import WarrantyCheckService
        updated = WarrantyCheckService(settings).check_all()
        self.stdout.write(f"    Warranty check: {updated} assets updated")
