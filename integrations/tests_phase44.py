"""
Phase 44 — two-way accounting sync (GitHub #145).

44.1 (v3.17.528): the organization -> provider-customer mapping becomes a real
table instead of a dict inside the connection's encrypted credentials blob, and
customers carry their full details rather than a bare display name.

These tests avoid the network entirely: the provider's `_api` is stubbed, so
what is under test is our mapping logic, our payload construction and our
constraint handling — not Intuit's API.
"""
from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.conf import settings as django_settings
from django.test import TestCase, override_settings

from core.models import Organization
from integrations.models import AccountingConnection, AccountingCustomerLink
from integrations.providers.accounting.base import AccountingProviderError
from integrations.providers.accounting.quickbooks_online import (
    QuickBooksOnlineProvider,
)


# Per CLAUDE.md: view tests dodge the 2FA enforcement and HTTPS redirect,
# neither of which is what these tests are about.
_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _response(status=200, payload=None, text=''):
    """A stand-in for requests.Response carrying just what the code reads."""
    resp = mock.MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text or json.dumps(payload or {})
    return resp


class _ProviderCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Organization.objects.create(name='MSP Co', slug='msp-co')
        cls.client_org = Organization.objects.create(
            name='Acme Ltd', slug='acme-ltd',
            legal_name='Acme Limited', email='ap@acme.example',
            phone='+1 555 0100', website='https://acme.example',
            street_address='1 Main St', city='Springfield', state='IL',
            postal_code='62701', country='United States',
            primary_contact_name='Jo Bloggs',
        )
        cls.conn = AccountingConnection.objects.create(
            organization=cls.tenant, provider_type='quickbooks_online',
            name='Books', sync_enabled=True, is_active=True)

    def provider(self, api):
        p = QuickBooksOnlineProvider(self.conn)
        p._api = api
        return p


class CustomerLinkModelTests(_ProviderCase):

    def test_one_client_maps_to_one_customer_per_connection(self):
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountingCustomerLink.objects.create(
                organization=self.tenant, connection=self.conn,
                client_org=self.client_org, provider_customer_id='2')

    def test_one_customer_is_claimed_by_one_client(self):
        """Two clients silently sharing a customer is how invoices land on the
        wrong account, so the database refuses it."""
        other = Organization.objects.create(name='Beta Inc', slug='beta-inc')
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountingCustomerLink.objects.create(
                organization=self.tenant, connection=self.conn,
                client_org=other, provider_customer_id='1')


class CustomerPayloadTests(_ProviderCase):

    def test_payload_carries_more_than_the_name(self):
        """Before 44.1 only DisplayName was sent, so somebody had to retype the
        address, email and phone on the QBO side."""
        body = self.provider(mock.MagicMock()).customer_payload(self.client_org)
        self.assertEqual(body['DisplayName'], 'Acme Ltd')
        self.assertEqual(body['CompanyName'], 'Acme Limited')
        self.assertEqual(body['PrimaryEmailAddr']['Address'], 'ap@acme.example')
        self.assertEqual(body['PrimaryPhone']['FreeFormNumber'], '+1 555 0100')
        self.assertEqual(body['BillAddr']['City'], 'Springfield')
        self.assertEqual(body['BillAddr']['PostalCode'], '62701')
        self.assertEqual(body['GivenName'], 'Jo')
        self.assertEqual(body['FamilyName'], 'Bloggs')

    def test_blank_fields_are_omitted_not_sent_empty(self):
        bare = Organization.objects.create(name='Bare Co', slug='bare-co')
        body = self.provider(mock.MagicMock()).customer_payload(bare)
        self.assertEqual(body['DisplayName'], 'Bare Co')
        for absent in ('PrimaryEmailAddr', 'PrimaryPhone', 'WebAddr', 'GivenName'):
            self.assertNotIn(absent, body)
        # `country` has a model default, so BillAddr is present but partial.
        self.assertNotIn('City', body.get('BillAddr', {}))


