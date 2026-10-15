"""
Customer boundary on PSA edit forms and client-account views (v3.17.599).

MSP staff work across every customer. A customer user (an org_user with a
membership in one customer) must not open, edit, or create records for a
different customer by changing an ID in the URL or the POST body.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import CannedReply, Charge, Contract, Invoice, Project
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerBoundaryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.msp = Organization.objects.create(name='MSP', slug='cb-msp')
        cls.cust_a = Organization.objects.create(name='Customer A', slug='cb-a')
        cls.cust_b = Organization.objects.create(name='Customer B', slug='cb-b')
        for org in (cls.msp, cls.cust_a, cls.cust_b):
            _enable_psa_for(org)

        cls.customer_user = User.objects.create_user('cb_editor', 'e@a.test', 'pw-cb-123')
        Membership.objects.create(
            user=cls.customer_user, organization=cls.cust_a, role=Role.EDITOR, is_active=True)
        cls.staff = User.objects.create_superuser('cb_staff', 's@msp.test', 'pw-cb-123')

        # B's records, both as the MSP books them and as owned by B directly.
        cls.contract_b = Contract.objects.create(
            organization=cls.cust_b, client_org=cls.cust_b, name='B managed',
            start_date=date(2026, 1, 1))
        cls.msp_contract_b = Contract.objects.create(
            organization=cls.msp, client_org=cls.cust_b, name='MSP-booked B',
            start_date=date(2026, 1, 1))
        cls.invoice_b = Invoice.objects.create(
            organization=cls.cust_b, client_org=cls.cust_b, title='B invoice',
            invoice_date=date(2026, 9, 1))
        cls.project_b = Project.objects.create(
            organization=cls.cust_b, client_org=cls.cust_b, name='B project')
        cls.reply_b = CannedReply.objects.create(
            organization=cls.cust_b, name='B reply', body='hi', created_by=cls.staff)
        cls.contract_a = Contract.objects.create(
            organization=cls.cust_a, client_org=cls.cust_a, name='A managed',
            start_date=date(2026, 1, 1))

    def _login(self, user, org):
        c = Client()
        c.force_login(user)
        session = c.session
        session['current_organization_id'] = org.id
        session.save()
        return c

    def test_customer_cannot_open_another_customers_records(self):
        c = self._login(self.customer_user, self.cust_a)
        for url in (
            f'/psa/contracts/{self.contract_b.pk}/edit/',
            f'/psa/contracts/{self.msp_contract_b.pk}/edit/',
            f'/psa/invoices/{self.invoice_b.pk}/edit/',
            f'/psa/projects/{self.project_b.pk}/edit/',
            f'/psa/canned/{self.reply_b.pk}/edit/',
            f'/psa/clients/{self.cust_b.pk}/account/',
        ):
            with self.subTest(url=url):
                self.assertEqual(c.get(url).status_code, 404)

    def test_customer_can_still_edit_own_records(self):
        c = self._login(self.customer_user, self.cust_a)
        self.assertEqual(c.get(f'/psa/contracts/{self.contract_a.pk}/edit/').status_code, 200)
        self.assertEqual(c.get(f'/psa/clients/{self.cust_a.pk}/account/').status_code, 200)

    def test_customer_cannot_add_charge_to_another_customer(self):
        c = self._login(self.customer_user, self.cust_a)
        r = c.post(f'/psa/clients/{self.cust_b.pk}/charge/',
                   {'description': 'sneaky', 'amount': '10.00'})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Charge.objects.filter(client_org=self.cust_b).exists())

    def test_customer_cannot_create_contract_for_another_customer(self):
        c = self._login(self.customer_user, self.cust_a)
        c.post('/psa/contracts/new/', {
            'client_org_id': str(self.cust_b.pk), 'client_org': str(self.cust_b.pk),
            'name': 'planted', 'contract_type': 'block_hours', 'status': 'draft',
        })
        self.assertFalse(Contract.objects.filter(name='planted').exists())

    def test_customer_dropdown_lists_only_own_customers(self):
        c = self._login(self.customer_user, self.cust_a)
        r = c.get('/psa/contracts/new/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.context['client_orgs']), [self.cust_a])

    def test_staff_still_work_across_customers(self):
        c = self._login(self.staff, self.cust_a)
        for url in (
            f'/psa/contracts/{self.contract_b.pk}/edit/',
            f'/psa/invoices/{self.invoice_b.pk}/edit/',
            f'/psa/projects/{self.project_b.pk}/edit/',
            f'/psa/clients/{self.cust_b.pk}/account/',
        ):
            with self.subTest(url=url):
                self.assertEqual(c.get(url).status_code, 200)

    def test_charge_add_by_staff_still_works(self):
        c = self._login(self.staff, self.cust_a)
        c.post(f'/psa/clients/{self.cust_b.pk}/charge/',
               {'description': 'onsite', 'amount': '25.00'})
        self.assertTrue(Charge.objects.filter(client_org=self.cust_b, amount=Decimal('25.00')).exists())
