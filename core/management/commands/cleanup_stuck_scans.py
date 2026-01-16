"""
Management command to cleanup stuck Snyk scans.

This command finds scans that have been in 'pending' or 'running' state for too long
and marks them as 'timeout'.

Usage:
    python manage.py cleanup_stuck_scans
    python manage.py cleanup_stuck_scans --timeout-hours 4
"""
from django.core.management.base import BaseCommand
from core.models import SnykScan


class Command(BaseCommand):
    help = 'Cleanup stuck Snyk scans (mark as timeout)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--timeout-hours',
            type=int,
            default=2,
            help='Hours after which a scan is considered stuck (default: 2)'
        )

    def handle(self, *args, **options):
        timeout_hours = options['timeout_hours']

        self.stdout.write(
            self.style.WARNING(
                f'Checking for stuck scans (timeout: {timeout_hours} hours)...'
            )
        )

        # Find stuck scans before cleanup (for reporting)
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        timeout_threshold = now - timedelta(hours=timeout_hours)

        stuck_scans = SnykScan.objects.filter(
            status__in=['pending', 'running'],
            started_at__lt=timeout_threshold
        )

        if not stuck_scans.exists():
            self.stdout.write(
                self.style.SUCCESS('No stuck scans found.')
            )
            return

        # List stuck scans
        self.stdout.write(
            self.style.WARNING(f'\nFound {stuck_scans.count()} stuck scan(s):')
        )
        for scan in stuck_scans:
            age_hours = (now - scan.started_at).total_seconds() / 3600
            self.stdout.write(
                f'  - {scan.scan_id}: {scan.status} for {age_hours:.1f} hours'
            )

        # Cleanup
        count = SnykScan.cleanup_stuck_scans(timeout_hours=timeout_hours)

        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Successfully marked {count} stuck scan(s) as timed out'
            )
        )
