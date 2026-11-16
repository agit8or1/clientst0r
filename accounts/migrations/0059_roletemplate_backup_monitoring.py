"""Backup monitoring: `view_backup_status` and `manage_backup_integrations`.

Both are new and off for every role. Built-in roles that still match what was
seeded (their checksum is unchanged) get the grants the built-in definitions
now carry (see accounts/role_seeds.py); customized roles are left exactly as
they are. Checksums are recomputed so "not customized" stays true.
"""
import hashlib

from django.db import migrations, models

NEW_KEYS = ('view_backup_status', 'manage_backup_integrations')
SKIP = {'is_system_template', 'is_archived'}

# seed_key -> permissions the built-in definition now grants.
GRANTS = {
    'org_owner': NEW_KEYS,
    'org_admin': NEW_KEYS,
    'service_manager': ('view_backup_status',),
    'tech_l1': ('view_backup_status',),
    'tech_l2': ('view_backup_status',),
    'tech_l3': ('view_backup_status',),
    'auditor': ('view_backup_status',),
}


# seed_key -> definition version that carries these grants.
VERSIONS = {'org_owner': 5}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def grant(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n not in NEW_KEYS]
    for rt in RoleTemplate.objects.filter(organization__isnull=True).exclude(seed_key='').exclude(seed_checksum=''):
        old = _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier)
        if old != rt.seed_checksum:
            continue  # customized: leave alone
        for key in GRANTS.get(rt.seed_key, ()):
            setattr(rt, key, True)
        rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
        # Same as the built-in definitions: Owner moves to version 5 (after
        # 0055 tax, 0056 pricing, 0058 profitability), the others to 2.
        if rt.seed_key in GRANTS:
            rt.seed_version = max(rt.seed_version, VERSIONS.get(rt.seed_key, 2))
        rt.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0058_roletemplate_view_profitability'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='view_backup_status',
            field=models.BooleanField(default=False, help_text='View backup monitoring: jobs, runs, repositories, alerts and restore tests.'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='manage_backup_integrations',
            field=models.BooleanField(default=False, help_text='Create / edit / delete backup connections and alert policies; record restore tests; acknowledge backup alerts.'),
        ),
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
