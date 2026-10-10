"""
v3.17.593 — a user with a 2FA device must have passed OTP in the current
session. Password-only logins (the stock /admin/login/ form) used to get a
full session because Enforce2FAMiddleware only checked that a device existed.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

# Keep Enforce2FAMiddleware — it is what's under test.
MIDDLEWARE_WITH_2FA = [m for m in django_settings.MIDDLEWARE if 'AxesMiddleware' not in m]


@override_settings(MIDDLEWARE=MIDDLEWARE_WITH_2FA, SECURE_SSL_REDIRECT=False, REQUIRE_2FA=True)
class UnverifiedSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('otp-user', password='pw', is_staff=True)
        self.device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)

    def test_password_only_session_is_ended(self):
        c = Client()
        c.force_login(self.user)  # what /admin/login/ produces: no OTP step
        resp = c.get('/core/secure-notes/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/account/login/'))
        self.assertNotIn('_auth_user_id', c.session)

    def test_device_management_blocked_until_verified(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get('/account/two_factor/disable/')
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('_auth_user_id', c.session)

    def test_verified_session_allowed(self):
        c = Client()
        c.force_login(self.user)
        s = c.session
        s[DEVICE_ID_SESSION_KEY] = self.device.persistent_id
        s.save()
        c.get('/core/secure-notes/')
        self.assertIn('_auth_user_id', c.session)
