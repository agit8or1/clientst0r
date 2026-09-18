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
        reclaimed_count = 0

        for task in tasks:
            if task.should_run():
                # Captured before claim() overwrites them: a task that was
                # sitting at 'running' got here only by being stale, and the
                # operator wants to know that happened.
                was_stale = task.last_status == 'running'
                stale_since = task.last_run_at

                if not task.claim():
                    # Another scheduler process took it between our read and
                    # our write. Its run is the real one; ours would be a
                    # duplicate.
                    skipped_count += 1
                    self.stdout.write(
                        f"  Skipped: {task.get_task_type_display()} (claimed by another scheduler run)"
                    )
                    continue

                if was_stale:
                    since = stale_since.isoformat() if stale_since else "an unrecorded time"
                    self.stdout.write(self.style.WARNING(
                        f"  Reclaimed: {task.get_task_type_display()} was left 'running' "
                        f"since {since} by a process that did not finish"
                    ))
                    reclaimed_count += 1

                self.stdout.write(f"  Running: {task.get_task_type_display()}")
                try:
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

        summary = f"Scheduler completed: {ran_count} tasks run, {skipped_count} tasks skipped"
        if reclaimed_count:
            summary += f", {reclaimed_count} stale run(s) reclaimed"
        self.stdout.write(self.style.SUCCESS(summary))

    def run_task(self, task):
        """Execute the actual task based on its type.

        These methods let their exceptions out on purpose. Nine of them used
        to wrap the `call_command` in `try/except Exception` and write the
        failure to stdout, which meant `run_task` returned normally, `handle`
        called `task.mark_completed()` with no error, and the task recorded
        `last_status='success'`. A nightly job could fail every night while
        the Scheduled Tasks page showed a green tick for it; the only trace
        was a line in the systemd journal that nobody reads.

        The caller in `handle` already does the right thing with an exception
        — `mark_completed(error=...)` records `failed` and the message — so
        the guards were not adding protection, only hiding the outcome.

        A task that legitimately has nothing to do should return quietly, the
        way `run_asset_age_check` does when its feature is switched off. That
        is different from failing, and is still reported as success.
        """
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
        elif task.task_type == 'prune_monitor_checks':
            self.run_prune_monitor_checks()
        elif task.task_type == 'network_config_backup':
            self.run_network_config_backup()
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

    def run_website_monitoring(self):
        """Run website monitoring checks."""
        from django.core.management import call_command
        call_command('check_websites', verbosity=0)

    def run_prune_monitor_checks(self):
        """Phase 40.1 (v3.17.538): trim website check history to the retention
        window. Delegates to the management command so the in-app scheduler and
        a hand-run prune take exactly the same path."""
        from django.core.management import call_command
        call_command('prune_monitor_checks', verbosity=0)

    def run_network_config_backup(self):
        """Phase 34.2 (v3.17.545): collect device configs that are due.

        Only targets past their own cadence are touched, so scheduling this
        more often than daily costs nothing extra per device.
        """
        from django.core.management import call_command
        call_command('backup_network_configs', verbosity=0)

    def run_psa_sync(self):
        """Run PSA synchronization."""
        from django.core.management import call_command
        call_command('sync_psa', verbosity=0)

    def run_accounting_sync(self):
        """Phase 44.3 (v3.17.531): two-way accounting sync.

        Delegates to the management command so the systemd timer and the in-app
        scheduler run exactly the same code path.
        """
        from django.core.management import call_command
        call_command('accounting_sync', verbosity=0)

    def run_password_breach_scan(self):
        """Check all passwords against HaveIBeenPwned breach database."""
        from django.core.management import call_command
        call_command('check_password_breaches', verbosity=1)

    def run_equipment_catalog_update(self):
        """Update equipment catalog with new hardware releases."""
        from django.core.management import call_command
        call_command('update_equipment_catalog', verbosity=1)

    def run_ssl_expiry_check(self):
        """Email about SSL certificates that are expiring, or have expired."""
        from core.models import SystemSetting
        from monitoring.expiry_notifications import check_ssl_expiry

        counts = check_ssl_expiry(SystemSetting.get_settings(), log=self.stdout.write)
        self.stdout.write(
            f"    SSL expiry check: {counts['due']} within warning window, "
            f"{counts['notified']} notified, {counts['skipped']} already sent"
        )

    def run_domain_expiry_check(self):
        """Email about domain registrations that are expiring, or have expired."""
        from core.models import SystemSetting
        from monitoring.expiry_notifications import check_domain_expiry

        counts = check_domain_expiry(SystemSetting.get_settings(), log=self.stdout.write)
        self.stdout.write(
            f"    Domain expiry check: {counts['due']} within warning window, "
            f"{counts['notified']} notified, {counts['skipped']} already sent"
        )

    def run_vault_password_expiry(self):
        """Check for expiring vault passwords and send email notifications."""
        from vault.models import Password
        from core.models import SystemSetting
        from core.mailer import (
            brand_name, default_from_email, get_smtp_connection,
            notification_recipients, send_to_recipients, site_url,
        )
        from django.utils import timezone
        from datetime import timedelta

        settings = SystemSetting.get_settings()
        if not settings.notify_on_password_expiry:
            self.stdout.write('    Vault password expiry notifications disabled — skipping')
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

        connection = get_smtp_connection(settings)
        if connection is None:
            self.stdout.write('    SMTP not configured — skipping vault password expiry emails')
            return

        base_url = site_url(settings)
        from_email = default_from_email(settings)

        # Group passwords by organisation so we can notify org-specific admins
        from collections import defaultdict
        by_org = defaultdict(list)
        for pw in all_due:
            by_org[pw.organization_id].append(pw)

        notified_count = 0
        for org_id, passwords in by_org.items():
            recipients = notification_recipients(org_id)

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
                detail_url = f'{base_url}/vault/{pw.pk}/' if base_url else f'/vault/{pw.pk}/'
                lines.append(f'  • {pw.title} ({status}): {detail_url}')

            org_name = passwords[0].organization.name if passwords[0].organization else 'Global'
            subject = f'[{brand_name(settings)}] Vault password expiry alert — {org_name}'
            body = (
                f'The following vault password{"s" if len(passwords) > 1 else ""} '
                f'{"are" if len(passwords) > 1 else "is"} expiring or have expired:\n\n'
                + '\n'.join(lines)
                + f'\n\nLog in to review and update: {base_url}/vault/'
            )

            sent = send_to_recipients(connection, from_email, recipients, subject, body)

            if sent > 0:
                Password.objects.filter(pk__in=[p.pk for p in passwords]).update(expiry_notification_sent=True)
                notified_count += len(passwords)
                self.stdout.write(f'    Notified {sent} recipient(s) about {len(passwords)} password(s) for {org_name}')

        self.stdout.write(f'    Vault password expiry check complete — {notified_count} password(s) notified')

    def run_python_dep_scan(self):
        """Scan installed Python packages for known CVEs (pip-audit)."""
        from django.core.management import call_command
        call_command('scan_python_packages', '--save', verbosity=0)
        self.stdout.write('    Python dep scan complete')

    def run_system_warnings_digest(self):
        """Email superusers a digest of unresolved system warnings."""
        from core.models import SystemSetting, SystemWarningNotification
        from core.system_warnings import collect_system_warnings, severity_summary, worst_severity
        from core.mailer import (
            brand_name, default_from_email, get_smtp_connection,
            notification_recipients, send_to_recipients, site_url,
        )

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
        recipients = notification_recipients()
        if not recipients:
            self.stdout.write('    No superuser recipients — marking warnings as notified anyway')
            for w in new_warnings:
                SystemWarningNotification.objects.update_or_create(
                    warning_id=w['id'],
                    defaults={'severity': w['severity'], 'title': w['title'], 'recipients_count': 0},
                )
            return

        connection = get_smtp_connection(settings)
        if connection is None:
            self.stdout.write('    SMTP connection failed — skipping system warnings digest')
            return

        from_email = default_from_email(settings)
        base_url = site_url(settings)
        brand = brand_name(settings)
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
            url = (base_url + w['action_url']) if (base_url and w['action_url']) else w['action_url']
            body_lines.append(f'  • [{w["severity"].upper()}] {w["title"]}')
            body_lines.append(f'      {w["detail"]}')
            if url:
                body_lines.append(f'      → {url}')
            body_lines.append('')
        body_lines.append(f'Review all warnings: {base_url}/core/security/')
        body = '\n'.join(body_lines)

        sent_to = send_to_recipients(connection, from_email, recipients, subject, body)

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
        call_command('check_updates', verbosity=1)

    def run_cleanup_stuck_scans(self):
        """Cleanup stuck security scans (Snyk scans running > 2 hours)."""
        from django.core.management import call_command
        call_command('cleanup_stuck_scans', verbosity=1)

    def run_scheduling_alerts(self):
        """Send email/SMS alerts for upcoming and overdue scheduled tasks."""
        from django.core.management import call_command
        call_command('check_scheduled_task_alerts', verbosity=1)

    def run_security_scan(self):
        """Run automated security scan and alert superusers on findings."""
        from django.core.management import call_command
        call_command('run_security_scan', verbosity=1)

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
