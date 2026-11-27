"""Administration → Integrations → Integrations follows the page's own rule.

integrations.views.integration_list admits, in global view, superusers,
Django staff and MSP technicians whose global role grants
integrations_configure (or _sync / _view), as long as the /integrations/
section rule (integrations_view) lets them in. The tab used to be drawn for
superusers only, so a technician who manages connections had no way there.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from accounts.models import RoleTemplate, UserType
from core import navigation
from core.tests.test_navbar_grouping import TEST_MIDDLEWARE, NavbarTestBase

User = get_user_model()


def _section():
    return next(s for s in navigation.SECTIONS if s.key == 'settings_integrations')


def _tab_keys(user, org=None):
    ctx = {'user': user, 'current_organization': org}
    return {t['key'] for t in navigation.resolve_tabs(_section(), ctx)}


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class IntegrationsTabGateTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        cache.clear()

    def tech(self, username, **flags):
        u = User.objects.create_user(username, f'{username}@x.com', 'pw')
        u.profile.user_type = UserType.STAFF
        if flags:
            u.profile.global_role_template = RoleTemplate.objects.create(name=f'{username} role', **flags)
        u.profile.save()
        return u

    def opens(self, user):
        """Does the Integrations page open for `user` in global view?"""
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.pop('current_organization_id', None)
        s.save()
        return self.client.get(reverse('integrations:integration_list')).status_code == 200

    def test_configure_holder_sees_the_tab(self):
        tech = self.tech('int_cfg', integrations_view=True, integrations_configure=True)
        self.assertIn('integrations:integration_list', _tab_keys(tech))

    def test_technician_without_integration_role_does_not(self):
        self.assertNotIn('integrations:integration_list', _tab_keys(self.tech('int_none')))

    def test_superuser_sees_the_tab(self):
        self.assertIn('integrations:integration_list', _tab_keys(self.make_superuser()))

    def test_global_view_tab_follows_the_platform_rule(self):
        """In global view the tab is drawn for platform viewers, and every
        drawn tab opens. A technician with no global role gets a page with
        no platform connections on it, so the tab is not drawn for them."""
        users = {
            'superuser': (self.make_superuser(), True),
            'configure': (self.tech('int_c', integrations_view=True, integrations_configure=True), True),
            'sync': (self.tech('int_s', integrations_view=True, integrations_sync=True), True),
            'view': (self.tech('int_v', integrations_view=True), True),
            # Configure without view: the /integrations/ section rule refuses.
            'configure_no_view': (self.tech('int_cnv', integrations_configure=True), False),
            'no_role': (self.tech('int_n'), False),
        }
        for name, (user, expected) in users.items():
            with self.subTest(user=name):
                cache.clear()
                shown = 'integrations:integration_list' in _tab_keys(user)
                self.assertEqual(shown, expected, name)
                if shown:
                    self.assertTrue(self.opens(user), name)
        self.assertFalse(self.opens(users['configure_no_view'][0]))

    def test_inside_a_customer_tab_follows_integrations_view_there(self):
        allowed = self.tech('int_cust_ok', integrations_view=True, integrations_configure=True)
        refused = self.tech('int_cust_no', integrations_configure=True)
        self.assertIn('integrations:integration_list', _tab_keys(allowed, self.org))
        self.assertNotIn('integrations:integration_list', _tab_keys(refused, self.org))

    def test_customer_users_are_not_offered_the_tab(self):
        owner = self.make_customer('owner', 'int_owner')
        self.assertNotIn('integrations:integration_list', _tab_keys(owner, self.org))
