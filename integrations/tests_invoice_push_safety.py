"""Duplicate-safe accounting push (integrations.services.invoice_push).

HTTP is faked at the requests.Session level so the real retry / ambiguity
handling in BaseAccountingProvider._request_with_retry runs: a timeout on a
POST must surface as "unknown", and the next push must reconcile before it is
allowed to create anything.
"""
import time
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

import requests
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from integrations.models import (
    AccountingAuditLog,
    AccountingConnection,
    AccountingCustomerLink,
    AccountingItemMapping,
    InvoicePushAttempt,
)
from integrations.providers.accounting import get_accounting_provider
from integrations.services.invoice_push import push_invoice_safely


class _Resp:
    def __init__(self, status, payload=None, text=''):
        self.status_code = status
        self._payload = payload or {}
        self.text = text or str(payload)
        self.headers = {}

    def json(self):
        return self._payload


class FakeQBO:
    """Just enough of the QBO API: create invoice, query invoices, read one."""

    def __init__(self):
        self.invoices = {}          # id -> row
        self.posts = []             # (url, body)
        self.queries = []
        self.next_id = 100
        self.post_behaviour = []    # list of 'ok' | 'timeout_landed' | 'timeout_lost' | '503'

    def request(self, method, url, headers=None, timeout=None, json=None, **kw):
        parsed = urlparse(url)
        path = parsed.path.split('/v3/company/realm-1', 1)[-1]
        if method == 'POST' and path == '/invoice':
            self.posts.append((url, json))
            behaviour = self.post_behaviour.pop(0) if self.post_behaviour else 'ok'
            if behaviour in ('ok', 'timeout_landed', '503_landed'):
                self.next_id += 1
                row = dict(json, Id=str(self.next_id))
                self.invoices[row['Id']] = row
            if behaviour.startswith('timeout'):
                raise requests.Timeout('read timed out')
            if behaviour.startswith('503'):
                return _Resp(503, text='Service Unavailable')
            return _Resp(200, {'Invoice': row})
        if method == 'GET' and path == '/query':
            q = unquote(parse_qs(parsed.query)['query'][0])
            self.queries.append(q)
            rows = list(self.invoices.values())
            if 'DocNumber' in q:
                doc = q.split("DocNumber = '", 1)[1].split("'", 1)[0]
                rows = [r for r in rows if r.get('DocNumber') == doc]
            return _Resp(200, {'QueryResponse': {'Invoice': rows} if rows else {}})
        if method == 'GET' and path.startswith('/invoice/'):
            ext = path.rsplit('/', 1)[-1]
            row = self.invoices.get(ext)
            if row is None:
                return _Resp(400, text='Object Not Found: 610')
            return _Resp(200, {'Invoice': row})
        raise AssertionError(f'unexpected {method} {url}')


class _Base(TestCase):
    provider_type = 'quickbooks_online'

    def setUp(self):
        from psa.models import Invoice, InvoiceLineItem
        self.org = Organization.objects.create(name='PushMSP')
        self.client_org = Organization.objects.create(name='PushClient')
        self.conn = AccountingConnection.objects.create(
            organization=self.org, provider_type=self.provider_type,
            name='Books', sync_enabled=True, is_active=True)
        self.conn.set_credentials({
            'client_id': 'cid', 'client_secret': 'sec',
            'access_token': 'tok', 'refresh_token': 'ref',
            'expires_at': time.time() + 3600,
            'realm_id': 'realm-1', 'tenant_id': 'tenant-1',
        })
        self.conn.save()
        AccountingCustomerLink.objects.create(
            organization=self.org, connection=self.conn,
            client_org=self.client_org, provider_customer_id='CUST-1')
        self.invoice = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Monthly', invoice_date=date(2026, 11, 1))
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Managed services',
            quantity=1, unit_price=Decimal('500'))

    def provider(self, fake):
        p = get_accounting_provider(self.conn)
        p.session = mock.MagicMock()
        p.session.request.side_effect = fake.request
        return p

    def push(self, fake, **kw):
        return push_invoice_safely(self.invoice, self.conn, self.provider(fake), **kw)