class EnsureCustomerTests(_ProviderCase):

    def test_existing_link_short_circuits_without_an_api_call(self):
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='42')
        api = mock.MagicMock()
        self.assertEqual(
            self.provider(api)._ensure_customer(self.client_org), '42')
        api.assert_not_called()

    def test_name_match_creates_a_link_rather_than_a_duplicate_customer(self):
        api = mock.MagicMock(return_value=_response(200, {
            'QueryResponse': {'Customer': [{'Id': '7', 'DisplayName': 'Acme Ltd'}]}}))
        got = self.provider(api)._ensure_customer(self.client_org)
        self.assertEqual(got, '7')
        link = AccountingCustomerLink.objects.get(
            connection=self.conn, client_org=self.client_org)
        self.assertEqual(link.provider_customer_id, '7')
        self.assertEqual(link.source, 'matched')

    def test_no_match_creates_the_customer_and_links_it(self):
        api = mock.MagicMock(side_effect=[
            _response(200, {'QueryResponse': {}}),                 # no match
            _response(200, {'Customer': {'Id': '9', 'DisplayName': 'Acme Ltd'}}),
        ])
        got = self.provider(api)._ensure_customer(self.client_org)
        self.assertEqual(got, '9')
        link = AccountingCustomerLink.objects.get(client_org=self.client_org)
        self.assertEqual(link.source, 'push')
        # The create must send the full payload, not just a name.
        _method, _path = api.call_args_list[1][0]
        self.assertIn('BillAddr', api.call_args_list[1][1]['json'])

    def test_a_customer_already_claimed_by_another_client_is_an_error(self):
        """Silently re-pointing the link would send Acme's invoices to Beta."""
        other = Organization.objects.create(name='Beta Inc', slug='beta-inc')
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=other, provider_customer_id='7')
        api = mock.MagicMock(return_value=_response(200, {
            'QueryResponse': {'Customer': [{'Id': '7', 'DisplayName': 'Acme Ltd'}]}}))
        with self.assertRaises(AccountingProviderError):
            self.provider(api)._ensure_customer(self.client_org)

    def test_an_apostrophe_in_a_client_name_does_not_break_the_query(self):
        """The name is interpolated into QBO's query language."""
        quoted = Organization.objects.create(name="O'Brien & Co", slug='obrien')
        api = mock.MagicMock(side_effect=[
            _response(200, {'QueryResponse': {}}),
            _response(200, {'Customer': {'Id': '11', 'DisplayName': "O'Brien & Co"}}),
        ])
        self.provider(api)._ensure_customer(quoted)
        query_path = api.call_args_list[0][0][1]
        self.assertNotIn("' ", query_path, 'apostrophe should be escaped/encoded')


class PullCustomersTests(_ProviderCase):

    def test_links_by_name_and_reports_the_rest(self):
        api = mock.MagicMock(side_effect=[
            _response(200, {'QueryResponse': {'Customer': [
                {'Id': '1', 'DisplayName': 'Acme Ltd'},
                {'Id': '2', 'DisplayName': 'Nobody We Know'},
            ]}}),
        ])
        result = self.provider(api).pull_customers()
        self.assertTrue(result['success'])
        self.assertEqual(result['linked'], 1)
        self.assertEqual(result['unmatched'], ['Nobody We Know'])
        self.assertTrue(AccountingCustomerLink.objects.filter(
            client_org=self.client_org, provider_customer_id='1').exists())

    def test_pull_never_invents_organizations(self):
        """Creating tenants from an accounting system is not a sync job's call."""
        before = Organization.objects.count()
        api = mock.MagicMock(side_effect=[
            _response(200, {'QueryResponse': {'Customer': [
                {'Id': '3', 'DisplayName': 'Brand New Corp'}]}}),
        ])
        self.provider(api).pull_customers()
        self.assertEqual(Organization.objects.count(), before)

    def test_already_linked_customers_are_counted_not_relinked(self):
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='1')
        api = mock.MagicMock(side_effect=[
            _response(200, {'QueryResponse': {'Customer': [
                {'Id': '1', 'DisplayName': 'Acme Ltd'}]}}),
        ])
        result = self.provider(api).pull_customers()
        self.assertEqual(result['already_linked'], 1)
        self.assertEqual(result['linked'], 0)


