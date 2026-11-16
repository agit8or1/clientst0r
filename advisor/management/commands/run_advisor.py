"""Run the Pricing Advisor detectors (scheduled task ``run_advisor``, nightly).

    manage.py run_advisor [--customer ID ...] [--today YYYY-MM-DD]

Idempotent: one open finding per customer + detector + period, updated in
place. Never changes contracts or prices.
"""
from datetime import date

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Compute per-customer profitability facts and run the Pricing Advisor detectors.'

    def add_arguments(self, parser):
        parser.add_argument('--customer', type=int, action='append', default=None,
                            help='Only this customer (organization id); repeatable.')
        parser.add_argument('--today', default=None, help='Evaluate as of this date (YYYY-MM-DD).')

    def handle(self, *args, **opts):
        from core.models import Organization
        from advisor.engine import run
        today = date.fromisoformat(opts['today']) if opts['today'] else None
        clients = None
        if opts['customer']:
            clients = Organization.objects.filter(pk__in=opts['customer'])
        result = run(today=today, clients=clients)
        self.stdout.write(f'Advisor: {result.customers} customer(s); {result.raised} raised, '
                          f'{result.updated} updated, {result.resolved} closed.')
        skipped = [v['label'] for v in result.coverage.values() if not v['evaluated']]
        if skipped:
            self.stdout.write('Not evaluated (missing data source): ' + ', '.join(skipped))
        if result.error:
            self.stderr.write(result.error)