class QBOTimeoutReconcileTests(_Base):

    def test_timeout_marks_unknown_not_failed(self):
        fake = FakeQBO()
        fake.post_behaviour = ['timeout_landed']
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'unknown')
        self.assertFalse(r['success'])
        att = InvoicePushAttempt.objects.get()
        self.assertEqual(att.state, InvoicePushAttempt.STATE_UNKNOWN)
        self.assertEqual(att.open_slot, str(self.invoice.pk))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.accounting_external_id, '')

    def test_timeout_then_retry_adopts_existing_invoice(self):
        fake = FakeQBO()
        fake.post_behaviour = ['timeout_landed']
        self.push(fake)
        self.assertEqual(len(fake.invoices), 1)

        r = self.push(fake)
        self.assertEqual(r['outcome'], 'adopted')
        self.assertTrue(r['success'])
        # Only the original POST — no second create.
        self.assertEqual(len(fake.posts), 1)
        self.assertEqual(len(fake.invoices), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.accounting_external_id,
                         next(iter(fake.invoices)))
        att = InvoicePushAttempt.objects.get()
        self.assertEqual(att.state, InvoicePushAttempt.STATE_SUCCEEDED)
        self.assertEqual(att.resolution, 'adopted')
        self.assertIsNone(att.open_slot)
        self.assertTrue(AccountingAuditLog.objects.filter(
            action='reconcile_invoice', success=True).exists())

    def test_timeout_then_retry_with_nothing_provider_side_creates_once(self):
        fake = FakeQBO()
        fake.post_behaviour = ['timeout_lost', 'ok']
        self.push(fake)
        self.assertEqual(len(fake.invoices), 0)

        r = self.push(fake)
        self.assertEqual(r['outcome'], 'created')
        self.assertEqual(len(fake.invoices), 1)
        self.assertEqual(len(fake.posts), 2)
        # The retry reuses the request id, so QBO can replay rather than create.
        rid = [parse_qs(urlparse(u).query)['requestid'][0] for u, _ in fake.posts]
        self.assertEqual(rid[0], rid[1])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.accounting_external_id, next(iter(fake.invoices)))
        # A third push is now refused as already pushed.
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'already_pushed')
        self.assertEqual(len(fake.posts), 2)

    def test_5xx_is_unknown_and_reconciled(self):
        fake = FakeQBO()
        fake.post_behaviour = ['503_landed']
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'unknown')
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'adopted')
        self.assertEqual(len(fake.invoices), 1)

    def test_payload_carries_key_docnumber_and_requestid(self):
        fake = FakeQBO()
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'created')
        url, body = fake.posts[0]
        att = InvoicePushAttempt.objects.get()
        self.assertIn(att.idempotency_key, body['PrivateNote'])
        self.assertEqual(body['DocNumber'], self.invoice.invoice_number[:21])
        self.assertEqual(parse_qs(urlparse(url).query)['requestid'][0], att.request_id)

    def test_search_failure_refuses_to_create(self):
        fake = FakeQBO()
        fake.post_behaviour = ['timeout_lost']
        self.push(fake)
        p = self.provider(fake)
        with mock.patch.object(p, 'find_invoice_by_key',
                               return_value={'status': 'error', 'error': 'HTTP 500'}):
            r = push_invoice_safely(self.invoice, self.conn, p)
        self.assertEqual(r['outcome'], 'reconcile_error')
        self.assertEqual(len(fake.posts), 1)
        # Still unknown — the next push must reconcile again.
        self.assertEqual(InvoicePushAttempt.objects.get().state,
                         InvoicePushAttempt.STATE_UNKNOWN)


