"""
Phase 44.3 (v3.17.531): the accounting sync job that actually gets scheduled.

Supersedes `accounting_sync_payments`, which inferred payment from an invoice
balance and — despite calling itself a cron in its own docstring — was never
wired to anything. This one runs customers, payments and invoice state in one
pass and is driven by a systemd timer (deploy/clientst0r-accounting-sync.timer)
or by the in-app scheduler.

Usage:
    manage.py accounting_sync [--connection ID] [--dry-run] [--since-hours N]
                              [--skip-customers] [--skip-payments] [--skip-invoices]
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from integrations.models import AccountingConnection
from integrations.providers.accounting import get_accounting_provider
from integrations.services.accounting_sync import sync_invoice_state, sync_payments


class Command(BaseCommand):
    help = 'Two-way sync with the configured accounting systems (Phase 44).'

    def add_arguments(self, parser):
        parser.add_argument('--connection', type=int, default=None,
                            help='Sync only this AccountingConnection id.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')
        parser.add_argument('--since-hours', type=int, default=48,
                            help='Look back this many hours for provider '
                                 'payment changes (default 48; the overlap is '
                                 'deliberate — the sync is idempotent, and a '
                                 'missed window loses payments).')
        parser.add_argument('--skip-customers', action='store_true')
        parser.add_argument('--skip-payments', action='store_true')
        parser.add_argument('--skip-invoices', action='store_true')

    def handle(self, *args, **options):
        connections = AccountingConnection.objects.filter(
            is_active=True, sync_enabled=True)
        if options['connection']:
            connections = connections.filter(pk=options['connection'])

        if not connections.exists():
            self.stdout.write(self.style.WARNING(
                'No active, sync-enabled accounting connections.'))
            return

        since = timezone.now() - timedelta(hours=max(1, options['since_hours']))
        dry_run = options['dry_run']
        total_errors = 0

        for connection in connections:
            provider = get_accounting_provider(connection)
            if provider is None:
                self.stderr.write(
                    f'{connection.name}: provider class not registered')
                total_errors += 1
                continue

            self.stdout.write(f'--- {connection.name} '
                              f'({connection.provider_type}) ---')
            errors = []

            if not options['skip_customers']:
                errors += self._run(
                    connection, 'customers',
                    lambda: provider.pull_customers(), dry_run)

            if not options['skip_payments']:
                errors += self._run(
                    connection, 'payments',
                    lambda: sync_payments(connection, provider, since=since,
                                          dry_run=dry_run), dry_run)

            if not options['skip_invoices']:
                errors += self._run(
                    connection, 'invoices',
                    lambda: sync_invoice_state(connection, provider,
                                               dry_run=dry_run), dry_run)

            # v3.17.531: these three fields have existed since the model was
            # created and were never written, so the connections page rendered
            # "Never" no matter how often the sync ran.
            connection.last_sync_at = timezone.now()
            connection.last_sync_status = 'error' if errors else 'ok'
            connection.last_error = '; '.join(errors)[:2000]
            connection.save(update_fields=['last_sync_at', 'last_sync_status',
                                           'last_error', 'updated_at'])
            total_errors += len(errors)

        if total_errors:
            self.stdout.write(self.style.WARNING(
                f'Finished with {total_errors} error(s).'))
        else:
            self.stdout.write(self.style.SUCCESS('Finished cleanly.'))

    def _run(self, connection, label, fn, dry_run):
        """Run one stage, returning its errors rather than raising.

        One stage failing must not abandon the others: a customer-pull outage
        should not also stop payments being imported.
        """
        prefix = '[dry-run] ' if dry_run else ''
        try:
            result = fn()
        except Exception as exc:
            self.stderr.write(f'  {label}: {exc}')
            return [f'{label}: {exc}']

        if hasattr(result, 'summary'):
            errors = list(result.errors)
            self.stdout.write(f'  {prefix}{label}: {result.summary()}')
        else:
            errors = [] if result.get('success') else [
                f"{label}: {result.get('error')}"]
            self.stdout.write(
                f"  {prefix}{label}: linked={result.get('linked', 0)} "
                f"unmatched={len(result.get('unmatched') or [])}")
        for err in errors:
            self.stderr.write(f'  {label}: {err}')
        return errors
