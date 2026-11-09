"""v3.17.652: extension reveals are audited and limited like web reveals,
the offline cache leaves out approval-gated entries, and the save-time
breach check sends only a hash prefix."""
import hashlib
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from vault.breach_checker import PasswordBreachChecker
from vault.models import Password, WebExtensionAuthToken
from vault.tests_extension_gate import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionRevealAuditTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='Example Realty', slug='ex-realty')
        self.user = User.objects.create_user('ext-652', password='pw')
        Membership.objects.create(user=self.user, organization=self.org, role=Role.OWNER, is_active=True)
        self.password = Password.objects.create(organization=self.org, title='Office Wi-Fi')
        self.password.set_password('synthetic-wifi-pass')
        self.password.save()
        self.secret, _ = WebExtensionAuthToken.issue(user=self.user, organization=self.org)

    def _reveal(self):
        return Client().post(f'/vault/api/extension/{self.password.pk}/reveal/',
                             HTTP_AUTHORIZATION=f'Bearer {self.secret}')

    def test_extension_reveal_is_audited_as_a_reveal(self):
        self.assertEqual(self._reveal().status_code, 200)
        row = AuditLog.objects.get(action='reveal', object_type='password', object_id=self.password.pk)
        self.assertEqual(row.organization, self.org)
        self.assertEqual(row.extra_data['event'], 'vault_extension_reveal')

    def test_extension_reveal_shares_the_30_per_hour_limit(self):
        codes = [self._reveal().status_code for _ in range(31)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30], 403)
        self.assertEqual(AuditLog.objects.filter(action='reveal', object_id=self.password.pk).count(), 30)

    def test_offline_cache_leaves_out_approval_gated_entries(self):
        gated = Password.objects.create(organization=self.org, title='Domain admin', requires_reveal_approval=True)
        with patch('vault.extension_views._has_extension_permission', return_value=True):
            resp = Client().get('/vault/api/extension/sync/', HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in resp.json()['passwords']}
        self.assertIn(self.password.pk, ids)
        self.assertNotIn(gated.pk, ids)


class BreachCheckTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_only_the_hash_prefix_is_sent(self):
        secret = 'synthetic-breached-pass'
        sha1 = hashlib.sha1(secret.encode(), usedforsecurity=False).hexdigest().upper()
        reply = MagicMock(text=f'{sha1[5:]}:42\r\n0000000000000000000000000000000000A:1')
        with patch('vault.breach_checker.requests.get', return_value=reply) as get:
            self.assertEqual(PasswordBreachChecker().check_password(secret), (True, 42))
        url = get.call_args.args[0]
        self.assertTrue(url.endswith(sha1[:5]))
        self.assertNotIn(sha1[5:], url)
        self.assertNotIn(secret, str(get.call_args))

    def test_saving_a_vault_entry_records_a_breach_check(self):
        from vault.forms import PasswordForm
        from vault.models import PasswordBreachCheck
        org = Organization.objects.create(name='Example Bakery', slug='ex-bakery')
        with patch('vault.forms.PasswordBreachChecker.check_password', return_value=(True, 7)):
            form = PasswordForm(data={'title': 'POS login 2', 'password_type': 'website',
                                      'plaintext_password': 'synthetic-pos-pass', 'hibp_scan_frequency': '24', 'client_access_mode': 'none'},
                                organization=org)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIn('7', form.breach_warning)
            form.instance.organization = org
            saved = form.save()
        check = PasswordBreachCheck.objects.get(password=saved)
        self.assertTrue(check.is_breached)
        self.assertEqual(check.breach_count, 7)
