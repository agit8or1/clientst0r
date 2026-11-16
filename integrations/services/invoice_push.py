"""Duplicate-safe invoice push to an accounting provider.

Every path that sends an invoice to QuickBooks Online / Xero goes through
`push_invoice_safely`. The provider adapters create a new invoice on every
POST, so the rules here are what keep a client from receiving two:

1. Claim. In a short transaction, with the invoice row locked, record an
   InvoicePushAttempt (state=pending) *before* calling the provider. Its
   `open_slot` column is unique per invoice, so the database refuses a second
   open attempt even where row locks are weak (SQLite) — a concurrent push
   sees "in flight" and stops.
2. Reconcile. If an earlier attempt's outcome is unknown (timeout, 5xx,
   crashed worker), or the push is forced, search the provider for an invoice
   carrying this invoice's push key. Found -> adopt its id; nothing is created.
   Search failed -> stop: absence is not confirmed, so creating is not safe.
3. Create, sending the push key (QBO PrivateNote + DocNumber / Xero Reference)
   and a request id (QBO `requestid`, Xero `Idempotency-Key`). A timeout or
   5xx marks the attempt *unknown*, never failed; the next push reconciles.

The HTTP call is made outside the claiming transaction on purpose: holding a
write transaction open across a network call stalls every other writer on
SQLite, and the unique open slot already serialises pushes per invoice.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from integrations.providers.accounting.base import (
    AccountingPreflightError,
    log_accounting_call,
)

logger = logging.getLogger('integrations.accounting.push')

# A pending attempt older than this is assumed to belong to a worker that died
# mid-request; it is treated as unknown (reconciled), never as failed.
STALE_PENDING_AFTER = timedelta(minutes=10)


def _result(outcome, *, success=False, invoice_id='', error=''):
    return {'success': success, 'outcome': outcome,
            'invoice_id': invoice_id, 'error': error}


def _key_for(invoice, connection):
    """Stable per (invoice, connection): reuse the key of any earlier attempt
    so every attempt for this pair can be found by the same marker."""
    from integrations.models import InvoicePushAttempt
    prior = (InvoicePushAttempt.objects
             .filter(invoice=invoice, connection=connection)
             .order_by('requested_at', 'pk')
             .values_list('idempotency_key', flat=True).first())
    return prior or f'CS-{invoice.pk}-{secrets.token_hex(4)}'


def _close(attempt, state, **fields):
    from integrations.models import InvoicePushAttempt
    attempt.state = state
    if state in (InvoicePushAttempt.STATE_SUCCEEDED, InvoicePushAttempt.STATE_FAILED):
        attempt.open_slot = None
        attempt.completed_at = timezone.now()
    for k, v in fields.items():
        setattr(attempt, k, v)
    attempt.save()


def _release(attempt, was_unknown, error, resolution):
    """Nothing was sent this time. An attempt that was already unknown goes
    back to unknown (the old request may still have landed); a fresh one is a
    definite failure."""
    from integrations.models import InvoicePushAttempt
    state = InvoicePushAttempt.STATE_UNKNOWN if was_unknown else InvoicePushAttempt.STATE_FAILED
    _close(attempt, state, error=str(error)[:2000], resolution=resolution)


def _is_absent_error(err):
    err = str(err or '')
    return err.startswith('HTTP 404') or 'Object Not Found' in err


def push_invoice_safely(invoice, connection, provider, *, user=None, force=False):
    """Push `invoice` through `provider` (bound to `connection`).

    Returns {'success', 'outcome', 'invoice_id', 'error'}; outcome is one of
    created, adopted, already_pushed, in_flight, exists, unknown, failed,
    refused, reconcile_error.

    `force` (a deliberate re-push of an invoice that already has a provider
    id) still reconciles: it refuses while the recorded provider invoice
    exists, and adopts rather than duplicates one carrying our key.
    """
    from psa.models import Invoice
    from integrations.models import InvoicePushAttempt

    now = timezone.now()
    reconcile = bool(force)
    was_unknown = False

    # ---- 1. claim ---------------------------------------------------------
    try:
        with transaction.atomic():
            inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
            open_att = (InvoicePushAttempt.objects.select_for_update()
                        .filter(invoice=inv, state__in=[
                            InvoicePushAttempt.STATE_PENDING,
                            InvoicePushAttempt.STATE_UNKNOWN])
                        .order_by('-requested_at').first())
            if open_att is not None:
                if (open_att.state == InvoicePushAttempt.STATE_PENDING
                        and open_att.requested_at > now - STALE_PENDING_AFTER):
                    return _result('in_flight', error=(
                        f'A push of invoice {inv.invoice_number} is already in '
                        f'progress (started {open_att.requested_at:%Y-%m-%d %H:%M:%S}). '
                        f'Wait for it to finish, then check the invoice.'))
                if open_att.connection_id != connection.pk:
                    return _result('refused', error=(
                        f'An earlier push of invoice {inv.invoice_number} to '
                        f'connection "{open_att.connection}" has an unknown '
                        f'outcome. Push it to that connection again so it can be '
                        f'reconciled before using a different one.'))
                was_unknown = True
                reconcile = True
                open_att.state = InvoicePushAttempt.STATE_PENDING
                open_att.requested_at = now
                open_att.tries += 1
                open_att.forced = open_att.forced or force
                if user is not None and getattr(user, 'pk', None):
                    open_att.requested_by = user
                open_att.save()
                attempt = open_att
            else:
                if inv.accounting_external_id and not force:
                    return _result('already_pushed', invoice_id=inv.accounting_external_id,
                                   error=(f'Invoice {inv.invoice_number} was already '
                                          f'pushed as id {inv.accounting_external_id}.'))
                attempt = InvoicePushAttempt.objects.create(
                    invoice=inv, connection=connection,
                    idempotency_key=_key_for(inv, connection),
                    request_id=uuid.uuid4().hex,
                    state=InvoicePushAttempt.STATE_PENDING,
                    open_slot=str(inv.pk), forced=bool(force),
                    requested_by=user if getattr(user, 'pk', None) else None,
                    requested_at=now,
                )
    except IntegrityError:
        # Another request claimed the open slot between our read and insert.
        return _result('in_flight', error=(
            f'A push of invoice {invoice.invoice_number} is already in progress.'))

    try:
        return _run(inv, attempt, connection, provider, reconcile=reconcile,
                    was_unknown=was_unknown, force=force)
    finally:
        try:
            invoice.refresh_from_db()
        except Exception:
            pass


def _run(inv, attempt, connection, provider, *, reconcile, was_unknown, force):
    from integrations.models import InvoicePushAttempt
    key = attempt.idempotency_key

    # ---- 2. reconcile -----------------------------------------------------
    if reconcile:
        # A forced re-push of an invoice we hold an id for: the recorded copy
        # must be gone (deleted / voided) before another is created.
        if (force and inv.accounting_external_id and inv.accounting_provider
                in ('', connection.provider_type)):
            try:
                fr = provider.fetch_invoice(inv.accounting_external_id)
            except Exception as exc:
                fr = {'success': False, 'error': str(exc)}
            if fr.get('success'):
                if not (fr.get('invoice') or {}).get('voided'):
                    msg = (f'Invoice {inv.invoice_number} still exists in '
                           f'{connection.get_provider_type_display()} as id '
                           f'{inv.accounting_external_id}. Not re-pushing: that '
                           f'would create a duplicate. Void or delete it there first.')
                    _release(attempt, was_unknown, msg, 'exists')
                    log_accounting_call(
                        connection=connection, action='push_refused',
                        resource_type='invoice', resource_id=inv.pk,
                        external_id=inv.accounting_external_id, success=False,
                        error_message=msg, request_summary=f'force key={key}')
                    return _result('exists', invoice_id=inv.accounting_external_id,
                                   error=msg)
            elif not _is_absent_error(fr.get('error')):
                msg = (f'Could not confirm whether invoice {inv.accounting_external_id} '
                       f'still exists in {connection.get_provider_type_display()} '
                       f'({fr.get("error")}). Nothing was pushed; try again later.')
                _release(attempt, was_unknown, msg, 'reconcile_error')
                return _result('reconcile_error', error=msg)

        try:
            res = provider.find_invoice_by_key(inv, key)
        except Exception as exc:
            res = {'status': 'error', 'error': str(exc)}
        status = res.get('status')
        if status == 'found' and res.get('external_id'):
            ext = str(res['external_id'])
            provider.adopt_invoice(inv, ext, res.get('data'))
            _close(attempt, InvoicePushAttempt.STATE_SUCCEEDED,
                   external_id=ext, resolution='adopted', error='')
            return _result('adopted', success=True, invoice_id=ext)
        if status != 'absent':
            msg = (f'Could not confirm whether invoice {inv.invoice_number} already '
                   f'exists in {connection.get_provider_type_display()} '
                   f'({res.get("error") or "search failed"}). Nothing was pushed, '
                   f'to avoid a duplicate; try again later.')
            _release(attempt, was_unknown, msg, 'reconcile_error')
            inv.last_push_error = msg[:500]
            inv.save(update_fields=['last_push_error', 'updated_at'])
            return _result('reconcile_error', error=msg)
        # Confirmed absent: create. A retried unknown attempt keeps its
        # request id, so a provider that did receive the first request (but
        # whose search index has not caught up) replays it instead.

    # ---- 3. create --------------------------------------------------------
    try:
        result = provider.push_invoice(inv, idempotency_key=key,
                                       request_id=attempt.request_id)
    except AccountingPreflightError as exc:
        _close(attempt, InvoicePushAttempt.STATE_FAILED, error=str(exc)[:2000],
               resolution='refused')
        return _result('refused', error=str(exc))
    except Exception as exc:
        # Unknown whether the provider created anything — do not call it failed.
        logger.exception('invoice push raised for invoice %s', inv.pk)
        log_accounting_call(
            connection=connection, action='push_invoice',
            resource_type='invoice', resource_id=inv.pk, success=False,
            error_message=f'outcome unknown: {exc}', request_summary=f'key={key}')
        _close(attempt, InvoicePushAttempt.STATE_UNKNOWN, error=str(exc)[:2000],
               resolution='')
        return _result('unknown', error=_unknown_msg(inv, exc))

    result = result or {}
    if result.get('success'):
        ext = str(result.get('invoice_id') or '')
        _close(attempt, InvoicePushAttempt.STATE_SUCCEEDED, external_id=ext,
               resolution='created', error='')
        return _result('created', success=True, invoice_id=ext)
    err = result.get('error') or 'unknown error'
    if result.get('ambiguous'):
        _close(attempt, InvoicePushAttempt.STATE_UNKNOWN, error=str(err)[:2000])
        return _result('unknown', error=_unknown_msg(inv, err))
    _close(attempt, InvoicePushAttempt.STATE_FAILED, error=str(err)[:2000],
           resolution='refused' if result.get('preflight') else 'failed')
    return _result('refused' if result.get('preflight') else 'failed', error=str(err))


def _unknown_msg(inv, err):
    return (f'The push of invoice {inv.invoice_number} may or may not have reached '
            f'the accounting system ({err}). Push again: the next attempt first '
            f'checks the accounting system for it and will not create a duplicate.')
