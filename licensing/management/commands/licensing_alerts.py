"""E-mail MSP staff about license renewals (30/60/90 days), unused licenses and
over-allocation. Each condition is sent once.

    python manage.py licensing_alerts [--dry-run]
"""
from django.core.management.base import BaseCommand

from licensing.alerts import send_alerts


class Command(BaseCommand):
    help = 'Send license renewal / utilization alerts.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Don't send or record anything.")

    def handle(self, *, dry_run=False, **kwargs):
        r = send_alerts(dry_run=dry_run)
        self.stdout.write(self.style.SUCCESS(
            f"License alerts: {r['alerts']} new condition(s) across {r['orgs']} customer(s), "
            f"{r['sent']} digest(s) {'would be ' if dry_run else ''}sent"))
