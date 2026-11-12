"""Roles & permissions program (authz-tech): API keys follow their owner's
*current* authority.

A key stops working when the owner loses `api_access` in the key's customer
(role change or demotion), when the customer is deactivated, and (already
before) when the owner is deactivated or loses the membership. Keys can only
be made by users whose role grants API access, never above the creator's own
role, and the toggle endpoint no longer changes state on GET.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from api.models import APIKey
from api.tests_view_permissions import TEST_MIDDLEWARE
from core.models import Organization


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class APIKeyCurrentAuthorityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Key org', slug='authz-key-org')
        self.user = User.objects.create_user('authz-key-owner', password='pw')
        self.m = Membership.objects.create(user=self.user, organization=self.org, role=Role.OWNER)
        _, raw = APIKey.create_key(organization=self.org, user=self.user, name='k', role=Role.OWNER)
        self.api = Client(HTTP_AUTHORIZATION=f'Bearer {raw}')

    def test_key_works_then_stops_when_role_loses_api_access(self):
        self.assertEqual(self.api.get('/api/assets/').status_code, 200)
        no_api = RoleTemplate.objects.create(name='authz no api', assets_view=True, api_access=False)
        self.m.role_template = no_api
        self.m.save()
        self.assertEqual(self.api.get('/api/assets/').status_code, 401)

    def test_demotion_to_readonly_ends_key(self):
        # Read-Only does not include API access.
        self.m.role = Role.READONLY
        self.m.save()
        self.assertEqual(self.api.get('/api/assets/').status_code, 401)

    def test_key_of_deactivated_customer_stops(self):
        self.org.is_active = False
        self.org.save()
        self.assertEqual(self.api.get('/api/assets/').status_code, 401)

    def test_deactivated_owner_key_stops(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.api.get('/api/assets/').status_code, 401)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class APIKeyCreationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Key create', slug='authz-key-create')
        self.c = Client()

    def _member(self, name, role):
        u = User.objects.create_user(name, password='pw')
        Membership.objects.create(user=u, organization=self.org, role=role)
        _login(self.c, u, self.org)
        return u

    def test_readonly_member_cannot_create_key(self):
        u = self._member('authz-key-ro', Role.READONLY)
        self.c.post(reverse('api:apikey_create'), {'name': 'mine', 'role': Role.READONLY})
        self.assertFalse(APIKey.objects.filter(user=u).exists())

    def test_editor_cannot_create_owner_level_key(self):
        u = self._member('authz-key-ed', Role.EDITOR)
        self.c.post(reverse('api:apikey_create'), {'name': 'big', 'role': Role.OWNER})
        self.assertFalse(APIKey.objects.filter(user=u).exists())
        resp = self.c.post(reverse('api:apikey_create'), {'name': 'ok', 'role': Role.EDITOR})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(APIKey.objects.filter(user=u, role=Role.EDITOR).exists())

    def test_toggle_requires_post(self):
        u = self._member('authz-key-tg', Role.OWNER)
        key, _ = APIKey.create_key(organization=self.org, user=u, name='t', role=Role.READONLY)
        resp = self.c.get(reverse('api:apikey_toggle', args=[key.pk]))
        self.assertEqual(resp.status_code, 405)
        key.refresh_from_db()
        self.assertTrue(key.is_active)
