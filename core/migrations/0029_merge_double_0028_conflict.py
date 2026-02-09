# Generated manually to resolve double 0028 merge conflict
# Fixes Issue #65: https://github.com/agit8or1/huduglue/issues/65

from django.db import migrations


class Migration(migrations.Migration):
    """
    Merge migration to resolve conflict between two different 0028 merges.

    Some users created their own 0028_merge_20260208_1948 before the
    official 0028_merge_migration_conflict was released. This brings
    both merge paths together.
    """

    dependencies = [
        ('core', '0028_merge_20260208_1948'),
        ('core', '0028_merge_migration_conflict'),
    ]

    operations = [
        # No operations needed - this is just a merge point
    ]
