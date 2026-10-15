"""
Secrets at rest: every converted column stores ciphertext (or a hash), the
application still reads the plaintext, forms do not echo it, and the data
migrations convert existing rows idempotently.
"""
import base64
import importlib
import json
import os
from types import SimpleNamespace

from django.apps import apps as global_apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings

from core.models import Organization, SystemSetting, Webhook, SecureNote
from vault import secret_fields as sf
from vault.encryption import encrypt as v1_encrypt


def _key():
    return base64.b64encode(os.urandom(32)).decode()


def raw(model, field, pk):
    """The column exactly as stored, bypassing the field's decryption."""
    qn = connection.ops.quote_name
    col = model._meta.get_field(field).column
    with connection.cursor() as cur:
        cur.execute(f'SELECT {qn(col)} FROM {qn(model._meta.db_table)} '
                    f'WHERE {qn(model._meta.pk.column)} = %s', [pk])
        return cur.fetchone()[0]


def set_raw(model, field, pk, value):
    qn = connection.ops.quote_name
    col = model._meta.get_field(field).column
    with connection.cursor() as cur:
        cur.execute(f'UPDATE {qn(model._meta.db_table)} SET {qn(col)} = %s '
                    f'WHERE {qn(model._meta.pk.column)} = %s', [value, pk])


SCHEMA_EDITOR = SimpleNamespace(connection=connection)


def make_ingestion_config(org, **kw):
    from psa.models import EmailIngestionConfig, Queue, TicketPriority, TicketType
    from psa.tests._base import _setup_seed
    _setup_seed()
    return EmailIngestionConfig(
        organization=org, imap_host='imap.x', username='u',
        default_queue=Queue.objects.first(),
        default_priority=TicketPriority.objects.first(),
        default_type=TicketType.objects.first(), **kw)


class EnvelopeTests(TestCase):
    def test_round_trip_and_prefix(self):
        ct = sf.seal('hunter2', 'a.B.c')
        self.assertTrue(ct.startswith('enc2$'))
        self.assertNotIn('hunter2', ct)
        self.assertEqual(sf.unseal(ct, 'a.B.c'), 'hunter2')

    def test_aad_binds_ciphertext_to_its_column(self):
        ct = sf.seal('hunter2', 'core.SystemSetting.smtp_password')
        with self.assertRaises(sf.SecretFieldError):
            sf.unseal(ct, 'core.SystemSetting.snyk_api_token')

    def test_previous_key_still_decrypts(self):
        old, new = _key(), _key()
        with override_settings(APP_MASTER_KEY=old):
            ct = sf.seal('s3cret', 'x')
        with override_settings(APP_MASTER_KEY=new, APP_MASTER_KEY_PREVIOUS=old):
            self.assertEqual(sf.unseal(ct, 'x'), 's3cret')
            # new writes use the new key only
            ct2 = sf.seal('s3cret', 'x')
        with override_settings(APP_MASTER_KEY=new):
            self.assertEqual(sf.unseal(ct2, 'x'), 's3cret')
            with self.assertRaises(sf.SecretFieldError):
                sf.unseal(ct, 'x')

    def test_v1_and_v2_layers_honour_previous_key(self):
        from vault.encryption import decrypt
        from vault.encryption_v2 import encrypt_password, decrypt_password
        old, new = _key(), _key()
        with override_settings(APP_MASTER_KEY=old):
            c1 = v1_encrypt('one')
            c2 = encrypt_password('two', org_id=5)
        with override_settings(APP_MASTER_KEY=new, APP_MASTER_KEY_PREVIOUS=old):
            self.assertEqual(decrypt(c1), 'one')
            self.assertEqual(decrypt_password(c2, org_id=5), 'two')

    def test_decrypt_v2_handles_v1_ciphertext_whose_nonce_starts_with_2(self):
        """Regression: 1 in 256 v1 values looked versioned and never decrypted."""
        from vault.encryption_v2 import decrypt_v2
        for _ in range(2000):
            ct = v1_encrypt('legacy')
            if base64.b64decode(ct)[0] == 2:
                break
        else:
            self.skipTest('no 0x02-prefixed nonce generated')
        self.assertEqual(decrypt_v2(ct), 'legacy')


