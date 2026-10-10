"""
v3.17.593 — browser-extension reveal/TOTP go through the shared reveal gate
(per-entry permission, approval requirement, VaultAccessRule).
"""
from unittest.mock import patch

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from vault.models import Password, VaultAccessRule, WebExtensionAuthToken


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionRevealGateTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='ExtGateCo', slug='ext-gate-co')
        self.user = User.objects.create_user('ext-gate', password='pw')
        Membership.objects.create(user=self.user, organization=self.org,
                                  role=Role.OWNER, is_active=True)
        self.password = Password.objects.create(organization=self.org, title='Router')
        self.password.set_password('s3cret-value')
        self.password.save()
        self.secret, _ = WebExtensionAuthToken.issue(user=self.user, organization=self.org)

    def _reveal(self):
        return Client().post(f'/vault/api/extension/{self.password.pk}/reveal/',
                             HTTP_AUTHORIZATION=f'Bearer {self.secret}')

    def test_reveal_allowed_without_rules(self):
        resp = self._reveal()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['password'], 's3cret-value')

    @patch('vault.access_rules._country_for_ip', return_value='CN')
    def test_access_rule_deny_blocks_reveal_and_totp(self, _cc):
        VaultAccessRule.objects.create(organization=self.org, name='No CN', scope='organization',
                                       effect='deny', blocked_countries=['CN'])
        self.assertEqual(self._reveal().status_code, 403)
        resp = Client().get(f'/vault/api/extension/{self.password.pk}/totp/',
                            HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        self.assertEqual(resp.status_code, 403)

    def test_policy_outage_fails_closed(self):
        with patch('vault.access_rules.evaluate', side_effect=RuntimeError('db down')):
            self.assertEqual(self._reveal().status_code, 503)
