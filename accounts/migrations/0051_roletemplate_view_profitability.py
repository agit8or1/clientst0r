"""The `view_profitability` role permission.

Labour cost and margin (profitability reports, margin analytics, effective
rate / realization, contract and project margin) were readable by anyone
holding `reports_view_financial`. They now have their own staff-only flag.

No existing access changes: every role template that holds
`reports_view_financial` gets `view_profitability` too. Customer roles may
hold the flag but it is never effective for a customer user (staff_only in
accounts.permission_registry).

Built-in roles keep their "not customized" state: their seed checksum covers
every permission field, so it is recomputed with the new field for each
built-in role whose checksum still matched what was seeded. The Owner and
Billing / Finance definitions gained the flag (seed version 2); uncustomized
copies already match it after the grant above, so they are marked version 2.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'view_profitability'
SKIP = {'is_system_template', 'is_archived'}
# Built-in definitions that hold the new flag as of seed version 2.
V2_KEYS = {'org_owner', 'billing_finance'}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def grant_from_financial(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.all():
        was_seeded = bool(rt.seed_key and rt.seed_checksum and
                          _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier)
                          == rt.seed_checksum)
        rt.view_profitability = bool(rt.reports_view_financial)
        fields = ['view_profitability']
        if was_seeded:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            fields.append('seed_checksum')
            if rt.seed_key in V2_KEYS and rt.seed_version < 2 and rt.view_profitability:
                rt.seed_version = 2
                fields.append('seed_version')
        rt.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0050_dashboard_global_layout'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='view_profitability',
            field=models.BooleanField(default=False, help_text='MSP staff only: labour cost, margin and profitability (profitability reports, margin analytics, effective rate, contract / project margin). Never shown to customer users.'),
        ),
        migrations.RunPython(grant_from_financial, migrations.RunPython.noop),
    ]
