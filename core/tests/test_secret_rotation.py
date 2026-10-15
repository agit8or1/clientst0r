"""
manage.py rotate_encryption_key and manage.py check_secrets_storage.
"""
import base64
import os
import tempfile
from io import StringIO

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from core.models import Organization, SystemSetting
from vault import secret_fields as sf


def _key():
    return base64.b64encode(os.urandom(32)).decode()


def raw(model, field, pk):
    qn = connection.ops.quote_name
    col = model._meta.get_field(field).column
    with connection.cursor() as cur:
        cur.execute(f'SELECT {qn(col)} FROM {qn(model._meta.db_table)} '
                    f'WHERE {qn(model._meta.pk.column)} = %s', [pk])
        return cur.fetchone()[0]


class RotateEncryptionKeyTests(TestCase):
    def setUp(self):
        self.old = _key()
        self.new = _key()
        self._ov = override_settings(APP_MASTER_KEY=self.old, APP_MASTER_KEY_PREVIOUS='')
        self._ov.enable()
        self.addCleanup(self._ov.disable)

        from integrations.models import PSAConnection
        from vault.models import Password, PersonalVault
        self.org = Organization.objects.create(name='Rot Org', slug='rot-org')
        self.user = User.objects.create_user('rot', 'r@x.com', 'pw')
        s = SystemSetting.get_settings()
        s.snyk_api_token = 'snyk-rot'
        s.smtp_password = 'smtp-rot'
        s.save()
        self.pw = Password(organization=self.org, title='p', password_type='website',
                           license_key='LIC-ROT')
        self.pw.set_password('vault-rot')
        self.pw.set_otp_secret('JBSWY3DPEHPK3PXP')
        self.pw.save()
        self.pv = PersonalVault(user=self.user, title='n')
        self.pv.set_content('personal-rot')
        self.pv.save()
        self.conn = PSAConnection(organization=self.org, provider_type='itflow', name='it',
                                  base_url='https://it.example')
        self.conn.set_credentials({'api_key': 'psa-rot'})
        self.conn.save()

    def _key_file(self, key):
        fh = tempfile.NamedTemporaryFile('w', delete=False, suffix='.key')
        fh.write(key)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def _assert_readable(self):
        from integrations.models import PSAConnection
        from vault.models import Password, PersonalVault
        s = SystemSetting.get_settings()
        self.assertEqual((s.snyk_api_token, s.smtp_password), ('snyk-rot', 'smtp-rot'))
        pw = Password.objects.get(pk=self.pw.pk)
        self.assertEqual(pw.get_password(), 'vault-rot')
        self.assertEqual(pw.get_otp_secret(), 'JBSWY3DPEHPK3PXP')
        self.assertEqual(pw.license_key, 'LIC-ROT')
        self.assertEqual(PersonalVault.objects.get(pk=self.pv.pk).get_content(), 'personal-rot')
        self.assertEqual(PSAConnection.objects.get(pk=self.conn.pk).get_credentials(),
                         {'api_key': 'psa-rot'})

    def test_rotate_to_new_key_file(self):
        before = raw(SystemSetting, 'snyk_api_token', 1)
        out = StringIO()
        call_command('rotate_encryption_key', new_key_file=self._key_file(self.new), stdout=out)
        self.assertIn('verified', out.getvalue())
        self.assertNotIn(self.new, out.getvalue())
        self.assertNotEqual(raw(SystemSetting, 'snyk_api_token', 1), before)
        with override_settings(APP_MASTER_KEY=self.new):
            self._assert_readable()
        # The old key alone no longer opens the rotated data.
        with self.assertRaises(sf.SecretFieldError):
            sf.unseal(raw(SystemSetting, 'snyk_api_token', 1), 'core.SystemSetting.snyk_api_token')

    def test_zero_downtime_rotation_with_previous_key(self):
        with override_settings(APP_MASTER_KEY=self.new, APP_MASTER_KEY_PREVIOUS=self.old):
            self._assert_readable()  # app keeps working mid-rotation
            call_command('rotate_encryption_key', stdout=StringIO())
        with override_settings(APP_MASTER_KEY=self.new, APP_MASTER_KEY_PREVIOUS=''):
            self._assert_readable()

    def test_dry_run_changes_nothing(self):
        before = raw(SystemSetting, 'snyk_api_token', 1)
        out = StringIO()
        call_command('rotate_encryption_key', new_key_file=self._key_file(self.new),
                     dry_run=True, stdout=out)
        self.assertIn('Dry run', out.getvalue())
        self.assertEqual(raw(SystemSetting, 'snyk_api_token', 1), before)
        self._assert_readable()

    def test_wrong_old_key_fails_safely(self):
        before = raw(SystemSetting, 'snyk_api_token', 1)
        before_pw = raw(type(self.pw), 'encrypted_password', self.pw.pk)
        with self.assertRaises(CommandError):
            call_command('rotate_encryption_key', new_key_file=self._key_file(self.new),
                         old_key_file=self._key_file(_key()), stdout=StringIO(), stderr=StringIO())
        self.assertEqual(raw(SystemSetting, 'snyk_api_token', 1), before)
        self.assertEqual(raw(type(self.pw), 'encrypted_password', self.pw.pk), before_pw)
        self._assert_readable()

    def test_invalid_new_key_rejected(self):
        with self.assertRaises(CommandError):
            call_command('rotate_encryption_key', new_key='not-a-key', stdout=StringIO())


class CheckSecretsStorageTests(TestCase):
    def test_clean_database_passes(self):
        s = SystemSetting.get_settings()
        s.snyk_api_token = 'fine'
        s.save()
        out = StringIO()
        call_command('check_secrets_storage', stdout=out)
        self.assertIn('No unprotected secrets', out.getvalue())

    def test_planted_plaintext_is_found(self):
        s = SystemSetting.get_settings()
        s.save()
        qn = connection.ops.quote_name
        with connection.cursor() as cur:
            cur.execute(f'UPDATE {qn(SystemSetting._meta.db_table)} SET '
                        f'{qn("snyk_api_token")} = %s', ['planted-plain-token'])
        out = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command('check_secrets_storage', stdout=out)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('core.SystemSetting.snyk_api_token', out.getvalue())
        self.assertNotIn('planted-plain-token', out.getvalue())

    def test_unhashed_token_is_found(self):
        from vault.models import WebExtensionAuthToken
        user = User.objects.create_user('chk', 'c@x.com', 'pw')
        _, row = WebExtensionAuthToken.issue(user=user)
        WebExtensionAuthToken.objects.filter(pk=row.pk).update(token_hash='raw-token-value')
        out = StringIO()
        with self.assertRaises(SystemExit):
            call_command('check_secrets_storage', stdout=out)
        self.assertIn('vault.WebExtensionAuthToken.token_hash', out.getvalue())

    def test_schema_check_flags_unprotected_secret_column(self):
        # Pretend a secret-named column is not covered by any list.
        from vault.secret_fields import HASHED_SECRET_FIELDS
        saved = list(HASHED_SECRET_FIELDS)
        HASHED_SECRET_FIELDS[:] = [x for x in saved if x[:3] != ('auth', 'User', 'password')]
        try:
            out = StringIO()
            with self.assertRaises(SystemExit):
                call_command('check_secrets_storage', schema_only=True, stdout=out)
            self.assertIn('auth.User.password', out.getvalue())
        finally:
            HASHED_SECRET_FIELDS[:] = saved
