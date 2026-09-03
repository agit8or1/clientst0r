"""
Phase 44.2 (v3.17.529): pull payments and invoice state from the accounting
system, for real.

What this replaces
------------------
`accounting_sync_payments` polled each pushed invoice's Balance and, when it
reached zero, synthesised a local Payment for the whole outstanding amount,
dated today, with method 'other'. Consequences:

  * a partial payment was invisible — a non-zero balance was skipped outright,
    so Invoice.status could never become 'partial' from the provider side;
  * the payment date, method and reference were fabricated;
  * nothing linked the local row to the provider payment, so a second run could
    not tell what it had already imported;
  * a payment voided provider-side left the invoice reading Paid forever.

This module reads provider Payment records instead, keyed by the provider's own
payment id, which fixes all four.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from integrations.providers.accounting.base import log_accounting_call

logger = logging.getLogger('integrations.accounting.sync')


@dataclass
class SyncResult:
    """What a run did, in terms an operator can act on."""
    payments_created: int = 0
    payments_updated: int = 0
    payments_voided: int = 0
    invoices_touched: int = 0
    unmatched_payments: list = field(default_factory=list)
    # Invoices whose provider total no longer matches ours — reported for a
    # human, never silently reconciled in either direction.
    drifted_invoices: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (f'created={self.payments_created} updated={self.payments_updated} '
                f'voided={self.payments_voided} invoices={self.invoices_touched} '
                f'drifted={len(self.drifted_invoices)} '
                f'unmatched={len(self.unmatched_payments)} errors={len(self.errors)}')


def _parse_optional_date(value):
    """Like _parse_date but returns None rather than inventing today."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


