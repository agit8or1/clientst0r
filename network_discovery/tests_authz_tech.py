"""Roles & permissions program (authz-tech): network discovery pages take
the customer from the URL, so the user must hold assets_view in that
customer, and token / collector actions need network_discovery_generate in
that customer (not on any membership)."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from locations.models import Location
from network_discovery.models import NetworkDiscoveryToken

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DiscoveryCustomerScopeTests(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='ND A', slug='authz-nd-a')
        self.b = Organization.objects.create(name='ND B', slug='authz-nd-b')
        self.loc_b = Location.objects.create(organization=self.b, name='B office')
        gen = RoleTemplate.objects.create(name='authz nd gen', assets_view=True,
                                          network_discovery_generate=True)
        self.user = User.objects.create_user('authz-nd-user', password='pw')
        Membership.objects.create(user=self.user, organization=self.a, role=Role.ADMIN, role_template=gen)
        self.c = Client()
        self.c.force_login(self.user)
        s = self.c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.a.id
        s.save()

    def _url(self, suffix=''):
        return f'/network-discovery/orgs/{self.b.pk}/locations/{self.loc_b.pk}/{suffix}'

    def test_other_customers_pages_are_404(self):
        for suffix in ('', 'topology/', 'port-map/', 'collectors/'):
            with self.subTest(suffix):
                self.assertEqual(self.c.get(self._url(suffix)).status_code, 404)

    def test_flag_at_one_customer_does_not_issue_tokens_for_another(self):
        self.c.post(self._url('generate/'))
        self.assertFalse(NetworkDiscoveryToken.objects.filter(organization=self.b).exists())

    def test_member_of_b_without_generate_cannot_issue(self):
        Membership.objects.create(user=self.user, organization=self.b, role=Role.READONLY)
        self.assertEqual(self.c.get(self._url()).status_code, 200)
        self.c.post(self._url('generate/'))
        self.assertFalse(NetworkDiscoveryToken.objects.filter(organization=self.b).exists())
