"""Server-side authorization regressions for resourcing (roles/permissions
program).

The MSP's team data (roster, cost rates, leave approvals, capacity, billable
targets) is for MSP technicians holding the resourcing_* flag; a customer
Owner/Admin holds those flags on their customer membership and must not reach
it. Nobody approves their own leave. Holiday writes follow the flag in the
holiday's own organization.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from resourcing.models import BillableTarget, Holiday, LeaveRequest, TechCostRate


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerAdminCannotReachMspTeamDataTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.msp = Organization.objects.create(name='R MSP', slug='authz-res-msp')
        cls.cust = Organization.objects.create(name='R Cust', slug='authz-res-cust')
        cls.tech = _make_msp_tech(User.objects.create_user('res-tech', 't@x.test', 'pw'))
        Membership.objects.create(user=cls.tech, organization=cls.msp, role=Role.EDITOR)
        cls.cust_owner = User.objects.create_user('res-cust-owner', 'o@c.test', 'pw')
        Membership.objects.create(user=cls.cust_owner, organization=cls.cust, role=Role.OWNER)
        TechCostRate.objects.create(user=cls.tech, rate_per_hour=Decimal('77.00'),
                                    effective_from=date(2026, 1, 1))
        cls.leave = LeaveRequest.objects.create(
            user=cls.tech, start_date=date(2026, 12, 1), end_date=date(2026, 12, 2))

    def _client(self, user, org):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = org.pk
        s.save()
        return c

    def test_customer_owner_gets_403_on_team_pages(self):
        c = self._client(self.cust_owner, self.cust)
        for url in (reverse('resourcing:tech_roster'),
                    reverse('resourcing:tech_cost_rate_list'),
                    reverse('resourcing:tech_cost_rate_edit', args=[self.tech.pk]),
                    reverse('resourcing:leave_approvals'),
                    reverse('resourcing:capacity_report'),
                    reverse('resourcing:billable_target_edit', args=[self.tech.pk])):
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_customer_owner_cannot_change_cost_rate_or_decide_leave(self):
        c = self._client(self.cust_owner, self.cust)
        r = c.post(reverse('resourcing:tech_cost_rate_edit', args=[self.tech.pk]),
                   {'rate_per_hour': '1.00', 'effective_from': '2026-02-01'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(TechCostRate.objects.filter(user=self.tech).count(), 1)
        r = c.post(reverse('resourcing:leave_decide', args=[self.leave.pk]), {'action': 'deny'})
        self.assertEqual(r.status_code, 403)
        r = c.post(reverse('resourcing:leave_approvals'),
                   {'action': 'deny', 'leave_ids': [self.leave.pk]})
        self.assertEqual(r.status_code, 403)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, 'pending')
        r = c.post(reverse('resourcing:billable_target_edit', args=[self.tech.pk]),
                   {'target_hours_per_week': '1'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(BillableTarget.objects.filter(user=self.tech).exists())

    def test_customer_profile_page_hides_loaded_cost_rate(self):
        r = self._client(self.cust_owner, self.cust).get(reverse('resourcing:my_resourcing'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['show_cost_rate'])
        self.assertNotContains(r, 'Loaded cost rate')

    def test_tech_sees_own_cost_rate(self):
        r = self._client(self.tech, self.msp).get(reverse('resourcing:my_resourcing'))
        self.assertTrue(r.context['show_cost_rate'])
        self.assertContains(r, '77.00')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LeaveSelfApprovalTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.msp = Organization.objects.create(name='L MSP', slug='authz-leave-msp')
        cls.mgr = _make_msp_tech(User.objects.create_user('leave-mgr', 'm@x.test', 'pw'))
        Membership.objects.create(user=cls.mgr, organization=cls.msp, role=Role.ADMIN)
        cls.tech = _make_msp_tech(User.objects.create_user('leave-tech', 't@x.test', 'pw'))
        cls.own = LeaveRequest.objects.create(
            user=cls.mgr, start_date=date(2026, 12, 1), end_date=date(2026, 12, 2))
        cls.other = LeaveRequest.objects.create(
            user=cls.tech, start_date=date(2026, 12, 1), end_date=date(2026, 12, 2))

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.mgr)

    def test_manager_cannot_approve_own_leave(self):
        r = self.c.post(reverse('resourcing:leave_decide', args=[self.own.pk]), {'action': 'approve'})
        self.assertEqual(r.status_code, 403)
        self.c.post(reverse('resourcing:leave_approvals'),
                    {'action': 'approve', 'leave_ids': [self.own.pk, self.other.pk]})
        self.own.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.own.status, 'pending')
        self.assertEqual(self.other.status, 'approved')

    def test_manager_approves_other_leave(self):
        r = self.c.post(reverse('resourcing:leave_decide', args=[self.other.pk]), {'action': 'approve'})
        self.assertEqual(r.status_code, 302)
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, 'approved')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class HolidayFlagFromOtherMembershipTests(TestCase):
    """Owner in A (holds resourcing_manage_holidays), Read-Only in B: the flag
    from A must not let them manage B's holidays."""

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Hol A', slug='authz-hol-a')
        cls.b = Organization.objects.create(name='Hol B', slug='authz-hol-b')
        cls.u = User.objects.create_user('hol-user', 'h@x.test', 'pw')
        Membership.objects.create(user=cls.u, organization=cls.a, role=Role.OWNER)
        Membership.objects.create(user=cls.u, organization=cls.b, role=Role.READONLY)
        cls.hol_b = Holiday.objects.create(organization=cls.b, name='B day',
                                           date=date.today() + timedelta(days=10))
        cls.hol_a = Holiday.objects.create(organization=cls.a, name='A day',
                                           date=date.today() + timedelta(days=10))

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.u)

    def test_cannot_edit_or_delete_other_orgs_holiday(self):
        self.assertEqual(self.c.get(reverse('resourcing:holiday_edit', args=[self.hol_b.pk])).status_code, 404)
        self.assertEqual(self.c.post(reverse('resourcing:holiday_delete', args=[self.hol_b.pk])).status_code, 404)
        self.assertTrue(Holiday.objects.filter(pk=self.hol_b.pk).exists())

    def test_cannot_create_holiday_in_other_org(self):
        self.c.post(reverse('resourcing:holiday_add'), {
            'organization': self.b.pk, 'name': 'Sneaky', 'date': '2026-12-24'})
        self.assertFalse(Holiday.objects.filter(name='Sneaky').exists())

    def test_own_org_still_managed(self):
        r = self.c.post(reverse('resourcing:holiday_delete', args=[self.hol_a.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Holiday.objects.filter(pk=self.hol_a.pk).exists())
