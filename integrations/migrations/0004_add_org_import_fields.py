# Generated migration for organization import fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0003_alter_psaconnection_provider_type_and_more'),
    ]

    operations = [
        # Add to PSAConnection
        migrations.AddField(
            model_name='psaconnection',
            name='import_organizations',
            field=models.BooleanField(
                default=False,
                help_text='Automatically import/create organizations from PSA companies'
            ),
        ),
        migrations.AddField(
            model_name='psaconnection',
            name='org_import_as_active',
            field=models.BooleanField(
                default=True,
                help_text='Set imported organizations as active'
            ),
        ),
        migrations.AddField(
            model_name='psaconnection',
            name='org_name_prefix',
            field=models.CharField(
                max_length=50,
                blank=True,
                default='',
                help_text='Prefix to add to imported organization names (e.g., "PSA-")'
            ),
        ),

        # Add to RMMConnection
        migrations.AddField(
            model_name='rmmconnection',
            name='import_organizations',
            field=models.BooleanField(
                default=False,
                help_text='Automatically import/create organizations from RMM sites/clients'
            ),
        ),
        migrations.AddField(
            model_name='rmmconnection',
            name='org_import_as_active',
            field=models.BooleanField(
                default=True,
                help_text='Set imported organizations as active'
            ),
        ),
        migrations.AddField(
            model_name='rmmconnection',
            name='org_name_prefix',
            field=models.CharField(
                max_length=50,
                blank=True,
                default='',
                help_text='Prefix to add to imported organization names (e.g., "RMM-")'
            ),
        ),
    ]
