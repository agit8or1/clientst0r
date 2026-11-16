"""Charge due invoices for customers who authorized autopay.

Run by the scheduler (ScheduledTask 'run_autopay', hourly). Safe to run as
often as you like: one attempt per invoice per due cycle and attempt number
(payments.autopay).
"""
from django.core.management.base import BaseCommand

from payments import autopay


class Command(BaseCommand):
    help = 'Charge due invoices against authorized default payment methods (autopay).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Count what would be charged.')

    def handle(self, *args, **options):
        summary = autopay.run(dry_run=options['dry_run'])
        self.stdout.write('autopay: ' + ', '.join(f'{k}={v}' for k, v in summary.items()))
