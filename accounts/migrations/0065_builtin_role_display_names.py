"""Plain display names for built-in roles (display only).

  tech_l1          RMM L1 — Help Desk            -> L1 Tech
  tech_l2          RMM L2 — Technician           -> L2 Tech
  tech_l3          RMM L3 — Senior Technician    -> L3 Tech
  service_manager  Service Manager               -> Manager
  sales_rep        Sales Representative          -> Sales
  auditor          Internal Read-Only / Auditor  -> Auditor

A role is renamed only while its name is still the built-in one (an
administrator's rename is kept) and only when no other role uses the new
name (then a review item is opened instead). Permissions, seed version and
checksum are untouched, so nobody's access changes. Reversible.
"""
from django.db import migrations

RENAMES = [
    ('tech_l1', 'RMM L1 — Help Desk', 'L1 Tech'),
    ('tech_l2', 'RMM L2 — Technician', 'L2 Tech'),
    ('tech_l3', 'RMM L3 — Senior Technician', 'L3 Tech'),
    ('service_manager', 'Service Manager', 'Manager'),
    ('sales_rep', 'Sales Representative', 'Sales'),
    ('auditor', 'Internal Read-Only / Auditor', 'Auditor'),
]


def _apply(apps, pairs):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    RoleReviewItem = apps.get_model('accounts', 'RoleReviewItem')
    for key, old, new in pairs:
        row = RoleTemplate.objects.filter(seed_key=key, organization__isnull=True).first()
        if row is None or row.name != old:
            continue
        if RoleTemplate.objects.filter(name=new, organization__isnull=True).exclude(pk=row.pk).exists():
            RoleReviewItem.objects.get_or_create(
                reason='other', role_template=row, status='open',
                defaults={'source': 'migration',
                          'detail': f"The built-in role '{old}' is now called '{new}', but another role already "
                                    'uses that name, so it was not renamed.'})
            continue
        RoleTemplate.objects.filter(pk=row.pk).update(name=new)


def forwards(apps, schema_editor):
    _apply(apps, RENAMES)


def backwards(apps, schema_editor):
    _apply(apps, [(k, new, old) for k, old, new in RENAMES])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0064_roletemplate_events_permissions'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
