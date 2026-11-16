"""Customer onboarding wizard: the `manage_customer_onboarding` role permission.

New and off for every role except where existing access is preserved:
uncustomized built-in Owner and Organization Administrator rows get it (their
definitions in accounts.role_seeds carry it, seed version bumped, checksum
recomputed); customized built-ins are left alone; custom roles that can already
manage organization settings (they could create clients, and edit quotes and
contract drafts before the wizard existed) get it too. Everything else stays off.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'manage_customer_onboarding'
SKIP = {'is_system_template', 'is_archived'}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


# Provisional seed versions (the coordinator sets final numbers at merge):
# Owner / Organization Administrator definitions carry the new permission.
SEED_VERSIONS = {'org_owner': 5, 'org_admin': 3}


def grant_and_keep_seed_checksums(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.all():
        fields = []
        if rt.seed_key:
            version = SEED_VERSIONS.get(rt.seed_key)
            uncustomized = bool(rt.seed_checksum and _checksum(
                {n: getattr(rt, n) for n in old_names}, rt.rmm_tier) == rt.seed_checksum)
            if version is None or not uncustomized:
                # Other built-ins keep their definition (flag off); customized
                # built-ins are left alone for the roles review.
                if uncustomized:
                    rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
                    fields.append('seed_checksum')
            else:
                setattr(rt, NEW_KEY, True)
                rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
                if rt.seed_version < version:
                    rt.seed_version = version
                    fields.append('seed_version')
                fields += [NEW_KEY, 'seed_checksum']
        elif rt.org_manage_settings and not getattr(rt, NEW_KEY):
            setattr(rt, NEW_KEY, True)  # custom roles that could already manage settings
            fields.append(NEW_KEY)
        if fields:
            rt.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0058_roletemplate_view_profitability'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='manage_customer_onboarding',
            field=models.BooleanField(default=False, help_text='Run the customer onboarding and lifecycle change wizards (MSP staff only). Commercial changes are drafts that still go through approval.'),
        ),
        migrations.RunPython(grant_and_keep_seed_checksums, migrations.RunPython.noop),
    ]
