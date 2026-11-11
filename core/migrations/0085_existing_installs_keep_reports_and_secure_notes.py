"""Reports & Analytics and Secure Notes keep working on upgrade.

Until this release `reports_enabled` and `secure_notes_enabled` were saved
on Settings → Features but read by nothing, so both modules were reachable
whatever the stored value. They now gate their module (core/feature_gates.py).
An install that had unticked either box, possibly long ago and with no
visible effect, would lose the module on upgrade; this sets both on for
existing rows so the upgrade changes nothing. Fresh installs get the field
default (on) and have no row yet.

Reverse is a no-op: the values before this migration were not enforced.
"""
from django.db import migrations


def keep_on(apps, schema_editor):
    SystemSetting = apps.get_model('core', 'SystemSetting')
    SystemSetting.objects.update(reports_enabled=True, secure_notes_enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0084_remove_unused_psa_surface_switches'),
    ]

    operations = [
        migrations.RunPython(keep_on, migrations.RunPython.noop),
    ]
