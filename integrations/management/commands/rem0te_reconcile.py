"""Run Rem0te reconciliation now (integrations/rem0te/reconcile.py): the
capabilities re-check when due, missed alert events, ticket link retries and
open action proposals, for every active Rem0te connection. The scheduler
already does this every minute (task poll_analysis_jobs); this is the manual
equivalent. --check forces the capabilities check."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Reconcile every active Rem0te connection now.'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true', help='re-check capabilities even when not due')

    def handle(self, *args, **opts):
        from integrations.models import RMMConnection
        from integrations.rem0te import health
        from integrations.rem0te.reconcile import reconcile
        for conn in RMMConnection.objects.filter(is_active=True, provider_type='rem0te').order_by('pk'):
            r = reconcile(conn, force_check=opts['check'])
            st = health.evaluate(conn)
            self.stdout.write(f'{conn.name}: {st["label"]}; {r["events"]} event(s), {r["proposals"]} proposal(s)'
                              + (f'; {st["reasons"][0]["message"]}' if st['reasons'] else ''))
