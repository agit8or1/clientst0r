"""Catch up the migration state with the ``Attachment.entity_type`` choices
added for the vehicles module (v3.17.509).

``choices`` is a Python-level attribute — ``sqlmigrate`` on this migration emits
``-- (no-op)``. It exists only so ``makemigrations --check`` is clean and a fresh
install's recorded state matches the model.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0003_alter_attachment_entity_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attachment',
            name='entity_type',
            field=models.CharField(choices=[('asset', 'Asset'), ('document', 'Document'), ('password', 'Password'), ('contact', 'Contact'), ('vendor', 'Vendor'), ('equipment_model', 'Equipment Model'), ('vehicle', 'Vehicle'), ('damage_report', 'Damage Report'), ('fuel_log', 'Fuel Log'), ('vehicle_receipt', 'Vehicle Receipt')], max_length=50),
        ),
    ]
