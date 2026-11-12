"""Server-side authorization regressions for CRM (roles/permissions program).

Commissions: deciding one needs crm_view_forecast and never the rep's own;
without forecast a rep sees only their own commissions. Lead-capture API keys
act for their owner's role.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CommissionAuthzTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from crm.models import Commission, Opportunity
        cls.msp = Organization.objects.create(name='Authz MSP', slug='authz-crm-msp')
        cls.cust = Organization.objects.create(name='Authz Cust', slug='authz-crm-cust')
        # Rep: manages the pipeline (Editor), no forecast flag.
        cls.rep = _make_msp_tech(User.objects.create_user('crm-rep', 'r@x.test', 'pw'))
        Membership.objects.create(user=cls.rep, organization=cls.msp, role=Role.EDITOR)
        cls.rep2 = _make_msp_tech(User.objects.create_user('crm-rep2', 'r2@x.test', 'pw'))
        Membership.objects.create(user=cls.rep2, organization=cls.msp, role=Role.EDITOR)
        # Manager: Owner role, holds crm_view_forecast.
        cls.mgr = _make_msp_tech(User.objects.create_user('crm-mgr', 'm@x.test', 'pw'))
        Membership.objects.create(user=cls.mgr, organization=cls.msp, role=Role.OWNER)

        def _commission(user, name):
            opp = Opportunity.objects.create(
                organization=cls.msp, client_org=cls.cust, name=name,
                estimated_value=Decimal('1000'), stage='closed_won', assigned_to=user)
            return Commission.objects.create(opportunity=opp, user=user, amount=Decimal('100'))
        cls.c_rep = _commission(cls.rep, 'Rep deal')
        cls.c_rep2 = _commission(cls.rep2, 'Rep2 deal')
        cls.c_mgr = _commission(cls.mgr, 'Mgr deal')

    def _client(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.msp.pk
        s.save()
        return c

    def test_rep_without_forecast_cannot_decide_any_commission(self):
        c = self._client(self.rep)
        for com in (self.c_rep, self.c_rep2):
            r = c.post(reverse('crm:commission_decide', args=[com.pk]), {'action': 'paid'})
            self.assertEqual(r.status_code, 403)
            com.refresh_from_db()
            self.assertEqual(com.status, 'pending')

    def test_rep_list_shows_only_own_commissions(self):
        r = self._client(self.rep).get(reverse('crm:commission_list'))
        self.assertEqual(r.status_code, 200)
        ids = {c.pk for c in r.context['commissions']}
        self.assertEqual(ids, {self.c_rep.pk})

    def test_manager_cannot_decide_own_commission(self):
        r = self._client(self.mgr).post(
            reverse('crm:commission_decide', args=[self.c_mgr.pk]), {'action': 'approve'})
        self.assertEqual(r.status_code, 403)
        self.c_mgr.refresh_from_db()
        self.assertEqual(self.c_mgr.status, 'pending')

    def test_manager_decides_reps_commission(self):
        r = self._client(self.mgr).post(
            reverse('crm:commission_decide', args=[self.c_rep.pk]), {'action': 'approve'})
        self.assertEqual(r.status_code, 302)
        self.c_rep.refresh_from_db()
        self.assertEqual(self.c_rep.status, 'approved')
        r = self._client(self.mgr).get(reverse('crm:commission_list'))
        self.assertEqual({c.pk for c in r.context['commissions']},
                         {self.c_rep.pk, self.c_rep2.pk, self.c_mgr.pk})


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LeadCaptureApiAuthzTests(TestCase):

    def _post(self, key):
        return Client().post(
            reverse('crm:lead_capture_api'),
            data='{"company_name": "Prospect", "email": "p@example.com"}',
            content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {key}')

    def test_key_of_member_without_crm_create_lead_is_refused(self):
        from api.models import APIKey
        from crm.models import Lead
        org = Organization.objects.create(name='Key Org', slug='authz-key-org')
        u = User.objects.create_user('key-ro', 'k@x.test', 'pw')
        Membership.objects.create(user=u, organization=org, role=Role.READONLY)
        _, key = APIKey.create_key(org, u, 'leads')
        r = self._post(key)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Lead.objects.filter(organization=org).exists())

    def test_key_of_owner_creates_lead(self):
        from api.models import APIKey
        from crm.models import Lead
        org = Organization.objects.create(name='Key Org 2', slug='authz-key-org2')
        u = User.objects.create_user('key-owner', 'ko@x.test', 'pw')
        Membership.objects.create(user=u, organization=org, role=Role.OWNER)
        _, key = APIKey.create_key(org, u, 'leads')
        r = self._post(key)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Lead.objects.filter(organization=org).exists())
