"""Encrypt secrets that were stored in plaintext or with the v1 layer.

Columns become EncryptedTextField / SealedTextField (enc2$ envelope: HKDF
purpose key + AAD bound to the column). Existing rows are converted in
place; already-converted rows are skipped. Reverse writes each column back
in the form the previous release read (plaintext, v1 or v2 org-0).
"""
import vault.secret_fields
from django.db import migrations

from vault.secret_fields import seal_column_operation


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0072_systemsetting_psa_closeout_require_time'),
    ]

    operations = [
        migrations.AlterField(
            model_name='organization',
            name='partner_secret',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='HMAC shared secret for verifying inbound webhook payloads. Auto-generated when is_outsourcing_partner flips to True.'),
        ),
        migrations.AlterField(
            model_name='securenote',
            name='encrypted_content',
            field=vault.secret_fields.SealedTextField(legacy='v1'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='azure_ad_client_secret',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Client secret (encrypted)', legacy='auto'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='dell_api_key',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Dell TechDirect API key for warranty lookups (encrypted)'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='github_pat',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='GitHub Personal Access Token for bug reporting (encrypted)', legacy='auto'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='hp_client_secret',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='HP API client secret for warranty lookups (encrypted)'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='ldap_bind_password',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Password for bind DN (encrypted)', legacy='auto'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='lenovo_client_secret',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Lenovo warranty API client secret (encrypted)'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='sms_auth_token',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='SMS provider auth token (encrypted)', legacy='auto'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='smtp_password',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='SMTP password (encrypted)', legacy='auto'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='snyk_api_token',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Snyk API token for vulnerability scanning (encrypted)'),
        ),
        migrations.AlterField(
            model_name='webhook',
            name='custom_headers',
            field=vault.secret_fields.EncryptedJSONField(blank=True, default=dict, help_text='Custom HTTP headers to include in requests (e.g., Authorization). Encrypted at rest.'),
        ),
        migrations.AlterField(
            model_name='webhook',
            name='secret',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='Secret key for signing webhook payloads (optional, encrypted)'),
        ),
        # Encrypt existing values in place (raw SQL; idempotent; reversible).
        seal_column_operation('core', 'Organization', 'partner_secret'),
        seal_column_operation('core', 'SecureNote', 'encrypted_content', legacy='v1'),
        seal_column_operation('core', 'SystemSetting', 'smtp_password', legacy='auto'),
        seal_column_operation('core', 'SystemSetting', 'ldap_bind_password', legacy='auto', restore='v2api0'),
        seal_column_operation('core', 'SystemSetting', 'azure_ad_client_secret', legacy='auto', restore='v2api0'),
        seal_column_operation('core', 'SystemSetting', 'snyk_api_token'),
        seal_column_operation('core', 'SystemSetting', 'github_pat', legacy='auto'),
        seal_column_operation('core', 'SystemSetting', 'sms_auth_token', legacy='auto'),
        seal_column_operation('core', 'SystemSetting', 'dell_api_key'),
        seal_column_operation('core', 'SystemSetting', 'hp_client_secret'),
        seal_column_operation('core', 'SystemSetting', 'lenovo_client_secret'),
        seal_column_operation('core', 'Webhook', 'secret'),
        seal_column_operation('core', 'Webhook', 'custom_headers'),
    ]
