"""Edit in Microsoft 365: the `office_edit_in_m365` role permission.

The permission is new and off for every role. Customer users need it (and
edit permission on the file) to send a working copy of a clientst0r Office
file to Microsoft 365; MSP staff follow their edit permission on the file and
do not need it. No existing access changes.

Built-in roles keep their "not customized" state: their seed checksum covers
every permission field, so it is recomputed with the new field (False) for
each built-in role whose checksum still matched what was seeded.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'office_edit_in_m365'
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
        ('accounts', '0046_roles_access_seed_and_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='office_edit_in_m365',
            field=models.BooleanField(default=False, help_text='Customer users: edit Office files in Microsoft 365 (a working copy). MSP staff follow their edit permission on the file.'),
        ),
        migrations.RunPython(keep_seed_checksums, migrations.RunPython.noop),
    ]
