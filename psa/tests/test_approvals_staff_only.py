"""/psa/approvals/ (internal approvals) is MSP staff only, and staff can't
decide a customer sign-off on the customer's behalf."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import PSAApproval
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ApprovalsStaffOnlyTests(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.org = Organization.objects.create(name='ApprCo', slug='appr-co')
        self.tech = _make_msp_tech(User.objects.create_user('appr_tech', password='pw'))
        Membership.objects.create(user=self.tech, organization=self.org,
                                  role=Role.OWNER, is_active=True)
        self.customer = User.objects.create_user('appr_cust', password='pw')
        Membership.objects.create(user=self.customer, organization=self.org,
                                  role=Role.OWNER, is_active=True)
        self.internal = PSAApproval.objects.create(
            organization=self.org, kind='expense', object_type='psa.Expense',
            object_id=1, object_repr='Hotel for onsite visit')
        self.client_signoff = PSAApproval.objects.create(
            organization=self.org, kind='quote', object_type='psa.Quote',
            object_id=2, object_repr='Firewall quote', is_client_approval=True)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        session = c.session
        session['current_organization_id'] = self.org.id
        session['2fa_prompted'] = True
        session.save()
        return c

    def test_customer_cannot_list_decide_or_view_history(self):
        c = self._client(self.customer)
        self.assertEqual(c.get('/psa/approvals/').status_code, 403)
        self.assertEqual(c.get(f'/psa/approvals/{self.internal.pk}/history/').status_code, 403)
        r = c.post(f'/psa/approvals/{self.internal.pk}/decide/', {'decision': 'approve'})
        self.assertEqual(r.status_code, 403)
        self.internal.refresh_from_db()
        self.assertEqual(self.internal.status, 'pending')

    def test_customer_menu_has_no_approvals_link(self):
        r = self._client(self.customer).get('/psa/my-work/')
        self.assertNotContains(r, 'href="/psa/approvals/"')

    def test_staff_can_decide_internal_approval(self):
        c = self._client(self.tech)
        r = c.get('/psa/approvals/')
        self.assertContains(r, 'Hotel for onsite visit')
        self.assertContains(r, 'Awaiting customer')
        c.post(f'/psa/approvals/{self.internal.pk}/decide/', {'decision': 'approve'})
        self.internal.refresh_from_db()
        self.assertEqual(self.internal.status, 'approved')
        self.assertEqual(self.internal.decided_by, self.tech)

    def test_staff_cannot_decide_customer_signoff(self):
        c = self._client(self.tech)
        c.post(f'/psa/approvals/{self.client_signoff.pk}/decide/', {'decision': 'approve'})
        self.client_signoff.refresh_from_db()
        self.assertEqual(self.client_signoff.status, 'pending')
        self.assertIsNone(self.client_signoff.decided_by)
