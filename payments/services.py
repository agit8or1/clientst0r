"""
Payment state machine: everything that changes money state goes through here.

Entry points are idempotent. The webhook handlers, the portal's return pages
(which re-read the provider so a payment still lands when a webhook is late
or blocked) and the autopay command may all report the same outcome; each of
`record_success`, `apply_refund` and `record_dispute` locks the attempt row
and writes its psa.Payment at most once.

A settled payment / refund / lost dispute writes a psa.Payment row (negative
for money going back) through the normal model save, which recomputes the
invoice's amount_paid and status. It never calls the accounting system:
the row's attempt / refund / dispute is marked accounting_post_status =
'pending' and the accounting pipeline posts it (payments.accounting).
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Dispute, GatewayCustomer, GatewaySettings, PaymentAttempt, Refund, SetupRequest, StoredPaymentMethod,
)

logger = logging.getLogger('payments')

GATEWAY_TYPES = ('stripe', 'gocardless')

PSA_METHOD = {'card': 'credit_card', 'us_bank_account': 'ach', 'sepa_debit': 'ach', 'bacs_debit': 'ach',
              'direct_debit': 'ach'}


class PaymentError(Exception):
    """A refusal or provider failure safe to show to the user."""


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def connection_for(organization=None):
    """The MSP's active, live-enabled gateway connection.

    One install serves one MSP; every Organization is a customer of it. The
    gateway account is the MSP's, so payment connections are install-global
    (platform-owned, organization empty) and collect for every customer.
    A PaymentConnection row with an organization set (possible in the shared
    connection model) is never used for collection. `organization` is
    accepted for call-site symmetry and ignored. With several active
    connections the oldest wins; keep one live connection."""
    from integrations.models import PaymentConnection
    return (PaymentConnection.objects
            .filter(is_active=True, sync_enabled=True, provider_type__in=GATEWAY_TYPES,
                    organization__isnull=True)
            .order_by('pk').first())


def connection_for_invoice(invoice):
    return connection_for()


def provider_for(connection):
    from integrations.providers.payment import get_payment_provider
    provider = get_payment_provider(connection)
    if provider is None:
        raise PaymentError('This payment connection has no gateway adapter.')
    return provider


def settings_for(connection) -> GatewaySettings:
    obj, _ = GatewaySettings.objects.get_or_create(connection=connection)
    return obj


def in_flight_amount(invoice) -> Decimal:
    """Money already on its way for this invoice (processing attempts)."""
    total = Decimal('0')
    for a in PaymentAttempt.objects.filter(invoice=invoice, status='processing'):
        total += a.amount
    return total


def amount_due(invoice) -> Decimal:
    if invoice.status in ('draft', 'void') or invoice.is_credit_memo:
        return Decimal('0.00')
    return max(Decimal('0.00'), invoice.net_balance_due - in_flight_amount(invoice))


def default_method(connection, client_org) -> Optional[StoredPaymentMethod]:
    return (StoredPaymentMethod.objects.filter(connection=connection, client_org=client_org, is_default=True,
                                               status__in=('active', 'pending')).first())


def new_key(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex}'


def payload_hash(raw: bytes) -> str:
    return hashlib.sha256(raw or b'').hexdigest()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit(user, action, organization, obj, description, success=True, **extra):
    try:
        from audit.models import AuditLog
        AuditLog.log(user=user if (user is not None and getattr(user, 'pk', None)) else None,
                     action=action, organization=organization,
                     object_type=obj.__class__.__name__.lower() if obj is not None else 'payment',
                     object_id=getattr(obj, 'pk', None), object_repr=str(obj)[:255] if obj is not None else '',
                     description=description, extra_data={k: str(v) for k, v in extra.items()},
                     success=success)
    except Exception:  # pragma: no cover - auditing must never break a payment
        logger.exception('payments: audit log failed')


# ---------------------------------------------------------------------------
# Customers and stored methods
# ---------------------------------------------------------------------------

def gateway_customer(connection, client_org, *, create=True) -> Optional[GatewayCustomer]:
    existing = GatewayCustomer.objects.filter(connection=connection, client_org=client_org).first()
    if existing or not create:
        return existing
    if connection.provider_type != 'stripe':
        return None  # GoCardless creates the customer inside the billing request flow
    provider = provider_for(connection)
    cid = provider.create_customer(name=client_org.name, email=getattr(client_org, 'email', '') or '',
                                   reference=str(client_org.pk),
                                   idempotency_key=f'clientst0r-customer-{connection.pk}-{client_org.pk}')
    try:
        with transaction.atomic():
            return GatewayCustomer.objects.create(connection=connection, client_org=client_org,
                                                  provider_customer_id=cid)
    except IntegrityError:
        return GatewayCustomer.objects.get(connection=connection, client_org=client_org)


def link_customer(connection, client_org, provider_customer_id) -> Optional[GatewayCustomer]:
    if not provider_customer_id:
        return gateway_customer(connection, client_org, create=False)
    try:
        with transaction.atomic():
            obj, _ = GatewayCustomer.objects.get_or_create(
                connection=connection, client_org=client_org,
                defaults={'provider_customer_id': provider_customer_id})
            return obj
    except IntegrityError:
        return GatewayCustomer.objects.filter(connection=connection, client_org=client_org).first()


def save_method(connection, client_org, provider_method_id, details, *, mandate_id='', customer=None,
                make_default=True, autopay_user=None, status='active') -> StoredPaymentMethod:
    """Store (or refresh) a provider method. Display details only."""
    fields = {k: details.get(k) for k in ('method_type', 'brand', 'last4', 'exp_month', 'exp_year', 'bank_name')
              if details.get(k) not in (None, '')}
    with transaction.atomic():
        method, created = StoredPaymentMethod.objects.select_for_update().get_or_create(
            connection=connection, provider_method_id=provider_method_id,
            defaults=dict(client_org=client_org, gateway_customer=customer, mandate_id=mandate_id,
                          status=status, **fields))
        if method.client_org_id != client_org.pk:
            raise PaymentError('That payment method belongs to another customer.')
        if not created:
            for k, v in fields.items():
                setattr(method, k, v)
            if method.status == 'detached':
                method.status = status
            if mandate_id:
                method.mandate_id = mandate_id
        has_default = StoredPaymentMethod.objects.filter(
            connection=connection, client_org=client_org, is_default=True,
            status__in=('active', 'pending')).exclude(pk=method.pk).exists()
        if make_default or not has_default:
            StoredPaymentMethod.objects.filter(connection=connection, client_org=client_org,
                                               is_default=True).exclude(pk=method.pk).update(is_default=False)
            method.is_default = True
        if autopay_user is not None:
            _authorize(method, autopay_user)
        method.save()
    audit(autopay_user, 'create' if created else 'update', client_org, method,
          f'Payment method {method.display} saved', provider=connection.provider_type)
    return method


def _authorize(method, user):
    method.authorized_for_autopay = True
    method.autopay_authorized_at = timezone.now()
    method.autopay_authorized_by = user


def set_autopay(method: StoredPaymentMethod, user, enabled: bool):
    with transaction.atomic():
        method = StoredPaymentMethod.objects.select_for_update().get(pk=method.pk)
        if enabled:
            if not method.usable:
                raise PaymentError('That payment method can no longer be charged.')
            # Autopay charges the default method, so authorizing one makes it the default.
            StoredPaymentMethod.objects.filter(connection=method.connection, client_org=method.client_org,
                                               is_default=True).exclude(pk=method.pk).update(is_default=False)
            method.is_default = True
            _authorize(method, user)
        else:
            method.authorized_for_autopay = False
        method.save()
    audit(user, 'update', method.client_org, method,
          f'Autopay {"authorized" if enabled else "turned off"} for {method.display}')
    return method


def set_default(method: StoredPaymentMethod, user):
    with transaction.atomic():
        StoredPaymentMethod.objects.filter(connection=method.connection, client_org=method.client_org,
                                           is_default=True).exclude(pk=method.pk).update(
            is_default=False, authorized_for_autopay=False)
        method.is_default = True
        method.save(update_fields=['is_default', 'updated_at'])
    audit(user, 'update', method.client_org, method, f'Default payment method set to {method.display}')


def remove_method(method: StoredPaymentMethod, user):
    """Detach at the provider (Stripe) / cancel the mandate (GoCardless)."""
    provider = provider_for(method.connection)
    try:
        if method.connection.provider_type == 'stripe':
            provider.detach_payment_method(method.provider_method_id)
        else:
            provider.cancel_mandate(method.mandate_id or method.provider_method_id)
    except Exception as exc:
        raise PaymentError(f'The provider refused to remove the method: {exc}')
    mark_method_detached(method.connection, method.provider_method_id)
    audit(user, 'delete', method.client_org, method, f'Payment method {method.display} removed')


def mark_method_detached(connection, provider_method_id, *, status='detached'):
    StoredPaymentMethod.objects.filter(connection=connection, provider_method_id=provider_method_id).update(
        status=status, is_default=False, authorized_for_autopay=False, updated_at=timezone.now())


# ---------------------------------------------------------------------------
# Starting payments (portal)
# ---------------------------------------------------------------------------

def _invoice_metadata(attempt):
    return {'clientst0r_attempt': attempt.idempotency_key,
            'clientst0r_invoice': attempt.invoice.invoice_number,
            'clientst0r_client': str(attempt.client_org_id)}


def _cancel_stale_checkouts(invoice):
    """A new checkout replaces any earlier one the customer abandoned."""
    for old in PaymentAttempt.objects.filter(invoice=invoice, kind='checkout',
                                             status__in=('created', 'requires_action')):
        if old.provider == 'stripe' and old.provider_session_id:
            try:
                provider_for(old.connection).expire_checkout_session(old.provider_session_id)
            except Exception:  # noqa: BLE001 — already expired / completed: the webhook decides
                logger.info('payments: could not expire checkout %s', old.provider_session_id)
        old.status = 'canceled'
        old.save(update_fields=['status', 'updated_at'])


def start_checkout(invoice, user, *, save_for_autopay: bool, success_url, cancel_url):
    """Create an attempt and the provider-hosted page that pays it. Returns
    (attempt, redirect_url). `success_url` / `cancel_url` are callables
    taking the attempt (they need its key)."""
    connection = connection_for_invoice(invoice)
    if connection is None:
        raise PaymentError('Online payment is not available for this invoice.')
    if not settings_for(connection).portal_payments_enabled:
        raise PaymentError('Online payment is turned off.')
    if PaymentAttempt.objects.filter(invoice=invoice, status='processing').exists():
        raise PaymentError('A payment for this invoice is already being processed.')
    amount = amount_due(invoice)
    if amount <= 0:
        raise PaymentError('Nothing is due on this invoice.')
    _cancel_stale_checkouts(invoice)
    attempt = PaymentAttempt.objects.create(
        invoice=invoice, client_org=invoice.client_org, connection=connection,
        provider=connection.provider_type, kind='checkout', amount=amount, currency=invoice.currency or 'USD',
        idempotency_key=new_key('pay'), save_for_autopay=save_for_autopay, created_by=user)
    provider = provider_for(connection)
    description = f'Invoice {invoice.invoice_number}'
    try:
        if connection.provider_type == 'stripe':
            customer = gateway_customer(connection, invoice.client_org)
            out = provider.create_checkout_payment(
                customer_id=customer.provider_customer_id, amount=amount, currency=attempt.currency,
                description=description, reference=str(attempt.pk), metadata=_invoice_metadata(attempt),
                success_url=success_url(attempt), cancel_url=cancel_url(attempt),
                save_for_future=save_for_autopay, idempotency_key=f'{attempt.idempotency_key}:checkout')
            attempt.provider_session_id = out['session_id']
            attempt.provider_object_id = out.get('payment_intent') or ''
            url = out['url']
        else:
            # GoCardless: if a usable mandate exists, charge it straight away;
            # otherwise send the customer to set one up, then charge.
            method = default_method(connection, invoice.client_org)
            if method is not None and not save_for_autopay:
                attempt.payment_method = method
                attempt.save(update_fields=['payment_method', 'updated_at'])
                _gc_create_payment(attempt)
                return attempt, success_url(attempt)
            customer = gateway_customer(connection, invoice.client_org, create=False)
            out = provider.create_mandate_flow(
                currency=attempt.currency, metadata={'clientst0r_attempt': attempt.idempotency_key},
                redirect_uri=success_url(attempt), exit_uri=cancel_url(attempt),
                customer_id=customer.provider_customer_id if customer else '',
                idempotency_key=attempt.idempotency_key)
            attempt.provider_session_id = out['billing_request_id']
            url = out['url']
    except PaymentError:
        raise
    except Exception as exc:
        attempt.status = 'failed'
        attempt.failure_message = str(exc)[:2000]
        attempt.save(update_fields=['status', 'failure_message', 'updated_at'])
        audit(user, 'create', invoice.client_org, attempt, 'Online payment could not be started', error=exc,
              success=False)
        raise PaymentError('The payment page could not be opened. Please try again later.')
    attempt.status = 'requires_action'
    attempt.save(update_fields=['provider_session_id', 'provider_object_id', 'status', 'updated_at'])
    audit(user, 'create', invoice.client_org, attempt,
          f'Online payment started for invoice {invoice.invoice_number}', amount=amount,
          provider=connection.provider_type)
    return attempt, url


def start_method_setup(connection, client_org, user, *, autopay: bool, success_url, cancel_url):
    """Provider-hosted flow to add / replace a payment method. Returns (setup, url)."""
    setup = SetupRequest.objects.create(connection=connection, client_org=client_org, requested_by=user,
                                        autopay_requested=autopay)
    provider = provider_for(connection)
    key = f'setup-{setup.pk}-{uuid.uuid4().hex[:12]}'
    meta = {'clientst0r_setup': str(setup.pk), 'clientst0r_client': str(client_org.pk)}
    currency = _client_currency(client_org)
    try:
        if connection.provider_type == 'stripe':
            customer = gateway_customer(connection, client_org)
            out = provider.create_checkout_setup(
                customer_id=customer.provider_customer_id, currency=currency, reference=f'setup-{setup.pk}',
                metadata=meta, success_url=success_url(setup), cancel_url=cancel_url(setup), idempotency_key=key)
            setup.provider_reference = out['session_id']
        else:
            customer = gateway_customer(connection, client_org, create=False)
            out = provider.create_mandate_flow(
                currency=currency, metadata=meta, redirect_uri=success_url(setup), exit_uri=cancel_url(setup),
                customer_id=customer.provider_customer_id if customer else '', idempotency_key=key)
            setup.provider_reference = out['billing_request_id']
    except Exception as exc:
        setup.status = 'failed'
        setup.save(update_fields=['status'])
        logger.warning('payments: method setup failed: %s', exc)
        raise PaymentError('The payment method page could not be opened. Please try again later.')
    setup.save(update_fields=['provider_reference'])
    audit(user, 'create', client_org, setup, 'Payment method setup started', provider=connection.provider_type)
    return setup, out['url']


def _client_currency(client_org):
    from psa.models import Invoice
    inv = Invoice.objects.filter(client_org=client_org).order_by('-invoice_date').first()
    return (inv.currency if inv else 'USD') or 'USD'


# ---------------------------------------------------------------------------
# Recording outcomes
# ---------------------------------------------------------------------------

def _lock(attempt) -> PaymentAttempt:
    return PaymentAttempt.objects.select_for_update().select_related('invoice', 'connection').get(pk=attempt.pk)


def record_processing(attempt, *, provider_object_id='', provider_status=''):
    with transaction.atomic():
        a = _lock(attempt)
        if a.status in ('succeeded',):
            return a
        a.status = 'processing'
        if provider_object_id:
            a.provider_object_id = provider_object_id
        if provider_status:
            a.provider_status = provider_status
        a.save(update_fields=['status', 'provider_object_id', 'provider_status', 'updated_at'])
        return a


def record_success(attempt, *, amount_received=None, fee=None, net=None, provider_object_id='',
                   provider_status='', method_type=''):
    """Settle an attempt: one psa.Payment, exactly once. Returns (attempt, created)."""
    from psa.models import Payment
    with transaction.atomic():
        a = _lock(attempt)
        if provider_object_id and not a.provider_object_id:
            a.provider_object_id = provider_object_id
        if provider_status:
            a.provider_status = provider_status
        if fee is not None and a.fee_amount is None:
            a.fee_amount = fee
        if net is not None and a.net_amount is None:
            a.net_amount = net
        if a.local_payment_id:
            a.save()
            return a, False
        received = Decimal(str(amount_received)) if amount_received is not None else a.amount
        if not method_type and a.payment_method_id:
            method_type = a.payment_method.method_type
        payment = Payment.objects.create(
            invoice=a.invoice, amount=received, paid_on=timezone.localdate(),
            method=PSA_METHOD.get(method_type, 'credit_card' if a.provider == 'stripe' else 'ach'),
            reference=f'{a.provider}:{a.provider_object_id or a.idempotency_key}'[:120],
            notes=f'Collected by {a.get_provider_display()} ({a.get_kind_display()}). '
                  f'Processing fee recorded separately on the payment attempt.',
            created_by=a.created_by)
        a.local_payment = payment
        a.amount_received = received
        a.status = 'succeeded'
        a.failure_code = ''
        a.failure_message = ''
        a.next_retry_at = None
        a.settled_at = timezone.now()
        a.accounting_post_status = 'pending'
        a.save()
    audit(None, 'create', a.client_org, a,
          f'Payment of {received} {a.currency} received for invoice {a.invoice.invoice_number}',
          provider=a.provider, fee=a.fee_amount, payment_id=payment.pk)
    return a, True


def record_failure(attempt, *, code='', message='', provider_status=''):
    """Mark failed and, for autopay, schedule the retry or give up."""
    with transaction.atomic():
        a = _lock(attempt)
        if a.status == 'succeeded':
            # Late failure after settlement (Direct Debit): reverse it.
            pass_through = True
        else:
            pass_through = False
            a.status = 'failed'
            a.failure_code = (code or '')[:80]
            a.failure_message = (message or '')[:2000]
            if provider_status:
                a.provider_status = provider_status
            final = False
            if a.kind == 'autopay':
                s = settings_for(a.connection)
                if a.attempt_number < s.autopay_max_attempts:
                    a.next_retry_at = timezone.now() + timedelta(days=s.retry_delay_after(a.attempt_number))
                else:
                    a.next_retry_at = None
                    final = True
            a.save()
    if pass_through:
        return record_dispute(a, provider_dispute_id=f'{a.provider_object_id}:late_failure',
                              amount=a.amount_received or a.amount, provider_status='late_failure',
                              status='lost', reason=code or 'late_failure')
    audit(None, 'update', a.client_org, a, f'Payment failed for invoice {a.invoice.invoice_number}: '
          f'{message or code}', provider=a.provider, success=False)
    if a.kind == 'autopay' and final:
        transaction.on_commit(lambda: notify_final_failure(a.pk))
    return a


def record_canceled(attempt, *, provider_status=''):
    with transaction.atomic():
        a = _lock(attempt)
        if a.status in ('succeeded',):
            return a
        a.status = 'canceled'
        a.provider_status = provider_status or a.provider_status
        a.save(update_fields=['status', 'provider_status', 'updated_at'])
        return a


def _negative_payment(attempt, amount, reference, note):
    from psa.models import Payment
    payment = Payment.objects.create(
        invoice=attempt.invoice, amount=-Decimal(str(amount)), paid_on=timezone.localdate(),
        method=attempt.local_payment.method if attempt.local_payment_id else 'other',
        reference=reference[:120], notes=note, created_by=None)
    invoice = attempt.invoice
    invoice.refresh_from_db()
    invoice.reopen_if_unpaid()
    return payment


def request_refund(attempt, amount, user, reason=''):
    """Staff refund (full or partial). The provider call happens after the
    Refund row exists, and the row's key travels as metadata, so the webhook
    that may beat us back always finds this row."""
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    if amount <= 0:
        raise PaymentError('Enter an amount above zero.')
    with transaction.atomic():
        a = _lock(attempt)
        if amount > a.refundable_amount:
            raise PaymentError(f'At most {a.refundable_amount} {a.currency} can be refunded.')
        already = a.refunded_amount + sum((r.amount for r in a.refunds.filter(status='pending')), Decimal('0'))
        refund = Refund.objects.create(attempt=a, amount=amount, currency=a.currency, reason=reason[:300],
                                       idempotency_key=new_key('refund'), requested_by=user)
    provider = provider_for(a.connection)
    try:
        kwargs = dict(payment_object_id=a.provider_object_id, amount=amount, currency=a.currency,
                      metadata={'clientst0r_refund': refund.idempotency_key},
                      idempotency_key=refund.idempotency_key)
        if a.provider == 'gocardless':
            kwargs['total_refunded_after'] = already + amount
        out = provider.create_refund(**kwargs)
    except Exception as exc:
        Refund.objects.filter(pk=refund.pk).update(status='failed', failure_message=str(exc)[:2000])
        audit(user, 'create', a.client_org, refund, f'Refund of {amount} {a.currency} failed: {exc}',
              success=False)
        raise PaymentError(f'The provider refused the refund: {exc}')
    Refund.objects.filter(pk=refund.pk).update(provider_refund_id=out['id'])
    audit(user, 'create', a.client_org, refund,
          f'Refund of {amount} {a.currency} requested for invoice {a.invoice.invoice_number}',
          reason=reason, provider_refund_id=out['id'])
    return apply_refund(a, provider_refund_id=out['id'], amount=amount, status=out['status'],
                        refund_key=refund.idempotency_key)


def apply_refund(attempt, *, provider_refund_id, amount, status, refund_key='', failure_message=''):
    """Record a refund's state (from our own call or a webhook). A refund made
    in the provider's dashboard gets a row here too. The negative psa.Payment
    is written once, when the refund succeeds."""
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    with transaction.atomic():
        a = _lock(attempt)
        refund = None
        if refund_key:
            refund = Refund.objects.select_for_update().filter(attempt=a, idempotency_key=refund_key).first()
        if refund is None and provider_refund_id:
            refund = Refund.objects.select_for_update().filter(provider_refund_id=provider_refund_id).first()
        if refund is None:
            refund = Refund.objects.create(attempt=a, amount=amount, currency=a.currency,
                                           idempotency_key=f'ext-{provider_refund_id}',
                                           provider_refund_id=provider_refund_id,
                                           reason='Refunded at the payment provider')
        if refund.attempt_id != a.pk:
            raise PaymentError('Refund belongs to another payment.')
        if provider_refund_id and not refund.provider_refund_id:
            refund.provider_refund_id = provider_refund_id
        if refund.status != 'succeeded':
            refund.status = status
            if failure_message:
                refund.failure_message = failure_message[:2000]
        if refund.status == 'succeeded' and not refund.local_payment_id:
            refund.local_payment = _negative_payment(
                a, refund.amount, f'{a.provider}:{refund.provider_refund_id or refund.idempotency_key}',
                f'Refund through {a.get_provider_display()}. {refund.reason}'.strip())
            refund.settled_at = timezone.now()
            refund.accounting_post_status = 'pending'
        refund.save()
    return refund


def record_dispute(attempt, *, provider_dispute_id, amount, provider_status='', status='open', reason='',
                   evidence_due_by=None):
    """Open / update a dispute. A lost dispute takes the money off the
    invoice (one negative psa.Payment); a won one changes nothing."""
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    with transaction.atomic():
        a = _lock(attempt)
        dispute, created = Dispute.objects.select_for_update().get_or_create(
            provider_dispute_id=provider_dispute_id,
            defaults=dict(attempt=a, amount=amount, currency=a.currency, reason=reason[:120],
                          provider_status=provider_status, status=status, evidence_due_by=evidence_due_by))
        if not created:
            if dispute.status == 'open':
                dispute.status = status
            dispute.provider_status = provider_status or dispute.provider_status
            dispute.evidence_due_by = evidence_due_by or dispute.evidence_due_by
        if dispute.status in ('won', 'lost') and not dispute.closed_at:
            dispute.closed_at = timezone.now()
        if dispute.status == 'lost' and not dispute.local_payment_id and a.local_payment_id:
            dispute.local_payment = _negative_payment(
                a, dispute.amount, f'{a.provider}:{dispute.provider_dispute_id}',
                f'Dispute / chargeback lost ({dispute.reason}).')
            dispute.accounting_post_status = 'pending'
        dispute.save()
    audit(None, 'create' if created else 'update', a.client_org, dispute,
          f'Dispute {dispute.provider_dispute_id} on invoice {a.invoice.invoice_number}: {dispute.status}',
          amount=amount, reason=reason)
    return dispute


# ---------------------------------------------------------------------------
# Provider-specific completion (shared by webhooks and return pages)
# ---------------------------------------------------------------------------

def attempt_by_key(connection, key) -> Optional[PaymentAttempt]:
    if not key:
        return None
    return PaymentAttempt.objects.filter(connection=connection, idempotency_key=key).first()


def stripe_sync_payment_intent(connection, pi: dict, attempt=None):
    """Apply a PaymentIntent's state to its attempt."""
    provider = provider_for(connection)
    meta = pi.get('metadata') or {}
    attempt = attempt or attempt_by_key(connection, meta.get('clientst0r_attempt')) or \
        PaymentAttempt.objects.filter(connection=connection, provider_object_id=pi.get('id')).first()
    if attempt is None:
        return None
    status = pi.get('status')
    if status == 'succeeded':
        full = pi
        if not isinstance(pi.get('latest_charge'), dict):
            try:
                full = provider.retrieve_payment_intent(pi['id'])
            except Exception:  # noqa: BLE001 — record the payment, the fee can follow
                logger.warning('payments: fee lookup failed for %s', pi.get('id'))
        received, fee, net = provider.fee_details(full)
        method_type = ''
        charge = full.get('latest_charge')
        if isinstance(charge, dict):
            method_type = (charge.get('payment_method_details') or {}).get('type', '')
        attempt, _ = record_success(attempt, amount_received=received, fee=fee, net=net,
                                    provider_object_id=pi['id'], provider_status=status, method_type=method_type)
        if attempt.save_for_autopay and pi.get('payment_method'):
            _stripe_store_method(connection, attempt.client_org, pi['payment_method'], pi.get('customer'),
                                 autopay_user=attempt.created_by)
    elif status == 'processing':
        record_processing(attempt, provider_object_id=pi['id'], provider_status=status)
    elif status == 'canceled':
        record_canceled(attempt, provider_status=status)
    elif status == 'requires_payment_method' and pi.get('last_payment_error'):
        err = pi['last_payment_error']
        record_failure(attempt, code=err.get('decline_code') or err.get('code') or '',
                       message=err.get('message') or 'The payment failed.', provider_status=status)
    return attempt


