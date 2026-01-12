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
        elif task.task_type == 'password_breach_scan':
            self.run_password_breach_scan()
        elif task.task_type == 'equipment_catalog_update':
            self.run_equipment_catalog_update()
        elif task.task_type == 'ssl_expiry_check':
            self.run_ssl_expiry_check()
        elif task.task_type == 'domain_expiry_check':
            self.run_domain_expiry_check()
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
