"""Sales tax: the `manage_tax_settings` role permission.

New, staff-only. Lets a role configure sales tax (mode, provider connection,
manual jurisdiction rates, tax categories, customer exemptions) and apply an
audited manual tax override when a tax provider is unreachable.

Built-in roles that were never customized are moved to seed version 2:
Owner (every permission) and Billing / Finance gain the flag; every other
untouched built-in role keeps it off and has its checksum recomputed with the
new field. Customized built-in roles and custom roles are left alone (an
administrator grants the flag in the role editor). No existing access is
removed.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'manage_tax_settings'
SKIP = {'is_system_template', 'is_archived'}
GRANT = {
    # seed_key -> new seed version
    'org_owner': 2,
    'billing_finance': 2,
}
BILLING_DESCRIPTION = (
    'Billing records, invoices, payment status and financial reports; reads commercial '
    'agreements and configures sales tax. No credentials, remote tools or security settings.')


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def forwards(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.exclude(seed_key='').exclude(seed_checksum=''):
        old = _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier)
        if old != rt.seed_checksum:
            continue  # customized: left as the administrator made it
        fields = ['seed_checksum']
        if rt.seed_key in GRANT and rt.seed_version < GRANT[rt.seed_key]:
            setattr(rt, NEW_KEY, True)
            rt.seed_version = GRANT[rt.seed_key]
            fields += [NEW_KEY, 'seed_version']
            if rt.seed_key == 'billing_finance':
                rt.description = BILLING_DESCRIPTION
                fields.append('description')
        rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
        rt.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0050_dashboard_global_layout'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='manage_tax_settings',
            field=models.BooleanField(default=False, help_text='Configure sales tax and apply audited manual tax overrides.'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