def _stripe_store_method(connection, client_org, pm_id, customer_id, *, autopay_user=None):
    provider = provider_for(connection)
    try:
        pm = provider.retrieve_payment_method(pm_id) if isinstance(pm_id, str) else pm_id
    except Exception:  # noqa: BLE001
        logger.warning('payments: could not read payment method %s', pm_id)
        return None
    customer = link_customer(connection, client_org, customer_id or pm.get('customer') or '')
    return save_method(connection, client_org, pm['id'], provider.method_details(pm), customer=customer,
                       autopay_user=autopay_user)


def stripe_complete_session(connection, session: dict):
    """checkout.session.completed / the success return page."""
    meta = session.get('metadata') or {}
    if session.get('mode') == 'setup':
        setup = SetupRequest.objects.filter(connection=connection, provider_reference=session.get('id')).first()
        if setup is None or setup.status == 'completed':
            return setup
        si = session.get('setup_intent')
        provider = provider_for(connection)
        si_obj = provider.retrieve_setup_intent(si) if isinstance(si, str) else si
        if not si_obj or si_obj.get('status') != 'succeeded':
            return setup
        pm = si_obj.get('payment_method')
        method = _stripe_store_method(connection, setup.client_org, pm, session.get('customer'),
                                      autopay_user=setup.requested_by if setup.autopay_requested else None)
        setup.status = 'completed'
        setup.payment_method = method
        setup.completed_at = timezone.now()
        setup.save(update_fields=['status', 'payment_method', 'completed_at'])
        return setup
    attempt = attempt_by_key(connection, meta.get('clientst0r_attempt')) or \
        PaymentAttempt.objects.filter(connection=connection, provider_session_id=session.get('id')).first()
    if attempt is None:
        return None
    pi = session.get('payment_intent')
    if not pi:
        return attempt
    provider = provider_for(connection)
    pi_obj = provider.retrieve_payment_intent(pi) if isinstance(pi, str) else pi
    if session.get('payment_status') in ('paid', 'no_payment_required') or pi_obj.get('status') == 'succeeded':
        stripe_sync_payment_intent(connection, pi_obj, attempt)
    elif pi_obj.get('status') == 'processing' or session.get('payment_status') == 'unpaid':
        record_processing(attempt, provider_object_id=pi_obj.get('id', ''), provider_status=pi_obj.get('status', ''))
    return attempt


