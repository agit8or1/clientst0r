"""
Phase 15 v1 (v3.17.291): cron-driven generator for recurring invoices.

For each active Contract whose `billing_frequency != 'none'` and whose
`next_billing_date <= today`, creates a draft Invoice for the period
and advances `next_billing_date` by one cycle. Idempotent — already-
billed periods don't get re-billed because the cron advances the date.

Scheduling (v3.17.599): run daily by the in-app scheduler (task type
`psa_generate_recurring_invoices`, Settings > Scheduler) with `--no-catch-up`.

Catch-up, and why the scheduler turns it off
--------------------------------------------
By default a contract whose `next_billing_date` is several periods in the past
is billed for every missed period in one run, oldest first, up to
`--max-per-contract` (12) invoices — the loop below invoices a period, advances
the cursor one cycle, and goes round again while the cursor is still <= today.

That is what an operator running this by hand after an outage wants. It is not
what a scheduler should do on its own: this job was never scheduled on most
installs until v3.17.599, so a contract can be a year behind, and switching the
schedule on would have raised a year of invoices overnight with nobody asking.

`--no-catch-up` (what the scheduler passes) bills only a contract that is in
its current period — `next_billing_date <= today` but one cycle later is in
the future — and bills it once. A contract more than one period behind is not
invoiced at all. It is logged, and the run ends with a CommandError naming
every such contract, so the scheduled task shows `failed` with the list in its
last error until someone decides: move the contract's next billing date to
the current period (skip the missed periods), or run this command by hand
without the flag to bill them.

Contracts flagged cancel-at-period-end are never billed, with or without the
flag (v3.17.600; before that only the scheduled path skipped them): their next
billing date is the end of the period the client has paid for, and
`psa_advance_subscription_lifecycle` cancels them on that date.
"""
from __future__ import annotations

import logging
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction, models
from django.utils import timezone

from psa.models import Contract

logger = logging.getLogger(__name__)

# How many skipped contracts to name in the CommandError (and so in the
# scheduled task's last_error); the full list always goes to the log.
_REPORT_LIMIT = 20


class _NothingToBill(Exception):
    """Internal: unwinds the transaction when there is nothing to bill."""


class Command(BaseCommand):
    help = 'Spawn draft Invoices from Contracts on their billing cadence.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--max-per-contract', type=int, default=12,
                            help='Cap catch-up cycles per contract (default 12).')
        parser.add_argument(
            '--no-catch-up', action='store_true',
            help='Bill only contracts in their current billing period, once. '
                 'A contract more than one period behind is skipped, never '
                 'back-billed, and reported: the command exits with an error '
                 'naming each one. The in-app scheduler always passes this.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        cap = options['max_per_contract']
        no_catch_up = options['no_catch_up']
        if no_catch_up:
            cap = 1
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
        # The next billing date of a cancel-at-period-end contract is the end
        # of its paid-up period: bill nothing, let the lifecycle job cancel
        # it. v3.17.600 — on every path. This used to apply only under
        # --no-catch-up, so a manual run billed the next period anyway and
        # advanced the cursor, and because the lifecycle job keys off that
        # cursor the contract was never cancelled.
        qs = qs.exclude(cancel_at_period_end=True)

        spawned = 0
        behind = []  # (contract, periods due) skipped under --no-catch-up
        held = []  # invoices not auto-pushed because approval is pending
        for contract in qs:
            if no_catch_up:
                due = self._periods_due(contract, today)
                if due > 1:
                    behind.append((contract, due))
                    logger.warning(
                        'Recurring invoices: skipped contract %s (%s, org %s): '
                        'next billing date %s leaves %d periods due (%d missed); '
                        'not back-billed.',
                        contract.pk, contract.name, contract.organization_id,
                        contract.next_billing_date, due, due - 1)
                    self.stdout.write(self.style.WARNING(
                        f'Skipped {contract.name}: next billing date '
                        f'{contract.next_billing_date} leaves {due} periods due '
                        f'({due - 1} missed; --no-catch-up); not back-billed.'))
                    continue
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
                        # The approval gate applies here exactly as it does
                        # to the manual push button: an invoice the
                        # thresholds flagged stays local until approved.
                        # Re-read: the flag is written by a post_save signal.
                        inv.refresh_from_db()
                        if inv.requires_approval:
                            held.append(inv)
                            logger.warning(
                                'Recurring invoices: %s not auto-pushed; '
                                'approval required (%s).',
                                inv.invoice_number, inv.approval_reason)
                            self.stdout.write(self.style.WARNING(
                                f'  {inv.invoice_number} requires approval '
                                f'({inv.approval_reason or "no reason given"}); '
                                f'not pushed to accounting.'))
                        else:
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
        if held:
            self.stdout.write(self.style.WARNING(
                f'{len(held)} invoice(s) held for approval and not pushed to '
                f'accounting: ' + ', '.join(i.invoice_number for i in held)
                + '. Approve each, then push it from the invoice page.'))

        if behind and dry:
            self.stdout.write(self.style.WARNING(
                '[dry] ' + self._behind_message(behind, spawned)))
        elif behind:
            # Raised after every up-to-date contract has been billed (each in
            # its own transaction above), so the current period still goes
            # out. The error is what makes the skip visible: the scheduler
            # records it as the task's last_error.
            raise CommandError(self._behind_message(behind, spawned))

    @staticmethod
    def _periods_due(contract, today, limit=1000):
        """Billing periods due by today: 1 for a contract in its current
        period, more when whole periods have been missed."""
        due = 0
        nxt = contract.next_billing_date
        while nxt is not None and nxt <= today and due < limit:
            due += 1
            nxt = Contract._advance_billing(nxt, contract.billing_frequency)
        return due

    @staticmethod
    def _behind_message(behind, spawned):
        names = '; '.join(
            f'{c.name} (#{c.pk}, next billing {c.next_billing_date}, '
            f'{due} periods due, {due - 1} missed)'
            for c, due in behind[:_REPORT_LIMIT])
        more = (f'; and {len(behind) - _REPORT_LIMIT} more (see log)'
                if len(behind) > _REPORT_LIMIT else '')
        return (
            f'{len(behind)} contract(s) skipped, more than one billing period '
            f'behind — not back-billed: {names}{more}. '
            f'{spawned} current-period invoice(s) were generated. '
            f'For each, set the next billing date to the current period to '
            f'skip the missed periods, or run '
            f'`manage.py psa_generate_recurring_invoices` by hand to bill them.')

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
