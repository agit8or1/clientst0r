"""
Autopay: charge the customer-authorized default method when an invoice is due.

Clientst0r decides what is due (invoice due date, less the connection's lead
days); the gateway only collects. One due cycle = one invoice due date. Per
cycle there are at most `autopay_max_attempts` attempts, numbered 1..N, and
(invoice, cycle, number) is unique, so running the command twice (or two
schedulers at once) cannot create a second attempt. Each attempt's
idempotency key is derived from the same triple and sent to the provider, so
even a crash between the provider call and our save cannot double-charge.

Retries: a failed attempt gets `next_retry_at` from the connection's retry
days; after the last attempt the cycle stops and staff are e-mailed once.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from . import services
from .models import GatewaySettings, PaymentAttempt, StoredPaymentMethod

logger = logging.getLogger('payments.autopay')

DUE_STATUSES = ('sent', 'partial', 'overdue')


def cycle_for(invoice):
    return (invoice.due_date or invoice.invoice_date).isoformat()


def candidate_invoices(connection, gs: GatewaySettings, today=None):
    from psa.models import Invoice
    today = today or timezone.localdate()
    horizon = today + timedelta(days=gs.autopay_lead_days)
    clients = (StoredPaymentMethod.objects.filter(connection=connection, is_default=True, authorized_for_autopay=True,
                                                  status='active')
               .values_list('client_org_id', flat=True))
    qs = (Invoice.objects.filter(status__in=DUE_STATUSES, is_credit_memo=False, client_org_id__in=list(clients))
          .filter(Q(due_date__lte=horizon) | Q(due_date__isnull=True, invoice_date__lte=horizon))
          .select_related('organization', 'client_org'))
    for inv in qs:
        if services.connection_for_invoice(inv) == connection:
            yield inv


def next_attempt_number(invoice, cycle, gs):
    """The number of the attempt to make now, or None (in flight, settled,
    waiting for the retry date, or out of attempts)."""
    attempts = list(PaymentAttempt.objects.filter(invoice=invoice, kind='autopay', autopay_cycle=cycle)
                    .order_by('attempt_number'))
    if not attempts:
        return 1
    if any(a.status in PaymentAttempt.OPEN_STATUSES or a.status == 'succeeded' for a in attempts):
        return None
    last = attempts[-1]
    if last.attempt_number >= gs.autopay_max_attempts:
        return None
    if last.next_retry_at and last.next_retry_at > timezone.now():
        return None
    return last.attempt_number + 1


def charge(attempt):
    """Make the provider call for a created autopay attempt."""
    provider = services.provider_for(attempt.connection)
    method = attempt.payment_method
    if attempt.provider == 'stripe':
        from integrations.providers.payment.stripe import StripeError
        customer = method.gateway_customer or services.gateway_customer(attempt.connection, attempt.client_org)
        try:
            pi = provider.charge_off_session(
                customer_id=customer.provider_customer_id, payment_method_id=method.provider_method_id,
                amount=attempt.amount, currency=attempt.currency,
                description=f'Invoice {attempt.invoice.invoice_number}',
                metadata=services._invoice_metadata(attempt), idempotency_key=attempt.idempotency_key)
        except StripeError as exc:
            pi = (exc.body.get('error') or {}).get('payment_intent')
            if pi:
                PaymentAttempt.objects.filter(pk=attempt.pk).update(provider_object_id=pi.get('id', ''))
            return services.record_failure(attempt, code=exc.code or 'card_error', message=str(exc),
                                           provider_status=(pi or {}).get('status', ''))
        except Exception as exc:  # network etc.: the next run retries with the same key
            return services.record_failure(attempt, code='provider_unreachable', message=str(exc))
        PaymentAttempt.objects.filter(pk=attempt.pk).update(provider_object_id=pi.get('id', ''))
        if pi.get('status') == 'requires_action':
            return services.record_failure(attempt, code='authentication_required',
                                           message='The bank asked the customer to authenticate this payment.',
                                           provider_status='requires_action')
        return services.stripe_sync_payment_intent(attempt.connection, pi, attempt)
    return services._gc_create_payment(attempt)


def run(*, now=None, dry_run=False, stdout=None):
    """Create and charge due autopay attempts. Returns a summary dict."""
    from integrations.models import PaymentConnection
    summary = {'created': 0, 'skipped': 0, 'succeeded': 0, 'processing': 0, 'failed': 0}
    conns = PaymentConnection.objects.filter(is_active=True, sync_enabled=True,
                                             provider_type__in=services.GATEWAY_TYPES,
                                             gateway_settings__autopay_enabled=True)
    for conn in conns:
        gs = conn.gateway_settings
        for inv in candidate_invoices(conn, gs):
            amount = services.amount_due(inv)
            if amount <= 0:
                summary['skipped'] += 1
                continue
            method = services.default_method(conn, inv.client_org)
            if method is None or not method.authorized_for_autopay or method.status != 'active':
                summary['skipped'] += 1
                continue
            cycle = cycle_for(inv)
            n = next_attempt_number(inv, cycle, gs)
            if n is None:
                summary['skipped'] += 1
                continue
            if dry_run:
                summary['created'] += 1
                continue
            try:
                with transaction.atomic():
                    attempt = PaymentAttempt.objects.create(
                        invoice=inv, client_org=inv.client_org, connection=conn, provider=conn.provider_type,
                        kind='autopay', payment_method=method, amount=amount, currency=inv.currency or 'USD',
                        idempotency_key=f'autopay-{inv.pk}-{cycle}-{n}', autopay_cycle=cycle, attempt_number=n)
            except IntegrityError:
                summary['skipped'] += 1  # another run made it
                continue
            summary['created'] += 1
            services.audit(None, 'create', inv.client_org, attempt,
                           f'Autopay attempt {n} for invoice {inv.invoice_number}', amount=amount)
            result = charge(attempt)
            result = PaymentAttempt.objects.get(pk=attempt.pk) if result is None else result
            status = getattr(result, 'status', 'failed')
            summary[status if status in summary else 'failed'] += 1
    return summary
