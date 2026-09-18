"""
Phase 15 v1 (v3.17.291): cron-driven generator for recurring invoices.

For each active Contract whose `billing_frequency != 'none'` and whose
`next_billing_date <= today`, creates a draft Invoice for the period
and advances `next_billing_date` by one cycle. Idempotent — already-
billed periods don't get re-billed because the cron advances the date.

Wire to a daily systemd timer.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction, models
from django.utils import timezone

from psa.models import Contract


class _NothingToBill(Exception):
    """Internal: unwinds the transaction when there is nothing to bill."""


class Command(BaseCommand):
    help = 'Spawn draft Invoices from Contracts on their billing cadence.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--max-per-contract', type=int, default=12,
                            help='Cap catch-up cycles per contract (default 12).')

    def handle(self, *args, **options):
        dry = options['dry_run']
        cap = options['max_per_contract']
        today = date.today()

        # Phase 15 v11 (v3.17.299): respect SystemSetting auto-push flag.
        try:
            from core.models import SystemSetting as _SS
            ss = _SS.get_settings()
            auto_push = bool(getattr(ss, 'psa_auto_push_recurring_invoices', False))
        except Exception:
            auto_push = False

        # Phase 15 v13: skip paused contracts (paused_at non-null)
        #
        # v3.17.581 — and skip contracts whose end_date has passed. This used
        # to filter on `status` alone, and nothing set a contract to expired:
        # `psa_auto_renew_contracts` only handles auto_renew=True, and
        # `psa_advance_subscription_lifecycle` only cancels contracts flagged
        # cancel_at_period_end. So a client who simply did not renew went on
        # being invoiced every month, indefinitely, while `Contract.for_ticket`
        # — which has always respected end_date — had already stopped treating
        # them as covered.
        #
        # `psa_advance_subscription_lifecycle` now expires them properly, but
        # this filter is the safety net: it holds even on an install where
        # that cron has never run.
        qs = Contract.objects.filter(
            status='active',
            next_billing_date__lte=today,
            paused_at__isnull=True,
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        ).exclude(billing_frequency='none')

        spawned = 0
        for contract in qs:
            cycles = 0
            while (contract.next_billing_date
                   and contract.next_billing_date <= today
                   and cycles < cap):
                if dry:
                    self.stdout.write(
                        f'[dry] would invoice {contract.name} for '
                        f'period {contract.next_billing_date}'
                    )
                    nxt = Contract._advance_billing(contract.next_billing_date,
                                                     contract.billing_frequency)
                    contract.next_billing_date = nxt
                else:
                    period = contract.next_billing_date
                    # v3.17.564 — the invoice and the cursor advance commit
                    # together or not at all. They used to be separate writes,
                    # and anything that interrupted the run between them left
                    # the invoice committed with the cursor unmoved, so the
                    # next daily run billed the same period again.
                    try:
                        with transaction.atomic():
                            inv = contract.generate_invoice(on_date=period)
                            if inv is None:
                                # Disabled or zero-amount; bail out of this
                                # contract. Raise so the transaction unwinds
                                # cleanly rather than committing a half-step.
                                raise _NothingToBill()
                            nxt = Contract._advance_billing(
                                period, contract.billing_frequency)
                            contract.last_billed_at = today
                            contract.next_billing_date = nxt
                            contract.save(update_fields=[
                                'last_billed_at', 'next_billing_date',
                                'updated_at',
                            ])
                    except _NothingToBill:
                        break
                    except IntegrityError:
                        # The uniqueness constraint caught a period already
                        # billed — a concurrent run, or a retry after one.
                        # Move the cursor past it rather than looping forever.
                        self.stdout.write(self.style.WARNING(
                            f'{contract.name}: period {period} is already '
                            f'invoiced; advancing without re-billing.'))
                        contract.next_billing_date = Contract._advance_billing(
                            period, contract.billing_frequency)
                        contract.save(update_fields=['next_billing_date',
                                                     'updated_at'])
                        cycles += 1
                        continue

                    spawned += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'Generated {inv.invoice_number} for '
                        f'{contract.name} (period {period})'
                    ))
                    # Phase 15 v11: optional auto-push to accounting.
                    # Deliberately outside the transaction: pushing to an
                    # external accounting system is not something a rollback
                    # can undo, so it must not be able to roll back the
                    # invoice either.
                    if auto_push:
                        try:
                            self._auto_push(inv)
                        except Exception as exc:
                            self.stdout.write(self.style.WARNING(
                                f'auto-push failed for {inv.invoice_number}: {exc}'))
                cycles += 1

        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}Processed {qs.count()} contract(s); '
            f'{spawned} invoice(s) generated.'
        ))

    def _auto_push(self, invoice):
        """Phase 15 v11 (v3.17.299): push a freshly-generated invoice
        to the org's configured sync-enabled AccountingConnection.
        Failures are logged but don't fail the cron — review the
        accounting reconciliation report for stragglers.
        """
        from integrations.models import AccountingConnection
        from integrations.providers.accounting import get_accounting_provider
        # Pinned connection wins, else first sync-enabled on the org
        conn = invoice.target_connection
        if conn is None or not (conn.is_active and conn.sync_enabled):
            conn = AccountingConnection.objects.filter(
                organization=invoice.organization,
                is_active=True, sync_enabled=True,
            ).first()
        if conn is None:
            self.stdout.write(self.style.WARNING(
                f'  no sync-enabled connection for {invoice.organization.name}; '
                f'invoice {invoice.invoice_number} stays draft'))
            return
        provider = get_accounting_provider(conn)
        if provider is None:
            return
        result = provider.push_invoice(invoice)
        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f'  pushed {invoice.invoice_number} → {conn.provider_type} '
                f'({result.get("invoice_id")})'))
        else:
            self.stdout.write(self.style.WARNING(
                f'  push failed for {invoice.invoice_number}: {result.get("error")}'))
