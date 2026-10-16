"""
v3.17.611 — 2FA secrets at rest (accounts/otp_storage.py).

TOTP seeds are encrypted in otp_totp_totpdevice.key and backup codes are
hashed in otp_static_statictoken.token, without changing how django-otp,
django-two-factor-auth, our profile enrolment or the mobile MFA step use
them.
"""
import base64
import importlib
from types import SimpleNamespace
import re
import time

import pyotp
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from vault import secret_fields as sf

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

migration = importlib.import_module('accounts.migrations.0036_encrypt_otp_secrets')


def _raw(table, col, pk):
    with connection.cursor() as cur:
        cur.execute(f'SELECT {col} FROM {table} WHERE id = %s', [pk])
        return cur.fetchone()[0]


def _set_raw(table, col, pk, value):
    with connection.cursor() as cur:
        cur.execute(f'UPDATE {table} SET {col} = %s WHERE id = %s', [value, pk])


def _run_migration():
    from django.apps import apps
    migration.forward(apps, SimpleNamespace(connection=connection))


def _code(device):
    return str(totp(device.bin_key, device.step, device.t0, device.digits)).zfill(device.digits)


class TOTPKeyStorageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('otp-store', password='pw')

    def test_fields_are_wrapped(self):
        self.assertIsInstance(TOTPDevice._meta.get_field('key'), sf.EncryptedHexKeyField)
        self.assertIsInstance(StaticToken._meta.get_field('token'), sf.HashedStaticTokenField)

    def test_key_encrypted_in_column_and_fits(self):
        device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)
        hex_key = TOTPDevice.objects.get(pk=device.pk).key
        raw = _raw('otp_totp_totpdevice', 'key', device.pk)
        self.assertTrue(raw.startswith('enc2h$'))
        self.assertNotIn(hex_key, raw)
        self.assertLessEqual(len(raw), 80)
        self.assertEqual(len(hex_key), 40)

    def test_verify_token_with_encrypted_key(self):
        device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)
        device = TOTPDevice.objects.get(pk=device.pk)
        self.assertTrue(device.verify_token(_code(device)))
        # Saving (verify updates last_t/drift) re-encrypts, never writes plaintext.
        self.assertTrue(_raw('otp_totp_totpdevice', 'key', device.pk).startswith('enc2h$'))

    def test_config_url_uses_real_seed(self):
        device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)
        device = TOTPDevice.objects.get(pk=device.pk)
        b32 = base64.b32encode(bytes.fromhex(device.key)).decode()
        self.assertIn(b32, device.config_url)

    def test_existing_plaintext_key_migrated_and_still_verifies(self):
        device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)
        hex_key = TOTPDevice.objects.get(pk=device.pk).key
        _set_raw('otp_totp_totpdevice', 'key', device.pk, hex_key)  # pre-0036 state
        # Readable before the migration (legacy fallback)
        self.assertEqual(TOTPDevice.objects.get(pk=device.pk).key, hex_key)
        _run_migration()
        raw = _raw('otp_totp_totpdevice', 'key', device.pk)
        self.assertTrue(raw.startswith('enc2h$'))
        device = TOTPDevice.objects.get(pk=device.pk)
        self.assertEqual(device.key, hex_key)
        self.assertTrue(device.verify_token(_code(device)))

    def test_mobile_mfa_verification(self):
        from api_mobile.auth_utils import verify_totp_code
        device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)
        device = TOTPDevice.objects.get(pk=device.pk)
        self.assertTrue(verify_totp_code(self.user, _code(device)))

    def test_rotation_reencrypts_seed(self):
        from django.core.management import call_command
        device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)
        before = _raw('otp_totp_totpdevice', 'key', device.pk)
        hex_key = TOTPDevice.objects.get(pk=device.pk).key
        call_command('rotate_encryption_key', stdout=open('/dev/null', 'w'))
        after = _raw('otp_totp_totpdevice', 'key', device.pk)
        self.assertNotEqual(before, after)
        self.assertEqual(TOTPDevice.objects.get(pk=device.pk).key, hex_key)


class StaticTokenStorageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('backup-store', password='pw')
        self.device = StaticDevice.objects.create(user=self.user, name='backup')

    def test_code_stored_hashed_and_verifies_once(self):
        tok = self.device.token_set.create(token='abcd2345')
        raw = _raw('otp_static_statictoken', 'token', tok.pk)
        self.assertNotEqual(raw, 'abcd2345')
        self.assertTrue(sf.is_hashed_static_token(raw))
        self.assertTrue(self.device.verify_token('abcd2345'))
        self.assertFalse(self.device.verify_token('abcd2345'))  # consumed
        self.assertFalse(self.device.verify_token('wrongone'))

    def test_existing_plaintext_code_migrated_and_still_verifies(self):
        tok = self.device.token_set.create(token='zzzz7777')
        _set_raw('otp_static_statictoken', 'token', tok.pk, 'zzzz7777')  # pre-0036
        _run_migration()
        self.assertTrue(sf.is_hashed_static_token(_raw('otp_static_statictoken', 'token', tok.pk)))
        self.assertTrue(self.device.verify_token('zzzz7777'))

    def test_check_secrets_storage_flags_plaintext(self):
        from io import StringIO
        from django.core.management import call_command
        tok = self.device.token_set.create(token='qqqq2222')
        _set_raw('otp_static_statictoken', 'token', tok.pk, 'qqqq2222')
        out = StringIO()
        with self.assertRaises(SystemExit):
            call_command('check_secrets_storage', stdout=out)
        self.assertIn('otp_static.StaticToken.token', out.getvalue())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TwoFactorFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('flow-user', password='pw-flow-123')

    def _login_wizard(self, c):
        return c.post('/account/login/', {
            'login_view-current_step': 'auth',
            'auth-username': 'flow-user', 'auth-password': 'pw-flow-123',
        })

    def test_login_with_totp(self):
        device = TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)
        device = TOTPDevice.objects.get(pk=device.pk)
        c = Client()
        self._login_wizard(c)
        resp = c.post('/account/login/', {
            'login_view-current_step': 'token', 'token-otp_token': _code(device),
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, 'content', b'')[:500])
        self.assertIn('_auth_user_id', c.session)

    def test_login_with_backup_code(self):
        TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)
        backup = StaticDevice.objects.create(user=self.user, name='backup')
        backup.token_set.create(token='bkup2345')
        c = Client()
        self._login_wizard(c)
        resp = c.post('/account/login/', {
            'login_view-current_step': 'backup', 'backup-otp_token': 'bkup2345',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', c.session)
        self.assertEqual(backup.token_set.count(), 0)

    def test_two_factor_setup_wizard_and_qr(self):
        c = Client()
        c.force_login(self.user)
        c.post('/account/two_factor/setup/', {'setup_view-current_step': 'welcome'})
        resp = c.post('/account/two_factor/setup/', {
            'setup_view-current_step': 'method', 'method-method': 'generator'})
        self.assertEqual(resp.status_code, 200)
        b32 = c.session['django_two_factor-qr_secret_key']
        qr = c.get('/account/two_factor/qrcode/')
        self.assertEqual(qr.status_code, 200)
        resp = c.post('/account/two_factor/setup/', {
            'setup_view-current_step': 'generator',
            'generator-token': pyotp.TOTP(b32).now(),
        })
        self.assertEqual(resp.status_code, 302, resp.content[:500] if hasattr(resp, 'content') else '')
        device = TOTPDevice.objects.get(user=self.user)
        self.assertTrue(_raw('otp_totp_totpdevice', 'key', device.pk).startswith('enc2h$'))
        self.assertEqual(base64.b32encode(device.bin_key).decode(), b32)

    def test_backup_tokens_shown_once(self):
        device = TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)
        c = Client()
        c.force_login(self.user)
        from django_otp import DEVICE_ID_SESSION_KEY
        s = c.session
        s[DEVICE_ID_SESSION_KEY] = device.persistent_id
        s.save()
        resp = c.post('/account/two_factor/backup/tokens/')
        self.assertEqual(resp.status_code, 200)
        codes = resp.context['fresh_tokens']
        self.assertEqual(len(codes), 10)
        for code in codes:
            self.assertContains(resp, code)
        stored = list(StaticToken.objects.values_list('token', flat=True))
        for code in codes:
            self.assertNotIn(code, stored)
        # A later visit cannot show them.
        later = c.get('/account/two_factor/backup/tokens/')
        for code in codes:
            self.assertNotContains(later, code)
        self.assertContains(later, '10 unused backup tokens')
        # And they work.
        backup = StaticDevice.objects.get(user=self.user, name='backup')
        self.assertTrue(backup.verify_token(codes[0]))

    def test_profile_enrolment(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post('/accounts/profile/2fa/', {'action': 'enable'})
        self.assertEqual(resp.status_code, 200)
        secret = resp.context['secret']
        self.assertNotIn(secret, c.session['totp_secret'])  # sealed in the session
        resp = c.post('/accounts/profile/2fa/', {'action': 'verify',
                                                 'code': pyotp.TOTP(secret).now()})
        self.assertEqual(resp.status_code, 302)
        device = TOTPDevice.objects.get(user=self.user, name='default')
        raw = _raw('otp_totp_totpdevice', 'key', device.pk)
        self.assertTrue(raw.startswith('enc2h$'))
        self.assertEqual(device.key, base64.b32decode(secret).hex())
