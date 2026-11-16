"""Pricing permissions (price books, service plans, labor rate cards).

Five new role permissions, off by default:
  pricing_manage_price_books, pricing_manage_service_plans,
  pricing_view_internal_cost_rates, pricing_manage_labor_rate_cards,
  pricing_approve_discounts.

Existing access is preserved, nothing else is granted:
  * existing (non built-in) role templates: the full-access global
    "Owner" / "Full Admin" templates get all five; any template that could
    already see cost rates (resourcing_view_team) gets
    pricing_view_internal_cost_rates.
  * built-in roles keep their "not customized" state (their seed checksum is
    recomputed with the new fields, as accounts 0047 did) and move to the next
    seed version of their definition when they were not customized:
      Owner             -> all five (version 3; 0055 made it 2 for sales tax)
      Billing / Finance -> all five (version 3; 0055 made it 2 for sales tax)
      Sales Manager     -> pricing_approve_discounts (version 2)
    A customized built-in is left alone and listed for review.
"""
import hashlib

from django.db import migrations, models

NEW_KEYS = ('pricing_manage_price_books', 'pricing_manage_service_plans', 'pricing_view_internal_cost_rates',
            'pricing_manage_labor_rate_cards', 'pricing_approve_discounts')
SKIP = {'is_system_template', 'is_archived'}
FULL_ACCESS_NAMES = ('Owner', 'Full Admin')
# Frozen copy of the pricing additions in accounts.role_seeds:
# seed_key -> (seed version they arrive in, permissions).
ADDITIONS = {
    'org_owner': (3, NEW_KEYS),
    'billing_finance': (3, NEW_KEYS),
    'sales_manager': (2, ('pricing_approve_discounts',)),
}


def _checksum(values, rmm_tier=''):
    # Frozen copy of accounts.role_seeds.checksum.
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


def forward(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    RoleReviewItem = apps.get_model('accounts', 'RoleReviewItem')
    names = [f.name for f in RoleTemplate._meta.get_fields()
             if isinstance(f, models.BooleanField) and f.name not in SKIP]
    old_names = [n for n in names if n not in NEW_KEYS]

    # Built-ins: keep the checksum of uncustomized rows valid.
    uncustomized = set()
    for rt in RoleTemplate.objects.exclude(seed_key='').exclude(seed_checksum=''):
        if _checksum({n: getattr(rt, n) for n in old_names}, rt.rmm_tier) == rt.seed_checksum:
            rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
            rt.save(update_fields=['seed_checksum'])
            uncustomized.add(rt.pk)

    # Built-ins: the definition versions that gained pricing permissions.
    for key, (version, additions) in ADDITIONS.items():
        for rt in RoleTemplate.objects.filter(seed_key=key, organization__isnull=True,
                                              seed_version__lt=version):
            if rt.pk in uncustomized:
                for k in additions:
                    setattr(rt, k, True)
                rt.seed_version = version
                rt.seed_checksum = _checksum({n: getattr(rt, n) for n in names}, rt.rmm_tier)
                rt.save()
            else:
                RoleReviewItem.objects.get_or_create(
                    reason='builtin_customized', role_template=rt, status='open',
                    defaults={'source': 'migration', 'detail': (
                        f"'{rt.name}' was customized, so version {version} of the built-in definition (pricing "
                        f"permissions: {', '.join(additions)}) was not applied. Add them by hand if wanted.")})

    # Other templates: preserve what they could already do.
    for rt in RoleTemplate.objects.filter(seed_key=''):
        full = rt.organization_id is None and rt.name in FULL_ACCESS_NAMES
        changed = False
        for k in NEW_KEYS:
            want = full or (k == 'pricing_view_internal_cost_rates' and rt.resourcing_view_team)
            if want and not getattr(rt, k):
                setattr(rt, k, True)
                changed = True
        if changed:
            rt.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0055_roletemplate_manage_tax_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='pricing_approve_discounts',
            field=models.BooleanField(default=False, help_text='Approve customer prices below an item minimum price.'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='pricing_manage_labor_rate_cards',
            field=models.BooleanField(default=False, help_text='Create / edit labor roles, rate cards and billing rules.'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='pricing_manage_price_books',
            field=models.BooleanField(default=False, help_text='Create / edit price books, items, tiers, customer overrides and scheduled changes.'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='pricing_manage_service_plans',
            field=models.BooleanField(default=False, help_text='Create / edit service plans and customer plan subscriptions.'),
        ),
        migrations.AddField(
            model_name='roletemplate',
            name='pricing_view_internal_cost_rates',
            field=models.BooleanField(default=False, help_text='See internal costs, margins and technician cost rates in pricing.'),
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
