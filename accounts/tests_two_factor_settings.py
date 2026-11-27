"""
My Profile → 2FA Settings: turning two-factor off needs the current password
or a valid code and is audit-logged (and refused when the install requires
2FA); turning it on hands out recovery codes once; the page links to them.
"""
import base64

import pyotp
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from audit.models import AuditLog

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
PASSWORD = 'pw-2fa-settings-123'


def _set_require_2fa(value):
    from core import security_policy
    from core.models import SystemSetting
    s = SystemSetting.get_settings()
    s.require_2fa = value
    s.save()
    security_policy.invalidate()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REQUIRE_2FA=None)
class TwoFactorSettingsTests(TestCase):

    def setUp(self):
        _set_require_2fa(False)
        self.user = User.objects.create_user('tfa-user', 'tfa@msp.test', PASSWORD, is_staff=True)
        self.c = Client()
        self.c.force_login(self.user)
        self.url = reverse('accounts:two_factor_setup')

    def _enrol(self):
        """A confirmed authenticator plus one recovery code; session verified."""
        device = TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)
        static = StaticDevice.objects.create(user=self.user, name='backup', confirmed=True)
        static.token_set.create(token='rcvy2345')
        self.user.profile.two_factor_enabled = True
        self.user.profile.save()
        s = self.c.session
        s[DEVICE_ID_SESSION_KEY] = device.persistent_id
        s.save()
        return device

    def _events(self, event):
        return AuditLog.objects.filter(user=self.user, extra_data__event=event)

    # -- disabling ---------------------------------------------------------

    def test_disable_without_confirmation_is_refused(self):
        self._enrol()
        r = self.c.post(self.url, {'action': 'disable'})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertTrue(self._events('two_factor_disable_refused').filter(success=False).exists())

    def test_disable_with_wrong_password_or_code_is_refused(self):
        self._enrol()
        self.c.post(self.url, {'action': 'disable', 'confirm_password': 'wrong', 'confirm_code': '000000'})
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())

    def test_disable_with_password_removes_every_device(self):
        self._enrol()
        r = self.c.post(self.url, {'action': 'disable', 'confirm_password': PASSWORD})
        self.assertRedirects(r, reverse('accounts:profile'), fetch_redirect_response=False)
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertFalse(StaticDevice.objects.filter(user=self.user).exists())
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.two_factor_enabled)
        self.assertTrue(self._events('two_factor_disabled').exists())

    def test_disable_with_authenticator_code(self):
        device = self._enrol()
        code = pyotp.TOTP(base64.b32encode(device.bin_key).decode()).now()
        self.c.post(self.url, {'action': 'disable', 'confirm_code': code})
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())

    def test_disable_with_recovery_code(self):
        self._enrol()
        self.c.post(self.url, {'action': 'disable', 'confirm_code': 'rcvy2345'})
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())

    def test_disable_get_does_nothing(self):
        self._enrol()
        self.c.get(self.url + '?action=disable')
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())

    def test_disable_refused_when_install_requires_2fa(self):
        self._enrol()
        _set_require_2fa(True)
        page = self.c.get(self.url)
        self.assertContains(page, 'id="two-factor-required-note"')
        self.assertNotContains(page, 'value="disable"')
        self.c.post(self.url, {'action': 'disable', 'confirm_password': PASSWORD})
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertTrue(self._events('two_factor_disable_refused').exists())

    def test_disable_form_asks_for_password_or_code(self):
        self._enrol()
        page = self.c.get(self.url)
        self.assertContains(page, 'name="confirm_password"')
        self.assertContains(page, 'name="confirm_code"')

    def test_library_disable_page_redirects_here(self):
        self._enrol()
        r = self.c.get('/account/two_factor/disable/')
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        r = self.c.post('/account/two_factor/disable/', {'understand': 'on'})
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())

    # -- recovery codes ----------------------------------------------------

    def test_settings_page_links_recovery_codes(self):
        self._enrol()
        page = self.c.get(self.url)
        self.assertContains(page, 'id="recovery-codes-link"')
        self.assertContains(page, reverse('two_factor:backup_tokens'))
        self.assertContains(page, 'You have 1 unused code.')

    def test_enabling_shows_recovery_codes_once(self):
        r = self.c.post(self.url, {'action': 'enable'})
        secret = r.context['secret']
        r = self.c.post(self.url, {'action': 'verify', 'code': pyotp.TOTP(secret).now()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Cache-Control'], 'no-store, private')
        codes = r.context['fresh_tokens']
        self.assertEqual(len(codes), 10)
        for code in codes:
            self.assertContains(r, code)
        self.assertEqual(StaticToken.objects.filter(device__user=self.user).count(), 10)
        # The session that proved the code counts as verified.
        self.assertIn(DEVICE_ID_SESSION_KEY, self.c.session)
        self.assertTrue(self._events('two_factor_enabled').exists())
        # A later visit only reports how many are left.
        page = self.c.get(reverse('two_factor:backup_tokens'))
        self.assertNotContains(page, codes[0])

    def test_wizard_setup_complete_offers_recovery_codes(self):
        self._enrol()
        page = self.c.get(reverse('two_factor:setup_complete'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Get recovery codes')
        self.assertContains(page, f'action="{reverse("two_factor:backup_tokens")}"')
