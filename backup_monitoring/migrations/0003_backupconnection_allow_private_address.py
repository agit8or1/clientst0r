from django.db import migrations, models


def keep_existing_working(apps, schema_editor):
    """Connections polled before v3.17.728 made unguarded requests, and an
    on-premises backup server is usually on a private address: keep the
    existing API connections working (LAN only; loopback, link-local and
    metadata addresses are refused from now on either way)."""
    BackupConnection = apps.get_model('backup_monitoring', 'BackupConnection')
    BackupConnection.objects.exclude(base_url='').update(allow_private_address=True)


class Migration(migrations.Migration):

    dependencies = [
        ('backup_monitoring', '0002_msp_wide_nullable_customer'),
    ]

    operations = [
        migrations.AddField(
            model_name='backupconnection',
            name='allow_private_address',
            field=models.BooleanField(
                default=False, verbose_name='Server is on a private network',
                help_text='Allow a private (LAN) address such as 10.x, 172.16-31.x or 192.168.x. '
                          'Only MSP staff who manage every customer can change this; changes are audited.'),
        ),
        migrations.RunPython(keep_existing_working, migrations.RunPython.noop),
    ]