class PushCustomerTests(_ProviderCase):

    def test_update_sends_the_current_sync_token(self):
        """QBO updates are full-replace; a stale token means somebody edited the
        customer there and we must not silently overwrite it."""
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='5')
        api = mock.MagicMock(side_effect=[
            _response(200, {'Customer': {'Id': '5', 'SyncToken': '3'}}),
            _response(200, {'Customer': {'Id': '5', 'DisplayName': 'Acme Ltd'}}),
        ])
        result = self.provider(api).push_customer(self.client_org)
        self.assertTrue(result['success'])
        self.assertFalse(result['created'])
        sent = api.call_args_list[1][1]['json']
        self.assertEqual(sent['SyncToken'], '3')
        self.assertEqual(sent['Id'], '5')

    def test_a_rejected_update_is_recorded_on_the_link(self):
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='5')
        api = mock.MagicMock(side_effect=[
            _response(200, {'Customer': {'Id': '5', 'SyncToken': '3'}}),
            _response(400, {}, text='Stale Object Error'),
        ])
        result = self.provider(api).push_customer(self.client_org)
        self.assertFalse(result['success'])
        link = AccountingCustomerLink.objects.get(client_org=self.client_org)
        self.assertIn('400', link.last_error)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerMappingViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Organization.objects.create(name='ViewCo', slug='view-co')
        cls.client_org = Organization.objects.create(name='Client A', slug='client-a')
        cls.conn = AccountingConnection.objects.create(
            organization=cls.tenant, provider_type='quickbooks_online',
            name='Books', sync_enabled=True, is_active=True)
        cls.admin = User.objects.create_superuser('acctadmin', 'a@x.com', 'pw')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_page_lists_linked_and_unlinked_clients(self):
        AccountingCustomerLink.objects.create(
            organization=self.tenant, connection=self.conn,
            client_org=self.client_org, provider_customer_id='1',
            display_name='Client A')
        r = self.client.get(f'/integrations/accounting/{self.conn.pk}/customers/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Client A')

    def test_pull_reports_unmatched_names_rather_than_a_bare_count(self):
        """A number tells the operator nothing they can act on."""
        fake = mock.MagicMock()
        fake.pull_customers.return_value = {
            'success': True, 'linked': 1, 'already_linked': 0,
            'unmatched': ['Ghost Ltd'], 'error': None,
        }
        with mock.patch('integrations.providers.accounting.get_accounting_provider',
                        return_value=fake):
            r = self.client.post(
                f'/integrations/accounting/{self.conn.pk}/customers/pull/',
                follow=True)
        self.assertContains(r, 'Ghost Ltd')

    def test_pull_requires_post(self):
        r = self.client.get(f'/integrations/accounting/{self.conn.pk}/customers/pull/')
        self.assertEqual(r.status_code, 405)


# ---------------------------------------------------------------------------
# 44.2 — real payment + invoice pull (v3.17.529)
# ---------------------------------------------------------------------------

class _InvoiceCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from decimal import Decimal as D
        from psa.models import Invoice, InvoiceLineItem

        cls.tenant = Organization.objects.create(name='SyncCo', slug='sync-co')
        cls.client_org = Organization.objects.create(name='Payer Ltd', slug='payer')
        cls.conn = AccountingConnection.objects.create(
            organization=cls.tenant, provider_type='quickbooks_online',
            name='Books', sync_enabled=True, is_active=True)
        cls.invoice = Invoice.objects.create(
            organization=cls.tenant, client_org=cls.client_org,
            title='Services', invoice_date=date(2026, 1, 1),
            due_date=date(2026, 2, 1), status='sent',
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-1',
        )
        InvoiceLineItem.objects.create(
            invoice=cls.invoice, description='Work', quantity=D('1'),
            unit_price=D('1000'))
        cls.invoice.recompute_totals()

    def fake_provider(self, **overrides):
        p = mock.MagicMock()
        p.provider_type = 'quickbooks_online'
        p.provider_name = 'QuickBooks Online'
        for key, value in overrides.items():
            getattr(p, key).return_value = value
        return p


