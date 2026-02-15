# Generated manually to resolve migration conflict
# Fixes Issue #65: https://github.com/agit8or1/clientst0r/issues/65

from django.db import migrations


class Migration(migrations.Migration):
    """
    Merge migration to resolve conflict between different versions of 0026.

    Some users have 0026_alter_snykscan_project_path while others have
    0026_add_global_locations_map_enabled. This merge brings both paths together.
    """

    dependencies = [
        ('core', '0026_add_global_locations_map_enabled'),
        ('core', '0027_add_location_map_and_secure_notes_toggles'),
    ]

    operations = [
        # No operations needed - this is just a merge point
    ]
