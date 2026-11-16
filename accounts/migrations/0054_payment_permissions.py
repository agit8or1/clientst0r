"""Payment processing role permissions: `process_refunds` and
`manage_payment_providers` (MSP staff only, off for every role).

No existing access changes. Built-in roles keep their "not customized" state:
the seed checksum covers every permission field, so it is recomputed with the
new fields (False) for each built-in role whose checksum still matched.
"""
import hashlib

from django.db import migrations, models

NEW_KEYS = ('process_refunds', 'manage_payment_providers')
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
        old = _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier)
        if old == rt.seed_checksum:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            rt.save(update_fields=['seed_checksum'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0053_roletemplate_manage_sso_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='process_refunds',
            field=models.BooleanField(default=False, help_text='Refund card / bank payments through the payment provider.'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='manage_payment_providers',
            field=models.BooleanField(default=False, help_text='Configure payment provider connections, webhook secrets and autopay.'),
        ),
        migrations.RunPython(keep_seed_checksums, migrations.RunPython.noop),
    ]
