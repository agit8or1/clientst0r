"""Single sign-on (OIDC): the `manage_sso_settings` role permission, and the
`oidc` authentication source on user profiles.

The permission is new and off for every role (critical, MSP staff only).
Until an administrator grants it in a global role, only superusers can
configure single sign-on. No existing access changes.

Built-in roles keep their "not customized" state: their seed checksum covers
every permission field, so it is recomputed with the new field (False) for
each built-in role whose checksum still matched what was seeded.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'manage_sso_settings'
SKIP = {'is_system_template', 'is_archived'}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def keep_seed_checksums(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.exclude(seed_key='').exclude(seed_checksum=''):
        old = _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier)
        if old == rt.seed_checksum:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            rt.save(update_fields=['seed_checksum'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0050_dashboard_global_layout'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='manage_sso_settings',
            field=models.BooleanField(default=False, help_text='MSP staff (global role): configure single sign-on (OIDC) providers, mappings and linked accounts.'),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='auth_source',
            field=models.CharField(choices=[('azure_ad', 'Azure AD / Microsoft Entra ID'), ('ldap', 'LDAP/Active Directory'), ('local', 'Local'), ('oidc', 'Single sign-on (OIDC)')], default='local', help_text='Authentication source for this user', max_length=20),
        ),
        migrations.RunPython(keep_seed_checksums, migrations.RunPython.noop),
    ]
