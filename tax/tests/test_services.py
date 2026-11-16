"""tax.services: manual matching, effective dates, exemptions, labor, the
provider-failure rule (error, never zero, finalize blocked), overrides and
organization isolation."""
from datetime import date, timedelta
from decimal import Decimal

import requests
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog
from tax import services
from tax.models import (
    CustomerTaxExemption, LineTaxCategory, ManualTaxRate, TaxCalculation, TaxCategory, TaxSettings,
)

from ._helpers import (
    AVALARA_CREDS, TAXJAR_CREDS, make_invoice, make_org, make_quote, patch_http, provider_settings, response,
)

D = Decimal


class ManualMatchingTests(TestCase):
    def setUp(self):
        self.org = make_org('Acme', 'acme')
        TaxSettings.objects.create(organization=None, mode='manual')

    def _rate(self, name, rate, org=None, **kw):
        return ManualTaxRate.objects.create(organization=org, name=name, rate=D(rate), **kw)

    def test_most_specific_wins(self):
        self._rate('US', '0.01', country='US')
        self._rate('CA', '0.06', state='CA')
        self._rate('SF city', '0.08625', state='CA', city='San Francisco')
        self._rate('941 prefix', '0.07', state='CA', zip_pattern='941*')
        exact = self._rate('94105', '0.09', state='CA', zip_pattern='94105')
        ship = services.ship_to_for(customer=self.org)
        self.assertEqual(services.match_manual_rate(self.org, ship, date(2026, 11, 1)), exact)
        exact.delete()
        self.assertEqual(services.match_manual_rate(self.org, ship, date(2026, 11, 1)).name, '941 prefix')
        ManualTaxRate.objects.filter(name='941 prefix').delete()
        self.assertEqual(services.match_manual_rate(self.org, ship, date(2026, 11, 1)).name, 'SF city')

    def test_no_match_for_other_state(self):
        self._rate('NY', '0.08', state='NY')
        ship = services.ship_to_for(customer=self.org)
        self.assertIsNone(services.match_manual_rate(self.org, ship, date(2026, 11, 1)))

    def test_effective_dates(self):
        self._rate('old', '0.05', state='CA', effective_to=date(2026, 6, 30))
        self._rate('new', '0.06', state='CA', effective_from=date(2026, 7, 1))
        ship = services.ship_to_for(customer=self.org)
        self.assertEqual(services.match_manual_rate(self.org, ship, date(2026, 6, 30)).name, 'old')
        self.assertEqual(services.match_manual_rate(self.org, ship, date(2026, 7, 1)).name, 'new')

    def test_install_wide_rates_apply_to_every_customer_and_org_rows_are_ignored(self):
        other = make_org('Other', 'other', state='CA', postal_code='94105')
        self._rate('MSP-wide CA', '0.07', state='CA')
        # A row carrying an organization is not part of the MSP-wide table.
        self._rate('stray org row', '0.20', org=other, state='CA', zip_pattern='94105')
        for customer in (self.org, other):
            ship = services.ship_to_for(customer=customer)
            self.assertEqual(services.match_manual_rate(customer, ship, date(2026, 11, 1)).name, 'MSP-wide CA')

    def test_manual_calculation_applies_to_draft(self):
        self._rate('CA', '0.0825', state='CA')
        inv = make_invoice(self.org)
        out = services.calculate_tax(inv)
        inv.refresh_from_db()
        self.assertEqual(out.status, 'ok')
        self.assertEqual(inv.tax_amount, D('82.50'))
        self.assertEqual(inv.total, D('1082.50'))
        self.assertEqual(out.jurisdictions[0]['name'], 'CA')
        calc = services.current_calculation(inv)
        self.assertEqual(calc.total_tax, D('82.50'))
        # A later recompute (e.g. a payment) keeps the calculated tax.
        inv.recompute_totals()
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, D('82.50'))

    def test_no_rate_is_an_error_not_zero(self):
        inv = make_invoice(self.org)
        out = services.calculate_tax(inv)
        self.assertTrue(out.blocked)
        self.assertIsNone(out.total_tax)
        self.assertTrue(services.finalize_document(inv).blocked)

    def test_outside_nexus_is_zero_with_reason(self):
        s = TaxSettings.objects.get(organization__isnull=True)
        s.nexus_regions = ['US-NY']
        s.save()
        out = services.calculate_tax(make_invoice(self.org))
        self.assertEqual(out.status, 'ok')
        self.assertEqual(out.total_tax, D('0.00'))
        self.assertIn('No nexus', out.message)

    def test_missing_address_is_an_error(self):
        bare = make_org('Bare', 'bare', state='', postal_code='')
        TaxSettings.objects.create(organization=bare, mode='manual')
        out = services.calculate_tax(make_invoice(bare))
        self.assertTrue(out.blocked)
        self.assertIn('billing address', out.message)


