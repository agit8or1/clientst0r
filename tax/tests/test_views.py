"""Tax settings pages, exemption management, the document panel actions and
the psa send gates."""
from decimal import Decimal
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import permission_registry as registry
from accounts.models import Membership, RoleTemplate
from audit.models import AuditLog
from tax import services
from tax.models import CustomerTaxExemption, ManualTaxRate, TaxCalculation, TaxCategory, TaxSettings

from ._helpers import TAXJAR_CREDS, TEST_MIDDLEWARE, make_invoice, make_org, make_quote, patch_http, \
    provider_settings, response

User = get_user_model()


def _enable_psa():
    from core.models import SystemSetting
    from psa.models import ClientPSASettings
    s = SystemSetting.get_settings()
    s.psa_enabled = True
    s.save()
    return ClientPSASettings


def _staff(user, role=None):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    if role is not None and hasattr(profile, 'global_role_template'):
        profile.global_role_template = role
    profile.save()
    return user


class PermissionRegistryTests(TestCase):
    def test_registered_staff_only_and_off_by_default(self):
        p = registry.get('manage_tax_settings')
        self.assertIsNotNone(p)
        self.assertEqual(p.module, 'billing')
        self.assertEqual(p.status, registry.ENFORCED)
        self.assertIn('manage_tax_settings', registry.STAFF_ONLY_KEYS)
        self.assertNotIn('manage_tax_settings', registry.CUSTOMER_ASSIGNABLE_KEYS)
        self.assertFalse(RoleTemplate._meta.get_field('manage_tax_settings').default)

    def test_builtin_billing_and_owner_roles_hold_it(self):
        from accounts.role_seeds import definitions
        defs = {d.key: d for d in definitions()}
        self.assertTrue(defs['org_owner'].flags.get('manage_tax_settings'))
        self.assertTrue(defs['billing_finance'].flags.get('manage_tax_settings'))
        self.assertFalse(defs['sales_rep'].flags.get('manage_tax_settings'))
        self.assertFalse(defs['customer_admin'].flags.get('manage_tax_settings'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(TestCase):
    def setUp(self):
        _enable_psa()
        self.a = make_org('Alpha', 'tv-alpha')
        self.b = make_org('Beta', 'tv-beta')
        self.root = User.objects.create_superuser('tv_root', 'r@x.com', 'pw')
        self.taxer_role = RoleTemplate.objects.create(name='Taxer', manage_tax_settings=True,
                                                      billing_send_invoices=True, billing_view_invoices=True,
                                                      crm_manage_pipeline=True)
        self.biller_role = RoleTemplate.objects.create(name='Biller', billing_send_invoices=True,
                                                       billing_view_invoices=True, crm_manage_pipeline=True)
        self.taxer = _staff(User.objects.create_user('tv_taxer', 't@x.com', 'pw'))
        Membership.objects.create(user=self.taxer, organization=self.a, role='admin',
                                  role_template=self.taxer_role, is_active=True)
        self.biller = _staff(User.objects.create_user('tv_biller', 'b@x.com', 'pw'))
        Membership.objects.create(user=self.biller, organization=self.a, role='admin',
                                  role_template=self.biller_role, is_active=True)

    def _select(self, org):
        session = self.client.session
        if org is None:
            session.pop('current_organization_id', None)
            session['global_view_mode'] = True
        else:
            session['current_organization_id'] = org.pk
            session['global_view_mode'] = False
        session.save()

    # -- settings ------------------------------------------------------------------------

    def test_settings_needs_permission(self):
        self.client.force_login(self.biller)
        self._select(self.a)
        self.assertEqual(self.client.get(reverse('tax:settings')).status_code, 403)
        self.client.force_login(self.taxer)
        self._select(self.a)
        self.assertEqual(self.client.get(reverse('tax:settings')).status_code, 200)

    def test_customer_user_never_holds_it(self):
        # Customer users (no staff profile) cannot hold staff-only flags.
        cust = User.objects.create_user('tv_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=cust, organization=self.b, role='admin',
                                  role_template=self.taxer_role, is_active=True)
        self.assertFalse(services.may_manage_tax(cust, self.b))

    def test_platform_scope_superuser_and_credentials_sealed(self):
        self.client.force_login(self.root)
        self._select(self.b)  # the selected customer does not matter: settings are MSP-wide
        r = self.client.post(reverse('tax:settings'), {
            'mode': 'taxjar', 'authoritative_system': 'provider', 'taxjar_api_key': 'tj-very-secret',
            'nexus_regions': 'us-ca, US-NY', 'sandbox': 'on', 'origin_region': 'tx'})
        self.assertEqual(r.status_code, 302)
        s = TaxSettings.objects.get(organization__isnull=True)
        self.assertEqual(s.mode, 'taxjar')
        self.assertEqual(s.nexus_regions, ['US-CA', 'US-NY'])
        self.assertEqual(s.origin_region, 'TX')
        self.assertEqual(s.connection.get_credentials()['api_key'], 'tj-very-secret')
        self.assertNotIn('tj-very-secret', s.connection.encrypted_credentials)
        page = self.client.get(reverse('tax:settings')).content.decode()
        self.assertNotIn('tj-very-secret', page)
        # Blank keeps the stored key.
        self.client.post(reverse('tax:settings'), {'mode': 'taxjar', 'taxjar_api_key': ''})
        s.connection.refresh_from_db()
        self.assertEqual(s.connection.get_credentials()['api_key'], 'tj-very-secret')
        self.assertTrue(AuditLog.objects.filter(object_type='tax.TaxSettings').exists())

    def test_test_connection(self):
        provider_settings(self.a, 'taxjar', TAXJAR_CREDS)
        self.client.force_login(self.root)
        self._select(self.a)
        with patch_http(response(200, {'regions': [{'region_code': 'CA'}]})):
            r = self.client.post(reverse('tax:test_connection'), follow=True)
        self.assertContains(r, 'Connection test: Authenticated')

    def test_rate_and_category_crud_is_msp_wide(self):
        self.client.force_login(self.taxer)
        self._select(self.a)
        r = self.client.post(reverse('tax:category_create'), {'code': 'labor', 'name': 'Labor', 'kind': 'labor',
                                                              'taxable': 'on', 'qbo_tax_code_id': '7'})
        self.assertEqual(r.status_code, 302)
        cat = TaxCategory.objects.get(code='labor')
        self.assertIsNone(cat.organization)  # MSP-wide whichever customer is selected
        r = self.client.post(reverse('tax:rate_create'), {'name': 'CA', 'rate': '0.0825', 'state': 'ca',
                                                          'applies_to': [str(cat.pk)]})
        self.assertEqual(r.status_code, 302)
        rate = ManualTaxRate.objects.get(name='CA')
        self.assertEqual((rate.organization, rate.state), (None, 'CA'))
        self.assertEqual(list(rate.applies_to.all()), [cat])
        bad = self.client.post(reverse('tax:rate_create'), {'name': 'Bad', 'rate': '8.25'})
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(ManualTaxRate.objects.filter(name='Bad').exists())
        # A stray row carrying an organization is not part of the MSP-wide table.
        other = ManualTaxRate.objects.create(organization=self.b, name='B', rate=Decimal('0.1'))
        self.assertEqual(self.client.get(reverse('tax:rate_edit', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tax:rate_delete', args=[other.pk])).status_code, 404)
        self.client.post(reverse('tax:rate_delete', args=[rate.pk]))
        self.assertFalse(ManualTaxRate.objects.filter(pk=rate.pk).exists())

    # -- exemptions ------------------------------------------------------------------------

    def test_exemption_lifecycle_with_certificate(self):
        self.client.force_login(self.taxer)
        self._select(self.a)
        url = reverse('tax:client_exemptions', args=[self.a.pk])
        pdf = SimpleUploadedFile('cert.pdf', b'%PDF-1.4\n%test\n', content_type='application/pdf')
        r = self.client.post(url, {'reason': 'resale', 'certificate_number': 'R-55', 'jurisdictions': 'us-ca',
                                   'valid_to': '2027-01-01', 'certificate': pdf})
        self.assertEqual(r.status_code, 302)
        ex = CustomerTaxExemption.objects.get(certificate_number='R-55')
        self.assertEqual(ex.jurisdictions, ['US-CA'])
        self.assertIsNotNone(ex.certificate)
        self.assertEqual(ex.certificate.entity_id, ex.pk)
        self.assertIsNone(ex.verified_at)
        self.client.post(reverse('tax:exemption_action', args=[self.a.pk, ex.pk, 'verify']))
        ex.refresh_from_db()
        self.assertEqual(ex.verified_by, self.taxer)
        bad = SimpleUploadedFile('cert.exe', b'MZ....', content_type='application/octet-stream')
        self.client.post(url, {'reason': 'resale', 'certificate_number': 'R-56', 'certificate': bad})
        self.assertFalse(CustomerTaxExemption.objects.filter(certificate_number='R-56').exists())

    def test_exemptions_need_permission(self):
        self.client.force_login(self.biller)
        self._select(self.a)
        self.assertEqual(self.client.get(reverse('tax:client_exemptions', args=[self.a.pk])).status_code, 403)
        # A customer user holding a role with the flag still cannot (staff only).
        cust = User.objects.create_user('tv_cust2', 'c2@x.com', 'pw')
        Membership.objects.create(user=cust, organization=self.b, role='admin',
                                  role_template=self.taxer_role, is_active=True)
        self.client.force_login(cust)
        self._select(self.b)
        r = self.client.get(reverse('tax:client_exemptions', args=[self.b.pk]))
        self.assertIn(r.status_code, (302, 403, 404))
        self.assertFalse(r.status_code == 200)

    # -- documents ------------------------------------------------------------------------

    def test_detail_pages_show_not_configured(self):
        TaxSettings.objects.create(organization=None, mode='none')
        inv = make_invoice(self.a)
        q = make_quote(self.a)
        self.client.force_login(self.root)
        self._select(self.a)
        for url in (reverse('psa:invoice_detail', args=[inv.pk]), reverse('psa:quote_detail', args=[q.pk])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'Tax not configured')

    def test_preview_shows_breakdown_and_isolation(self):
        TaxSettings.objects.create(organization=None, mode='manual')
        ManualTaxRate.objects.create(organization=None, name='California', rate=Decimal('0.1'), state='CA')
        inv = make_invoice(self.a)
        self.client.force_login(self.biller)
        self._select(self.a)
        r = self.client.post(reverse('tax:preview', args=['invoice', inv.pk]), follow=True)
        self.assertContains(r, 'California')
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, Decimal('100.00'))
        other = make_invoice(self.b)
        r = self.client.post(reverse('tax:preview', args=['invoice', other.pk]))
        self.assertIn(r.status_code, (403, 404))

    def test_override_view_needs_permission_and_is_audited(self):
        provider_settings(self.a, 'taxjar', TAXJAR_CREDS)
        inv = make_invoice(self.a)
        self.client.force_login(self.biller)
        self._select(self.a)
        self.client.post(reverse('tax:override', args=['invoice', inv.pk]), {'amount': '5', 'reason': 'x'})
        self.assertFalse(TaxCalculation.objects.filter(provider='override').exists())
        self.client.force_login(self.taxer)
        self._select(self.a)
        self.client.post(reverse('tax:override', args=['invoice', inv.pk]),
                         {'amount': '5.55', 'reason': 'outage'})
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, Decimal('5.55'))
        self.assertTrue(AuditLog.objects.filter(description__icontains='Manual tax override').exists())

    def test_invoice_email_blocked_on_provider_error(self):
        provider_settings(self.a, 'taxjar', TAXJAR_CREDS)
        inv = make_invoice(self.a)
        self.client.force_login(self.root)
        self._select(self.a)
        with patch_http(side_effect=requests.Timeout()), \
                mock.patch('psa.pdf.email_invoice', return_value=1) as sent:
            r = self.client.post(reverse('psa:invoice_email', args=[inv.pk]), {'recipient': 'c@example.com'},
                                 follow=True)
        sent.assert_not_called()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'draft')
        self.assertContains(r, 'was not sent')

    def test_quote_email_blocked_on_provider_error(self):
        provider_settings(self.a, 'taxjar', TAXJAR_CREDS)
        q = make_quote(self.a)
        self.client.force_login(self.root)
        self._select(self.a)
        with patch_http(side_effect=requests.Timeout()), \
                mock.patch('psa.pdf.email_quote', return_value=1) as sent:
            self.client.post(reverse('psa:quote_email', args=[q.pk]), {'recipient': 'c@example.com'})
        sent.assert_not_called()
        q.refresh_from_db()
        self.assertEqual(q.status, 'draft')

    def test_invoice_marked_sent_blocked_then_allowed_after_override(self):
        provider_settings(self.a, 'taxjar', TAXJAR_CREDS)
        inv = make_invoice(self.a)
        self.client.force_login(self.root)
        self._select(self.a)
        post = {'client_org_id': self.a.pk, 'client_org': self.a.pk, 'title': 'I', 'status': 'sent'}
        with patch_http(side_effect=requests.Timeout()):
            self.client.post(reverse('psa:invoice_edit', args=[inv.pk]), post)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'draft')
        services.apply_manual_override(inv, self.root, '9.99', 'outage')
        with patch_http() as m:
            self.client.post(reverse('psa:invoice_edit', args=[inv.pk]), post)
        m.assert_not_called()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')
        self.assertEqual(inv.tax_amount, Decimal('9.99'))

    def test_new_quote_in_manual_mode_is_taxed_on_save(self):
        TaxSettings.objects.create(organization=None, mode='manual')
        ManualTaxRate.objects.create(organization=None, name='CA', rate=Decimal('0.05'), state='CA')
        self.client.force_login(self.root)
        self._select(self.a)
        self.client.post(reverse('psa:quote_create'), {
            'client_org_id': self.a.pk, 'client_org': self.a.pk, 'title': 'New', 'status': 'draft',
            'li_description': ['Router'], 'li_quantity': ['2'], 'li_unit_price': ['100']})
        from psa.models import Quote
        q = Quote.objects.get(title='New')
        self.assertEqual(q.tax_rate, Decimal('0'))
        self.assertEqual(q.tax_amount, Decimal('10.00'))
        self.assertEqual(services.current_calculation(q).provider, 'manual')

    def test_client_overview_panel(self):
        self.client.force_login(self.taxer)
        self._select(self.a)
        r = self.client.get(reverse('accounts:organization_detail', args=[self.a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse('tax:client_exemptions', args=[self.a.pk]))
