"""
Run every 5 minutes via cron. For each active SecurityVendorConnection
whose poll_interval has elapsed, look up the matching SecurityProvider
adapter and run sync().
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Poll all active security-vendor connections for new alerts.'

    def add_arguments(self, parser):
        parser.add_argument('--connection-id', type=int)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from security_alerts.models import SecurityVendorConnection

        qs = SecurityVendorConnection.objects.filter(is_active=True, sync_enabled=True)
        if opts['connection_id']:
            qs = qs.filter(pk=opts['connection_id'])

        now = timezone.now()
        ran = 0
        for conn in qs:
            # Skip if last_sync_at is recent enough
            if conn.last_sync_at:
                next_due = conn.last_sync_at + timedelta(minutes=conn.poll_interval_minutes)
                if next_due > now:
                    continue
            # Only a working API adapter polls; a stub (supports_polling =
            # False) is skipped so its connection never shows a false "OK".
            from security_alerts.capabilities import api_adapter
            adapter = api_adapter(conn.provider)
            if not adapter:
                self.stdout.write(f'  [skip] No API integration for {conn.provider}; webhook only')
                continue
            self.stdout.write(f'  Polling {conn.name}...')
            if opts['dry_run']:
                continue
            result = adapter.sync(conn)
            self.stdout.write(f'    -> {result}')
            ran += 1

        self.stdout.write(self.style.SUCCESS(f'Polled {ran} connection{"s" if ran != 1 else ""}.'))
