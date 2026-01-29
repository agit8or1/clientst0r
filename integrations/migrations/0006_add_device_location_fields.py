# Generated migration for adding device location fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0005_add_rangermsp_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='rmmdevice',
            name='latitude',
            field=models.DecimalField(blank=True, decimal_places=7, help_text='Device latitude for map display', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='rmmdevice',
            name='longitude',
            field=models.DecimalField(blank=True, decimal_places=7, help_text='Device longitude for map display', max_digits=10, null=True),
        ),
        migrations.AddIndex(
            model_name='rmmdevice',
            index=models.Index(fields=['latitude', 'longitude'], name='rmm_devices_lat_lon_idx'),
        ),
    ]
