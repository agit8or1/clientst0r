"""Secrets at rest for security_alerts.

- SecurityVendorConnection.webhook_token / SIEMWebhookEndpoint.token: renamed
  to *_hash and replaced in place by HMAC-SHA256 of the token. URLs already
  configured at vendors keep working (the presented token hashes to the stored
  value). Irreversible: rolling back past this migration means issuing new
  webhook URLs.
- webhook_secret / hmac_secret / credentials_encrypted: encrypted in place
  (enc2$ envelope). Reverse decrypts back to plaintext.
"""
import vault.secret_fields
from django.db import migrations, models
from vault.secret_fields import hash_token_column_operation, seal_column_operation


class Migration(migrations.Migration):

    dependencies = [
        ('security_alerts', '0005_remediationplaybook_remediationplaybookstep'),
    ]

    operations = [
        # --- vendor connections -------------------------------------------
        migrations.RenameField(
            model_name='securityvendorconnection',
            old_name='webhook_token',
            new_name='webhook_token_hash',
        ),
        migrations.AlterField(
            model_name='securityvendorconnection',
            name='webhook_token_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64,
                                   help_text='HMAC-SHA256 of the inbound webhook URL token.'),
        ),
        migrations.AlterField(
            model_name='securityvendorconnection',
            name='webhook_secret',
            field=vault.secret_fields.EncryptedTextField(
                blank=True,
                help_text='HMAC shared secret for verifying inbound webhook payloads (encrypted).'),
        ),
        migrations.AlterField(
            model_name='securityvendorconnection',
            name='credentials_encrypted',
            field=vault.secret_fields.EncryptedTextField(
                blank=True,
                help_text='Encrypted blob of provider-specific creds (API key / token / username+password / etc).'),
        ),
        hash_token_column_operation('security_alerts', 'SecurityVendorConnection',
                                    'webhook_token_hash', 'security_alerts.vendor.webhook'),
        seal_column_operation('security_alerts', 'SecurityVendorConnection', 'webhook_secret'),
        seal_column_operation('security_alerts', 'SecurityVendorConnection', 'credentials_encrypted'),

        # --- SIEM endpoints -----------------------------------------------
        migrations.RemoveIndex(
            model_name='siemwebhookendpoint',
            name='siem_webhoo_token_d32869_idx',
        ),
        migrations.RenameField(
            model_name='siemwebhookendpoint',
            old_name='token',
            new_name='token_hash',
        ),
        migrations.AlterField(
            model_name='siemwebhookendpoint',
            name='token_hash',
            field=models.CharField(max_length=64, unique=True,
                                   help_text='HMAC-SHA256 of the per-endpoint URL token. Auto-generated.'),
        ),
        migrations.AddIndex(
            model_name='siemwebhookendpoint',
            index=models.Index(fields=['token_hash'], name='siem_webhoo_token_h_5c67cb_idx'),
        ),
        migrations.AlterField(
            model_name='siemwebhookendpoint',
            name='hmac_secret',
            field=vault.secret_fields.EncryptedTextField(
                blank=True,
                help_text='If set, inbound POSTs MUST send an X-Cst0r-Signature header containing '
                          'hex-encoded HMAC-SHA256(secret, body). Encrypted at rest.'),
        ),
        hash_token_column_operation('security_alerts', 'SIEMWebhookEndpoint',
                                    'token_hash', 'security_alerts.siem.webhook'),
        seal_column_operation('security_alerts', 'SIEMWebhookEndpoint', 'hmac_secret'),
    ]