class ConcurrentPushTests(_Base):

    def test_second_push_sees_in_flight_attempt(self):
        InvoicePushAttempt.objects.create(
            invoice=self.invoice, connection=self.conn,
            idempotency_key='CS-x', request_id='r1',
            state=InvoicePushAttempt.STATE_PENDING,
            open_slot=str(self.invoice.pk))
        fake = FakeQBO()
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'in_flight')
        self.assertEqual(fake.posts, [])
        self.assertEqual(fake.queries, [])

    def test_database_allows_only_one_open_attempt(self):
        InvoicePushAttempt.objects.create(
            invoice=self.invoice, connection=self.conn,
            idempotency_key='CS-x', request_id='r1',
            open_slot=str(self.invoice.pk))
        with self.assertRaises(IntegrityError), transaction.atomic():
            InvoicePushAttempt.objects.create(
                invoice=self.invoice, connection=self.conn,
                idempotency_key='CS-x', request_id='r2',
                open_slot=str(self.invoice.pk))

    def test_racing_insert_reports_in_flight(self):
        """The loser of a race between read and insert hits the unique slot."""
        fake = FakeQBO()
        real_create = InvoicePushAttempt.objects.create

        def racing_create(**kw):
            # Another worker claims the slot first.
            real_create(**dict(kw, request_id='winner'))
            return real_create(**kw)

        with mock.patch.object(InvoicePushAttempt.objects, 'create',
                               side_effect=racing_create):
            r = self.push(fake)
        self.assertEqual(r['outcome'], 'in_flight')
        self.assertEqual(fake.posts, [])

    def test_stale_pending_is_reconciled_not_ignored(self):
        fake = FakeQBO()
        fake.post_behaviour = ['timeout_landed']
        self.push(fake)
        att = InvoicePushAttempt.objects.get()
        # Simulate a worker that died mid-request long ago.
        InvoicePushAttempt.objects.filter(pk=att.pk).update(
            state=InvoicePushAttempt.STATE_PENDING,
            requested_at=timezone.now() - timedelta(hours=1))
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'adopted')
        self.assertEqual(len(fake.posts), 1)


class ForceRepushTests(_Base):

    def test_force_refused_while_recorded_invoice_exists(self):
        fake = FakeQBO()
        self.push(fake)
        self.invoice.refresh_from_db()
        r = self.push(fake, force=True)
        self.assertEqual(r['outcome'], 'exists')
        self.assertEqual(len(fake.posts), 1)
        self.assertTrue(AccountingAuditLog.objects.filter(action='push_refused').exists())

    def test_force_adopts_key_match_instead_of_duplicating(self):
        fake = FakeQBO()
        self.push(fake)
        self.invoice.refresh_from_db()
        # Local id points at something deleted provider-side, but our keyed
        # invoice is still there under another id.
        real_id = self.invoice.accounting_external_id
        self.invoice.accounting_external_id = 'GONE-1'
        self.invoice.save(update_fields=['accounting_external_id'])
        r = self.push(fake, force=True)
        self.assertEqual(r['outcome'], 'adopted')
        self.assertEqual(r['invoice_id'], real_id)
        self.assertEqual(len(fake.posts), 1)

    def test_force_creates_when_provider_copy_is_gone(self):
        fake = FakeQBO()
        self.push(fake)
        fake.invoices.clear()      # deleted in QBO
        r = self.push(fake, force=True)
        self.assertEqual(r['outcome'], 'created')
        self.assertEqual(len(fake.posts), 2)
        self.assertEqual(len(fake.invoices), 1)
        # A fresh logical push gets a fresh request id (else QBO would replay
        # the deleted invoice's response) but keeps the same push key.
        atts = list(InvoicePushAttempt.objects.order_by('pk'))
        self.assertNotEqual(atts[0].request_id, atts[1].request_id)
        self.assertEqual(atts[0].idempotency_key, atts[1].idempotency_key)