def _gc_create_payment(attempt):
    """Collect against the attempt's mandate (GoCardless)."""
    provider = provider_for(attempt.connection)
    method = attempt.payment_method
    try:
        p = provider.create_payment(
            mandate_id=method.mandate_id or method.provider_method_id, amount=attempt.amount,
            currency=attempt.currency, description=f'Invoice {attempt.invoice.invoice_number}',
            metadata={'clientst0r_attempt': attempt.idempotency_key}, idempotency_key=attempt.idempotency_key)
    except Exception as exc:
        code = getattr(exc, 'code', '') or 'provider_error'
        return record_failure(attempt, code=code, message=str(exc))
    return gocardless_apply_payment_state(attempt, p.get('status', ''), payment_id=p.get('id', ''))


GC_PROCESSING = ('pending_customer_approval', 'pending_submission', 'submitted')
GC_SUCCESS = ('confirmed', 'paid_out')
GC_FAILED = ('failed', 'customer_approval_denied')


def gocardless_apply_payment_state(attempt, state, *, payment_id='', cause=''):
    if state in GC_PROCESSING:
        return record_processing(attempt, provider_object_id=payment_id, provider_status=state)
    if state in GC_SUCCESS:
        a, _ = record_success(attempt, provider_object_id=payment_id, provider_status=state,
                              method_type='direct_debit')
        return a
    if state in GC_FAILED:
        return record_failure(attempt, code=cause or state, message=f'Direct Debit payment {state}'
                              + (f' ({cause})' if cause else ''), provider_status=state)
    if state == 'cancelled':
        return record_canceled(attempt, provider_status=state)
    if state == 'charged_back':
        return record_dispute(attempt, provider_dispute_id=f'{payment_id or attempt.provider_object_id}:chargeback',
                              amount=attempt.amount_received or attempt.amount, provider_status=state,
                              status='lost', reason=cause or 'charged_back')
    return attempt


