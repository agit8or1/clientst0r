"""Move integration credentials off the v1 layer; hash distributor webhook tokens.

v1 encrypted each credential value separately with the raw master key and no
AAD. Each blob is now one enc2$ envelope (HKDF purpose key, AAD bound to
the column), which also covers non-string values v1 left in the clear.
Reverse restores v1 per-value JSON. The webhook token hash is not reversible.
"""
import vault.secret_fields
from django.db import migrations, models

from vault.secret_fields import hash_token_column_operation, seal_column_operation


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0030_alter_accountingauditlog_action'),
    ]

    operations = [
        migrations.RenameField(
            model_name='distributorconnection',
            old_name='webhook_token',
            new_name='webhook_token_hash',
        ),
        migrations.AlterField(
            model_name='distributorconnection',
            name='webhook_token_hash',
            field=models.CharField(blank=True, db_index=True, help_text='HMAC-SHA256 of the per-connection webhook URL token.', max_length=64),
        ),
        migrations.AlterField(
            model_name='accountingconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='distributorconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, help_text='Encrypted JSON with API keys, customer IDs, etc.', legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='distributorconnection',
            name='encrypted_webhook_secret',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json_key:s'),
        ),
        migrations.AlterField(
            model_name='grandstreamconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='m365connection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, help_text='Encrypted JSON with client_id and client_secret', legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='omadaconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='paymentconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='psaconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(help_text='Encrypted (enc2$ envelope) JSON with API keys, secrets, tokens', legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='rmmconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(help_text='Encrypted (enc2$ envelope) JSON with API keys, secrets, tokens', legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='taxconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='unificonnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, help_text='Encrypted JSON with api_key', legacy='v1_json'),
        ),
        migrations.AlterField(
            model_name='warrantyconnection',
            name='encrypted_credentials',
            field=vault.secret_fields.SealedTextField(blank=True, legacy='v1_json'),
        ),
        # Credential blobs: v1 per-value JSON -> one enc2$ envelope.
        seal_column_operation('integrations', 'PSAConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'RMMConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'UnifiConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'OmadaConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'GrandstreamConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'M365Connection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'DistributorConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'AccountingConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'PaymentConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'WarrantyConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'TaxConnection', 'encrypted_credentials', legacy='v1_json'),
        seal_column_operation('integrations', 'DistributorConnection', 'encrypted_webhook_secret', legacy='v1_json_key:s'),
        # Webhook URL tokens: raw -> HMAC (irreversible; existing URLs keep working).
        hash_token_column_operation('integrations', 'DistributorConnection', 'webhook_token_hash',
                                    'integrations.distributor.webhook'),
    ]
