"""Software licensing: the `manage_licensing` role permission.

New, MSP-staff-only and off for every existing role (no existing access
changes). License cost visibility reuses `pricing_view_internal_cost_rates`.
Built-in roles keep their "not customized"
state: their seed checksum is recomputed with the new fields (False) for each
built-in role whose checksum still matched what was seeded. The seed
definitions are then re-applied (Owner moved to version 5, Organization
Administrator to version 2): untouched built-ins pick up the new
permissions, customized ones are left alone and listed for review.
"""
import hashlib

from django.db import migrations, models

NEW_KEYS = ('manage_licensing',)
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


def reseed(apps, schema_editor):
    from accounts.role_seeds import seed_builtin_roles
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    RoleReviewItem = apps.get_model('accounts', 'RoleReviewItem')
    seed_builtin_roles(RoleTemplate, RoleReviewItem=RoleReviewItem, source='migration')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0058_roletemplate_view_profitability'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='manage_licensing',
            field=models.BooleanField(default=False, help_text='Create / edit / delete software license subscriptions and assignments, and run license syncs.'),
        ),
        migrations.RunPython(keep_seed_checksums, migrations.RunPython.noop),
        migrations.RunPython(reseed, migrations.RunPython.noop),
    ]
