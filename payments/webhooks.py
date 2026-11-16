"""
Webhook receivers for Stripe and GoCardless.

Each connection has its own endpoint URL (/payments/webhooks/<provider>/<id>/)
so the right signing secret is known before the body is trusted. Every event
is verified, then recorded in GatewayEvent under a unique (provider,
event_id): a redelivered event that was already processed is acknowledged
and skipped. An event whose processing raised is stored with the error and
answered 500, so the provider redelivers it and it is processed again.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import services
from .models import GatewayEvent, PaymentAttempt

logger = logging.getLogger('payments.webhooks')


def process_event(connection, provider, event_id, event_type, raw, handler):
    """Run `handler()` once per (provider, event_id). Returns 'processed',
    'duplicate' or 'error'."""
    phash = services.payload_hash(raw)
    try:
        with transaction.atomic():
            try:
                with transaction.atomic():
                    ev = GatewayEvent.objects.create(connection=connection, provider=provider, event_id=event_id,
                                                     event_type=event_type[:120], payload_hash=phash)
            except IntegrityError:
                ev = GatewayEvent.objects.select_for_update().get(provider=provider, event_id=event_id)
                if ev.processed_at:
                    return 'duplicate'
            handler()
            ev.processed_at = timezone.now()
            ev.error = ''
            ev.save(update_fields=['processed_at', 'error'])
        return 'processed'
    except Exception as exc:  # noqa: BLE001 — recorded, and the provider retries
        logger.exception('payments: %s event %s failed', provider, event_id)
        GatewayEvent.objects.update_or_create(
            provider=provider, event_id=event_id,
            defaults=dict(connection=connection, event_type=event_type[:120], payload_hash=phash,
                          error=str(exc)[:4000], processed_at=None))
        return 'error'


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

STRIPE_REFUND_STATUS = {'succeeded': 'succeeded', 'pending': 'pending', 'requires_action': 'pending',
                        'failed': 'failed', 'canceled': 'canceled'}


def _ts(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


def _stripe_attempt_for_pi(connection, pi_id):
    if not pi_id:
        return None
    return PaymentAttempt.objects.filter(connection=connection, provider_object_id=pi_id).first()


def _stripe_refund(connection, refund):
    from integrations.providers.payment.stripe import from_minor
    pi_id = refund.get('payment_intent')
    attempt = _stripe_attempt_for_pi(connection, pi_id)
    if attempt is None:
        return
    services.apply_refund(
        attempt, provider_refund_id=refund['id'],
        amount=from_minor(refund.get('amount'), refund.get('currency', attempt.currency)),
        status=STRIPE_REFUND_STATUS.get(refund.get('status'), 'pending'),
        refund_key=(refund.get('metadata') or {}).get('clientst0r_refund', ''),
        failure_message=refund.get('failure_reason') or '')


def handle_stripe_event(connection, event):
    from integrations.providers.payment.stripe import from_minor
    etype = event.get('type', '')
    obj = (event.get('data') or {}).get('object') or {}

    if etype in ('checkout.session.completed', 'checkout.session.async_payment_succeeded',
                 'checkout.session.async_payment_failed'):
        attempt = services.stripe_complete_session(connection, obj)
        if etype.endswith('async_payment_failed') and isinstance(attempt, PaymentAttempt) and obj.get('payment_intent'):
            pi = services.provider_for(connection).retrieve_payment_intent(obj['payment_intent'])
            services.stripe_sync_payment_intent(connection, pi, attempt)
    elif etype == 'checkout.session.expired':
        attempt = PaymentAttempt.objects.filter(connection=connection, provider_session_id=obj.get('id')).first()
        if attempt is not None and attempt.status in ('created', 'requires_action'):
            services.record_canceled(attempt, provider_status='expired')
    elif etype in ('payment_intent.succeeded', 'payment_intent.processing', 'payment_intent.payment_failed',
                   'payment_intent.canceled'):
        services.stripe_sync_payment_intent(connection, obj)
    elif etype == 'charge.refunded':
        refunds = (obj.get('refunds') or {}).get('data')
        if refunds is None:
            refunds = services.provider_for(connection).list_refunds(obj.get('payment_intent'))
        for r in refunds:
            r.setdefault('payment_intent', obj.get('payment_intent'))
            _stripe_refund(connection, r)
    elif etype in ('refund.created', 'refund.updated', 'refund.failed', 'charge.refund.updated'):
        _stripe_refund(connection, obj)
    elif etype in ('charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed',
                   'charge.dispute.funds_withdrawn', 'charge.dispute.funds_reinstated'):
        attempt = _stripe_attempt_for_pi(connection, obj.get('payment_intent'))
        if attempt is None:
            return
        pstatus = obj.get('status', '')
        status = {'won': 'won', 'warning_closed': 'won', 'lost': 'lost'}.get(pstatus, 'open')
        services.record_dispute(
            attempt, provider_dispute_id=obj['id'],
            amount=from_minor(obj.get('amount'), obj.get('currency', attempt.currency)),
            provider_status=pstatus, status=status, reason=obj.get('reason') or '',
            evidence_due_by=_ts((obj.get('evidence_details') or {}).get('due_by')))
    elif etype == 'payment_method.detached':
        services.mark_method_detached(connection, obj.get('id', ''))
    # Anything else is acknowledged and ignored.


def receive_stripe(connection, raw: bytes, headers):
    """Returns (http_status, message)."""
    provider = services.provider_for(connection)
    if not provider.verify_webhook(raw, headers):
        return 400, 'invalid signature'
    try:
        event = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return 400, 'invalid payload'
    if not event.get('id'):
        return 400, 'missing event id'
    result = process_event(connection, 'stripe', event['id'], event.get('type', ''), raw,
                           lambda: handle_stripe_event(connection, event))
    return (500, 'error') if result == 'error' else (200, result)


# ---------------------------------------------------------------------------
# GoCardless
# ---------------------------------------------------------------------------

GC_REFUND_STATUS = {'created': 'pending', 'pending_submission': 'pending', 'submitted': 'pending',
                    'paid': 'succeeded', 'refund_settled': 'succeeded', 'funds_returned': 'failed',
                    'failed': 'failed', 'bounced': 'failed', 'cancelled': 'canceled'}
GC_MANDATE_ACTIVE = ('active', 'reinstated', 'replaced')
GC_MANDATE_DEAD = ('cancelled', 'failed', 'expired', 'consumed', 'blocked', 'suspended_by_payer')


def handle_gocardless_event(connection, event):
    provider = services.provider_for(connection)
    rtype = event.get('resource_type', '')
    action = event.get('action', '')
    links = event.get('links') or {}
    cause = (event.get('details') or {}).get('cause', '')

    if rtype == 'payments' and links.get('payment'):
        payment = provider.retrieve_payment(links['payment'])
        attempt = services.attempt_by_key(connection, (payment.get('metadata') or {}).get('clientst0r_attempt')) \
            or PaymentAttempt.objects.filter(connection=connection, provider_object_id=payment['id']).first()
        if attempt is None:
            return
        state = payment.get('status', action)
        if action == 'late_failure_settled':
            state = 'failed'
        services.gocardless_apply_payment_state(attempt, state, payment_id=payment['id'], cause=cause)
    elif rtype == 'mandates' and links.get('mandate'):
        mid = links['mandate']
        if action in GC_MANDATE_ACTIVE:
            from .models import StoredPaymentMethod
            StoredPaymentMethod.objects.filter(connection=connection, provider_method_id=mid).exclude(
                status='detached').update(status='active', updated_at=timezone.now())
        elif action in GC_MANDATE_DEAD:
            services.mark_method_detached(connection, mid, status='inactive')
    elif rtype == 'refunds' and links.get('refund'):
        refund = provider.retrieve_refund(links['refund'])
        pay_id = (refund.get('links') or {}).get('payment') or links.get('payment')
        attempt = PaymentAttempt.objects.filter(connection=connection, provider_object_id=pay_id).first()
        if attempt is None:
            return
        status = GC_REFUND_STATUS.get(action) or GC_REFUND_STATUS.get(refund.get('status', ''), 'pending')
        services.apply_refund(
            attempt, provider_refund_id=refund['id'],
            amount=provider.amount_from_minor(refund.get('amount'), refund.get('currency', attempt.currency)),
            status=status, refund_key=(refund.get('metadata') or {}).get('clientst0r_refund', ''),
            failure_message=cause)
    elif rtype == 'billing_requests' and action == 'fulfilled' and links.get('billing_request'):
        br = provider.retrieve_billing_request(links['billing_request'])
        services.gocardless_complete_billing_request(connection, br)


def receive_gocardless(connection, raw: bytes, headers):
    provider = services.provider_for(connection)
    if not provider.verify_webhook(raw, headers):
        # GoCardless documents 498 for a signature that does not match.
        return 498, 'invalid signature'
    try:
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return 400, 'invalid payload'
    errors = 0
    for event in body.get('events') or []:
        if not event.get('id'):
            continue
        etype = f"{event.get('resource_type', '')}.{event.get('action', '')}"
        result = process_event(connection, 'gocardless', event['id'], etype, json.dumps(event).encode(),
                               lambda e=event: handle_gocardless_event(connection, e))
        errors += result == 'error'
    return (500, 'error') if errors else (200, 'ok')
