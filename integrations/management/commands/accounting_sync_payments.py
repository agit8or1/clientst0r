"""
Phase 27 v8 (v3.17.280): pull payment status back from QBO/Xero.

For every Invoice with `accounting_external_id` set and a non-zero local
balance, query the provider's current Balance / AmountDue. When provider
says paid (balance=0) and we still show outstanding, create a Payment row
to close the local invoice. Idempotent — already-paid invoices are
skipped.

SUPERSEDED (v3.17.530) by `accounting_sync`, which reads real provider payment
records instead of inferring payment from a zero balance, and which IS wired to a
timer. This command is kept working for anyone who scripted it, but it cannot see
partial payments and never could.

NOT SCHEDULED. v3.17.280 left this line reading "wire to a daily systemd
timer alongside the existing accounting jobs" as a to-do, nobody wired it, and
docs/ROADMAP.md then described the timer as shipped. There is no unit in
deploy/, no crontab entry and no `run_scheduler` task type for this command —
it only ever runs when a human types it. Corrected in v3.17.526; scheduling is
tracked as Phase 44 (GitHub #145) along with the rest of two-way sync.

Also note what this does and does not do: it polls Balance and infers payment.
It does not read provider Payment objects, so a partial payment is invisible
(non-zero balance is skipped) and the Payment row it writes carries today's
date and method 'other' rather than the real ones.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import F, Q

from integrations.models import AccountingConnection
from integrations.providers.accounting import get_accounting_provider
from integrations.providers.accounting.base import log_accounting_call
from psa.models import Invoice, Payment


class Command(BaseCommand):
    help = 'Sync payment status from QBO/Xero — close local invoices that the provider already shows as paid.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--connection-id', type=int, default=None,
                            help='Limit to one AccountingConnection by pk.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        conn_filter = options.get('connection_id')

        conn_qs = AccountingConnection.objects.filter(is_active=True)
        if conn_filter:
            conn_qs = conn_qs.filter(pk=conn_filter)

        total_synced = 0
        for conn in conn_qs:
            provider = get_accounting_provider(conn)
            if provider is None:
                self.stdout.write(self.style.WARNING(
                    f'No provider class for {conn.name}; skipping'))
                continue

            # Outstanding pushed invoices on this org
            invs = (Invoice.objects
                    .filter(organization=conn.organization,
                            pushed_to_accounting_at__isnull=False,
                            accounting_external_id__gt='')
                    .filter(~Q(status='paid') & ~Q(status='void')
                            & Q(amount_paid__lt=F('total'))))
            for inv in invs:
                try:
                    res = provider.poll_invoice_balance(inv)
                except NotImplementedError:
                    self.stdout.write(self.style.WARNING(
                        f'{conn.get_provider_type_display()} adapter has no '
                        f'poll_invoice_balance — skipping'))
                    break
                except Exception as exc:
                    log_accounting_call(
                        connection=conn, action='poll_balance',
                        resource_type='invoice', resource_id=inv.pk,
                        success=False, error_message=str(exc),
                    )
                    continue
                if not res.get('success'):
                    log_accounting_call(
                        connection=conn, action='poll_balance',
                        resource_type='invoice', resource_id=inv.pk,
                        success=False,
                        error_message=res.get('error') or 'unknown',
                    )
                    continue
                balance = res.get('balance')
                if balance is None or balance > 0:
                    # Still owed there too — nothing to sync.
                    continue

                # Provider says paid. Local total - amount_paid is the
                # outstanding balance; record one Payment to close it.
                from decimal import Decimal as _D
                local_outstanding = _D(str(inv.total)) - _D(str(inv.amount_paid))
                if local_outstanding <= 0:
                    continue
                if dry:
                    self.stdout.write(
                        f'[dry] would record {local_outstanding} on '
                        f'{inv.invoice_number} (provider says paid)'
                    )
                else:
                    Payment.objects.create(
                        invoice=inv,
                        amount=local_outstanding,
                        paid_on=date.today(),
                        method='other',
                        reference=f'auto-sync from {conn.provider_type}',
                        notes='Synced by accounting_sync_payments — provider '
                              'showed Balance=0 while local copy still had a '
                              'balance. Amount and date are inferred, not read '
                              'from the provider payment record.',
                    )
                    log_accounting_call(
                        connection=conn, action='poll_balance',
                        resource_type='invoice', resource_id=inv.pk,
                        external_id=inv.accounting_external_id,
                        success=True,
                        request_summary=f'invoice={inv.invoice_number}',
                        response_summary=f'closed local: {local_outstanding}',
                    )
                    total_synced += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'Closed {inv.invoice_number} ({local_outstanding}) '
                        f'from {conn.provider_type}'
                    ))

        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}{total_synced} invoice(s) synced.'
        ))
