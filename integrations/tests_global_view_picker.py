"""
Integrations page in global view (no organization selected).

The RMM, UniFi, Microsoft 365, Omada and Grandstream connections belong to an
organization, so their Add pages send a user without one back to the list.
The list explains that and offers an organization picker that returns to it.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalViewPickerTests(TestCase):

    def setUp(self):
        self.a = Organization.objects.create(name='Acme Picker', slug='acme-picker')
        self.b = Organization.objects.create(name='Bolt Picker', slug='bolt-picker')
        self.root = User.objects.create_superuser('picker_root', 'r@x.test', 'pw')
        self.c = Client()
        self.c.force_login(self.root)

    def _global(self):
        s = self.c.session
        s['global_view_mode'] = True
        s.pop('current_organization_id', None)
        s.save()

    def test_global_view_shows_picker(self):
        self._global()
        body = self.c.get('/integrations/').content.decode()
        self.assertIn('You are in global view', body)
        self.assertIn('/accounts/switch/%d/?next=/integrations/' % self.a.id, body)
        self.assertIn('Bolt Picker', body)

    def test_selected_org_hides_picker(self):
        s = self.c.session
        s['current_organization_id'] = self.a.id
        s.save()
        body = self.c.get('/integrations/').content.decode()
        self.assertNotIn('You are in global view', body)

    def test_member_sees_only_own_orgs(self):
        u = User.objects.create_user('picker_member', 'm@x.test', 'pw')
        Membership.objects.create(user=u, organization=self.a, role=Role.OWNER, is_active=True)
        c = Client()
        c.force_login(u)
        # A member always gets an organization picked by the middleware.
        body = c.get('/integrations/').content.decode()
        self.assertNotIn('Bolt Picker', body)

    def test_switch_follows_safe_next(self):
        r = self.c.get('/accounts/switch/%d/?next=/integrations/' % self.a.id)
        self.assertRedirects(r, '/integrations/', fetch_redirect_response=False)
        self.assertEqual(self.c.session['current_organization_id'], self.a.id)

    def test_switch_ignores_offsite_next(self):
        for bad in ('https://evil.test/', '//evil.test/', 'javascript:alert(1)'):
            r = self.c.get('/accounts/switch/%d/' % self.a.id, {'next': bad})
            self.assertNotIn('evil', r['Location'])
            self.assertFalse(r['Location'].startswith('javascript'))
