"""v3.17.678: the update check runs every 15 minutes (was hourly), so the
"Update Available" pill shows up soon after a release. Only a task still on
the old hourly default is changed; an interval someone set by hand is kept."""
from django.db import migrations


def forwards(apps, schema_editor):
    ScheduledTask = apps.get_model('core', 'ScheduledTask')
    ScheduledTask.objects.filter(task_type='update_check', interval_minutes=60).update(interval_minutes=15)


def backwards(apps, schema_editor):
    ScheduledTask = apps.get_model('core', 'ScheduledTask')
    ScheduledTask.objects.filter(task_type='update_check', interval_minutes=15).update(interval_minutes=60)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0099_dashboard_role_defaults'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