class QBOItemMappingTests(_Base):

    def setUp(self):
        super().setUp()
        line = self.invoice.line_items.get()
        line.gl_account_code = '4100'
        line.save()

    def test_itemref_uses_mapped_item_id(self):
        AccountingItemMapping.objects.create(
            connection=self.conn, gl_account_code='4100', provider_item_id='77')
        fake = FakeQBO()
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'created')
        detail = fake.posts[0][1]['Line'][0]['SalesItemLineDetail']
        self.assertEqual(detail['ItemRef'], {'value': '77'})

    def test_unmapped_code_falls_back_to_default_item(self):
        self.conn.default_item_id = '5'
        self.conn.save()
        fake = FakeQBO()
        self.push(fake)
        detail = fake.posts[0][1]['Line'][0]['SalesItemLineDetail']
        self.assertEqual(detail['ItemRef'], {'value': '5'})

    def test_missing_mapping_and_default_refuses_push(self):
        fake = FakeQBO()
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'refused')
        self.assertIn('4100', r['error'])
        self.assertEqual(fake.posts, [])
        att = InvoicePushAttempt.objects.get()
        self.assertEqual(att.state, InvoicePushAttempt.STATE_FAILED)
        self.assertIsNone(att.open_slot)
        self.assertTrue(AccountingAuditLog.objects.filter(action='push_refused').exists())

    def test_account_code_is_never_sent_as_itemref(self):
        AccountingItemMapping.objects.create(
            connection=self.conn, gl_account_code='4100', provider_item_id='77')
        fake = FakeQBO()
        self.push(fake)
        self.assertNotIn("'4100'", str(fake.posts[0][1]['Line']))


class XeroTests(_Base):
    provider_type = 'xero'

    def test_timeout_then_retry_adopts_by_reference(self):
        posted, stored = [], []

        def request(method, url, headers=None, json=None, **kw):
            if method == 'POST' and url.endswith('/Invoices'):
                posted.append((headers, json))
                row = dict(json['Invoices'][0], InvoiceID='X-1', Status='AUTHORISED')
                stored.append(row)
                raise requests.Timeout('timed out')
            if method == 'GET' and '/Invoices?where=' in url:
                return _Resp(200, {'Invoices': stored})
            raise AssertionError(url)

        fake = mock.MagicMock()
        fake.request.side_effect = request
        r = self.push(fake)
        self.assertEqual(r['outcome'], 'unknown')
        att = InvoicePushAttempt.objects.get()
        self.assertIn(att.idempotency_key, posted[0][1]['Invoices'][0]['Reference'])
        self.assertEqual(posted[0][0]['Idempotency-Key'], att.request_id)

        r = self.push(fake)
        self.assertEqual(r['outcome'], 'adopted')
        self.assertEqual(len(posted), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.accounting_external_id, 'X-1')

    def _payment(self):
        from psa.models import Payment
        self.invoice.accounting_provider = 'xero'
        self.invoice.accounting_external_id = 'X-1'
        self.invoice.save()
        return Payment.objects.create(
            invoice=self.invoice, amount=Decimal('100'),
            paid_on=date(2026, 11, 5), reference='CHK1234567890')

    def test_payment_without_bank_account_refuses(self):
        payment = self._payment()
        fake = mock.MagicMock()
        r = self.provider(fake).record_payment(payment)
        self.assertFalse(r['success'])
        self.assertIn('bank account', r['error'])
        fake.request.assert_not_called()
        self.assertTrue(AccountingAuditLog.objects.filter(
            action='push_refused', resource_type='payment').exists())

    def test_payment_uses_configured_bank_account(self):
        self.conn.payment_account_code = '090-BANK'
        self.conn.save()
        payment = self._payment()
        fake = mock.MagicMock()
        fake.request.return_value = _Resp(200, {'Payments': [{'PaymentID': 'P-1'}]})
        r = self.provider(fake).record_payment(payment)
        self.assertTrue(r['success'])
        body = fake.request.call_args.kwargs['json']
        self.assertEqual(body['Payments'][0]['Account'], {'Code': '090-BANK'})
        self.assertTrue(AccountingAuditLog.objects.filter(
            action='record_payment', success=True, external_id='P-1').exists())