class LaborAndCategoryTests(TestCase):
    def setUp(self):
        self.org = make_org('Labor Co', 'labor-co')
        self.settings = TaxSettings.objects.create(organization=None, mode='manual', labor_taxable=False)
        self.labor = TaxCategory.objects.create(organization=None, code='labor', name='Labor', kind='labor')
        self.rate = ManualTaxRate.objects.create(organization=None, name='CA', rate=D('0.10'), state='CA')
        self.inv = make_invoice(self.org, lines=(('Laptop', '1', '1000.00', 'manual'),
                                                 ('Install', '2', '100.00', 'time')))

    def test_labor_not_taxable_by_default(self):
        out = services.calculate_tax(self.inv)
        self.assertEqual(out.total_tax, D('100.00'))

    def test_labor_taxable_toggle(self):
        self.settings.labor_taxable = True
        self.settings.save()
        self.assertEqual(services.calculate_tax(self.inv).total_tax, D('120.00'))

    def test_jurisdiction_overrides_labor_default(self):
        self.rate.labor_taxable = True
        self.rate.save()
        self.assertEqual(services.calculate_tax(self.inv).total_tax, D('120.00'))

    def test_explicit_line_category_and_rate_category_list(self):
        sw = TaxCategory.objects.create(organization=None, code='saas', name='SaaS', kind='software',
                                        taxable=False)
        laptop = self.inv.line_items.get(description='Laptop')
        LineTaxCategory.objects.create(line_type='invoice_line', line_id=laptop.pk, category=sw)
        self.assertEqual(services.calculate_tax(self.inv).total_tax, D('0.00'))
        goods = TaxCategory.objects.create(organization=None, code='goods', name='Goods', kind='goods')
        LineTaxCategory.objects.filter(line_id=laptop.pk).update(category=goods)
        self.rate.applies_to.set([self.labor])
        self.settings.labor_taxable = True
        self.settings.save()
        # The rate taxes labor only: the laptop is not taxed here.
        self.assertEqual(services.calculate_tax(self.inv).total_tax, D('20.00'))

    def test_line_flag_non_taxable(self):
        self.inv.line_items.filter(description='Laptop').update(is_taxable=False)
        self.assertEqual(services.calculate_tax(self.inv).total_tax, D('0.00'))


