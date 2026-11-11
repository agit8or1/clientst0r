"""`billing_view_invoices` gates the invoice page, its PDF and the client
account page.

Before this, any signed-in user who could reach PSA opened an invoice or a
customer's account summary (balance, aging, payments) without the flag:
editors and read-only customer users, and MSP technicians whose global role
leaves billing out. Holders keep access; another customer's invoice stays a
404 for customer users, whatever customer the session is on.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.models import Invoice
from psa.tests._base import (TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech,
                             _setup_seed)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceViewPermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.a = Organization.objects.create(name='Billing A', slug='bill-a')
        cls.b = Organization.objects.create(name='Billing B', slug='bill-b')
        for org in (cls.a, cls.b):
            _enable_psa_for(org)
        cls.inv_a = Invoice.objects.create(organization=cls.a, client_org=cls.a, title='A invoice',
                                           invoice_date=date(2026, 9, 1), total=Decimal('10.00'))
        cls.inv_b = Invoice.objects.create(organization=cls.b, client_org=cls.b, title='B invoice',
                                           invoice_date=date(2026, 9, 1), total=Decimal('20.00'))

        cls.owner_a = User.objects.create_user('bill_owner', 'o@a.test', 'pw')
        Membership.objects.create(user=cls.owner_a, organization=cls.a, role=Role.OWNER, is_active=True)
        cls.editor_a = User.objects.create_user('bill_editor', 'e@a.test', 'pw')
        Membership.objects.create(user=cls.editor_a, organization=cls.a, role=Role.EDITOR, is_active=True)
        no_billing = RoleTemplate.objects.create(name='No billing', billing_view_invoices=False)
        cls.readonly_a = User.objects.create_user('bill_ro', 'r@a.test', 'pw')
        Membership.objects.create(user=cls.readonly_a, organization=cls.a, role=Role.READONLY,
                                  role_template=no_billing, is_active=True)

        cls.tech_plain = _make_msp_tech(User.objects.create_user('bill_tech', 't@msp.test', 'pw'))
        cls.tech_no_billing = _make_msp_tech(User.objects.create_user('bill_tech_nb', 'n@msp.test', 'pw'))
        p = cls.tech_no_billing.profile
        p.global_role_template = RoleTemplate.objects.create(name='Tech no billing', tickets_view=True)
        p.save()
        cls.tech_billing = _make_msp_tech(User.objects.create_user('bill_tech_b', 'b@msp.test', 'pw'))
        p = cls.tech_billing.profile
        p.global_role_template = RoleTemplate.objects.create(name='Tech billing', billing_view_invoices=True)
        p.save()
        cls.su = User.objects.create_superuser('bill_su', 's@msp.test', 'pw')

    def _client(self, user, org=None):
        c = Client()
        c.force_login(user)
        if org is not None:
            session = c.session
            session['current_organization_id'] = org.pk
            session.save()
        return c

    def _urls(self, inv, org):
        return (f'/psa/invoices/{inv.pk}/', f'/psa/invoices/{inv.pk}/pdf/', f'/psa/clients/{org.pk}/account/')

    def test_customer_roles_without_the_flag_get_403(self):
        for user in (self.editor_a, self.readonly_a):
            c = self._client(user, self.a)
            for url in self._urls(self.inv_a, self.a):
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(c.get(url).status_code, 403)

    def test_staff_global_role_without_the_flag_gets_403(self):
        c = self._client(self.tech_no_billing)
        for url in self._urls(self.inv_a, self.a):
            with self.subTest(url=url):
                self.assertEqual(c.get(url).status_code, 403)

    def test_holders_keep_access(self):
        cases = ((self.owner_a, self.a), (self.tech_billing, None), (self.tech_plain, None), (self.su, None))
        for user, org in cases:
            c = self._client(user, org)
            for url in (f'/psa/invoices/{self.inv_a.pk}/', f'/psa/clients/{self.a.pk}/account/'):
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(c.get(url).status_code, 200)

    def test_cross_customer_is_404_for_customer_users(self):
        c = self._client(self.owner_a, self.a)
        for url in self._urls(self.inv_b, self.b):
            with self.subTest(url=url):
                self.assertEqual(c.get(url).status_code, 404)

    def test_cross_customer_is_404_in_global_view_too(self):
        # No current customer on the session: the invoice lookup used to be
        # unscoped for everyone in that case.
        c = self._client(self.owner_a)
        session = c.session
        session['global_view_mode'] = True
        session.save()
        self.assertEqual(c.get(f'/psa/invoices/{self.inv_b.pk}/').status_code, 404)
        self.assertEqual(c.get(f'/psa/invoices/{self.inv_b.pk}/pdf/').status_code, 404)

    def test_pdf_opens_for_a_holder(self):
        # invoice_pdf used to raise NameError (Invoice not imported) for everyone.
        from unittest import mock
        with mock.patch('psa.pdf.render_invoice_pdf', return_value=b'%PDF-1.4 test'):
            r = self._client(self.owner_a, self.a).get(f'/psa/invoices/{self.inv_a.pk}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_list_shows_only_invoices_the_user_may_view(self):
        # The list showed numbers, titles and totals to users the invoice page
        # itself refuses.
        for user in (self.editor_a, self.readonly_a, self.tech_no_billing):
            with self.subTest(user=user.username):
                page = self._client(user, self.a).get('/psa/invoices/').content.decode()
                self.assertNotIn('A invoice', page)
        page = self._client(self.owner_a, self.a).get('/psa/invoices/').content.decode()
        self.assertIn('A invoice', page)
        self.assertNotIn('B invoice', page)
        for user in (self.tech_billing, self.tech_plain, self.su):
            with self.subTest(user=user.username):
                self.assertIn('A invoice', self._client(user, self.a).get('/psa/invoices/').content.decode())

    def test_email_needs_the_send_flag(self):
        from unittest import mock
        with mock.patch('psa.pdf.email_invoice') as send:
            r = self._client(self.editor_a, self.a).post(f'/psa/invoices/{self.inv_a.pk}/email/',
                                                         {'recipient': 'x@a.test'})
            self.assertEqual(r.status_code, 403)
            # A technician whose global role leaves billing out; with a
            # membership that allows writing, the flag is what refuses them.
            Membership.objects.create(user=self.tech_no_billing, organization=self.a, role=Role.EDITOR,
                                      is_active=True)
            r = self._client(self.tech_no_billing, self.a).post(f'/psa/invoices/{self.inv_a.pk}/email/',
                                                                {'recipient': 'x@a.test'})
            self.assertEqual(r.status_code, 403)
            send.assert_not_called()

    def test_email_is_bounded_to_the_customer_users_own_customers(self):
        # A customer user who is also a member of B, with A selected, can't
        # reach B's invoice through A's session, and vice versa.
        from unittest import mock
        with mock.patch('psa.pdf.email_invoice') as send:
            r = self._client(self.owner_a, self.a).post(f'/psa/invoices/{self.inv_b.pk}/email/',
                                                        {'recipient': 'x@a.test'})
            self.assertEqual(r.status_code, 404)
            send.assert_not_called()
