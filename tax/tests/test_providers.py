"""Avalara AvaTax and TaxJar adapters against mocked HTTP. No live calls:
real sandbox credentials are needed to check the wire format end to end
(see docs/TAX.md, "Sandbox verification")."""
from datetime import date
from decimal import Decimal

import requests
from django.test import TestCase

from integrations.models import TaxConnection
from integrations.providers.tax import TaxLine, TaxRequest, get_tax_provider

from ._helpers import AVALARA_CREDS, TAXJAR_CREDS, make_org, patch_http, response


def _req(**kw):
    base = dict(document_type='invoice', document_code='INV-1', document_date=date(2026, 11, 1),
                customer_code='acme', ship_from={'line1': '9 Origin', 'city': 'Austin', 'region': 'TX',
                                                 'postal_code': '78701', 'country': 'US'},
                ship_to={'line1': '1 Main', 'city': 'San Francisco', 'region': 'CA', 'postal_code': '94105',
                         'country': 'US'},
                lines=[TaxLine('1', Decimal('100.00'), tax_code='P0000000'),
                       TaxLine('2', Decimal('50.00'), taxable=False)])
    base.update(kw)
    return TaxRequest(**base)


class AvalaraTests(TestCase):
    def setUp(self):
        self.org = make_org('Ava Org', 'ava-org')
        self.conn = TaxConnection.objects.create(organization=self.org, provider_type='avalara', name='a')
        self.conn.set_credentials(AVALARA_CREDS)
        self.conn.save()

    def test_success_preview_is_a_sales_order(self):
        p = get_tax_provider(self.conn, sandbox=True)
        body = {'code': 'abc', 'totalTax': 8.63, 'status': 'Saved',
                'lines': [{'lineNumber': '1', 'tax': 8.63, 'taxableAmount': 100},
                          {'lineNumber': '2', 'tax': 0, 'taxableAmount': 0}],
                'summary': [{'jurisName': 'CALIFORNIA', 'jurisType': 'State', 'rate': 0.06, 'tax': 6.0},
                            {'jurisName': 'SAN FRANCISCO', 'jurisType': 'County', 'rate': 0.0263, 'tax': 2.63}]}
        with patch_http(response(201, body)) as m:
            r = p.calculate(_req())
        self.assertTrue(r.success)
        self.assertEqual(r.total_tax, Decimal('8.63'))
        self.assertFalse(r.committed)
        self.assertEqual(len(r.jurisdictions), 2)
        method, url = m.call_args.args[:2]
        payload = m.call_args.kwargs['json']
        self.assertEqual((method, url), ('POST', 'https://sandbox-rest.avatax.com/api/v2/transactions/create'))
        self.assertEqual(payload['type'], 'SalesOrder')
        self.assertFalse(payload['commit'])
        self.assertNotIn('code', payload)
        self.assertEqual(payload['lines'][0]['taxCode'], 'P0000000')
        self.assertEqual(payload['lines'][1]['taxCode'], 'NT')
        self.assertEqual(m.call_args.kwargs['auth'], ('1100', 'lk-secret'))

    def test_commit_is_a_committed_sales_invoice_with_exemption(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(201, {'code': 'INV-1', 'totalTax': 0, 'status': 'Committed',
                                       'lines': [], 'summary': []})) as m:
            r = p.calculate(_req(commit=True, exemption_number='EX-9', entity_use_code='G'))
        payload = m.call_args.kwargs['json']
        self.assertEqual(m.call_args.args[1], 'https://rest.avatax.com/api/v2/transactions/create')
        self.assertEqual(payload['type'], 'SalesInvoice')
        self.assertTrue(payload['commit'])
        self.assertEqual(payload['code'], 'INV-1')
        self.assertEqual(payload['exemptionNo'], 'EX-9')
        self.assertEqual(payload['entityUseCode'], 'G')
        self.assertTrue(r.committed)
        self.assertEqual(r.total_tax, Decimal('0.00'))

    def test_credit_memo_is_a_return_with_negative_amounts(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(201, {'code': 'CM', 'totalTax': -8.63, 'status': 'Committed',
                                       'lines': [], 'summary': []})) as m:
            r = p.calculate(_req(document_type='credit_memo', commit=True, original_document_code='INV-1'))
        payload = m.call_args.kwargs['json']
        self.assertEqual(payload['type'], 'ReturnInvoice')
        self.assertEqual(payload['lines'][0]['amount'], -100.0)
        self.assertEqual(payload['referenceCode'], 'INV-1')
        self.assertEqual(r.total_tax, Decimal('-8.63'))

    def test_error_is_failure_without_amount(self):
        p = get_tax_provider(self.conn)
        err = {'error': {'code': 'InvalidAddress', 'message': 'Address not geocoded',
                         'details': [{'description': 'zip unknown'}]}}
        with patch_http(response(400, err)):
            r = p.calculate(_req())
        self.assertFalse(r.success)
        self.assertIsNone(r.total_tax)
        self.assertIn('InvalidAddress', r.error)

    def test_timeout_is_failure_not_zero(self):
        p = get_tax_provider(self.conn)
        with patch_http(side_effect=requests.Timeout()):
            r = p.calculate(_req())
        self.assertFalse(r.success)
        self.assertIsNone(r.total_tax)
        self.assertIn('timed out', r.error)

    def test_missing_total_is_failure(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, {'code': 'x'})):
            r = p.calculate(_req())
        self.assertFalse(r.success)
        self.assertIsNone(r.total_tax)

    def test_missing_credentials_never_calls(self):
        self.conn.set_credentials({'account_id': '1'})
        self.conn.save()
        p = get_tax_provider(self.conn)
        with patch_http() as m:
            r = p.calculate(_req())
        m.assert_not_called()
        self.assertFalse(r.success)
        self.assertIn('license_key', r.error)

    def test_ping(self):
        p = get_tax_provider(self.conn, sandbox=True)
        with patch_http(response(200, {'authenticated': True, 'version': '24.1'})) as m:
            ok, msg = p.test_connection()
        self.assertTrue(ok)
        self.assertEqual(m.call_args.args[1], 'https://sandbox-rest.avatax.com/api/v2/utilities/ping')
        with patch_http(response(200, {'authenticated': False})):
            ok, msg = p.test_connection()
        self.assertFalse(ok)

    def test_void(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, {'status': 'Cancelled'})) as m:
            ok, _ = p.void('INV-1')
        self.assertTrue(ok)
        self.assertEqual(m.call_args.args[1],
                         'https://rest.avatax.com/api/v2/companies/DEFAULT/transactions/INV-1/void')
        self.assertEqual(m.call_args.kwargs['json'], {'code': 'DocVoided'})


