"""
Tests for accounts permission utilities + RoleTemplate boolean gates.

v3.17.145 — adds Reports + financials permission groups (RoleTemplate
booleans) and the `accounts.permission_utils.user_has_perm/require_perm`
helpers that mirror the v3.17.134 KB pattern.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings


# Mirror the test middleware setup from psa.tests so we bypass the 2FA
# enforcement middleware and django-axes lockouts.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReportsPermissionTests(TestCase):
    """v3.17.145: report views gated by RoleTemplate booleans."""

    @classmethod
    def setUpTestData(cls):
        cls.tech = User.objects.create_user('tech', 't@x.com', 'pw')
        # By default an Editor membership = reports_view_financial=False
        cls.admin = User.objects.create_user('admin', 'a@x.com', 'pw',
                                              is_superuser=True, is_staff=True)

    def setUp(self):
        # An MSP technician (User Type Staff) with no global role: their
        # memberships decide the report flags. /reports/ is MSP staff only
        # since v3.17.618, so a plain member is a customer user (403).
        from psa.tests._base import _make_msp_tech
        _make_msp_tech(self.tech)

    def test_customer_owner_cannot_open_reports(self):
        """v3.17.618: an Owner membership grants reports_view_financial, and
        profitability-by-client covers every customer; a customer user with
        that membership opened it."""
        from accounts.models import Membership, Role
        from core.models import Organization
        org = Organization.objects.create(name='Cust Owners', slug='perm-cust-own')
        customer = User.objects.create_user('cust-own', 'co@x.com', 'pw')
        Membership.objects.create(user=customer, organization=org, role=Role.OWNER,
                                  is_active=True)
        self.client.force_login(customer)
        for url in ('/reports/psa/profitability-by-client/', '/reports/wallboard/data/'):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_user_has_perm_returns_false_for_anon(self):
        from accounts.permission_utils import user_has_perm
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(user_has_perm(AnonymousUser(), 'reports_view_financial'))

    def test_user_has_perm_returns_true_for_superuser(self):
        from accounts.permission_utils import user_has_perm
        self.assertTrue(user_has_perm(self.admin, 'reports_view_financial'))
        self.assertTrue(user_has_perm(self.admin, 'reports_view_capacity'))
        self.assertTrue(user_has_perm(self.admin, 'resourcing_manage_cost_rates'))

    def test_user_has_perm_returns_false_for_user_without_membership(self):
        from accounts.permission_utils import user_has_perm
        # Plain user — no memberships, no role_template — gets nothing.
        self.assertFalse(user_has_perm(self.tech, 'reports_view_financial'))
        self.assertFalse(user_has_perm(self.tech, 'reports_view_dashboards'))

    def test_tech_blocked_from_financial_report(self):
        self.client.force_login(self.tech)
        r = self.client.get('/reports/psa/profitability-by-client/')
        self.assertIn(r.status_code, [302, 403])

    def test_superuser_passes(self):
        self.client.force_login(self.admin)
        r = self.client.get('/reports/psa/profitability-by-client/')
        self.assertEqual(r.status_code, 200)

    def test_role_template_grant_unblocks_tech(self):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        org = Organization.objects.create(name='X', slug='perm-x')
        rt = RoleTemplate.objects.create(
            name='AccountingTech',
            reports_view_dashboards=True,
            reports_view_financial=True,
        )
        Membership.objects.create(
            user=self.tech, organization=org,
            role='editor', role_template=rt, is_active=True,
        )
        self.client.force_login(self.tech)
        r = self.client.get('/reports/psa/profitability-by-client/')
        self.assertEqual(r.status_code, 200)

    def test_capacity_report_gated_on_view_capacity(self):
        self.client.force_login(self.tech)
        r = self.client.get('/resourcing/capacity/')
        self.assertIn(r.status_code, [302, 403])

    def test_capacity_report_unblocked_with_role_template(self):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        org = Organization.objects.create(name='Y', slug='perm-y')
        rt = RoleTemplate.objects.create(
            name='ManagerLite',
            reports_view_capacity=True,
        )
        Membership.objects.create(
            user=self.tech, organization=org,
            role='editor', role_template=rt, is_active=True,
        )
        self.client.force_login(self.tech)
        r = self.client.get('/resourcing/capacity/')
        self.assertEqual(r.status_code, 200)

    def test_tech_roster_gated_on_view_team(self):
        self.client.force_login(self.tech)
        r = self.client.get('/resourcing/roster/')
        self.assertIn(r.status_code, [302, 403])

    def test_tech_roster_unblocked_with_role_template(self):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        org = Organization.objects.create(name='Z', slug='perm-z')
        rt = RoleTemplate.objects.create(
            name='OpsLead',
            resourcing_view_team=True,
        )
        Membership.objects.create(
            user=self.tech, organization=org,
            role='editor', role_template=rt, is_active=True,
        )
        self.client.force_login(self.tech)
        r = self.client.get('/resourcing/roster/')
        self.assertEqual(r.status_code, 200)

    def test_sla_trends_gated_on_view_sla(self):
        self.client.force_login(self.tech)
        r = self.client.get('/reports/psa/sla-trends/')
        self.assertIn(r.status_code, [302, 403])

    def test_owner_membership_grants_financial_via_simple_role_fallback(self):
        """Membership with `role=owner` and no role_template still grants
        the new flags via the SimpleNamespace fallback."""
        from accounts.models import Membership, Role
        from core.models import Organization
        org = Organization.objects.create(name='Owners', slug='perm-own')
        Membership.objects.create(
            user=self.tech, organization=org,
            role=Role.OWNER, role_template=None, is_active=True,
        )
        self.client.force_login(self.tech)
        r = self.client.get('/reports/psa/profitability-by-client/')
        self.assertEqual(r.status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuickActionsEditorTests(TestCase):
    """v3.17.230: editable dashboard Quick Actions."""

    def setUp(self):
        from accounts.models import UserProfile
        self.user = User.objects.create_user('qa-user', 'qa@x.com', 'pw')
        UserProfile.objects.get_or_create(user=self.user)

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_get_renders_selected_and_available(self):
        c = Client()
        self._login(c)
        r = c.get('/accounts/profile/quick-actions/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Customize Quick Actions')
        # Default-selected tiles render in the selected column.
        self.assertContains(r, 'New Ticket')
        self.assertContains(r, 'Add Asset')

    def test_post_saves_selected_keys_in_order(self):
        from accounts.models import UserProfile
        c = Client()
        self._login(c)
        r = c.post('/accounts/profile/quick-actions/', {
            'selected': ['add_asset', 'new_password', 'wallboard'],
        })
        self.assertEqual(r.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.quick_actions_config,
                         ['add_asset', 'new_password', 'wallboard'])

    def test_post_filters_unknown_keys(self):
        from accounts.models import UserProfile
        c = Client()
        self._login(c)
        c.post('/accounts/profile/quick-actions/', {
            'selected': ['add_asset', 'totally_made_up', 'wallboard'],
        })
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.quick_actions_config, ['add_asset', 'wallboard'])

    def test_reset_clears_config(self):
        from accounts.models import UserProfile
        profile = UserProfile.objects.get(user=self.user)
        profile.quick_actions_config = ['add_asset']
        profile.save()
        c = Client()
        self._login(c)
        c.post('/accounts/profile/quick-actions/', {'reset': '1'})
        profile.refresh_from_db()
        self.assertEqual(profile.quick_actions_config, [])

    def test_resolve_for_user_uses_default_when_empty(self):
        from core.quick_actions import resolve_for_user, DEFAULT_QUICK_ACTION_KEYS
        ctx = {'psa_enabled': True, 'vehicles_enabled': True}
        actions = resolve_for_user(self.user, ctx)
        keys = [a['key'] for a in actions]
        # Defaults come through (modulo URL-resolution; everything in
        # DEFAULT_QUICK_ACTION_KEYS uses real URL names that resolve in the
        # test environment).
        self.assertGreater(len(keys), 0)
        for k in keys:
            self.assertIn(k, DEFAULT_QUICK_ACTION_KEYS)

    def test_resolve_for_user_respects_saved_order(self):
        from accounts.models import UserProfile
        from core.quick_actions import resolve_for_user
        from django.contrib.auth.models import User as _U
        profile = UserProfile.objects.get(user=self.user)
        profile.quick_actions_config = ['wallboard', 'add_asset']
        profile.save()
        # Re-fetch the user so the cached `.profile` related accessor picks
        # up the updated config rather than the stale one cached at create time.
        fresh = _U.objects.get(pk=self.user.pk)
        ctx = {'psa_enabled': False, 'vehicles_enabled': False}
        actions = resolve_for_user(fresh, ctx)
        keys = [a['key'] for a in actions]
        self.assertEqual(keys, ['wallboard', 'add_asset'])

    def test_resolve_for_user_drops_psa_actions_when_psa_disabled(self):
        from accounts.models import UserProfile
        from core.quick_actions import resolve_for_user
        from django.contrib.auth.models import User as _U
        profile = UserProfile.objects.get(user=self.user)
        profile.quick_actions_config = ['new_ticket', 'add_asset']
        profile.save()
        fresh = _U.objects.get(pk=self.user.pk)
        ctx = {'psa_enabled': False, 'vehicles_enabled': False}
        actions = resolve_for_user(fresh, ctx)
        keys = [a['key'] for a in actions]
        self.assertNotIn('new_ticket', keys)
        self.assertIn('add_asset', keys)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MemberWelcomeEmailTests(TestCase):
    """v3.17.214: send a welcome email when a user is added to an org."""

    def setUp(self):
        from django.core import mail
        from accounts.models import Membership, Role
        from core.models import Organization
        mail.outbox = []
        self.org = Organization.objects.create(name='WelcomeOrg', slug='welcome-org')
        self.owner = User.objects.create_user('owner', 'owner@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        Membership.objects.create(
            user=self.owner, organization=self.org,
            role=Role.OWNER, is_active=True,
        )
        self.invitee = User.objects.create_user('newbie', 'newbie@x.com', 'pw',
                                                 first_name='New')

    def test_send_member_welcome_email_helper(self):
        from django.core import mail
        from accounts.models import Membership, Role
        from accounts.views import send_member_welcome_email
        m = Membership.objects.create(
            user=self.invitee, organization=self.org,
            role=Role.EDITOR, is_active=True,
            invited_by=self.owner,
        )
        sent = send_member_welcome_email(m, request=None)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn('WelcomeOrg', msg.subject)
        self.assertEqual(msg.to, ['newbie@x.com'])
        self.assertIn('WelcomeOrg', msg.body)

    def test_helper_skips_when_user_has_no_email(self):
        from django.core import mail
        from accounts.models import Membership, Role
        from accounts.views import send_member_welcome_email
        u = User.objects.create_user('noemail', '', 'pw')
        m = Membership.objects.create(
            user=u, organization=self.org,
            role=Role.READONLY, is_active=True,
        )
        sent = send_member_welcome_email(m, request=None)
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)

    def test_member_add_view_sends_welcome(self):
        from django.core import mail
        self.client.force_login(self.owner)
        r = self.client.post(
            f'/accounts/organizations/{self.org.id}/members/add/',
            data={'email': 'newbie@x.com', 'role': 'editor'},
        )
        self.assertIn(r.status_code, [200, 302])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('WelcomeOrg', mail.outbox[0].subject)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MemberRoleAssignBoundaryTests(TestCase):
    """member_role_assign only accepts a system-wide RoleTemplate or one
    owned by the current customer — never another customer's custom role."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role, RoleTemplate
        from core.models import Organization
        cls.org_a = Organization.objects.create(name='RoleCustA', slug='role-cust-a')
        cls.org_b = Organization.objects.create(name='RoleCustB', slug='role-cust-b')
        cls.owner = User.objects.create_user('role-owner', 'ro@x.com', 'pw')
        Membership.objects.create(
            user=cls.owner, organization=cls.org_a, role=Role.OWNER, is_active=True,
        )
        cls.member = User.objects.create_user('role-member', 'rm@x.com', 'pw')
        cls.member_ms = Membership.objects.create(
            user=cls.member, organization=cls.org_a, role=Role.READONLY, is_active=True,
        )
        cls.system_tpl = RoleTemplate.objects.create(
            name='Sys Role', organization=None, is_system_template=True,
        )
        cls.own_tpl = RoleTemplate.objects.create(
            name='Cust A Role', organization=cls.org_a,
        )
        cls.foreign_tpl = RoleTemplate.objects.create(
            name='Cust B Role', organization=cls.org_b,
        )

    def setUp(self):
        self.client.force_login(self.owner)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org_a.id
        s.save()

    def _assign(self, tpl):
        return self.client.post(
            f'/accounts/members/{self.member.id}/assign-role/',
            {'role_template_id': tpl.id},
        )

    def test_other_customers_role_template_rejected(self):
        r = self._assign(self.foreign_tpl)
        self.assertEqual(r.status_code, 404)
        self.member_ms.refresh_from_db()
        self.assertIsNone(self.member_ms.role_template_id)

    def test_system_role_template_accepted(self):
        r = self._assign(self.system_tpl)
        self.assertEqual(r.status_code, 302)
        self.member_ms.refresh_from_db()
        self.assertEqual(self.member_ms.role_template_id, self.system_tpl.id)

    def test_own_customer_role_template_accepted(self):
        r = self._assign(self.own_tpl)
        self.assertEqual(r.status_code, 302)
        self.member_ms.refresh_from_db()
        self.assertEqual(self.member_ms.role_template_id, self.own_tpl.id)