class PaymentPullTests(_InvoiceCase):

    def _payment_row(self, **kw):
        from decimal import Decimal as D
        row = {'external_id': 'PMT-1', 'amount': D('1000'),
               'txn_date': '2026-01-15', 'reference': 'chk 900',
               'invoice_external_ids': ['QBO-1'], 'voided': False}
        row.update(kw)
        return row

    def test_a_real_payment_is_imported_with_its_own_date_and_id(self):
        """The old sync fabricated today's date and stored no provider id."""
        from datetime import date
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_payments
        from psa.models import Payment

        provider = self.fake_provider(
            fetch_payments={'success': True, 'payments': [self._payment_row()]})
        result = sync_payments(self.conn, provider)

        self.assertEqual(result.payments_created, 1)
        payment = Payment.objects.get(invoice=self.invoice)
        self.assertEqual(payment.amount, D('1000'))
        self.assertEqual(payment.paid_on, date(2026, 1, 15))
        self.assertEqual(payment.accounting_external_id, 'PMT-1')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

    def test_a_partial_payment_marks_the_invoice_partial(self):
        """Unreachable before: a non-zero balance was skipped entirely."""
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_payments

        provider = self.fake_provider(fetch_payments={
            'success': True,
            'payments': [self._payment_row(amount=D('400'))]})
        sync_payments(self.conn, provider)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, D('400'))
        self.assertEqual(self.invoice.status, 'partial')

    def test_running_twice_does_not_double_count(self):
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_payments
        from psa.models import Payment

        provider = self.fake_provider(
            fetch_payments={'success': True, 'payments': [self._payment_row()]})
        sync_payments(self.conn, provider)
        second = sync_payments(self.conn, provider)

        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)
        self.assertEqual(second.payments_created, 0)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, D('1000'))

    def test_a_changed_amount_updates_rather_than_duplicates(self):
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_payments
        from psa.models import Payment

        provider = self.fake_provider(
            fetch_payments={'success': True, 'payments': [self._payment_row()]})
        sync_payments(self.conn, provider)

        provider.fetch_payments.return_value = {
            'success': True, 'payments': [self._payment_row(amount=D('600'))]}
        result = sync_payments(self.conn, provider)

        self.assertEqual(result.payments_updated, 1)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, D('600'))
        self.assertEqual(self.invoice.status, 'partial')

    def test_a_voided_payment_reopens_the_invoice(self):
        """recompute_totals used to be one-way — an invoice could reach Paid but
        never leave it, so a voided payment left it reading Paid with nothing
        against it."""
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_payments
        from psa.models import Payment

        provider = self.fake_provider(
            fetch_payments={'success': True, 'payments': [self._payment_row()]})
        sync_payments(self.conn, provider)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

        provider.fetch_payments.return_value = {
            'success': True, 'payments': [self._payment_row(voided=True)]}
        result = sync_payments(self.conn, provider)

        self.assertEqual(result.payments_voided, 1)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 0)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, D('0'))
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_an_invoice_marked_paid_by_hand_is_not_reopened(self):
        """Regression guard (v3.17.533).

        Making recompute_totals two-way initially reopened *any* invoice showing
        Paid with no Payment rows behind it — which is how cash, cheques and
        invoices settled straight in the accounting system are recorded. They
        would have quietly gone back to overdue and started accruing late fees.
        Only an invoice whose payments actually went away may be reopened.
        """
        from decimal import Decimal as D
        from psa.models import Invoice, InvoiceLineItem

        from datetime import date
        manual = Invoice.objects.create(
            organization=self.tenant, client_org=self.client_org,
            title='Paid in cash', invoice_date=date(2026, 1, 1),
            status='paid', amount_paid=D('200'))
        InvoiceLineItem.objects.create(
            invoice=manual, description='Callout', quantity=D('1'),
            unit_price=D('200'))

        manual.recompute_totals()
        manual.refresh_from_db()
        self.assertEqual(manual.status, 'paid',
                         'recompute_totals must never reopen an invoice')

        # The explicit call does reopen it — that is the caller saying "I just
        # removed a payment", which recompute_totals cannot know on its own.
        manual.amount_paid = D('0')
        manual.reopen_if_unpaid()
        manual.refresh_from_db()
        self.assertIn(manual.status, ('sent', 'overdue'))

    def test_a_payment_for_an_unknown_invoice_is_reported_not_invented(self):
        from integrations.services.accounting_sync import sync_payments
        from psa.models import Payment

        provider = self.fake_provider(fetch_payments={
            'success': True,
            'payments': [self._payment_row(invoice_external_ids=['QBO-999'])]})
        result = sync_payments(self.conn, provider)

        self.assertEqual(result.unmatched_payments, ['PMT-1'])
        self.assertEqual(Payment.objects.count(), 0)

    def test_dry_run_writes_nothing(self):
        from integrations.services.accounting_sync import sync_payments
        from psa.models import Payment

        provider = self.fake_provider(
            fetch_payments={'success': True, 'payments': [self._payment_row()]})
        result = sync_payments(self.conn, provider, dry_run=True)

        self.assertEqual(result.payments_created, 1)
        self.assertEqual(Payment.objects.count(), 0)

    def test_a_fetch_failure_is_an_error_not_a_silent_no_op(self):
        from integrations.services.accounting_sync import sync_payments
        provider = self.fake_provider(
            fetch_payments={'success': False, 'error': 'HTTP 500', 'payments': []})
        result = sync_payments(self.conn, provider)
        self.assertFalse(result.ok)
        self.assertIn('HTTP 500', result.errors[0])