class ExemptionTests(TestCase):
    def setUp(self):
        self.org = make_org('Exempt Co', 'exempt-co')
        TaxSettings.objects.create(organization=None, mode='manual')
        ManualTaxRate.objects.create(organization=None, name='CA', rate=D('0.10'), state='CA')
        self.user = get_user_model().objects.create_user('ver', 'v@x.com', 'pw')

    def _ex(self, **kw):
        d = dict(client=self.org, reason='resale', certificate_number='R-1', verified_by=self.user,
                 verified_at=timezone.now())
        d.update(kw)
        return CustomerTaxExemption.objects.create(**d)

    def test_valid_certificate_zeroes_tax_with_reason(self):
        ex = self._ex(valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31))
        inv = make_invoice(self.org)
        out = services.calculate_tax(inv)
        inv.refresh_from_db()
        self.assertEqual(out.status, 'exempt')
        self.assertEqual(inv.tax_amount, D('0.00'))
        self.assertIn('R-1', out.message)
        self.assertEqual(services.current_calculation(inv).exemption, ex)

    def test_expired_certificate_is_taxed(self):
        self._ex(valid_to=date(2026, 10, 31))
        out = services.calculate_tax(make_invoice(self.org))
        self.assertEqual(out.status, 'ok')
        self.assertEqual(out.total_tax, D('100.00'))

    def test_unverified_or_other_region_is_taxed(self):
        self._ex(verified_at=None, verified_by=None)
        self.assertEqual(services.calculate_tax(make_invoice(self.org)).total_tax, D('100.00'))
        CustomerTaxExemption.objects.all().delete()
        self._ex(jurisdictions=['US-NY'])
        self.assertEqual(services.calculate_tax(make_invoice(self.org)).total_tax, D('100.00'))

    def test_exemption_sent_to_avalara(self):
        TaxSettings.objects.filter(organization__isnull=True).delete()
        provider_settings(self.org, 'avalara', AVALARA_CREDS)
        self._ex(reason='government', certificate_number='GOV-7')
        inv = make_invoice(self.org)
        with patch_http(response(201, {'code': 'x', 'totalTax': 0, 'lines': [], 'summary': []})) as m:
            out = services.calculate_tax(inv)
        payload = m.call_args.kwargs['json']
        self.assertEqual(payload['exemptionNo'], 'GOV-7')
        self.assertEqual(payload['entityUseCode'], 'B')
        self.assertEqual(out.status, 'exempt')


class ModeTests(TestCase):
    def setUp(self):
        self.org = make_org('Mode Co', 'mode-co')

    def test_mode_none_is_explicit_not_configured_zero(self):
        TaxSettings.objects.create(organization=None, mode='none')
        inv = make_invoice(self.org, tax_rate='0.08')
        out = services.calculate_tax(inv)
        inv.refresh_from_db()
        self.assertEqual(out.status, 'not_configured')
        self.assertIn('Tax not configured', out.message)
        self.assertEqual(inv.tax_amount, D('0.00'))

    def test_mode_none_never_rewrites_a_sent_invoice(self):
        inv = make_invoice(self.org, tax_rate='0.08', status='sent')
        self.assertEqual(inv.tax_amount, D('80.00'))
        TaxSettings.objects.create(organization=None, mode='none')
        inv.recompute_totals()
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, D('80.00'))

    def test_no_settings_keeps_flat_rate(self):
        inv = make_invoice(self.org, tax_rate='0.08')
        self.assertEqual(inv.tax_amount, D('80.00'))
        out = services.calculate_tax(inv)
        self.assertEqual(out.status, 'ok')
        self.assertEqual(out.total_tax, D('80.00'))

    def test_flat_zero_rate_says_not_configured(self):
        out = services.calculate_tax(make_invoice(self.org))
        self.assertEqual(out.status, 'not_configured')