def _parse_date(value) -> date:
    """Provider dates are ISO strings; fall back to today only as a last resort."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value[:10], '%Y-%m-%d').date()
        except ValueError:
            pass
    return timezone.now().date()


def sync_payments(connection, provider, *, since=None, limit=500,
                  dry_run=False) -> SyncResult:
    """Import provider payments against invoices pushed from this system.

    Idempotent by `(accounting_provider, accounting_external_id)` on Payment —
    a re-run updates rather than duplicates.
    """
    from psa.models import Invoice, Payment

    result = SyncResult()
    fetched = provider.fetch_payments(since=since, limit=limit)
    if not fetched.get('success'):
        result.errors.append(fetched.get('error') or 'fetch_payments failed')
        return result

    for row in fetched.get('payments') or []:
        external_id = row.get('external_id')
        if not external_id:
            continue

        invoice_ids = row.get('invoice_external_ids') or []
        invoices = list(Invoice.objects.filter(
            organization=connection.organization,
            accounting_provider=provider.provider_type,
            accounting_external_id__in=invoice_ids,
        )) if invoice_ids else []

        if not invoices:
            # A payment against an invoice raised directly in the accounting
            # system. Reported, not invented: there is no local invoice to
            # attach it to and guessing one would corrupt somebody's ledger.
            result.unmatched_payments.append(external_id)
            continue

        # A payment can settle several invoices at once. Allocate to the first
        # match rather than duplicating the full amount against each.
        invoice = invoices[0]
        amount = Decimal(str(row.get('amount') or '0'))
        existing = Payment.objects.filter(
            accounting_provider=provider.provider_type,
            accounting_external_id=external_id).first()

        if row.get('voided'):
            if existing and not dry_run:
                inv = existing.invoice
                existing.delete()
                # Deleting bypasses Payment.save(), so the invoice has to be
                # told to recompute — otherwise it keeps reading Paid.
                inv.recompute_totals()
                result.payments_voided += 1
                result.invoices_touched += 1
            elif existing:
                result.payments_voided += 1
            continue

        if existing:
            changed = (existing.amount != amount
                       or existing.invoice_id != invoice.pk)
            if changed and not dry_run:
                existing.amount = amount
                existing.paid_on = _parse_date(row.get('txn_date'))
                existing.invoice = invoice
                existing.save()
                result.invoices_touched += 1
            if changed:
                result.payments_updated += 1
            continue

        if dry_run:
            result.payments_created += 1
            continue

        try:
            with transaction.atomic():
                Payment.objects.create(
                    invoice=invoice,
                    amount=amount,
                    paid_on=_parse_date(row.get('txn_date')),
                    method='other',
                    reference=row.get('reference') or '',
                    accounting_provider=provider.provider_type,
                    accounting_external_id=external_id,
                    notes=f'Imported from {provider.provider_name}.',
                )
            result.payments_created += 1
            result.invoices_touched += 1
        except IntegrityError as exc:
            # The unique constraint doing its job — a concurrent run got there
            # first. Not an error worth failing the sync over.
            logger.info('payment %s already imported: %s', external_id, exc)

    log_accounting_call(
        connection=connection, action='pull_payments',
        resource_type='payment', success=result.ok,
        request_summary=f'since={since} limit={limit} dry_run={dry_run}',
        response_summary=result.summary(),
        error_message='; '.join(result.errors)[:500],
    )
    return result


def sync_invoice_state(connection, provider, *, limit=200,
                       dry_run=False) -> SyncResult:
    """Reconcile pushed invoices against the provider's copy.

    Handles what payment sync cannot see: an invoice voided or deleted in the
    accounting system. Both used to leave the local invoice untouched forever.
    """
    from psa.models import Invoice

    result = SyncResult()
    invoices = Invoice.objects.filter(
        organization=connection.organization,
        accounting_provider=provider.provider_type,
    ).exclude(accounting_external_id='').exclude(status='void')[:limit]

    for invoice in invoices:
        try:
            fetched = provider.fetch_invoice(invoice.accounting_external_id)
        except Exception as exc:
            result.errors.append(f'{invoice.invoice_number}: {exc}')
            continue

        if not fetched.get('success'):
            error = fetched.get('error') or ''
            # A 404 means it is gone provider-side. Flag it rather than voiding
            # the local invoice: deleting revenue records on the strength of one
            # HTTP status is not a call a sync job should make.
            if '404' in error:
                if not dry_run:
                    invoice.last_push_error = (
                        'Not found in the accounting system — it may have been '
                        'deleted there. Local copy left untouched.')
                    invoice.save(update_fields=['last_push_error', 'updated_at'])
                result.invoices_touched += 1
            else:
                result.errors.append(f'{invoice.invoice_number}: {error}')
            continue

        remote = fetched.get('invoice') or {}
        changed_fields = []

        if remote.get('voided') and invoice.status != 'void':
            invoice.status = 'void'
            changed_fields.append('status')
            result.invoices_touched += 1

        # Record what the provider currently says. The total is stored rather
        # than applied: our total is derived from line items, and overwriting it
        # would leave the invoice disagreeing with its own lines. The
        # reconciliation report surfaces the difference for a human to settle.
        remote_total = remote.get('total')
        if remote_total is not None and invoice.provider_total_amount != remote_total:
            invoice.provider_total_amount = remote_total
            changed_fields.append('provider_total_amount')
            if remote_total != invoice.total:
                result.drifted_invoices.append(
                    f'{invoice.invoice_number}: provider {remote_total} '
                    f'vs local {invoice.total}')

        # The due date is safe to apply — nothing local derives from it, and the
        # provider is the system of record for when the client owes money.
        remote_due = _parse_optional_date(remote.get('due_date'))
        if remote_due and remote_due != invoice.due_date:
            invoice.due_date = remote_due
            changed_fields.append('due_date')
            result.invoices_touched += 1

        invoice.provider_synced_at = timezone.now()
        changed_fields.append('provider_synced_at')

        if changed_fields and not dry_run:
            invoice.save(update_fields=changed_fields + ['updated_at'])

    log_accounting_call(
        connection=connection, action='pull_invoices',
        resource_type='invoice', success=result.ok,
        request_summary=f'limit={limit} dry_run={dry_run}',
        response_summary=result.summary(),
        error_message='; '.join(result.errors)[:500],
    )
    return result
