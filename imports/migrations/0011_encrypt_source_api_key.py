"""Encrypt ImportJob.source_api_key (IT Glue / Hudu API keys) at rest.
"""
import vault.secret_fields
from django.db import migrations

from vault.secret_fields import seal_column_operation


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0010_import_outcome_and_rollback_snapshot'),
    ]

    operations = [
        migrations.AlterField(
            model_name='importjob',
            name='source_api_key',
            field=vault.secret_fields.EncryptedTextField(blank=True, help_text='API key for authentication - not needed for MagicPlan (encrypted at rest)'),
        ),
        seal_column_operation('imports', 'ImportJob', 'source_api_key'),
    ]
