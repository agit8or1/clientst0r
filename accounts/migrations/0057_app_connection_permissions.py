"""Agit8or Connect: `view_app_connections` and `manage_app_connections`.

Both are new, MSP-staff-only permissions and off for every role, so no
existing access changes: superusers reach Connected Applications; anyone else
needs a role an administrator grants them on (same pattern as 0047).

Built-in roles keep their "not customized" state: their seed checksum covers
every permission field, so it is recomputed with the new fields (False) for
each built-in role whose checksum still matched what was seeded.
"""
import hashlib

from django.db import migrations, models

NEW_KEYS = ('view_app_connections', 'manage_app_connections')
SKIP = {'is_system_template', 'is_archived'}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def keep_seed_checksums(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n not in NEW_KEYS]
    for rt in RoleTemplate.objects.exclude(seed_key='').exclude(seed_checksum=''):
        if _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier) == rt.seed_checksum:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            rt.save(update_fields=['seed_checksum'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0056_pricing_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='view_app_connections',
            field=models.BooleanField(default=False, help_text='Agit8or Connect: see connected applications, their permissions, customer grants, key fingerprints and activity (never secrets).'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='manage_app_connections',
            field=models.BooleanField(default=False, help_text='Agit8or Connect: pair, approve, test, rotate, disconnect and revoke connected applications and use the emergency kill switch. High-risk grants also need a second administrator.'),
        ),
        migrations.RunPython(keep_seed_checksums, migrations.RunPython.noop),
    ]
