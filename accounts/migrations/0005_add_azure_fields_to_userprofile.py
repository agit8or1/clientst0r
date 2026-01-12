# Generated migration for Azure AD fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_userprofile_global_role_template_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='auth_source',
            field=models.CharField(
                blank=True,
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
                help_text='Azure AD Object ID (OID)',
                max_length=255
            ),
        ),
    ]
