# Generated migration for Azure AD fields

from django.db import migrations, models


def set_default_auth_source(apps, schema_editor):
    """Set auth_source='local' for all existing UserProfile records."""
    UserProfile = apps.get_model('accounts', 'UserProfile')
    UserProfile.objects.filter(auth_source='').update(auth_source='local')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_userprofile_global_role_template_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='auth_source',
            field=models.CharField(
                choices=[
                    ('local', 'Local'),
                    ('ldap', 'LDAP/Active Directory'),
                    ('azure_ad', 'Azure AD / Microsoft Entra ID'),
                ],
                default='local',
                help_text='Authentication source for this user',
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='azure_ad_oid',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Azure AD Object ID (OID)',
                max_length=255
            ),
        ),
        # Set default for existing records
        migrations.RunPython(set_default_auth_source, migrations.RunPython.noop),
    ]