class InvoiceStatePullTests(_InvoiceCase):

    def test_a_voided_provider_invoice_voids_the_local_one(self):
        from integrations.services.accounting_sync import sync_invoice_state
        provider = self.fake_provider(fetch_invoice={
            'success': True, 'error': None,
            'invoice': {'external_id': 'QBO-1', 'voided': True}})
        sync_invoice_state(self.conn, provider)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'void')

    def test_a_missing_provider_invoice_is_flagged_not_voided(self):
        """Deleting revenue records on the strength of one 404 is not a call a
        sync job gets to make."""
        from integrations.services.accounting_sync import sync_invoice_state
        provider = self.fake_provider(fetch_invoice={
            'success': False, 'error': 'HTTP 404: not found', 'invoice': None})
        sync_invoice_state(self.conn, provider)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'void')
        self.assertIn('deleted', self.invoice.last_push_error)


# ---------------------------------------------------------------------------
# 44.4 — retry semantics (v3.17.531)
# ---------------------------------------------------------------------------

class RetryTests(_ProviderCase):

    def setUp(self):
        # Keep the tests fast: the backoff maths is not what is under test.
        patcher = mock.patch('time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_read_retries_a_500_and_succeeds(self):
        p = QuickBooksOnlineProvider(self.conn)
        send = mock.MagicMock(side_effect=[_response(500), _response(200, {'ok': 1})])
        result = p._request_with_retry(send, method='GET')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(send.call_count, 2)

    def test_a_write_does_not_retry_a_500(self):
        """A 5xx on a POST /invoice is ambiguous: the invoice may already exist
        provider-side. Replaying it is how you get a duplicate in front of a
        client, which is exactly what the v3.17.526 push guard prevents."""
        p = QuickBooksOnlineProvider(self.conn)
        send = mock.MagicMock(side_effect=[_response(500), _response(200)])
        result = p._request_with_retry(send, method='POST')
        self.assertEqual(result.status_code, 500)
        self.assertEqual(send.call_count, 1, 'a write must not be replayed')

    def test_a_write_does_retry_a_429(self):
        """Rate-limited means rejected before processing, so a replay is safe."""
        p = QuickBooksOnlineProvider(self.conn)
        throttled = _response(429)
        throttled.headers = {'Retry-After': '0'}
        send = mock.MagicMock(side_effect=[throttled, _response(200)])
        result = p._request_with_retry(send, method='POST')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(send.call_count, 2)

    def test_a_write_that_never_returns_is_not_replayed(self):
        import requests as _requests
        p = QuickBooksOnlineProvider(self.conn)
        send = mock.MagicMock(side_effect=_requests.ConnectionError('timeout'))
        with self.assertRaises(AccountingProviderError) as ctx:
            p._request_with_retry(send, method='POST')
        self.assertIn('may or may not', str(ctx.exception))
        self.assertEqual(send.call_count, 1)

    def test_a_401_forces_one_refresh_and_replays(self):
        p = QuickBooksOnlineProvider(self.conn)
        send = mock.MagicMock(side_effect=[_response(401), _response(200)])
        refresh = mock.MagicMock()
        result = p._request_with_retry(send, method='GET', on_auth_failure=refresh)
        self.assertEqual(result.status_code, 200)
        refresh.assert_called_once()

    def test_a_persistent_401_gives_up_rather_than_looping(self):
        p = QuickBooksOnlineProvider(self.conn)
        send = mock.MagicMock(return_value=_response(401))
        refresh = mock.MagicMock()
        result = p._request_with_retry(send, method='GET', on_auth_failure=refresh)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(refresh.call_count, 1, 'only one forced refresh')


# ---------------------------------------------------------------------------
# 44.3 — scheduling and on-demand sync (v3.17.530)
# ---------------------------------------------------------------------------

class SyncCommandTests(_InvoiceCase):

    def test_command_records_last_sync_on_the_connection(self):
        """These three fields existed since the model was created and were never
        written, so the connections page always read 'Never'."""
        from django.core.management import call_command
        from io import StringIO

        provider = self.fake_provider(
            pull_customers={'success': True, 'linked': 0, 'already_linked': 0,
                            'unmatched': [], 'error': None},
            fetch_payments={'success': True, 'payments': [], 'error': None},
            fetch_invoice={'success': True, 'error': None,
                           'invoice': {'external_id': 'QBO-1', 'voided': False}},
        )
        with mock.patch(
                'integrations.management.commands.accounting_sync.get_accounting_provider',
                return_value=provider):
            call_command('accounting_sync', stdout=StringIO(), verbosity=0)

        self.conn.refresh_from_db()
        self.assertIsNotNone(self.conn.last_sync_at)
        self.assertEqual(self.conn.last_sync_status, 'ok')

    def test_one_failing_stage_does_not_abandon_the_others(self):
        """A customer-pull outage must not also stop payments importing."""
        from django.core.management import call_command
        from io import StringIO

        provider = self.fake_provider(
            fetch_payments={'success': True, 'payments': [], 'error': None},
            fetch_invoice={'success': True, 'error': None,
                           'invoice': {'external_id': 'QBO-1', 'voided': False}},
        )
        provider.pull_customers.side_effect = RuntimeError('customer API down')

        with mock.patch(
                'integrations.management.commands.accounting_sync.get_accounting_provider',
                return_value=provider):
            call_command('accounting_sync', stdout=StringIO(),
                         stderr=StringIO(), verbosity=0)

        provider.fetch_payments.assert_called()
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'error')
        self.assertIn('customer API down', self.conn.last_error)

    def test_disabled_connections_are_skipped(self):
        from django.core.management import call_command
        from io import StringIO

        self.conn.sync_enabled = False
        self.conn.save()
        provider = self.fake_provider()
        with mock.patch(
                'integrations.management.commands.accounting_sync.get_accounting_provider',
                return_value=provider):
            call_command('accounting_sync', stdout=StringIO(), verbosity=0)
        provider.fetch_payments.assert_not_called()


