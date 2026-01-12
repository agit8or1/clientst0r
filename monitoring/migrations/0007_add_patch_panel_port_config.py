"""
Add port configuration field to RackResource for detailed patch panel management.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0006_rackdevice_equipment_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='rackresource',
            name='port_configuration',
            field=models.JSONField(
                default=dict,
                blank=True,
                help_text="Detailed port configuration for patch panels and network equipment"
            ),
        ),
        migrations.AddField(
            model_name='rackresource',
            name='rack_units',
            field=models.PositiveIntegerField(
                default=1,
                help_text="Height in rack units (U)"
            ),
        ),
    ]
