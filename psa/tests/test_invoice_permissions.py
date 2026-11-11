"""
Invoice edit and payment recording follow the billing role flags.

  * invoice_form (create / edit) needs `billing_send_invoices` for the
    customer billed (or the customer it is booked under). There is no
    separate "manage invoices" flag: sending is the existing invoice-edit
    right.
  * payment_add needs `billing_record_payments` the same way.
  * Both reach only invoices of the user's own customers (customer users);
    roles that hold the flags (Owner, Admin, a global role granting them,
    superusers) keep their access.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from core.models import Organization
from psa.models import Invoice, InvoiceLineItem, Payment
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed


def _staff(user, role):
    profile = user.profile if hasattr(user, 'profile') else UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    return user


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoicePermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.a = Organization.objects.create(name='IP Alpha', slug='ip-alpha')
        cls.b = Organization.objects.create(name='IP Bravo', slug='ip-bravo')
        for org in (cls.a, cls.b):
            _enable_psa_for(org)
        viewer = RoleTemplate.objects.create(name='IP invoice viewer', billing_view_invoices=True)
        biller = RoleTemplate.objects.create(name='IP biller', billing_view_invoices=True,
                                             billing_send_invoices=True, billing_record_payments=True)
        cls.tech_viewer = _staff(User.objects.create_user('ip_view', 'v@msp.test', 'pw-ip-123'), viewer)
        cls.tech_biller = _staff(User.objects.create_user('ip_bill', 'b@msp.test', 'pw-ip-123'), biller)
        for u in (cls.tech_viewer, cls.tech_biller):
            Membership.objects.create(user=u, organization=cls.a, role=Role.EDITOR, is_active=True)
        cls.owner_a = User.objects.create_user('ip_owner', 'o@alpha.test', 'pw-ip-123')
        Membership.objects.create(user=cls.owner_a, organization=cls.a, role=Role.OWNER, is_active=True)
        cls.editor_a = User.objects.create_user('ip_editor', 'e@alpha.test', 'pw-ip-123')
        Membership.objects.create(user=cls.editor_a, organization=cls.a, role=Role.EDITOR, is_active=True)
        cls.admin = User.objects.create_superuser('ip_admin', 'ad@x.test', 'pw-ip-123')

    def setUp(self):
        self.inv_a = self._invoice(self.a, 'Alpha draft')
        self.inv_b = self._invoice(self.b, 'Bravo draft')

    def _invoice(self, org, title):
        inv = Invoice.objects.create(organization=org, client_org=org, title=title,
                                     invoice_date=date.today(), status='draft')
        InvoiceLineItem.objects.create(invoice=inv, description='Work', quantity=1, unit_price=Decimal('100'))
        inv.recompute_totals()
        return inv

    def _c(self, user, org):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = org.pk
        s.save()
        return c

    def _edit(self, user, inv, org=None):
        return self._c(user, org or inv.organization).post(
            reverse('psa:invoice_edit', args=[inv.pk]), {'title': 'Changed', 'client_org': str(inv.client_org_id)})

    def _pay(self, user, inv, org=None):
        return self._c(user, org or inv.organization).post(
            reverse('psa:payment_add', args=[inv.pk]), {'amount': '25', 'method': 'ach'})

    # --- payment_add ------------------------------------------------------

    def test_payment_route_works(self):
        r = self._pay(self.admin, self.inv_a)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 1)

    def test_payment_needs_record_payments(self):
        self.assertEqual(self._pay(self.tech_viewer, self.inv_a).status_code, 403)
        self.assertEqual(self._pay(self.editor_a, self.inv_a).status_code, 403)
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self._pay(self.tech_biller, self.inv_a).status_code, 302)
        self.assertEqual(self._pay(self.owner_a, self.inv_a).status_code, 302)
        self.assertEqual(Payment.objects.filter(invoice=self.inv_a).count(), 2)

    def test_payment_limited_to_the_users_customers(self):
        # Owner of Alpha, session pointed at Bravo: not their customer.
        r = self._pay(self.owner_a, self.inv_b, org=self.b)
        self.assertIn(r.status_code, (302, 403, 404))
        self.assertFalse(Payment.objects.filter(invoice=self.inv_b).exists())

    # --- invoice_form -----------------------------------------------------

    def test_edit_needs_send_invoices(self):
        for u in (self.tech_viewer, self.editor_a):
            self.assertEqual(self._edit(u, self.inv_a).status_code, 403, u.username)
            self.assertEqual(self._c(u, self.a).get(
                reverse('psa:invoice_edit', args=[self.inv_a.pk])).status_code, 403, u.username)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.title, 'Alpha draft')
        for u in (self.tech_biller, self.owner_a, self.admin):
            self.assertEqual(self._edit(u, self.inv_a).status_code, 302, u.username)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.title, 'Changed')

    def test_create_needs_send_invoices(self):
        before = Invoice.objects.count()
        data = {'title': 'New one', 'client_org': str(self.a.pk), 'client_org_id': str(self.a.pk)}
        for u in (self.tech_viewer, self.editor_a):
            self.assertEqual(self._c(u, self.a).get(reverse('psa:invoice_create')).status_code, 403)
            self.assertEqual(self._c(u, self.a).post(reverse('psa:invoice_create'), data).status_code, 403)
        self.assertEqual(Invoice.objects.count(), before)
        r = self._c(self.owner_a, self.a).post(reverse('psa:invoice_create'), data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Invoice.objects.count(), before + 1)

    def test_edit_limited_to_the_users_customers(self):
        r = self._edit(self.owner_a, self.inv_b, org=self.b)
        self.assertIn(r.status_code, (302, 403, 404))
        self.inv_b.refresh_from_db()
        self.assertEqual(self.inv_b.title, 'Bravo draft')
        # Nor can they bill Bravo from their own invoice form.
        r = self._c(self.owner_a, self.a).post(reverse('psa:invoice_create'),
                                               {'title': 'Sneaky', 'client_org': str(self.b.pk),
                                                'client_org_id': str(self.b.pk)})
        self.assertFalse(Invoice.objects.filter(title='Sneaky').exists())