class SchedulerRegistrationTests(TestCase):

    def test_accounting_sync_is_a_registered_task_type(self):
        """A timer ships too, but installs running the in-app scheduler need
        this entry or the task cannot be created at all."""
        from core.models import ScheduledTask
        self.assertIn('accounting_sync', dict(ScheduledTask.TASK_TYPES))

    def test_the_scheduler_dispatches_it(self):
        """A registered choice with no dispatch branch would fall through to the
        'unknown task type' path and silently never run."""
        import inspect
        from core.management.commands.run_scheduler import Command
        source = inspect.getsource(Command)
        self.assertIn("task.task_type == 'accounting_sync'", source)
        self.assertTrue(hasattr(Command, 'run_accounting_sync'))


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SyncNowViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Organization.objects.create(name='NowCo', slug='now-co')
        cls.conn = AccountingConnection.objects.create(
            organization=cls.tenant, provider_type='quickbooks_online',
            name='Books', sync_enabled=True, is_active=True)
        cls.admin = User.objects.create_superuser('nowadmin', 'n@x.com', 'pw')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_sync_now_runs_the_command(self):
        with mock.patch('django.core.management.call_command') as called:
            r = self.client.post(f'/integrations/accounting/{self.conn.pk}/sync/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(called.called)
        self.assertEqual(called.call_args[0][0], 'accounting_sync')

    def test_sync_now_refuses_a_disabled_connection(self):
        self.conn.sync_enabled = False
        self.conn.save()
        with mock.patch('django.core.management.call_command') as called:
            self.client.post(f'/integrations/accounting/{self.conn.pk}/sync/',
                             follow=True)
        called.assert_not_called()

    def test_sync_now_requires_post(self):
        r = self.client.get(f'/integrations/accounting/{self.conn.pk}/sync/')
        self.assertEqual(r.status_code, 405)


class DeployUnitTests(TestCase):
    """The roadmap claimed a timer for three releases while none existed."""

    def test_the_systemd_units_are_shipped(self):
        from pathlib import Path
        from django.conf import settings as dj

        deploy = Path(dj.BASE_DIR) / 'deploy'
        service = deploy / 'clientst0r-accounting-sync.service'
        timer = deploy / 'clientst0r-accounting-sync.timer'
        self.assertTrue(service.is_file(), 'service unit missing')
        self.assertTrue(timer.is_file(), 'timer unit missing')
        self.assertIn('manage.py accounting_sync', service.read_text())
        self.assertIn('OnUnitActiveSec', timer.read_text())


class InvoiceUpdatePullTests(_InvoiceCase):
    """GitHub #145 asked for invoice *updates*, not just voids."""

    def test_provider_total_is_recorded_not_applied(self):
        """Our total derives from line items. Overwriting it would leave the
        invoice disagreeing with its own lines, which is worse than disagreeing
        with QuickBooks — so the difference is recorded for a human."""
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_invoice_state

        provider = self.fake_provider(fetch_invoice={
            'success': True, 'error': None,
            'invoice': {'external_id': 'QBO-1', 'voided': False,
                        'total': D('1250'), 'due_date': '2026-02-01'}})
        result = sync_invoice_state(self.conn, provider)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.provider_total_amount, D('1250'))
        self.assertEqual(self.invoice.total, D('1000'), 'local total untouched')
        self.assertEqual(self.invoice.provider_total_drift, D('250'))
        self.assertEqual(len(result.drifted_invoices), 1)

    def test_a_changed_due_date_is_applied(self):
        """Nothing local derives from the due date, and the provider is the
        system of record for when the client owes money."""
        from datetime import date
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_invoice_state

        provider = self.fake_provider(fetch_invoice={
            'success': True, 'error': None,
            'invoice': {'external_id': 'QBO-1', 'voided': False,
                        'total': D('1000'), 'due_date': '2026-03-15'}})
        sync_invoice_state(self.conn, provider)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.due_date, date(2026, 3, 15))

    def test_matching_totals_are_not_reported_as_drift(self):
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_invoice_state

        provider = self.fake_provider(fetch_invoice={
            'success': True, 'error': None,
            'invoice': {'external_id': 'QBO-1', 'voided': False,
                        'total': D('1000'), 'due_date': '2026-02-01'}})
        result = sync_invoice_state(self.conn, provider)
        self.assertEqual(result.drifted_invoices, [])
        self.invoice.refresh_from_db()
        self.assertIsNotNone(self.invoice.provider_synced_at)

    def test_dry_run_records_drift_without_writing(self):
        from decimal import Decimal as D
        from integrations.services.accounting_sync import sync_invoice_state

        provider = self.fake_provider(fetch_invoice={
            'success': True, 'error': None,
            'invoice': {'external_id': 'QBO-1', 'voided': False,
                        'total': D('9999'), 'due_date': '2026-02-01'}})
        result = sync_invoice_state(self.conn, provider, dry_run=True)

        self.assertEqual(len(result.drifted_invoices), 1)
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.provider_total_amount)