class ProviderFailureTests(TestCase):
    """The hard rule: a provider failure is an error, never zero, and blocks sending."""

    def setUp(self):
        self.org = make_org('Prov Co', 'prov-co')
        self.settings = provider_settings(self.org, 'taxjar', TAXJAR_CREDS)
        self.user = get_user_model().objects.create_user('plain', 'p@x.com', 'pw')
        self.admin = get_user_model().objects.create_superuser('root', 'r@x.com', 'pw')

    def test_timeout_is_error_and_leaves_tax_alone(self):
        inv = make_invoice(self.org, tax_rate='0.05')
        before = inv.tax_amount
        with patch_http(side_effect=requests.Timeout()):
            out = services.calculate_tax(inv)
        inv.refresh_from_db()
        self.assertEqual(out.status, 'error')
        self.assertIsNone(out.total_tax)
        self.assertEqual(inv.tax_amount, before)
        calc = services.current_calculation(inv)
        self.assertEqual(calc.status, 'error')
        self.assertIsNone(calc.total_tax)
        self.settings.connection.refresh_from_db()
        self.assertIn('timed out', self.settings.connection.last_error)

    def test_finalize_blocked_on_provider_error(self):
        inv = make_invoice(self.org)
        with patch_http(response(500, {'error': 'Server', 'detail': 'down'})):
            out = services.finalize_document(inv)
        self.assertTrue(out.blocked)
        self.assertIn('was not sent', out.message)
        self.assertIn('manage_tax_settings', out.message)

    def test_no_connection_is_an_error(self):
        self.settings.connection = None
        self.settings.save()
        out = services.calculate_tax(make_invoice(self.org))
        self.assertTrue(out.blocked)

    def test_override_requires_permission(self):
        inv = make_invoice(self.org)
        with self.assertRaises(PermissionDenied):
            services.apply_manual_override(inv, self.user, '12.34', 'provider down')
        self.assertFalse(TaxCalculation.objects.filter(provider='override').exists())

    def test_override_is_audited_and_unblocks_finalize(self):
        inv = make_invoice(self.org)
        with patch_http(side_effect=requests.Timeout()):
            self.assertTrue(services.finalize_document(inv).blocked)
        with self.assertRaises(ValueError):
            services.apply_manual_override(inv, self.admin, '12.34', '')
        calc = services.apply_manual_override(inv, self.admin, '12.34', 'TaxJar outage, rate from portal')
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, D('12.34'))
        self.assertIn('Replaces calculation', calc.error)
        self.assertTrue(AuditLog.objects.filter(object_type='psa.Invoice', object_id=inv.pk,
                                                description__icontains='Manual tax override').exists())
        with patch_http() as m:
            out = services.finalize_document(inv)
        m.assert_not_called()
        self.assertFalse(out.blocked)
        self.assertEqual(out.provider, 'override')

    def test_failed_preview_keeps_override_current(self):
        inv = make_invoice(self.org)
        services.apply_manual_override(inv, self.admin, '7.00', 'outage')
        with patch_http(side_effect=requests.Timeout()):
            out = services.calculate_tax(inv)
        self.assertTrue(out.blocked)
        self.assertEqual(services.current_calculation(inv).provider, 'override')
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, D('7.00'))
        self.assertFalse(services.finalize_document(inv).blocked)

    def test_override_lapses_when_lines_change(self):
        from psa.models import InvoiceLineItem
        inv = make_invoice(self.org)
        services.apply_manual_override(inv, self.admin, '12.34', 'outage')
        InvoiceLineItem.objects.create(invoice=inv, description='More', quantity=D('1'), unit_price=D('5'))
        with patch_http(side_effect=requests.Timeout()):
            self.assertTrue(services.finalize_document(inv).blocked)

    def test_commit_once(self):
        inv = make_invoice(self.org)
        body = {'tax': {'amount_to_collect': 86.25, 'breakdown': {'line_items': []}}}
        with patch_http(response(200, body), response(201, {})) as m:
            out = services.finalize_document(inv)
        self.assertEqual(m.call_count, 2)
        self.assertTrue(out.calculation.committed)
        with patch_http() as m:
            again = services.finalize_document(inv)
        m.assert_not_called()
        self.assertEqual(again.total_tax, D('86.25'))
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, D('86.25'))

    def test_quote_preview_never_commits(self):
        q = make_quote(self.org)
        body = {'tax': {'amount_to_collect': 86.25, 'breakdown': {'line_items': []}}}
        with patch_http(response(200, body)) as m:
            out = services.finalize_document(q)
        self.assertEqual(m.call_count, 1)  # /v2/taxes only, no order
        self.assertFalse(out.calculation.committed)

    def test_void_on_invoice_void(self):
        inv = make_invoice(self.org)
        body = {'tax': {'amount_to_collect': 1, 'breakdown': {'line_items': []}}}
        with patch_http(response(200, body), response(201, {})):
            services.finalize_document(inv)
        inv.status = 'sent'
        inv.save()
        with patch_http(response(200, {})) as m, self.captureOnCommitCallbacks(execute=True):
            inv.status = 'void'
            inv.save()
        self.assertEqual(m.call_args.args[0], 'DELETE')
        self.assertIsNotNone(TaxCalculation.objects.get(committed=True).voided_at)


