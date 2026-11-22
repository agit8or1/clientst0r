"""Payment processing tests. All provider HTTP is mocked (requests.request);
nothing reaches Stripe or GoCardless."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization, SystemSetting
from integrations.models import PaymentConnection
from integrations.providers.payment import gocardless as gc_mod
from integrations.providers.payment import stripe as stripe_mod
from psa.models import ClientPSASettings, Invoice, InvoiceLineItem, Payment

from . import autopay, services
from .models import (
    Dispute, GatewayCustomer, GatewayEvent, GatewaySettings, PaymentAttempt, Refund, SetupRequest,
    StoredPaymentMethod,
)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

WHSEC = 'whsec_test_secret'
GC_SECRET = 'gc_webhook_secret'


# ---------------------------------------------------------------------------
# Fake provider HTTP
# ---------------------------------------------------------------------------

class FakeHTTP:
    """Routes requests.request(method, url, ...) to handlers keyed by
    (METHOD, path regex). Records every call."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def add(self, method, pattern, body, status=200):
        self.routes.append((method, re.compile(pattern + '$'), body, status))

    def __call__(self, method, url, headers=None, data=None, json=None, params=None, timeout=None):
        path = re.sub(r'^https://[^/]+', '', url)
        self.calls.append({'method': method, 'path': path, 'headers': headers or {}, 'data': data,
                           'json': json, 'params': params})
        for m, rx, body, status in reversed(self.routes):
            if m == method and rx.match(path):
                payload = body(path, data, json) if callable(body) else body
                resp = mock.Mock(status_code=status, content=b'x')
                resp.json.return_value = payload
                return resp
        raise AssertionError(f'unexpected provider call {method} {path}')

    def paths(self, method=None):
        return [c['path'] for c in self.calls if method is None or c['method'] == method]


def stripe_sig(body: bytes, secret=WHSEC, ts=None):
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f'{ts}.'.encode() + body, hashlib.sha256).hexdigest()
    return f't={ts},v1={sig}'


