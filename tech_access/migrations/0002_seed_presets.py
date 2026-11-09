"""Seed the built-in L1/L2/L3 presets. Idempotent: a preset that exists is
left exactly as it is, so re-running migrations never widens anything."""
from django.db import migrations


def seed(apps, schema_editor):
    from tech_access.services import seed_presets
    seed_presets(apps.get_model('tech_access', 'AccessPreset'))


class Migration(migrations.Migration):
    dependencies = [('tech_access', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
