"""Customer health score: the `manage_health_score_settings` role permission.

New and off by default. Role templates that can already change organization
settings (`org_manage_settings`) get it so their holders keep managing
configuration; nobody else is granted anything. Built-in roles keep their
"not customized" state: their seed checksum covers every permission field, so
it is recomputed for each built-in role whose checksum still matched what was
seeded.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'manage_health_score_settings'
SKIP = {'is_system_template', 'is_archived'}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def grant_to_settings_admins(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.all():
        seeded = bool(rt.seed_key and rt.seed_checksum)
        matched = seeded and _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier) == rt.seed_checksum
        if rt.org_manage_settings:
            rt.manage_health_score_settings = True
            rt.save(update_fields=[NEW_KEY])
        if matched:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            rt.save(update_fields=['seed_checksum'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0050_dashboard_global_layout'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='manage_health_score_settings',
            field=models.BooleanField(default=False, help_text='Customer health score: change the dimension and signal weights and thresholds.'),
        ),
        migrations.RunPython(grant_to_settings_admins, migrations.RunPython.noop),
    ]
