"""
Phase 27 gap: pull payments, invoice state and customers from Xero.

QuickBooks Online gained a real payment pull in Phase 44 (v3.17.531); the Xero
provider never implemented `fetch_payments`, `fetch_invoice` or
`pull_customers`, so every scheduled `accounting_sync` run raised
NotImplementedError for each stage of a Xero connection and marked it 'error'.

The fixtures below follow the shape of Xero's documented Accounting API
responses (GET /Payments, GET /Invoices/{id}, GET /Contacts), including the
'/Date(ms+0000)/' JSON date form. No network: the provider's `_api` (or its
HTTP session) is stubbed.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone as dt_tz
from decimal import Decimal as D
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization
from integrations.models import AccountingConnection, AccountingCustomerLink
from integrations.providers.accounting.xero import XeroProvider
from integrations.services.accounting_sync import sync_invoice_state, sync_payments


def _response(status=200, payload=None, text=''):
    resp = mock.MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text or json.dumps(payload or {})
    resp.headers = {}
    return resp


def _xero_payment(payment_id, amount, *, invoice_id='XINV-1', status='AUTHORISED',
                  payment_type='ACCRECPAYMENT', invoice_type='ACCREC',
                  date_ms=1768435200000, reference='EFT 1234'):
    """One element of GET /Payments -> Payments[], as Xero returns it."""
    return {
        'PaymentID': payment_id,
        'BatchPaymentID': None,
        'Date': f'/Date({date_ms}+0000)/',
        'BankAmount': amount,
        'Amount': amount,
        'Reference': reference,
        'CurrencyRate': 1.0,
        'PaymentType': payment_type,
        'Status': status,
        'UpdatedDateUTC': f'/Date({date_ms + 3600000}+0000)/',
        'HasAccount': True,
        'IsReconciled': False,
        'Account': {'AccountID': 'ACC-090', 'Code': '090'},
        'Invoice': {
            'Type': invoice_type,
            'InvoiceID': invoice_id,
            'InvoiceNumber': 'INV-0042',
            'Contact': {'ContactID': 'C-1', 'Name': 'Payer Ltd'},
            'CurrencyCode': 'USD',
        },
    }


def _payments_page(*rows):
    return {'Id': 'resp-1', 'Status': 'OK', 'ProviderName': 'ClientSt0r',
            'DateTimeUTC': '/Date(1768500000000)/',
            'pagination': {'page': 1, 'pageSize': 100, 'pageCount': 1,
                           'itemCount': len(rows)},
            'Payments': list(rows)}


class _XeroCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        from psa.models import Invoice, InvoiceLineItem
        cls.tenant = Organization.objects.create(name='XeroCo', slug='xero-co')
        cls.client_org = Organization.objects.create(name='Payer Ltd', slug='payer-x')
        cls.conn = AccountingConnection.objects.create(
            organization=cls.tenant, provider_type='xero',
            name='Xero Books', sync_enabled=True, is_active=True)
        cls.invoice = Invoice.objects.create(
            organization=cls.tenant, client_org=cls.client_org,
            title='Services', invoice_date=date(2026, 1, 1),
            due_date=date(2026, 2, 1), status='sent',
            accounting_provider='xero', accounting_external_id='XINV-1')
        InvoiceLineItem.objects.create(
            invoice=cls.invoice, description='Work', quantity=D('1'),
            unit_price=D('1000'))
        cls.invoice.recompute_totals()

    def setUp(self):
        self.conn.refresh_from_db()
        self.conn.set_credentials({
            'client_id': 'cid', 'client_secret': 'secret',
            'access_token': 'tok', 'refresh_token': 'ref',
            'expires_at': time.time() + 3600, 'tenant_id': 'tenant-1'})
        self.conn.save()

    def provider(self, api=None):
        p = XeroProvider(self.conn)
        if api is not None:
            p._api = api
        return p


class XeroFetchPaymentsTests(_XeroCase):

    def test_parses_documented_payment_shape(self):
        api = mock.MagicMock(return_value=_response(200, _payments_page(
            _xero_payment('P-1', 400.0))))
        got = self.provider(api).fetch_payments()
        self.assertTrue(got['success'])
        self.assertEqual(len(got['payments']), 1)
        row = got['payments'][0]
        self.assertEqual(row['external_id'], 'P-1')
        self.assertEqual(row['amount'], D('400.0'))
        self.assertEqual(row['txn_date'], '2026-01-15')
        self.assertEqual(row['reference'], 'EFT 1234')
        self.assertEqual(row['invoice_external_ids'], ['XINV-1'])
        self.assertFalse(row['voided'])

    def test_deleted_payment_is_reported_as_voided(self):
        api = mock.MagicMock(return_value=_response(200, _payments_page(
            _xero_payment('P-1', 400.0, status='DELETED'))))
        row = self.provider(api).fetch_payments()['payments'][0]
        self.assertTrue(row['voided'])

    def test_bill_payments_and_credit_refunds_are_ignored(self):
        api = mock.MagicMock(return_value=_response(200, _payments_page(
            _xero_payment('P-bill', 50.0, payment_type='ACCPAYPAYMENT',
                          invoice_type='ACCPAY'),
            _xero_payment('P-refund', 20.0, payment_type='ARCREDITPAYMENT'),
            _xero_payment('P-ok', 10.0))))
        ids = [p['external_id'] for p in self.provider(api).fetch_payments()['payments']]
        self.assertEqual(ids, ['P-ok'])

    def test_since_becomes_if_modified_since_and_pages_are_followed(self):
        first = _payments_page(*[_xero_payment(f'P-{i}', 1.0) for i in range(100)])
        second = _payments_page(_xero_payment('P-last', 1.0))
        api = mock.MagicMock(side_effect=[_response(200, first),
                                          _response(200, second)])
        since = datetime(2026, 1, 10, 6, 30, tzinfo=dt_tz.utc)
        got = self.provider(api).fetch_payments(since=since)
        self.assertEqual(len(got['payments']), 101)
        self.assertEqual(api.call_count, 2)
        self.assertIn('page=1', api.call_args_list[0][0][1])
        self.assertIn('page=2', api.call_args_list[1][0][1])
        self.assertEqual(api.call_args_list[0][1]['headers']['If-Modified-Since'],
                         '2026-01-10T06:30:00')

    def test_tenant_header_and_token_reach_the_wire(self):
        """Exercise _api for real: the Payments call is a normal tenant-scoped GET."""
        p = self.provider()
        p.session = mock.MagicMock()
        p.session.request.return_value = _response(200, _payments_page())
        p.fetch_payments()
        method, url = p.session.request.call_args[0][:2]
        headers = p.session.request.call_args[1]['headers']
        self.assertEqual(method, 'GET')
        self.assertTrue(url.startswith('https://api.xero.com/api.xro/2.0/Payments'))
        self.assertEqual(headers['Xero-tenant-id'], 'tenant-1')
        self.assertEqual(headers['Authorization'], 'Bearer tok')

    def test_server_error_is_an_error(self):
        api = mock.MagicMock(return_value=_response(500, text='boom'))
        got = self.provider(api).fetch_payments()
        self.assertFalse(got['success'])
        self.assertFalse(got.get('needs_attention'))


class XeroPaymentsForbiddenTests(_XeroCase):
    """A 403 means the consent lacks payment access. Retrying every hour will
    not change that, so it parks with an actionable message instead."""

    def _forbidden(self):
        return _response(403, {'Type': None, 'Title': 'Forbidden', 'Status': 403,
                               'Detail': 'AuthorizationUnsuccessful'})

    def test_403_parks_the_pull_with_an_actionable_message(self):
        api = mock.MagicMock(return_value=self._forbidden())
        got = self.provider(api).fetch_payments()
        self.assertFalse(got['success'])
        self.assertTrue(got['needs_attention'])
        self.assertIn('Connect', got['error'])
        self.assertIn('accounting.payments.read', got['error'])
        self.conn.refresh_from_db()
        self.assertTrue(self.conn.get_credentials().get('payments_forbidden'))

        # Second run: no API call, same message.
        api2 = mock.MagicMock()
        again = self.provider(api2).fetch_payments()
        api2.assert_not_called()
        self.assertTrue(again['needs_attention'])

    def test_sync_reports_attention_not_error(self):
        api = mock.MagicMock(return_value=self._forbidden())
        result = sync_payments(self.conn, self.provider(api))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.attention), 1)

    def test_command_marks_connection_attention_not_error(self):
        api = mock.MagicMock(return_value=self._forbidden())
        provider = self.provider(api)
        with mock.patch(
                'integrations.management.commands.accounting_sync.get_accounting_provider',
                return_value=provider):
            call_command('accounting_sync', '--skip-customers', '--skip-invoices',
                         stdout=StringIO(), stderr=StringIO(), verbosity=0)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'attention')
        self.assertIn('Payments (HTTP 403)', self.conn.last_error)

    def test_reconnecting_clears_the_park(self):
        self.conn.update_credentials(payments_forbidden='1')
        self.conn.save()
        token = _response(200, {'access_token': 'new', 'refresh_token': 'r2',
                                'expires_in': 1800})
        tenants = _response(200, [{'tenantId': 'tenant-1'}])
        with mock.patch('integrations.providers.accounting.xero.requests.post',
                        return_value=token), \
                mock.patch('integrations.providers.accounting.xero.requests.get',
                           return_value=tenants):
            self.provider().handle_callback(code='c', redirect_uri='https://x/cb')
        self.conn.refresh_from_db()
        self.assertFalse(self.conn.get_credentials().get('payments_forbidden'))


class XeroPaymentSyncTests(_XeroCase):
    """The full path: Xero payload -> sync_payments -> local Payment rows."""

    def _sync(self, *rows):
        api = mock.MagicMock(return_value=_response(200, _payments_page(*rows)))
        return sync_payments(self.conn, self.provider(api))

    def test_partial_payment_marks_invoice_partial(self):
        from psa.models import Payment
        result = self._sync(_xero_payment('P-1', 400.0))
        self.assertEqual(result.payments_created, 1)
        pay = Payment.objects.get(accounting_external_id='P-1')
        self.assertEqual(pay.accounting_provider, 'xero')
        self.assertEqual(pay.amount, D('400'))
        self.assertEqual(pay.paid_on, date(2026, 1, 15))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'partial')

    def test_second_payment_settles_it_and_rerun_is_idempotent(self):
        from psa.models import Payment
        rows = (_xero_payment('P-1', 400.0), _xero_payment('P-2', 600.0))
        self._sync(*rows)
        again = self._sync(*rows)
        self.assertEqual(again.payments_created, 0)
        self.assertEqual(again.payments_updated, 0)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 2)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

    def test_payment_deleted_in_xero_reopens_the_invoice(self):
        from psa.models import Payment
        self._sync(_xero_payment('P-1', 1000.0))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')
        result = self._sync(_xero_payment('P-1', 1000.0, status='DELETED'))
        self.assertEqual(result.payments_voided, 1)
        self.assertFalse(Payment.objects.filter(accounting_external_id='P-1').exists())
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_payment_on_invoice_raised_in_xero_is_unmatched(self):
        result = self._sync(_xero_payment('P-9', 50.0, invoice_id='NOT-OURS'))
        self.assertEqual(result.unmatched_payments, ['P-9'])


class XeroInvoiceAndCustomerPullTests(_XeroCase):

    def test_fetch_invoice_reads_status_total_and_due_date(self):
        api = mock.MagicMock(return_value=_response(200, {'Invoices': [{
            'Type': 'ACCREC', 'InvoiceID': 'XINV-1', 'InvoiceNumber': 'INV-0042',
            'Status': 'VOIDED', 'Total': 1000.0, 'AmountDue': 0.0,
            'Date': '/Date(1767225600000+0000)/', 'DateString': '2026-01-01T00:00:00',
            'DueDate': '/Date(1772236800000+0000)/', 'DueDateString': '2026-02-28T00:00:00',
        }]}))
        got = self.provider(api).fetch_invoice('XINV-1')
        self.assertTrue(got['success'])
        self.assertTrue(got['invoice']['voided'])
        self.assertEqual(got['invoice']['total'], D('1000.0'))
        self.assertEqual(got['invoice']['due_date'], '2026-02-28')

    def test_invoice_state_sync_voids_and_applies_due_date(self):
        api = mock.MagicMock(return_value=_response(200, {'Invoices': [{
            'InvoiceID': 'XINV-1', 'Status': 'VOIDED', 'Total': 1000.0,
            'AmountDue': 0.0, 'DueDateString': '2026-02-28T00:00:00'}]}))
        result = sync_invoice_state(self.conn, self.provider(api))
        self.assertTrue(result.ok)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'void')
        self.assertEqual(self.invoice.due_date, date(2026, 2, 28))

    def test_pull_customers_links_by_name_and_skips_archived(self):
        Organization.objects.create(name='Archived Co', slug='archived-co')
        api = mock.MagicMock(return_value=_response(200, {'Contacts': [
            {'ContactID': 'C-1', 'Name': 'Payer Ltd', 'ContactStatus': 'ACTIVE',
             'IsCustomer': True},
            {'ContactID': 'C-2', 'Name': 'Archived Co', 'ContactStatus': 'ARCHIVED',
             'IsCustomer': True},
            {'ContactID': 'C-3', 'Name': 'Nobody Here', 'ContactStatus': 'ACTIVE',
             'IsCustomer': True},
        ]}))
        got = self.provider(api).pull_customers()
        self.assertTrue(got['success'])
        self.assertEqual(got['linked'], 1)
        self.assertEqual(got['unmatched'], ['Nobody Here'])
        link = AccountingCustomerLink.objects.get(connection=self.conn)
        self.assertEqual((link.client_org, link.provider_customer_id),
                         (self.client_org, 'C-1'))

    def test_full_command_run_is_ok_for_a_xero_connection(self):
        """Before this every stage raised NotImplementedError for Xero."""
        def api(method, path, **kw):
            if path.startswith('/Contacts'):
                return _response(200, {'Contacts': []})
            if path.startswith('/Payments'):
                return _response(200, _payments_page(_xero_payment('P-1', 1000.0)))
            return _response(200, {'Invoices': [{
                'InvoiceID': 'XINV-1', 'Status': 'PAID', 'Total': 1000.0,
                'AmountDue': 0.0}]})
        provider = self.provider(mock.MagicMock(side_effect=api))
        with mock.patch(
                'integrations.management.commands.accounting_sync.get_accounting_provider',
                return_value=provider):
            call_command('accounting_sync', stdout=StringIO(), stderr=StringIO(),
                         verbosity=0)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'ok', self.conn.last_error)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

    def test_the_scheduler_task_runs_the_same_command(self):
        """The in-app scheduler's accounting_sync task calls this command, so a
        Xero connection takes the same path there."""
        import inspect
        from core.management.commands.run_scheduler import Command
        self.assertIn("call_command('accounting_sync'",
                      inspect.getsource(Command.run_accounting_sync))
