"""The `act_on_pricing_recommendations` role permission (Pricing Advisor).

Accepting a Pricing Advisor recommendation creates a draft quote or a draft
contract amendment; dismissing one records a reason. Neither changes an
active contract or a price. The flag is MSP staff only (staff_only in
accounts.permission_registry), so a customer role that holds it grants
nothing.

Existing access: every role template that could already read financial
reports AND send invoices (Owner, Billing / Finance and custom roles built
like them) gets the flag. Other roles start without it.

Built-in roles keep their "not customized" state: their seed checksum covers
every permission field, so it is recomputed with the new field for each
built-in role whose checksum still matched what was seeded.

The Owner and Billing / Finance definitions gained the flag (Owner version 7,
after backup monitoring 0059 and health score 0060; Billing / Finance version
5); uncustomized copies already match it after the grant above, so they are
marked with those versions.
"""
import hashlib

from django.db import migrations, models

NEW_KEY = 'act_on_pricing_recommendations'
SKIP = {'is_system_template', 'is_archived'}
# Built-in definitions that carry the flag -> their new version.
SEED_VERSIONS = {'org_owner': 7, 'billing_finance': 5}
SEED_KEYS = set(SEED_VERSIONS)


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def grant(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n != NEW_KEY]
    for rt in RoleTemplate.objects.all():
        was_seeded = bool(rt.seed_key and rt.seed_checksum and
                          _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier)
                          == rt.seed_checksum)
        setattr(rt, NEW_KEY, bool(rt.reports_view_financial and rt.billing_send_invoices))
        fields = [NEW_KEY]
        if was_seeded:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            fields.append('seed_checksum')
            if rt.seed_key in SEED_KEYS and rt.seed_version < SEED_VERSIONS[rt.seed_key] and getattr(rt, NEW_KEY):
                rt.seed_version = SEED_VERSIONS[rt.seed_key]
                fields.append('seed_version')
        rt.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0060_roletemplate_manage_health_score_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='act_on_pricing_recommendations',
            field=models.BooleanField(default=False, help_text='MSP staff only: accept or dismiss Pricing Advisor recommendations. Accepting creates a draft quote or contract amendment; nothing active is changed.'),
        ),
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
