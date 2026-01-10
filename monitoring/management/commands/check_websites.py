"""
Django management command to check all website monitors
Usage: python manage.py check_websites [--force] [--all]
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from monitoring.models import WebsiteMonitor


class Command(BaseCommand):
    help = 'Check enabled website monitors (respects check intervals unless --force or --all)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force check all enabled monitors regardless of check interval',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Check all enabled monitors (same as --force)',
        )

    def handle(self, *args, **options):
        force = options.get('force', False) or options.get('all', False)

        # Get all enabled monitors
        monitors = WebsiteMonitor.objects.filter(is_enabled=True)

        if monitors.count() == 0:
            self.stdout.write(self.style.WARNING("No enabled website monitors found"))
            return

        self.stdout.write(f"Found {monitors.count()} enabled website monitor(s)")

        checked_count = 0
        skipped_count = 0

        for monitor in monitors:
            # Check if it's time to check this monitor
            if not force and monitor.last_checked_at:
                minutes_since_check = (timezone.now() - monitor.last_checked_at).total_seconds() / 60
                if minutes_since_check < monitor.check_interval_minutes:
                    skipped_count += 1
                    continue

            self.stdout.write(f"\nChecking: {monitor.name}")
            self.stdout.write(f"  URL: {monitor.url}")

            # Use the model's built-in check_status method
            try:
                monitor.check_status()

                # Display results
                status_color = self.style.SUCCESS if monitor.status == 'active' else self.style.WARNING if monitor.status == 'warning' else self.style.ERROR
                self.stdout.write(status_color(f"  Status: {monitor.status.upper()}"))

                if monitor.last_status_code:
                    self.stdout.write(f"  HTTP: {monitor.last_status_code}")

                if monitor.last_response_time_ms:
                    self.stdout.write(f"  Response Time: {monitor.last_response_time_ms}ms")

                if monitor.ssl_enabled and monitor.ssl_expires_at:
                    days_until = (monitor.ssl_expires_at - timezone.now()).days
                    ssl_status = self.style.WARNING if monitor.is_ssl_expiring_soon else self.style.SUCCESS
                    self.stdout.write(ssl_status(f"  SSL: Expires in {days_until} days ({monitor.ssl_subject})"))

                if monitor.last_error:
                    self.stdout.write(self.style.WARNING(f"  Error: {monitor.last_error}"))

                checked_count += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Failed to check: {str(e)}"))

        # Summary
        self.stdout.write("\n" + "="*50)
        self.stdout.write(self.style.SUCCESS(f"Checked: {checked_count} monitor(s)"))
        if skipped_count > 0:
            self.stdout.write(f"Skipped: {skipped_count} (not due for check)")
        self.stdout.write("="*50)