class CustomerIsolationTests(TestCase):
    """One MSP per install: customers share the MSP-wide tax setup, but one
    customer's exemption and address never affect another customer."""

    def setUp(self):
        self.a = make_org('Cust A', 'iso-a')                                  # San Francisco, CA
        self.b = make_org('Cust B', 'iso-b', city='Albany', state='NY', postal_code='12207')
        TaxSettings.objects.create(organization=None, mode='manual')
        ManualTaxRate.objects.create(organization=None, name='CA', rate=D('0.10'), state='CA')
        ManualTaxRate.objects.create(organization=None, name='NY', rate=D('0.08'), state='NY')
        user = get_user_model().objects.create_user('iso', 'i@x.com', 'pw')
        CustomerTaxExemption.objects.create(client=self.a, reason='resale', certificate_number='A-1',
                                            verified_by=user, verified_at=timezone.now())

    def test_exemption_belongs_to_its_customer(self):
        self.assertEqual(services.calculate_tax(make_invoice(self.a)).status, 'exempt')
        out_b = services.calculate_tax(make_invoice(self.b))
        self.assertEqual(out_b.status, 'ok')
        self.assertEqual(out_b.total_tax, D('80.00'))

    def test_jurisdiction_comes_from_each_customers_billing_address(self):
        CustomerTaxExemption.objects.all().delete()
        self.assertEqual(services.calculate_tax(make_invoice(self.a)).jurisdictions[0]['name'], 'CA')
        self.assertEqual(services.calculate_tax(make_invoice(self.b)).jurisdictions[0]['name'], 'NY')

    def test_calculations_are_per_document(self):
        ia, ib = make_invoice(self.a), make_invoice(self.b)
        services.calculate_tax(ia)
        services.calculate_tax(ib)
        self.assertEqual(services.current_calculation(ia).organization, self.a)
        self.assertEqual(services.current_calculation(ib).organization, self.b)
        self.assertEqual(TaxCalculation.objects.filter(document_type='invoice', document_id=ia.pk).count(), 1)


class AccountingMappingTests(TestCase):
    def test_tax_mapping_for_push(self):
        from tax.accounting import tax_mapping_for_push
        org = make_org('Map', 'map')
        TaxSettings.objects.create(organization=None, mode='manual', labor_taxable=False)
        TaxCategory.objects.create(organization=None, code='labor', name='Labor', kind='labor',
                                   qbo_tax_code_id='5', xero_tax_type='EXEMPTOUTPUT')
        TaxCategory.objects.create(organization=None, code='goods', name='Goods', kind='goods', is_default=True,
                                   qbo_tax_code_id='3', xero_tax_type='OUTPUT2')
        ManualTaxRate.objects.create(organization=None, name='CA', rate=D('0.1'), state='CA')
        inv = make_invoice(org, lines=(('Laptop', '1', '100', 'manual'), ('Work', '1', '50', 'time')))
        services.calculate_tax(inv)
        m = tax_mapping_for_push(inv, 'quickbooks_online')
        laptop = inv.line_items.get(description='Laptop').pk
        work = inv.line_items.get(description='Work').pk
        self.assertTrue(m['send_tax'])
        self.assertFalse(m['stale'])
        self.assertEqual(m['lines'][laptop]['tax_code'], '3')
        self.assertEqual(m['lines'][laptop]['tax'], D('10.00'))
        self.assertFalse(m['lines'][work]['taxable'])
        self.assertEqual(tax_mapping_for_push(inv, 'xero')['lines'][work]['tax_code'], 'EXEMPTOUTPUT')
