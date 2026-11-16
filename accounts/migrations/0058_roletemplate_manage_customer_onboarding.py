"""Customer onboarding wizard: the `manage_customer_onboarding` role permission.

New and off for every role except where existing access is preserved: built-in
Owner and Organization Administrator roles, and any role template that can
already manage organization settings (they could create clients, and edit
quotes and contract drafts before the wizard existed), receive it. Everything
else stays off. Built-in roles keep their "not customized" state: the seed
checksum covers every permission field, so it is recomputed with the new field
for each built-in role whose checksum still matched what was seeded.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'manage_customer_onboarding'
SKIP = {'is_system_template', 'is_archived'}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def grant_and_keep_seed_checksums(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.all():
        matched = bool(rt.seed_key and rt.seed_checksum
                       and _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier) == rt.seed_checksum)
        grant = rt.seed_key in ('org_owner', 'org_admin') or (not rt.seed_key and rt.org_manage_settings)
        fields = []
        if grant and not getattr(rt, NEW_KEY):
            setattr(rt, NEW_KEY, True)
            fields.append(NEW_KEY)
        if matched:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            fields.append('seed_checksum')
        if fields:
            rt.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0057_app_connection_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='manage_customer_onboarding',
            field=models.BooleanField(default=False, help_text='Run the customer onboarding and lifecycle change wizards (MSP staff only). Commercial changes are drafts that still go through approval.'),
        ),
        migrations.RunPython(grant_and_keep_seed_checksums, migrations.RunPython.noop),
    ]
