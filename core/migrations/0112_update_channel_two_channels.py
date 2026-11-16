"""Settings -> Updates has two channels: Official release ('stable') and
Preview / testing ('preview'). The separate Prerelease channel (v3.17.697 to
v3.17.700) is folded into Preview / testing."""
from django.db import migrations, models


def prerelease_to_preview(apps, schema_editor):
    SystemSetting = apps.get_model('core', 'SystemSetting')
    SystemSetting.objects.filter(update_channel='prerelease').update(update_channel='preview')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0111_scheduledtask_licensing_tasks'),
    ]

    operations = [
        migrations.RunPython(prerelease_to_preview, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='systemsetting',
            name='update_channel',
            field=models.CharField(choices=[('stable', 'Official release: latest signed published release'), ('preview', 'Preview / testing: newest commit on main (unreleased)')], default='stable', max_length=10),
        ),
    ]