class TaxJarTests(TestCase):
    def setUp(self):
        self.org = make_org('TJ Org', 'tj-org')
        self.conn = TaxConnection.objects.create(organization=self.org, provider_type='taxjar', name='t')
        self.conn.set_credentials(TAXJAR_CREDS)
        self.conn.save()

    TAX_BODY = {'tax': {'amount_to_collect': 8.63, 'rate': 0.08625, 'has_nexus': True,
                        'jurisdictions': {'country': 'US', 'state': 'CA', 'county': 'SAN FRANCISCO',
                                          'city': 'SAN FRANCISCO'},
                        'breakdown': {'state_tax_collectable': 6.0, 'state_tax_rate': 0.06,
                                      'county_tax_collectable': 2.63, 'county_tax_rate': 0.0263,
                                      'line_items': [{'id': '1', 'tax_collectable': 8.63, 'taxable_amount': 100,
                                                      'combined_tax_rate': 0.08625},
                                                     {'id': '2', 'tax_collectable': 0, 'taxable_amount': 0}]}}}

    def test_success(self):
        p = get_tax_provider(self.conn, sandbox=True)
        with patch_http(response(200, self.TAX_BODY)) as m:
            r = p.calculate(_req(exemption_type='wholesale'))
        self.assertTrue(r.success)
        self.assertEqual(r.total_tax, Decimal('8.63'))
        self.assertEqual([j['type'] for j in r.jurisdictions], ['state', 'county'])
        self.assertEqual(m.call_args.args[1], 'https://api.sandbox.taxjar.com/v2/taxes')
        self.assertEqual(m.call_args.kwargs['headers']['Authorization'], 'Bearer tj-secret')
        payload = m.call_args.kwargs['json']
        self.assertEqual(payload['to_zip'], '94105')
        self.assertEqual(payload['exemption_type'], 'wholesale')
        self.assertEqual(payload['line_items'][1]['product_tax_code'], '99999')
        self.assertEqual(payload['amount'], 150.0)

    def test_commit_reports_an_order(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, self.TAX_BODY), response(201, {'order': {}})) as m:
            r = p.calculate(_req(commit=True))
        self.assertTrue(r.success and r.committed)
        self.assertEqual(m.call_count, 2)
        second = m.call_args_list[1]
        self.assertEqual(second.args[1], 'https://api.taxjar.com/v2/transactions/orders')
        self.assertEqual(second.kwargs['json']['transaction_id'], 'INV-1')
        self.assertEqual(second.kwargs['json']['sales_tax'], 8.63)

    def test_credit_memo_reports_a_refund(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, self.TAX_BODY), response(201, {'refund': {}})) as m:
            r = p.calculate(_req(document_type='credit_memo', document_code='CM-1', commit=True,
                                 original_document_code='INV-1'))
        second = m.call_args_list[1]
        self.assertEqual(second.args[1], 'https://api.taxjar.com/v2/transactions/refunds')
        self.assertEqual(second.kwargs['json']['transaction_reference_id'], 'INV-1')
        self.assertEqual(second.kwargs['json']['amount'], -150.0)
        self.assertEqual(r.total_tax, Decimal('-8.63'))

    def test_report_failure_fails_the_calculation(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, self.TAX_BODY), response(500, {'error': 'Server', 'detail': 'x'})):
            r = p.calculate(_req(commit=True))
        self.assertFalse(r.success)
        self.assertIsNone(r.total_tax)

    def test_error(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(400, {'status': 400, 'error': 'Bad Request', 'detail': 'to_zip invalid'})):
            r = p.calculate(_req())
        self.assertFalse(r.success)
        self.assertIsNone(r.total_tax)
        self.assertIn('to_zip invalid', r.error)

    def test_timeout_is_failure_not_zero(self):
        p = get_tax_provider(self.conn)
        with patch_http(side_effect=requests.Timeout()):
            r = p.calculate(_req())
        self.assertFalse(r.success)
        self.assertIsNone(r.total_tax)

    def test_nexus_regions_test_connection(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, {'regions': [{'region_code': 'CA'}, {'region_code': 'NY'}]})) as m:
            ok, msg = p.test_connection()
        self.assertTrue(ok)
        self.assertIn('CA, NY', msg)
        self.assertEqual(m.call_args.args[:2], ('GET', 'https://api.taxjar.com/v2/nexus/regions'))

    def test_void_deletes_order(self):
        p = get_tax_provider(self.conn)
        with patch_http(response(200, {'order': {}})) as m:
            ok, _ = p.void('INV-1')
        self.assertTrue(ok)
        self.assertEqual(m.call_args.args[:2], ('DELETE', 'https://api.taxjar.com/v2/transactions/orders/INV-1'))