class TransparentFieldTests(TestCase):
    """Every EncryptedTextField column: ciphertext in the DB, plaintext in Python."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Sec Org', slug='sec-org')
        cls.user = User.objects.create_user('secuser', 's@x.com', 'pw')

    def _assert_encrypted(self, model, field, pk, plaintext):
        stored = raw(model, field, pk)
        self.assertTrue(sf.is_sealed(stored), f'{model.__name__}.{field} not sealed')
        self.assertNotIn(plaintext, stored)
        self.assertEqual(getattr(model.objects.get(pk=pk), field), plaintext)

    def test_system_setting_secrets(self):
        s = SystemSetting.get_settings()
        values = {
            'smtp_password': 'smtp-pw-1', 'ldap_bind_password': 'ldap-pw-1',
            'azure_ad_client_secret': 'az-secret-1', 'snyk_api_token': 'snyk-tok-1',
            'git' + 'hub_pat': 'ghp_abc123def', 'sms_auth_token': 'sms-tok-1',
            'dell_api_key': 'dell-key-1', 'hp_client_secret': 'hp-secret-1',
            'lenovo_client_secret': 'lenovo-secret-1',
        }
        for k, v in values.items():
            setattr(s, k, v)
        s.save()
        for k, v in values.items():
            self._assert_encrypted(SystemSetting, k, s.pk, v)
        s = SystemSetting.get_settings()
        self.assertEqual(s.get_smtp_password_decrypted(), 'smtp-pw-1')
        self.assertEqual(s.get_azure_ad_client_secret_decrypted(), 'az-secret-1')

    def test_smtp_connection_gets_plaintext_password(self):
        from core.mailer import get_smtp_connection
        s = SystemSetting.get_settings()
        s.smtp_enabled, s.smtp_host, s.smtp_password = True, 'mail.example.com', 'smtp-pw-2'
        s.save()
        conn = get_smtp_connection(SystemSetting.get_settings())
        self.assertEqual(conn.password, 'smtp-pw-2')

    def test_warranty_lookup_uses_plaintext_key(self):
        s = SystemSetting.get_settings()
        s.dell_api_key = 'dell-live-key'
        s.save()
        self.assertEqual(SystemSetting.get_settings().dell_api_key, 'dell-live-key')

    def test_partner_secret(self):
        org = Organization.objects.create(name='Partner', slug='partner-x',
                                          is_outsourcing_partner=True)
        secret = Organization.objects.get(pk=org.pk).partner_secret
        self.assertEqual(len(secret), 64)
        self._assert_encrypted(Organization, 'partner_secret', org.pk, secret)

    def test_webhook_secret_and_headers(self):
        from core.webhook_sender import generate_signature
        wh = Webhook.objects.create(organization=self.org, name='w', url='https://x.example',
                                    events=['asset.created'], secret='whsec-1',
                                    custom_headers={'Authorization': 'Bearer tok-1'})
        self._assert_encrypted(Webhook, 'secret', wh.pk, 'whsec-1')
        stored = raw(Webhook, 'custom_headers', wh.pk)
        self.assertTrue(sf.is_sealed(stored))
        self.assertNotIn('tok-1', stored)
        wh = Webhook.objects.get(pk=wh.pk)
        self.assertEqual(wh.custom_headers, {'Authorization': 'Bearer tok-1'})
        self.assertEqual(generate_signature('{}', wh.secret), generate_signature('{}', 'whsec-1'))

    def test_import_job_api_key(self):
        from imports.models import ImportJob
        job = ImportJob.objects.create(source_type='itglue', source_url='https://api.itglue.com',
                                       source_api_key='itg-key-1')
        self._assert_encrypted(ImportJob, 'source_api_key', job.pk, 'itg-key-1')

    def test_web_push_auth_secret(self):
        from psa.models import WebPushSubscription
        sub = WebPushSubscription.objects.create(user=self.user, endpoint='https://push.example/1',
                                                 p256dh_key='pub', auth_secret='auth-1')
        self._assert_encrypted(WebPushSubscription, 'auth_secret', sub.pk, 'auth-1')

    def test_security_vendor_and_siem_secrets(self):
        from security_alerts.models import SecurityVendorConnection, SIEMWebhookEndpoint
        conn = SecurityVendorConnection.objects.create(
            organization=self.org, name='EDR', provider='sentinelone', category='edr',
            credentials_encrypted='{"api_key": "s1-key"}')
        self._assert_encrypted(SecurityVendorConnection, 'credentials_encrypted', conn.pk,
                               '{"api_key": "s1-key"}')
        self._assert_encrypted(SecurityVendorConnection, 'webhook_secret', conn.pk,
                               conn.issued_webhook_secret)
        self.assertEqual(raw(SecurityVendorConnection, 'webhook_token_hash', conn.pk),
                         SecurityVendorConnection.hash_webhook_token(conn.issued_webhook_token))
        ep = SIEMWebhookEndpoint.objects.create(organization=self.org, name='Splunk')
        self._assert_encrypted(SIEMWebhookEndpoint, 'hmac_secret', ep.pk, ep.issued_hmac_secret)
        self.assertNotIn(ep.issued_token, raw(SIEMWebhookEndpoint, 'token_hash', ep.pk))
        self.assertEqual(SIEMWebhookEndpoint.lookup_by_token(ep.issued_token).pk, ep.pk)

    def test_vault_license_key(self):
        from vault.models import Password
        pw = Password(organization=self.org, title='Office', password_type='software_license',
                      license_key='XXXX-YYYY-ZZZZ')
        pw.set_password('pw')
        pw.save()
        self._assert_encrypted(Password, 'license_key', pw.pk, 'XXXX-YYYY-ZZZZ')

    def test_secure_note_content_sealed(self):
        note = SecureNote(sender=self.user, title='t')
        note.set_content('note body 1')
        note.save()
        stored = raw(SecureNote, 'encrypted_content', note.pk)
        self.assertTrue(sf.is_sealed(stored))
        self.assertEqual(SecureNote.objects.get(pk=note.pk).get_content(), 'note body 1')

    def test_integration_credentials_sealed(self):
        from integrations.models import PSAConnection, DistributorConnection
        conn = PSAConnection(organization=self.org, provider_type='connectwise_manage',
                             name='cw', base_url='https://cw.example')
        conn.set_credentials({'private_key': 'cw-priv', 'port': 8443})
        conn.save()
        stored = raw(PSAConnection, 'encrypted_credentials', conn.pk)
        self.assertTrue(sf.is_sealed(stored))
        self.assertNotIn('cw-priv', stored)
        self.assertNotIn('8443', stored)  # v1 left non-string values in the clear
        self.assertEqual(PSAConnection.objects.get(pk=conn.pk).get_credentials(),
                         {'private_key': 'cw-priv', 'port': 8443})
        d = DistributorConnection.objects.create(organization=self.org,
                                                 provider_type='ingram_xvantage', name='i')
        d.set_webhook_secret('dist-hmac')
        d.save()
        self.assertTrue(sf.is_sealed(raw(DistributorConnection, 'encrypted_webhook_secret', d.pk)))

    def test_email_ingestion_password_sealed(self):
        from psa.models import EmailIngestionConfig
        cfg = make_ingestion_config(self.org, name='inbox')
        cfg.set_password('imap-pw-1')
        cfg.save()
        stored = raw(EmailIngestionConfig, 'encrypted_password', cfg.pk)
        self.assertTrue(sf.is_sealed(stored))
        self.assertEqual(EmailIngestionConfig.objects.get(pk=cfg.pk).get_password(), 'imap-pw-1')

    def test_dumpdata_exports_ciphertext(self):
        from django.core import serializers
        s = SystemSetting.get_settings()
        s.snyk_api_token = 'snyk-dump-1'
        s.save()
        out = serializers.serialize('json', [SystemSetting.get_settings()])
        self.assertNotIn('snyk-dump-1', out)
        self.assertIn('enc2$', out)

    def test_undecryptable_value_is_preserved_not_blanked(self):
        s = SystemSetting.get_settings()
        s.snyk_api_token = 'snyk-keep'
        s.save()
        with override_settings(APP_MASTER_KEY=_key()):
            obj = SystemSetting.get_settings()
            self.assertTrue(sf.is_sealed(obj.snyk_api_token))
            obj.save()  # must not overwrite with '' or double-encrypt
        self.assertEqual(SystemSetting.get_settings().snyk_api_token, 'snyk-keep')


class FormsDoNotEchoSecretsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Form Org', slug='form-org')

    def test_webhook_form_masks_secret_and_header_values(self):
        from core.webhook_forms import WebhookForm, HEADER_VALUE_MASK
        wh = Webhook.objects.create(organization=self.org, name='w', url='https://x.example',
                                    events=['asset.created'], secret='whsec-echo',
                                    custom_headers={'Authorization': 'Bearer echo-tok'})
        html = str(WebhookForm(instance=wh))
        self.assertNotIn('whsec-echo', html)
        self.assertNotIn('echo-tok', html)
        self.assertIn('Authorization', html)
        # Submitting the masked form keeps both stored values.
        form = WebhookForm(data={
            'name': 'w', 'url': 'https://x.example', 'events': ['asset.created'],
            'secret': '', 'is_active': 'on',
            'custom_headers': json.dumps({'Authorization': HEADER_VALUE_MASK, 'X-New': 'v'}),
        }, instance=wh)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        wh = Webhook.objects.get(pk=wh.pk)
        self.assertEqual(wh.secret, 'whsec-echo')
        self.assertEqual(wh.custom_headers, {'Authorization': 'Bearer echo-tok', 'X-New': 'v'})

    def test_security_vendor_form_does_not_echo_credentials(self):
        from security_alerts.forms import SecurityVendorConnectionForm
        from security_alerts.models import SecurityVendorConnection
        conn = SecurityVendorConnection.objects.create(
            organization=self.org, name='EDR', provider='sentinelone', category='edr',
            credentials_encrypted='s1-echo-key')
        html = str(SecurityVendorConnectionForm(instance=conn))
        self.assertNotIn('s1-echo-key', html)

    def test_psa_connection_form_keeps_secret_on_blank(self):
        from integrations.forms import PSAConnectionForm
        from integrations.models import PSAConnection
        conn = PSAConnection(organization=self.org, provider_type='kaseya_bms', name='k',
                             base_url='https://k.example')
        conn.set_credentials({'api_key': 'kaseya-echo-key', 'api_secret': 'kaseya-echo-secret'})
        conn.save()
        html = str(PSAConnectionForm(instance=conn, organization=self.org))
        self.assertNotIn('kaseya-echo-key', html)
        self.assertNotIn('kaseya-echo-secret', html)
        form = PSAConnectionForm(data={
            'provider_type': 'kaseya_bms', 'name': 'k', 'base_url': 'https://k.example',
            'sync_interval_minutes': 60, 'kaseya_api_key': '', 'kaseya_api_secret': '',
        }, instance=conn, organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        creds = PSAConnection.objects.get(pk=conn.pk).get_credentials()
        self.assertEqual(creds['api_key'], 'kaseya-echo-key')
        self.assertEqual(creds['api_secret'], 'kaseya-echo-secret')

    def test_rmm_connection_form_does_not_echo(self):
        from integrations.forms import RMMConnectionForm
        from integrations.models import RMMConnection
        conn = RMMConnection(organization=self.org, provider_type='ninjaone', name='n',
                             base_url='https://n.example')
        conn.set_credentials({'client_id': 'cid', 'client_secret': 'ninja-echo-secret',
                              'refresh_token': 'ninja-echo-refresh'})
        conn.save()
        html = str(RMMConnectionForm(instance=conn, organization=self.org))
        self.assertNotIn('ninja-echo-secret', html)
        self.assertNotIn('ninja-echo-refresh', html)

    def test_vault_form_does_not_echo_license_key(self):
        from vault.forms import PasswordForm
        from vault.models import Password
        pw = Password(organization=self.org, title='Lic', password_type='software_license',
                      license_key='LIC-ECHO-123')
        pw.set_password('x')
        pw.save()
        html = str(PasswordForm(instance=pw, organization=self.org))
        self.assertNotIn('LIC-ECHO-123', html)

    def test_admin_formfield_for_encrypted_field_does_not_render_value(self):
        from django.contrib.admin.widgets import AdminTextareaWidget
        field = SystemSetting._meta.get_field('snyk_api_token').formfield(widget=AdminTextareaWidget)
        self.assertNotIn('abc-admin', field.widget.render('snyk_api_token', 'abc-admin'))


class ExtensionTokenHashingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('ext_hash', 'e@x.com', 'pw')

    def test_new_token_stored_hashed_and_authenticates(self):
        from vault.models import WebExtensionAuthToken
        secret, row = WebExtensionAuthToken.issue(user=self.user)
        stored = raw(WebExtensionAuthToken, 'token_hash', row.pk)
        self.assertNotEqual(stored, secret)
        self.assertTrue(sf.looks_like_token_hash(stored))
        self.assertEqual(row.token_prefix, secret[:8])
        self.assertEqual(WebExtensionAuthToken.lookup(secret).pk, row.pk)
        self.assertIsNone(WebExtensionAuthToken.lookup(secret + 'x'))

    def test_token_list_response_has_no_secret_material(self):
        from vault.models import WebExtensionAuthToken
        from vault.tests import TEST_MIDDLEWARE
        secret, row = WebExtensionAuthToken.issue(user=self.user)
        self.client.force_login(self.user)
        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False):
            r = self.client.get('/vault/api/extension/tokens/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn(secret, body)
        self.assertNotIn(row.token_hash, body)
        self.assertEqual(r.json()['tokens'][0]['token_prefix'], secret[:8])

    def test_migrated_raw_token_keeps_working(self):
        from vault.models import WebExtensionAuthToken
        from vault.extension_auth import resolve_extension_token
        _, row = WebExtensionAuthToken.issue(user=self.user)
        legacy = 'legacy-raw-token-' + 'a' * 26  # pre-migration rows held the raw token
        set_raw(WebExtensionAuthToken, 'token_hash', row.pk, legacy)
        op = sf.hash_token_column_operation('vault', 'WebExtensionAuthToken', 'token_hash',
                                            'vault.webextension', prefix_field='token_prefix')
        op.code(global_apps, SCHEMA_EDITOR)
        op.code(global_apps, SCHEMA_EDITOR)  # idempotent
        stored = raw(WebExtensionAuthToken, 'token_hash', row.pk)
        self.assertEqual(stored, WebExtensionAuthToken.hash(legacy))
        req = SimpleNamespace(META={'HTTP_AUTHORIZATION': f'Bearer {legacy}'},
                              headers={'Authorization': f'Bearer {legacy}'})
        found, err = resolve_extension_token(req)
        self.assertIsNone(err)
        self.assertEqual(found.pk, row.pk)


class DataMigrationTests(TestCase):
    """The RunPython operations used by the migrations, run against legacy rows."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Mig Org', slug='mig-org')

    def _run(self, *args, **kw):
        return sf.seal_existing_rows(global_apps, SCHEMA_EDITOR, *args, **kw)

    def test_plaintext_row_is_sealed_and_idempotent(self):
        s = SystemSetting.get_settings()
        s.save()
        set_raw(SystemSetting, 'snyk_api_token', s.pk, 'plain-snyk')
        self.assertEqual(self._run('core', 'SystemSetting', 'snyk_api_token'), 1)
        stored = raw(SystemSetting, 'snyk_api_token', s.pk)
        self.assertTrue(sf.is_sealed(stored))
        self.assertEqual(SystemSetting.get_settings().snyk_api_token, 'plain-snyk')
        self.assertEqual(self._run('core', 'SystemSetting', 'snyk_api_token'), 0)
        self.assertEqual(raw(SystemSetting, 'snyk_api_token', s.pk), stored)

    def test_v1_and_v2_legacy_values_are_decoded_then_sealed(self):
        from vault.encryption_v2 import encrypt_api_credentials
        s = SystemSetting.get_settings()
        s.save()
        set_raw(SystemSetting, 'smtp_password', s.pk, v1_encrypt('v1-smtp'))
        set_raw(SystemSetting, 'ldap_bind_password', s.pk, encrypt_api_credentials('v2-ldap', org_id=0))
        # Before migrating, the field already reads legacy values.
        self.assertEqual(SystemSetting.get_settings().smtp_password, 'v1-smtp')
        self._run('core', 'SystemSetting', 'smtp_password', legacy='auto')
        self._run('core', 'SystemSetting', 'ldap_bind_password', legacy='auto')
        s = SystemSetting.get_settings()
        self.assertEqual((s.smtp_password, s.ldap_bind_password), ('v1-smtp', 'v2-ldap'))
        self.assertTrue(sf.is_sealed(raw(SystemSetting, 'smtp_password', s.pk)))

    def test_v1_credential_blob_is_sealed(self):
        from integrations.models import PSAConnection
        from vault.encryption import encrypt_dict
        conn = PSAConnection.objects.create(organization=self.org, provider_type='itflow',
                                            name='it', base_url='https://it.example',
                                            encrypted_credentials='')
        set_raw(PSAConnection, 'encrypted_credentials', conn.pk,
                json.dumps(encrypt_dict({'api_key': 'itflow-legacy'})))
        # Legacy blob still readable before migrating
        self.assertEqual(PSAConnection.objects.get(pk=conn.pk).get_credentials()['api_key'],
                         'itflow-legacy')
        self._run('integrations', 'PSAConnection', 'encrypted_credentials', legacy='v1_json')
        stored = raw(PSAConnection, 'encrypted_credentials', conn.pk)
        self.assertTrue(sf.is_sealed(stored))
        self.assertEqual(PSAConnection.objects.get(pk=conn.pk).get_credentials(),
                         {'api_key': 'itflow-legacy'})
        # Reverse restores the v1 shape the previous release reads.
        sf.unseal_existing_rows(global_apps, SCHEMA_EDITOR, 'integrations', 'PSAConnection',
                                'encrypted_credentials', restore='v1_json')
        legacy = json.loads(raw(PSAConnection, 'encrypted_credentials', conn.pk))
        self.assertNotIn('itflow-legacy', legacy['api_key'])

    def test_email_password_legacy_key_shape(self):
        from psa.models import EmailIngestionConfig
        from vault.encryption import encrypt_dict
        cfg = make_ingestion_config(self.org, name='m')
        cfg.save()
        set_raw(EmailIngestionConfig, 'encrypted_password', cfg.pk,
                json.dumps(encrypt_dict({'p': 'imap-legacy'})))
        self._run('psa', 'EmailIngestionConfig', 'encrypted_password', legacy='v1_json_key:p')
        self.assertTrue(sf.is_sealed(raw(EmailIngestionConfig, 'encrypted_password', cfg.pk)))
        self.assertEqual(EmailIngestionConfig.objects.get(pk=cfg.pk).get_password(), 'imap-legacy')

    def test_reverse_restores_plaintext(self):
        s = SystemSetting.get_settings()
        s.dell_api_key = 'dell-rev'
        s.save()
        sf.unseal_existing_rows(global_apps, SCHEMA_EDITOR, 'core', 'SystemSetting', 'dell_api_key')
        self.assertEqual(raw(SystemSetting, 'dell_api_key', s.pk), 'dell-rev')

    def test_vault_v1_passwords_upgraded_to_v2(self):
        from vault.models import Password
        from vault.encryption_v2 import decrypt_password, decrypt_totp_secret
        mig = importlib.import_module('vault.migrations.0015_hash_extension_tokens_encrypt_license')
        pw = Password(organization=self.org, title='old', password_type='website')
        pw.set_password('x')
        pw.save()
        set_raw(Password, 'encrypted_password', pw.pk, v1_encrypt('v1-vault-pw'))
        set_raw(Password, 'otp_secret', pw.pk, 'otpauth://totp/x?secret=JBSWY3DPEHPK3PXP')
        mig.upgrade_v1_to_v2(global_apps, SCHEMA_EDITOR)
        stored = raw(Password, 'encrypted_password', pw.pk)
        self.assertEqual(base64.b64decode(stored)[0], 2)
        self.assertEqual(decrypt_password(stored, org_id=self.org.pk), 'v1-vault-pw')
        otp = raw(Password, 'otp_secret', pw.pk)
        self.assertFalse(otp.startswith('otpauth://'))
        self.assertEqual(decrypt_totp_secret(otp, org_id=self.org.pk),
                         'otpauth://totp/x?secret=JBSWY3DPEHPK3PXP')
        # idempotent
        mig.upgrade_v1_to_v2(global_apps, SCHEMA_EDITOR)
        self.assertEqual(raw(Password, 'encrypted_password', pw.pk), stored)
        self.assertEqual(Password.objects.get(pk=pw.pk).get_password(), 'v1-vault-pw')
