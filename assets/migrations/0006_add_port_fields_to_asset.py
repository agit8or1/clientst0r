"""
Add port configuration fields directly to Asset model.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0005_equipmentmodel_asset_equipment_model_vendor_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='port_count',
            field=models.PositiveIntegerField(blank=True, help_text='Number of ports', null=True),
        ),
        migrations.AddField(
            model_name='asset',
            name='ports',
            field=models.JSONField(blank=True, default=list, help_text='Port configuration data'),
        ),
        migrations.AddField(
            model_name='asset',
            name='vlans',
            field=models.JSONField(blank=True, default=list, help_text='VLAN configuration data'),
        ),
    ]
