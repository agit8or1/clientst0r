"""Default access groups, created once and empty (grant nothing until an
administrator adds members). Scope: all customers. A group that already
exists - by seed key or by name - is never touched, and a group deleted
later is not re-created (only this migration seeds them).

Frozen copy of accounts.access_groups.DEFAULT_GROUPS."""
from django.db import migrations

DEFAULT_GROUPS = (
    ('l1_tech', 'L1 Tech', 'tech_l1', 'Level 1 technicians.'),
    ('l2_tech', 'L2 Tech', 'tech_l2', 'Level 2 technicians.'),
    ('l3_tech', 'L3 Tech', 'tech_l3', 'Level 3 technicians.'),
    ('managers', 'Managers', 'service_manager', 'Service managers.'),
    ('sales', 'Sales', 'sales_rep', 'Sales team.'),
    ('sales_managers', 'Sales Managers', 'sales_manager', 'Sales managers.'),
    ('owners', 'Owners', 'org_owner', 'Business owners.'),
    ('administrators', 'Administrators', 'org_admin', 'Administrators of users, roles and settings.'),
    ('billing', 'Billing', 'billing_finance', 'Billing and finance.'),
    ('auditors', 'Auditors', 'auditor', 'Read-only reviewers.'),
)


def forwards(apps, schema_editor):
    from accounts.access_groups import seed_default_groups
    seed_default_groups(apps.get_model('tech_access', 'TechnicianGroup'),
                        apps.get_model('accounts', 'RoleTemplate'), groups=DEFAULT_GROUPS)


def backwards(apps, schema_editor):
    TechnicianGroup = apps.get_model('tech_access', 'TechnicianGroup')
    # Only the untouched, empty default groups go.
    for g in TechnicianGroup.objects.filter(seed_key__in=[k for k, *_ in DEFAULT_GROUPS]):
        if not g.members.exists() and not g.assignments.exists():
            g.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tech_access', '0008_access_groups'),
        ('accounts', '0065_builtin_role_display_names'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