def gc_sig(body: bytes, secret=GC_SECRET):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def pi_obj(pi_id, attempt, *, status='succeeded', amount=10000, fee=320, pm='pm_card_1'):
    return {'id': pi_id, 'object': 'payment_intent', 'status': status, 'amount': amount,
            'amount_received': amount if status == 'succeeded' else 0, 'currency': 'usd',
            'customer': 'cus_1', 'payment_method': pm,
            'metadata': {'clientst0r_attempt': attempt.idempotency_key},
            'latest_charge': {'id': 'ch_1', 'payment_method_details': {'type': 'card'},
                              'balance_transaction': {'fee': fee, 'net': amount - fee, 'currency': 'usd'}}}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class PaymentsBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.acme = Organization.objects.create(name='Acme', slug='pay-acme')
        cls.globex = Organization.objects.create(name='Globex', slug='pay-globex')
        for o in (cls.acme, cls.globex):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True, enabled=True)
        cls.stripe = PaymentConnection.objects.create(provider_type='stripe', name='Stripe', sync_enabled=True,
                                                      base_url='https://api.stripe.com')
        cls.stripe.set_credentials({'api_key': 'sk_test_1', 'webhook_secret': WHSEC, 'publishable_key': 'pk_test'})
        cls.stripe.save()
        cls.inv_a = cls.make_invoice(cls.acme, Decimal('100.00'))
        cls.inv_b = cls.make_invoice(cls.globex, Decimal('250.00'))

    @staticmethod
    def make_invoice(org, amount, due=None, status='sent'):
        inv = Invoice.objects.create(organization=org, client_org=org, title='Managed services',
                                     invoice_date=date.today() - timedelta(days=10),
                                     due_date=due or date.today(), status=status, currency='USD')
        InvoiceLineItem.objects.create(invoice=inv, description='Monthly', quantity=1, unit_price=amount,
                                       is_taxable=False)
        inv.recompute_totals()
        inv.refresh_from_db()
        return inv

    def setUp(self):
        self.http = FakeHTTP()
        patcher = mock.patch('requests.request', side_effect=self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def attempt(self, invoice=None, **kw):
        invoice = invoice or self.inv_a
        defaults = dict(invoice=invoice, client_org=invoice.client_org, connection=self.stripe, provider='stripe',
                        amount=invoice.balance, currency='USD', idempotency_key=services.new_key('t'),
                        status='requires_action')
        defaults.update(kw)
        return PaymentAttempt.objects.create(**defaults)

    def post_stripe(self, event, *, sig=None):
        body = json.dumps(event).encode()
        return Client().post(reverse('payments:stripe_webhook', args=[self.stripe.pk]), data=body,
                             content_type='application/json',
                             HTTP_STRIPE_SIGNATURE=sig if sig is not None else stripe_sig(body))


def ev(event_id, etype, obj):
    return {'id': event_id, 'type': etype, 'data': {'object': obj}}


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------

class SignatureTests(TestCase):
    body = b'{"id":"evt_1"}'

    def test_stripe_valid(self):
        self.assertTrue(stripe_mod.verify_signature(self.body, stripe_sig(self.body), WHSEC))

    def test_stripe_invalid(self):
        self.assertFalse(stripe_mod.verify_signature(self.body, stripe_sig(self.body, 'whsec_other'), WHSEC))
        self.assertFalse(stripe_mod.verify_signature(self.body + b' ', stripe_sig(self.body), WHSEC))
        self.assertFalse(stripe_mod.verify_signature(self.body, '', WHSEC))
        self.assertFalse(stripe_mod.verify_signature(self.body, 't=abc,v1=00', WHSEC))
        self.assertFalse(stripe_mod.verify_signature(self.body, stripe_sig(self.body), ''))

    def test_stripe_expired_and_future(self):
        old = int(time.time()) - 301
        self.assertFalse(stripe_mod.verify_signature(self.body, stripe_sig(self.body, ts=old), WHSEC))
        future = int(time.time()) + 301
        self.assertFalse(stripe_mod.verify_signature(self.body, stripe_sig(self.body, ts=future), WHSEC))
        self.assertTrue(stripe_mod.verify_signature(self.body, stripe_sig(self.body, ts=int(time.time()) - 200),
                                                    WHSEC))

    def test_stripe_multiple_v1_any_matches(self):
        good = stripe_sig(self.body)
        ts = good.split(',')[0]
        header = f'{ts},v1=deadbeef,{good.split(",")[1]}'
        self.assertTrue(stripe_mod.verify_signature(self.body, header, WHSEC))

    def test_gocardless(self):
        self.assertTrue(gc_mod.verify_signature(self.body, gc_sig(self.body), GC_SECRET))
        self.assertFalse(gc_mod.verify_signature(self.body, gc_sig(self.body, 'other'), GC_SECRET))
        self.assertFalse(gc_mod.verify_signature(self.body, '', GC_SECRET))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebhookEndpointTests(PaymentsBase):

    def test_bad_signature_rejected_and_not_recorded(self):
        a = self.attempt()
        resp = self.post_stripe(ev('evt_bad', 'payment_intent.succeeded', pi_obj('pi_1', a)), sig='t=1,v1=00')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(GatewayEvent.objects.exists())
        self.assertFalse(Payment.objects.filter(invoice=self.inv_a).exists())

    def test_expired_signature_rejected(self):
        a = self.attempt()
        body = json.dumps(ev('evt_old', 'payment_intent.succeeded', pi_obj('pi_1', a))).encode()
        resp = Client().post(reverse('payments:stripe_webhook', args=[self.stripe.pk]), data=body,
                             content_type='application/json',
                             HTTP_STRIPE_SIGNATURE=stripe_sig(body, ts=int(time.time()) - 600))
        self.assertEqual(resp.status_code, 400)

    def test_wrong_provider_endpoint_404(self):
        resp = Client().post(reverse('payments:gocardless_webhook', args=[self.stripe.pk]), data=b'{}',
                             content_type='application/json')
        self.assertEqual(resp.status_code, 404)

    def test_get_not_allowed(self):
        resp = Client().get(reverse('payments:stripe_webhook', args=[self.stripe.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_unsigned_post_refused_on_both_webhooks(self):
        # SR-36: the csrf_exempt webhooks rely on the signature alone; a POST
        # with no signature header at all is refused and records nothing.
        gc = PaymentConnection.objects.create(provider_type='gocardless', name='GC-unsigned')
        gc.set_credentials({'access_token': 't', 'webhook_secret': GC_SECRET, 'environment': 'sandbox'})
        gc.save()
        for name, pk in (('stripe_webhook', self.stripe.pk), ('gocardless_webhook', gc.pk)):
            resp = Client(enforce_csrf_checks=True).post(
                reverse('payments:' + name, args=[pk]), data=b'{"events": []}',
                content_type='application/json')
            self.assertTrue(400 <= resp.status_code < 500, (name, resp.status_code))
        self.assertFalse(GatewayEvent.objects.exists())


# ---------------------------------------------------------------------------
# Settlement exactly once
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StripeSettlementTests(PaymentsBase):

    def test_success_creates_payment_with_fee_separate(self):
        a = self.attempt()
        resp = self.post_stripe(ev('evt_1', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        self.assertEqual(resp.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, 'succeeded')
        self.assertEqual(a.fee_amount, Decimal('3.20'))
        self.assertEqual(a.net_amount, Decimal('96.80'))
        self.assertEqual(a.accounting_post_status, 'pending')
        p = a.local_payment
        self.assertEqual(p.amount, Decimal('100.00'))  # gross, fee not netted off
        self.assertEqual(p.method, 'credit_card')
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.status, 'paid')

    def test_duplicate_event_processed_once(self):
        a = self.attempt()
        event = ev('evt_dup', 'payment_intent.succeeded', pi_obj('pi_1', a))
        self.assertEqual(self.post_stripe(event).content, b'processed')
        self.assertEqual(self.post_stripe(event).content, b'duplicate')
        self.assertEqual(GatewayEvent.objects.filter(event_id='evt_dup').count(), 1)
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)

    def test_distinct_events_same_payment_one_payment_row(self):
        a = self.attempt()
        self.post_stripe(ev('evt_a', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        self.post_stripe(ev('evt_b', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)

    def test_success_before_checkout_completed(self):
        a = self.attempt(provider_session_id='cs_1')
        self.post_stripe(ev('evt_pi', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        session = {'id': 'cs_1', 'mode': 'payment', 'payment_status': 'paid', 'payment_intent': 'pi_1',
                   'customer': 'cus_1', 'metadata': {'clientst0r_attempt': a.idempotency_key}}
        self.http.add('GET', '/v1/payment_intents/pi_1', pi_obj('pi_1', a))
        self.post_stripe(ev('evt_cs', 'checkout.session.completed', session))
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)
        a.refresh_from_db()
        self.assertEqual(a.status, 'succeeded')

    def test_checkout_completed_before_success(self):
        payer = User.objects.create_user('pay-payer', 'payer@acme.test', 'pw')
        a = self.attempt(provider_session_id='cs_1', save_for_autopay=True, created_by=payer)
        GatewayCustomer.objects.create(connection=self.stripe, client_org=self.acme, provider_customer_id='cus_1')
        self.http.add('GET', '/v1/payment_intents/pi_1', pi_obj('pi_1', a))
        self.http.add('GET', '/v1/payment_methods/pm_card_1', {
            'id': 'pm_card_1', 'type': 'card', 'customer': 'cus_1',
            'card': {'brand': 'visa', 'last4': '4242', 'exp_month': 12, 'exp_year': 2030}})
        session = {'id': 'cs_1', 'mode': 'payment', 'payment_status': 'paid', 'payment_intent': 'pi_1',
                   'customer': 'cus_1', 'metadata': {'clientst0r_attempt': a.idempotency_key}}
        self.post_stripe(ev('evt_cs', 'checkout.session.completed', session))
        self.post_stripe(ev('evt_pi', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)
        method = StoredPaymentMethod.objects.get(provider_method_id='pm_card_1')
        self.assertEqual((method.brand, method.last4, method.client_org), ('visa', '4242', self.acme))
        self.assertTrue(method.is_default)
        self.assertTrue(method.authorized_for_autopay)
        self.assertEqual(method.autopay_authorized_by, payer)

    def test_async_processing_then_success(self):
        a = self.attempt()
        self.post_stripe(ev('evt_p', 'payment_intent.processing', pi_obj('pi_1', a, status='processing')))
        a.refresh_from_db()
        self.assertEqual(a.status, 'processing')
        self.assertFalse(Payment.objects.filter(invoice=self.inv_a).exists())
        self.assertEqual(services.amount_due(self.inv_a), Decimal('0.00'))  # in flight, not payable twice
        self.post_stripe(ev('evt_s', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        a.refresh_from_db()
        self.assertEqual(a.status, 'succeeded')
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)

    def test_payment_failed(self):
        a = self.attempt()
        pi = pi_obj('pi_1', a, status='requires_payment_method')
        pi['last_payment_error'] = {'code': 'card_declined', 'decline_code': 'insufficient_funds',
                                    'message': 'Your card has insufficient funds.'}
        self.post_stripe(ev('evt_f', 'payment_intent.payment_failed', pi))
        a.refresh_from_db()
        self.assertEqual((a.status, a.failure_code), ('failed', 'insufficient_funds'))
        self.assertFalse(Payment.objects.filter(invoice=self.inv_a).exists())

    def test_handler_error_recorded_and_retried(self):
        a = self.attempt()
        event = ev('evt_err', 'payment_intent.succeeded', pi_obj('pi_1', a))
        with mock.patch('payments.services.record_success', side_effect=RuntimeError('boom')):
            resp = self.post_stripe(event)
        self.assertEqual(resp.status_code, 500)
        row = GatewayEvent.objects.get(event_id='evt_err')
        self.assertIn('boom', row.error)
        self.assertIsNone(row.processed_at)
        self.assertEqual(self.post_stripe(event).content, b'processed')
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)

    def test_attempt_on_other_connection_ignored(self):
        other = PaymentConnection.objects.create(provider_type='stripe', name='Other', sync_enabled=True)
        a = self.attempt(connection=other)
        self.post_stripe(ev('evt_x', 'payment_intent.succeeded', pi_obj('pi_1', a)))
        self.assertFalse(Payment.objects.filter(invoice=self.inv_a).exists())


# ---------------------------------------------------------------------------
# Refunds and disputes
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RefundDisputeTests(PaymentsBase):

    def settled(self):
        a = self.attempt(provider_object_id='pi_1')
        services.record_success(a, amount_received=Decimal('100.00'), provider_object_id='pi_1')
        a.refresh_from_db()
        return a

    def test_partial_refund(self):
        a = self.settled()

        def refund_body(path, data, js):
            meta = dict(data).get('metadata[clientst0r_refund]')
            return {'id': 're_1', 'status': 'succeeded', 'metadata': {'clientst0r_refund': meta}}
        self.http.add('POST', '/v1/refunds', refund_body)
        refund = services.request_refund(a, Decimal('40.00'), None, 'Goodwill')
        self.assertEqual(refund.status, 'succeeded')
        self.assertEqual(refund.local_payment.amount, Decimal('-40.00'))
        self.assertEqual(refund.accounting_post_status, 'pending')
        call = [c for c in self.http.calls if c['path'] == '/v1/refunds'][0]
        self.assertIn(('amount', '4000'), call['data'])
        self.assertEqual(call['headers']['Idempotency-Key'], refund.idempotency_key)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.amount_paid, Decimal('60.00'))
        self.assertEqual(self.inv_a.status, 'partial')
        a.refresh_from_db()
        self.assertEqual(a.refundable_amount, Decimal('60.00'))
        # The webhook for the same refund changes nothing.
        charge = {'id': 'ch_1', 'payment_intent': 'pi_1', 'refunds': {'data': [
            {'id': 're_1', 'amount': 4000, 'currency': 'usd', 'status': 'succeeded',
             'metadata': {'clientst0r_refund': refund.idempotency_key}}]}}
        self.post_stripe(ev('evt_r', 'charge.refunded', charge))
        self.assertEqual(Refund.objects.count(), 1)
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a, amount__lt=0).count(), 1)

    def test_refund_over_refundable_refused(self):
        a = self.settled()
        with self.assertRaises(services.PaymentError):
            services.request_refund(a, Decimal('100.01'), None)
        self.assertFalse(Refund.objects.exists())

    def test_full_refund_reopens_invoice(self):
        a = self.settled()
        self.http.add('POST', '/v1/refunds', {'id': 're_2', 'status': 'succeeded'})
        services.request_refund(a, Decimal('100.00'), None)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.amount_paid, Decimal('0.00'))
        self.assertIn(self.inv_a.status, ('sent', 'overdue'))

    def test_dashboard_refund_via_webhook(self):
        self.settled()
        self.post_stripe(ev('evt_rd', 'refund.updated', {'id': 're_d', 'payment_intent': 'pi_1', 'amount': 2500,
                                                         'currency': 'usd', 'status': 'succeeded', 'metadata': {}}))
        r = Refund.objects.get(provider_refund_id='re_d')
        self.assertEqual(r.amount, Decimal('25.00'))
        self.assertEqual(r.local_payment.amount, Decimal('-25.00'))

    def test_dispute_recorded_then_lost_once(self):
        self.settled()
        dispute = {'id': 'dp_1', 'payment_intent': 'pi_1', 'charge': 'ch_1', 'amount': 10000, 'currency': 'usd',
                   'status': 'needs_response', 'reason': 'fraudulent',
                   'evidence_details': {'due_by': int(time.time()) + 86400}}
        self.post_stripe(ev('evt_d1', 'charge.dispute.created', dispute))
        d = Dispute.objects.get(provider_dispute_id='dp_1')
        self.assertEqual((d.status, d.reason), ('open', 'fraudulent'))
        self.assertIsNotNone(d.evidence_due_by)
        self.assertIsNone(d.local_payment_id)
        closed = dict(dispute, status='lost')
        self.post_stripe(ev('evt_d2', 'charge.dispute.closed', closed))
        self.post_stripe(ev('evt_d3', 'charge.dispute.closed', closed))
        d.refresh_from_db()
        self.assertEqual(d.status, 'lost')
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a, amount__lt=0).count(), 1)
        self.assertEqual(d.accounting_post_status, 'pending')

    def test_dispute_won_changes_nothing(self):
        self.settled()
        dispute = {'id': 'dp_2', 'payment_intent': 'pi_1', 'amount': 10000, 'currency': 'usd', 'status': 'won',
                   'reason': 'product_not_received'}
        self.post_stripe(ev('evt_dw', 'charge.dispute.closed', dispute))
        self.assertEqual(Dispute.objects.get().status, 'won')
        self.assertFalse(Payment.objects.filter(amount__lt=0).exists())


# ---------------------------------------------------------------------------
# Autopay
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AutopayTests(PaymentsBase):

    def setUp(self):
        super().setUp()
        self.gs = services.settings_for(self.stripe)
        self.gs.autopay_enabled = True
        self.gs.autopay_max_attempts = 2
        self.gs.autopay_retry_days = '3'
        self.gs.save()
        self.customer = GatewayCustomer.objects.create(connection=self.stripe, client_org=self.acme,
                                                       provider_customer_id='cus_1')
        self.method = StoredPaymentMethod.objects.create(
            connection=self.stripe, client_org=self.acme, gateway_customer=self.customer,
            provider_method_id='pm_1', brand='visa', last4='4242', is_default=True,
            authorized_for_autopay=True, autopay_authorized_at=timezone.now())

    def decline(self):
        self.http.add('POST', '/v1/payment_intents', {'error': {
            'type': 'card_error', 'code': 'card_declined', 'decline_code': 'generic_decline',
            'message': 'Your card was declined.',
            'payment_intent': {'id': 'pi_dec', 'status': 'requires_payment_method'}}}, status=402)

    def test_running_twice_creates_one_attempt(self):
        self.http.add('POST', '/v1/payment_intents', lambda p, d, j: pi_obj(
            'pi_auto', PaymentAttempt.objects.get(kind='autopay')))
        call_command('run_autopay', verbosity=0)
        call_command('run_autopay', verbosity=0)
        attempts = PaymentAttempt.objects.filter(invoice=self.inv_a, kind='autopay')
        self.assertEqual(attempts.count(), 1)
        a = attempts.get()
        self.assertEqual(a.status, 'succeeded')
        self.assertEqual(a.idempotency_key, f'autopay-{self.inv_a.pk}-{self.inv_a.due_date.isoformat()}-1')
        post = [c for c in self.http.calls if c['path'] == '/v1/payment_intents'][0]
        self.assertEqual(post['headers']['Idempotency-Key'], a.idempotency_key)
        self.assertIn(('off_session', 'true'), post['data'])
        self.assertEqual(len([c for c in self.http.calls if c['method'] == 'POST']), 1)
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)
        # Other customer (no authorized method) untouched.
        self.assertFalse(PaymentAttempt.objects.filter(invoice=self.inv_b).exists())

    def test_unauthorized_method_not_charged(self):
        self.method.authorized_for_autopay = False
        self.method.save()
        autopay.run()
        self.assertFalse(PaymentAttempt.objects.exists())

    def test_not_yet_due_not_charged(self):
        Invoice.objects.filter(pk=self.inv_a.pk).update(due_date=date.today() + timedelta(days=5))
        autopay.run()
        self.assertFalse(PaymentAttempt.objects.exists())

    def test_failure_schedules_retry_then_gives_up(self):
        self.decline()
        autopay.run()
        a1 = PaymentAttempt.objects.get(attempt_number=1)
        self.assertEqual((a1.status, a1.failure_code), ('failed', 'generic_decline'))
        self.assertIsNotNone(a1.next_retry_at)
        self.assertAlmostEqual((a1.next_retry_at - timezone.now()).days, 2, delta=1)
        autopay.run()  # before the retry date: nothing
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        PaymentAttempt.objects.filter(pk=a1.pk).update(next_retry_at=timezone.now() - timedelta(minutes=1))
        with mock.patch('payments.services.notify_final_failure') as notify, \
                self.captureOnCommitCallbacks(execute=True):
            autopay.run()
        a2 = PaymentAttempt.objects.get(attempt_number=2)
        self.assertEqual(a2.status, 'failed')
        self.assertIsNone(a2.next_retry_at)
        notify.assert_called_once_with(a2.pk)
        autopay.run()  # out of attempts
        self.assertEqual(PaymentAttempt.objects.count(), 2)

    def test_final_failure_notified_once(self):
        a = self.attempt(kind='autopay', autopay_cycle='2026-01-01', attempt_number=2, status='failed')
        self.assertTrue(services.notify_final_failure(a.pk))
        self.assertFalse(services.notify_final_failure(a.pk))

    def test_async_failure_via_webhook_schedules_retry(self):
        self.http.add('POST', '/v1/payment_intents', lambda p, d, j: pi_obj(
            'pi_auto', PaymentAttempt.objects.get(kind='autopay'), status='processing'))
        autopay.run()
        a = PaymentAttempt.objects.get()
        self.assertEqual(a.status, 'processing')
        pi = pi_obj('pi_auto', a, status='requires_payment_method')
        pi['last_payment_error'] = {'code': 'insufficient_funds', 'message': 'ACH returned'}
        self.post_stripe(ev('evt_af', 'payment_intent.payment_failed', pi))
        a.refresh_from_db()
        self.assertEqual(a.status, 'failed')
        self.assertIsNotNone(a.next_retry_at)


# ---------------------------------------------------------------------------
# GoCardless
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GoCardlessTests(PaymentsBase):

    def setUp(self):
        super().setUp()
        # One MSP per install: the gateway connection is install-global.
        PaymentConnection.objects.filter(pk=self.stripe.pk).update(sync_enabled=False)
        self.gc = PaymentConnection.objects.create(provider_type='gocardless', name='GC', sync_enabled=True)
        self.gc.set_credentials({'access_token': 'sandbox_tok', 'webhook_secret': GC_SECRET,
                                 'environment': 'sandbox'})
        self.gc.save()

    def post_gc(self, events, sig=None):
        body = json.dumps({'events': events}).encode()
        return Client().post(reverse('payments:gocardless_webhook', args=[self.gc.pk]), data=body,
                             content_type='application/json',
                             HTTP_WEBHOOK_SIGNATURE=sig if sig is not None else gc_sig(body))

    def test_sandbox_base_url(self):
        p = services.provider_for(self.gc)
        self.assertEqual(p.connection.base_url, gc_mod.SANDBOX_URL)

    def test_invalid_signature_498(self):
        self.assertEqual(self.post_gc([{'id': 'EV1'}], sig='00').status_code, 498)
        self.assertFalse(GatewayEvent.objects.exists())

    def test_mandate_flow_then_payment_states(self):
        self.assertEqual(services.connection_for_invoice(self.inv_b), self.gc)
        self.http.add('POST', '/billing_requests', {'billing_requests': {'id': 'BRQ1'}})
        self.http.add('POST', '/billing_request_flows', {'billing_request_flows': {
            'authorisation_url': 'https://pay-sandbox.gocardless.com/flow/BRF1'}})
        payer = User.objects.create_user('pay-gc-payer', 'p@globex.test', 'pw')
        attempt, url = services.start_checkout(self.inv_b, payer, save_for_autopay=True,
                                               success_url=lambda a: 'https://x/ok', cancel_url=lambda a: 'https://x/no')
        self.assertEqual(url, 'https://pay-sandbox.gocardless.com/flow/BRF1')
        br_call = [c for c in self.http.calls if c['path'] == '/billing_requests'][0]
        self.assertIn('mandate_request', br_call['json']['billing_requests'])
        self.assertNotIn('payment_request', br_call['json']['billing_requests'])
        self.assertTrue(br_call['headers']['Idempotency-Key'])
        self.assertEqual(br_call['headers']['GoCardless-Version'], gc_mod.API_VERSION)

        self.http.add('GET', '/billing_requests/BRQ1', {'billing_requests': {
            'id': 'BRQ1', 'status': 'fulfilled', 'metadata': {'clientst0r_attempt': attempt.idempotency_key},
            'links': {'mandate_request_mandate': 'MD1', 'customer': 'CU1'}}})
        self.http.add('GET', '/mandates/MD1', {'mandates': {'id': 'MD1', 'status': 'pending_submission',
                                                            'scheme': 'ach',
                                                            'links': {'customer': 'CU1', 'customer_bank_account': 'BA1'}}})
        self.http.add('GET', '/customer_bank_accounts/BA1', {'customer_bank_accounts': {
            'id': 'BA1', 'account_number_ending': '6789', 'bank_name': 'First Bank'}})
        self.http.add('POST', '/payments', {'payments': {'id': 'PM1', 'status': 'pending_submission',
                                                         'metadata': {'clientst0r_attempt': attempt.idempotency_key}}})
        r = self.post_gc([{'id': 'EV1', 'resource_type': 'billing_requests', 'action': 'fulfilled',
                           'links': {'billing_request': 'BRQ1'}}])
        self.assertEqual(r.status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual((attempt.status, attempt.provider_object_id), ('processing', 'PM1'))
        method = StoredPaymentMethod.objects.get(provider_method_id='MD1')
        self.assertEqual((method.last4, method.bank_name, method.status), ('6789', 'First Bank', 'pending'))
        self.assertTrue(method.authorized_for_autopay)
        self.assertEqual(method.autopay_authorized_by, payer)
        pay_call = [c for c in self.http.calls if c['path'] == '/payments'][0]
        self.assertEqual(pay_call['json']['payments']['amount'], 25000)
        self.assertEqual(pay_call['json']['payments']['links']['mandate'], 'MD1')
        self.assertEqual(pay_call['headers']['Idempotency-Key'], attempt.idempotency_key)

        # submitted -> confirmed: settles once; paid_out again changes nothing.
        for i, state in enumerate(('submitted', 'confirmed', 'paid_out')):
            self.http.add('GET', '/payments/PM1', {'payments': {
                'id': 'PM1', 'status': state, 'metadata': {'clientst0r_attempt': attempt.idempotency_key}}})
            self.post_gc([{'id': f'EVP{i}', 'resource_type': 'payments', 'action': state,
                           'links': {'payment': 'PM1'}}])
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'succeeded')
        self.assertEqual(Payment.objects.filter(invoice=self.inv_b).count(), 1)
        self.assertEqual(Payment.objects.get(invoice=self.inv_b).method, 'ach')

        # charged back -> lost dispute, one reversal
        self.http.add('GET', '/payments/PM1', {'payments': {'id': 'PM1', 'status': 'charged_back', 'metadata': {}}})
        self.post_gc([{'id': 'EVCB', 'resource_type': 'payments', 'action': 'charged_back',
                       'links': {'payment': 'PM1'}, 'details': {'cause': 'payment_charged_back'}}])
        self.assertEqual(Dispute.objects.get().status, 'lost')
        self.assertEqual(Payment.objects.filter(invoice=self.inv_b, amount__lt=0).count(), 1)

    def test_failed_payment_and_mandate_cancelled(self):
        method = StoredPaymentMethod.objects.create(connection=self.gc, client_org=self.globex,
                                                    provider_method_id='MD2', mandate_id='MD2',
                                                    method_type='direct_debit', is_default=True,
                                                    authorized_for_autopay=True)
        a = self.attempt(self.inv_b, connection=self.gc, provider='gocardless', provider_object_id='PM2',
                         payment_method=method, status='processing')
        self.http.add('GET', '/payments/PM2', {'payments': {'id': 'PM2', 'status': 'failed', 'metadata': {}}})
        self.post_gc([{'id': 'EVF', 'resource_type': 'payments', 'action': 'failed', 'links': {'payment': 'PM2'},
                       'details': {'cause': 'insufficient_funds'}},
                      {'id': 'EVM', 'resource_type': 'mandates', 'action': 'cancelled', 'links': {'mandate': 'MD2'}}])
        a.refresh_from_db()
        self.assertEqual((a.status, a.failure_code), ('failed', 'insufficient_funds'))
        method.refresh_from_db()
        self.assertEqual(method.status, 'inactive')
        self.assertFalse(method.authorized_for_autopay)

    def test_refund_total_amount_confirmation(self):
        a = self.attempt(self.inv_b, connection=self.gc, provider='gocardless', provider_object_id='PM3')
        services.record_success(a, provider_object_id='PM3')
        self.http.add('POST', '/refunds', {'refunds': {'id': 'RF1'}})
        services.request_refund(a, Decimal('50.00'), None)
        body = [c for c in self.http.calls if c['path'] == '/refunds'][0]['json']['refunds']
        self.assertEqual((body['amount'], body['total_amount_confirmation']), (5000, 5000))
        r = Refund.objects.get()
        self.assertEqual(r.status, 'pending')
        self.http.add('GET', '/refunds/RF1', {'refunds': {'id': 'RF1', 'amount': 5000, 'currency': 'USD',
                                                          'links': {'payment': 'PM3'},
                                                          'metadata': {'clientst0r_refund': r.idempotency_key}}})
        self.post_gc([{'id': 'EVR', 'resource_type': 'refunds', 'action': 'paid', 'links': {'refund': 'RF1'}}])
        r.refresh_from_db()
        self.assertEqual(r.status, 'succeeded')
        self.assertEqual(r.local_payment.amount, Decimal('-50.00'))


# ---------------------------------------------------------------------------
# Portal: billing contacts only, tenant isolation
# ---------------------------------------------------------------------------

def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalBillingTests(PaymentsBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        billing_role = RoleTemplate.objects.filter(seed_key='customer_billing_contact').first() or \
            RoleTemplate.objects.create(name='Billing Contact (test)', portal_billing_contact=True)
        cls.billing_role = billing_role
        cls.alice = User.objects.create_user('pay-alice', 'alice@acme.test', 'pw')     # Acme billing contact
        cls.bob = User.objects.create_user('pay-bob', 'bob@globex.test', 'pw')         # Globex billing contact
        cls.carl = User.objects.create_user('pay-carl', 'carl@acme.test', 'pw')        # Acme, not billing
        Membership.objects.create(user=cls.alice, organization=cls.acme, role=Role.READONLY,
                                  role_template=billing_role, is_active=True)
        Membership.objects.create(user=cls.bob, organization=cls.globex, role=Role.READONLY,
                                  role_template=billing_role, is_active=True)
        Membership.objects.create(user=cls.carl, organization=cls.acme, role=Role.OWNER, is_active=True)
        cls.pay_b = Payment.objects.create(invoice=cls.inv_b, amount=Decimal('10.00'), paid_on=date.today())
        cls.method_b = StoredPaymentMethod.objects.create(connection=cls.stripe, client_org=cls.globex,
                                                          provider_method_id='pm_b', last4='1111')

    def test_billing_home_lists_own_invoices_only(self):
        r = _login(self.alice).get(reverse('portal:billing_home'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.inv_a.invoice_number)
        self.assertNotContains(r, self.inv_b.invoice_number)
        self.assertContains(r, '100.00')

    def test_non_billing_member_refused(self):
        c = _login(self.carl)
        for url in (reverse('portal:billing_home'), reverse('portal:billing_invoice', args=[self.inv_a.pk]),
                    reverse('portal:billing_methods')):
            self.assertEqual(c.get(url).status_code, 403, url)
        self.assertEqual(c.post(reverse('portal:billing_invoice_pay', args=[self.inv_a.pk])).status_code, 403)
        self.assertNotContains(c.get(reverse('portal:kb_list')), 'portal/billing/')

    def test_nav_link_for_billing_contact(self):
        self.assertContains(_login(self.alice).get(reverse('portal:billing_home')), 'href="/portal/billing/"')

    def test_idor_other_customer(self):
        c = _login(self.alice)
        attempt_b = self.attempt(self.inv_b)
        setup_b = SetupRequest.objects.create(connection=self.stripe, client_org=self.globex)
        self.assertEqual(c.get(reverse('portal:billing_invoice', args=[self.inv_b.pk])).status_code, 404)
        self.assertEqual(c.post(reverse('portal:billing_invoice_pay', args=[self.inv_b.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('portal:billing_receipt', args=[self.pay_b.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('portal:billing_pay_return', args=[attempt_b.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('portal:billing_pay_cancel', args=[attempt_b.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('portal:billing_setup_return', args=[setup_b.pk])).status_code, 404)
        self.assertEqual(c.post(reverse('portal:billing_method_action', args=[self.method_b.pk]),
                                {'action': 'remove'}).status_code, 404)
        self.assertEqual(self.http.calls, [])
        self.method_b.refresh_from_db()
        self.assertEqual(self.method_b.status, 'active')

    def test_draft_invoice_hidden(self):
        draft = self.make_invoice(self.acme, Decimal('5.00'), status='draft')
        self.assertEqual(_login(self.alice).get(reverse('portal:billing_invoice', args=[draft.pk])).status_code, 404)

    def test_portal_invoice_layout_branding_and_boundary(self):
        """Phase 102.5: the portal renders the invoice's stored layout, the MSP footer escaped,
        and never another customer's invoice or ticket subjects."""
        from core.models import SystemSetting
        from psa.models import InvoiceLineItem
        ss = SystemSetting.get_settings()
        ss.invoice_footer_text = 'Pay <b>now</b>'
        ss.save()
        Invoice.objects.filter(pk=self.inv_a.pk).update(presentation='monthly')
        r = _login(self.alice).get(reverse('portal:billing_invoice', args=[self.inv_a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<th>Category</th>', html=False)
        self.assertContains(r, 'Pay &lt;b&gt;now&lt;/b&gt;')
        self.assertNotContains(r, 'Pay <b>now</b>')
        self.assertEqual(_login(self.alice).get(reverse('portal:billing_invoice', args=[self.inv_b.pk])).status_code, 404)
        self.assertEqual(InvoiceLineItem.objects.filter(invoice=self.inv_a).count(),
                         len(r.context['present']['lines']))

    def test_invoice_detail_hides_internal_fields(self):
        li = self.inv_a.line_items.first()
        li.gl_account_code = 'GL-SECRET-4000'
        li.save()
        Invoice.objects.filter(pk=self.inv_a.pk).update(notes='internal margin 40%')
        r = _login(self.alice).get(reverse('portal:billing_invoice', args=[self.inv_a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'GL-SECRET-4000')
        self.assertNotContains(r, 'internal margin')
        self.assertContains(r, 'Pay now')

    def test_pay_now_redirects_to_stripe_checkout(self):
        self.http.add('POST', '/v1/customers', {'id': 'cus_new'})
        self.http.add('POST', '/v1/checkout/sessions', {'id': 'cs_new', 'url': 'https://checkout.stripe.com/c/cs_new'})
        r = _login(self.alice).post(reverse('portal:billing_invoice_pay', args=[self.inv_a.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://checkout.stripe.com/c/cs_new')
        a = PaymentAttempt.objects.get(invoice=self.inv_a)
        self.assertEqual((a.status, a.provider_session_id, a.amount), ('requires_action', 'cs_new', Decimal('100.00')))
        session = dict([c for c in self.http.calls if c['path'] == '/v1/checkout/sessions'][0]['data'])
        self.assertEqual(session['mode'], 'payment')
        self.assertEqual(session['line_items[0][price_data][unit_amount]'], '10000')
        self.assertEqual(session['payment_intent_data[metadata][clientst0r_attempt]'], a.idempotency_key)
        self.assertNotIn('payment_intent_data[setup_future_usage]', session)
        # Collect-only: no Stripe invoices, subscriptions, prices or products.
        for path in self.http.paths():
            self.assertNotRegex(path, r'/v1/(invoices|subscriptions|prices|products)')
        self.assertEqual(GatewayCustomer.objects.get(client_org=self.acme).provider_customer_id, 'cus_new')

    def test_save_for_autopay_requires_consent(self):
        r = _login(self.alice).post(reverse('portal:billing_invoice_pay', args=[self.inv_a.pk]),
                                    {'save_for_autopay': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PaymentAttempt.objects.exists())

    def test_return_page_settles_without_webhook(self):
        a = self.attempt(provider_session_id='cs_r')
        self.http.add('GET', '/v1/checkout/sessions/cs_r', {
            'id': 'cs_r', 'mode': 'payment', 'payment_status': 'paid', 'payment_intent': 'pi_r',
            'metadata': {'clientst0r_attempt': a.idempotency_key}})
        self.http.add('GET', '/v1/payment_intents/pi_r', pi_obj('pi_r', a))
        r = _login(self.alice).get(reverse('portal:billing_pay_return', args=[a.pk]))
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.status, 'succeeded')
        # Webhook arriving afterwards: still one payment.
        self.post_stripe(ev('evt_late', 'payment_intent.succeeded', pi_obj('pi_r', a)))
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)

    def test_receipt_pdf(self):
        a = self.attempt(provider_object_id='pi_rc')
        a, _ = services.record_success(a, amount_received=Decimal('100.00'))
        r = _login(self.alice).get(reverse('portal:billing_receipt', args=[a.local_payment_id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_autopay_toggle_records_consent(self):
        m = StoredPaymentMethod.objects.create(connection=self.stripe, client_org=self.acme,
                                               provider_method_id='pm_a', last4='4242', is_default=False)
        c = _login(self.alice)
        url = reverse('portal:billing_method_action', args=[m.pk])
        c.post(url, {'action': 'autopay_on'})  # no consent
        m.refresh_from_db()
        self.assertFalse(m.authorized_for_autopay)
        c.post(url, {'action': 'autopay_on', 'autopay_consent': 'on'})
        m.refresh_from_db()
        self.assertTrue(m.authorized_for_autopay and m.is_default)
        self.assertEqual(m.autopay_authorized_by, self.alice)
        self.assertIsNotNone(m.autopay_authorized_at)
        c.post(url, {'action': 'autopay_off'})
        m.refresh_from_db()
        self.assertFalse(m.authorized_for_autopay)

    def test_remove_method_detaches_at_provider(self):
        m = StoredPaymentMethod.objects.create(connection=self.stripe, client_org=self.acme,
                                               provider_method_id='pm_rm', last4='0005')
        self.http.add('POST', '/v1/payment_methods/pm_rm/detach', {'id': 'pm_rm'})
        _login(self.alice).post(reverse('portal:billing_method_action', args=[m.pk]), {'action': 'remove'})
        m.refresh_from_db()
        self.assertEqual(m.status, 'detached')

    def test_add_method_uses_hosted_setup(self):
        GatewayCustomer.objects.create(connection=self.stripe, client_org=self.acme, provider_customer_id='cus_a')
        self.http.add('POST', '/v1/checkout/sessions', {'id': 'cs_set', 'url': 'https://checkout.stripe.com/c/cs_set'})
        r = _login(self.alice).post(reverse('portal:billing_method_add'))
        self.assertEqual(r['Location'], 'https://checkout.stripe.com/c/cs_set')
        data = dict(self.http.calls[0]['data'])
        self.assertEqual(data['mode'], 'setup')
        setup = SetupRequest.objects.get()
        self.assertEqual((setup.client_org, setup.provider_reference), (self.acme, 'cs_set'))
        # Completion via webhook stores the method.
        self.http.add('GET', '/v1/setup_intents/seti_1', {'id': 'seti_1', 'status': 'succeeded',
                                                          'payment_method': 'pm_new'})
        self.http.add('GET', '/v1/payment_methods/pm_new', {'id': 'pm_new', 'type': 'us_bank_account',
                                                            'us_bank_account': {'last4': '6789', 'bank_name': 'Chase'}})
        self.post_stripe(ev('evt_set', 'checkout.session.completed', {
            'id': 'cs_set', 'mode': 'setup', 'setup_intent': 'seti_1', 'customer': 'cus_a', 'metadata': {}}))
        m = StoredPaymentMethod.objects.get(provider_method_id='pm_new')
        self.assertEqual((m.method_type, m.last4, m.bank_name, m.client_org), ('us_bank_account', '6789', 'Chase',
                                                                              self.acme))
        self.assertFalse(m.authorized_for_autopay)

    def test_no_connection_no_pay_button(self):
        PaymentConnection.objects.filter(pk=self.stripe.pk).update(sync_enabled=False)
        r = _login(self.alice).get(reverse('portal:billing_invoice', args=[self.inv_a.pk]))
        self.assertNotContains(r, 'Pay now')
        r = _login(self.alice).post(reverse('portal:billing_invoice_pay', args=[self.inv_a.pk]))
        self.assertFalse(PaymentAttempt.objects.exists())

    def test_customer_cannot_open_staff_payments(self):
        r = _login(self.alice).get(reverse('payments:index'))
        self.assertIn(r.status_code, (302, 403))


# ---------------------------------------------------------------------------
# Staff permission gates
# ---------------------------------------------------------------------------

def make_staff(username, **flags):
    from accounts.models import UserType
    user = User.objects.create_user(username, f'{username}@msp.test', 'pw')
    role = RoleTemplate.objects.create(name=f'role-{username}', **flags)
    profile = user.profile
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    return user


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StaffPermissionTests(PaymentsBase):

    def settled(self):
        a = self.attempt(provider_object_id='pi_s')
        a, _ = services.record_success(a, amount_received=Decimal('100.00'))
        return a

    def test_refund_requires_process_refunds(self):
        a = self.settled()
        viewer = make_staff('pay-viewer', billing_view_invoices=True)
        c = _login(viewer)
        self.assertEqual(c.get(reverse('payments:attempt_detail', args=[a.pk])).status_code, 200)
        r = c.post(reverse('payments:attempt_refund', args=[a.pk]), {'amount': '10.00', 'confirm': 'on'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Refund.objects.exists())

        refunder = make_staff('pay-refunder', billing_view_invoices=True, process_refunds=True)
        self.http.add('POST', '/v1/refunds', {'id': 're_s', 'status': 'succeeded'})
        r = _login(refunder).post(reverse('payments:attempt_refund', args=[a.pk]),
                                  {'amount': '10.00', 'confirm': 'on', 'reason': 'test'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Refund.objects.get().amount, Decimal('10.00'))
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(object_type='refund', user=refunder).exists())

    def test_attempt_detail_hidden_without_billing_view(self):
        a = self.settled()
        nobody = make_staff('pay-nobody')
        self.assertEqual(_login(nobody).get(reverse('payments:attempt_detail', args=[a.pk])).status_code, 404)

    def test_manage_providers_gate(self):
        tech = make_staff('pay-tech', integrations_configure=True)
        c = _login(tech)
        self.assertEqual(c.get(reverse('payments:connection_create')).status_code, 403)
        self.assertEqual(c.get(reverse('payments:connection_edit', args=[self.stripe.pk])).status_code, 403)
        admin = make_staff('pay-admin', manage_payment_providers=True)
        c = _login(admin)
        self.assertEqual(c.get(reverse('payments:connection_edit', args=[self.stripe.pk])).status_code, 200)
        r = c.post(reverse('payments:connection_edit', args=[self.stripe.pk]), {
            'name': 'Stripe', 'provider_type': 'stripe', 'is_active': 'on', 'sync_enabled': 'on',
            'secret_key': '', 'webhook_secret': 'whsec_new', 'publishable_key': 'pk_live_2',
            'environment': 'live', 'portal_payments_enabled': 'on', 'autopay_enabled': 'on',
            'autopay_lead_days': '2', 'autopay_max_attempts': '4', 'autopay_retry_days': '1,2',
            'failure_notify_email': 'ar@msp.test'})
        self.assertEqual(r.status_code, 302)
        self.stripe.refresh_from_db()
        creds = self.stripe.get_credentials()
        self.assertEqual(creds['api_key'], 'sk_test_1')  # blank keeps the secret
        self.assertEqual((creds['webhook_secret'], creds['publishable_key']), ('whsec_new', 'pk_live_2'))
        self.assertNotIn('whsec_new', self.stripe.encrypted_credentials)
        gs = GatewaySettings.objects.get(connection=self.stripe)
        self.assertEqual((gs.autopay_enabled, gs.autopay_max_attempts, gs.retry_delays()), (True, 4, [1, 2]))
        page = c.get(reverse('payments:connection_edit', args=[self.stripe.pk]))
        self.assertNotContains(page, 'whsec_new')
        self.assertNotContains(page, 'sk_test_1')

    def test_customer_owned_connection_never_used(self):
        """Connections are the MSP's (install-global). A PaymentConnection row
        owned by a customer organization collects nothing, receives no
        webhooks and is not editable from the payments pages."""
        PaymentConnection.objects.filter(pk=self.stripe.pk).update(sync_enabled=False)
        own = PaymentConnection.objects.create(provider_type='stripe', name='Acme own', sync_enabled=True,
                                               organization=self.acme)
        own.set_credentials({'api_key': 'sk_test_x', 'webhook_secret': WHSEC})
        own.save()
        self.assertIsNone(services.connection_for_invoice(self.inv_a))
        body = b'{"id":"evt_own","type":"x","data":{"object":{}}}'
        r = Client().post(reverse('payments:stripe_webhook', args=[own.pk]), data=body,
                          content_type='application/json', HTTP_STRIPE_SIGNATURE=stripe_sig(body))
        self.assertEqual(r.status_code, 404)
        admin = make_staff('pay-admin2', manage_payment_providers=True)
        self.assertEqual(_login(admin).get(reverse('payments:connection_edit', args=[own.pk])).status_code, 404)

    def test_new_connection_is_platform_owned(self):
        admin = make_staff('pay-admin3', manage_payment_providers=True)
        r = _login(admin).post(reverse('payments:connection_create'), {
            'name': 'GoCardless', 'provider_type': 'gocardless', 'is_active': 'on', 'secret_key': 'tok',
            'webhook_secret': 's', 'environment': 'sandbox', 'autopay_lead_days': '0',
            'autopay_max_attempts': '3', 'autopay_retry_days': '3,5,7'})
        self.assertEqual(r.status_code, 302)
        conn = PaymentConnection.objects.get(name='GoCardless')
        self.assertIsNone(conn.organization_id)
        self.assertEqual(conn.base_url, gc_mod.SANDBOX_URL)

    def test_registry_entries(self):
        from accounts import permission_registry as reg
        for key in ('process_refunds', 'manage_payment_providers'):
            p = reg.get(key)
            self.assertTrue(p.staff_only)
            self.assertFalse(p.customer_assignable)
            self.assertFalse(RoleTemplate._meta.get_field(key).default)
        self.assertEqual(reg.get('portal_billing_contact').status, reg.ENFORCED)


# ---------------------------------------------------------------------------
# No card data
# ---------------------------------------------------------------------------

class NoCardDataTests(TestCase):
    FORBIDDEN = re.compile(r'(card_?number|^pan$|_pan$|cvv|cvc|security_code|account_number|routing|iban|'
                           r'sort_code|track|magstripe)', re.I)

    def test_no_pan_or_cvv_fields(self):
        from django.apps import apps
        for model in apps.get_app_config('payments').get_models():
            for field in model._meta.get_fields():
                self.assertIsNone(self.FORBIDDEN.search(field.name), f'{model.__name__}.{field.name}')

    def test_last4_is_four_chars(self):
        self.assertEqual(StoredPaymentMethod._meta.get_field('last4').max_length, 4)

    def test_method_details_keep_only_display_fields(self):
        details = stripe_mod.StripeProvider.method_details({
            'id': 'pm_1', 'type': 'card',
            'card': {'brand': 'visa', 'last4': '4242', 'exp_month': 1, 'exp_year': 2031, 'fingerprint': 'f'}})
        self.assertEqual(set(details), {'method_type', 'brand', 'last4', 'exp_month', 'exp_year', 'bank_name'})


class StripeEncodingTests(TestCase):
    def test_flatten_and_minor_units(self):
        flat = dict(stripe_mod._flatten({'a': {'b': [{'c': 1}]}, 'x': True, 'n': None}))
        self.assertEqual(flat, {'a[b][0][c]': '1', 'x': 'true'})
        self.assertEqual(stripe_mod.to_minor(Decimal('10.005'), 'usd'), 1001)
        self.assertEqual(stripe_mod.to_minor(Decimal('500'), 'jpy'), 500)
        self.assertEqual(stripe_mod.from_minor(1234, 'usd'), Decimal('12.34'))
