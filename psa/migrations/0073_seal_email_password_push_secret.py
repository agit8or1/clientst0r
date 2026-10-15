"""Encrypt the IMAP ingestion password (was v1 per-value JSON) and the Web Push
subscription auth secret (was plaintext) with the enc2$ envelope.
"""
import vault.secret_fields
from django.db import migrations

from vault.secret_fields import seal_column_operation


class Migration(migrations.Migration):

    dependencies = [
        ('psa', '0072_service_catalog_guided_requests'),
    ]

    operations = [
        migrations.AlterField(
            model_name='emailingestionconfig',
            name='encrypted_password',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json_key:p'),
        ),
        migrations.AlterField(
            model_name='webpushsubscription',
            name='auth_secret',
            field=vault.secret_fields.EncryptedTextField(help_text='Auth secret from the browser (base64). Encrypted at rest.'),
        ),
        seal_column_operation('psa', 'EmailIngestionConfig', 'encrypted_password', legacy='v1_json_key:p'),
        seal_column_operation('psa', 'WebPushSubscription', 'auth_secret'),
    ]