def gocardless_complete_billing_request(connection, br: dict, *, user=None):
    """billing_requests.fulfilled / the redirect back from the hosted flow:
    store the mandate, then collect for the attempt (if this was Pay now)."""
    if br.get('status') != 'fulfilled':
        return None
    links = br.get('links') or {}
    mandate_id = links.get('mandate_request_mandate') or ''
    meta = br.get('metadata') or {}
    attempt = attempt_by_key(connection, meta.get('clientst0r_attempt')) or \
        PaymentAttempt.objects.filter(connection=connection, provider_session_id=br.get('id')).first()
    setup = None
    if attempt is None:
        setup = SetupRequest.objects.filter(connection=connection, provider_reference=br.get('id')).first()
    client_org = attempt.client_org if attempt else (setup.client_org if setup else None)
    if client_org is None or not mandate_id:
        return None
    provider = provider_for(connection)
    details = provider.mandate_details(mandate_id)
    customer = link_customer(connection, client_org, links.get('customer') or details.get('customer_id'))
    autopay_user = None
    if attempt is not None and attempt.save_for_autopay:
        autopay_user = attempt.created_by
    elif setup is not None and setup.autopay_requested:
        autopay_user = setup.requested_by
    mstatus = details.get('mandate_status', '')
    method = save_method(connection, client_org, mandate_id, details, mandate_id=mandate_id, customer=customer,
                         autopay_user=autopay_user, status='active' if mstatus == 'active' else 'pending')
    if setup is not None and setup.status != 'completed':
        setup.status = 'completed'
        setup.payment_method = method
        setup.completed_at = timezone.now()
        setup.save(update_fields=['status', 'payment_method', 'completed_at'])
        return setup
    if attempt is not None:
        with transaction.atomic():
            a = _lock(attempt)
            if a.provider_object_id or a.status in ('succeeded', 'processing', 'canceled'):
                return a
            a.payment_method = method
            a.save(update_fields=['payment_method', 'updated_at'])
        return _gc_create_payment(a)
    return None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notify_final_failure(attempt_id):
    """E-mail once when autopay gives up on an invoice's due cycle."""
    with transaction.atomic():
        a = PaymentAttempt.objects.select_for_update().select_related('invoice', 'connection').get(pk=attempt_id)
        if a.final_failure_notified_at:
            return False
        a.final_failure_notified_at = timezone.now()
        a.save(update_fields=['final_failure_notified_at', 'updated_at'])
    try:
        from core.mailer import (default_from_email, get_smtp_connection, notification_recipients,
                                 send_to_recipients)
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        conn = get_smtp_connection(s)
        if conn is None:
            logger.warning('payments: autopay gave up on attempt %s; no SMTP to notify', a.pk)
        configured = settings_for(a.connection).failure_notify_email
        recipients = [e.strip() for e in configured.split(',') if e.strip()] if configured else \
            notification_recipients(a.client_org_id)
        body = (f'Autopay could not collect invoice {a.invoice.invoice_number} for {a.client_org.name} '
                f'after {a.attempt_number} attempt(s).\n\nAmount: {a.amount} {a.currency}\n'
                f'Last error: {a.failure_message or a.failure_code}\n\n'
                'No further automatic attempts will be made for this due date.')
        if conn is not None:
            send_to_recipients(conn, default_from_email(s), recipients,
                               f'Autopay failed: invoice {a.invoice.invoice_number}', body)
    except Exception:  # pragma: no cover
        logger.exception('payments: final failure notification failed')
    audit(None, 'update', a.client_org, a, f'Autopay gave up on invoice {a.invoice.invoice_number}',
          success=False)
    return True
