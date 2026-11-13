"""Seed the starter contract templates and clauses (sample language that must
be reviewed before use). Idempotent; `manage.py contracts_seed_templates`
re-creates any that were deleted."""
from django.db import migrations


def seed(apps, schema_editor):
    from contracts.starter_templates import seed as do_seed
    do_seed(apps)


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
