"""
Export equipment catalog as Django fixtures for new installations.
"""
from django.core.management.base import BaseCommand
from django.core import serializers
from assets.models import EquipmentVendor, EquipmentCategory, EquipmentModel
import json


class Command(BaseCommand):
    help = 'Export equipment catalog to fixtures'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='fixtures/equipment_catalog.json',
            help='Output fixture file path',
        )

    def handle(self, *args, **options):
        output_file = options['output']

        self.stdout.write('Exporting equipment catalog...')

        # Get all equipment data
        vendors = list(EquipmentVendor.objects.all())
        categories = list(EquipmentCategory.objects.all())
        models = list(EquipmentModel.objects.all())

        all_objects = vendors + categories + models

        self.stdout.write(f'  Vendors: {len(vendors)}')
        self.stdout.write(f'  Categories: {len(categories)}')
        self.stdout.write(f'  Models: {len(models)}')

        # Serialize to JSON
        fixture_data = serializers.serialize('json', all_objects, indent=2)

        # Write to file
        import os
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        with open(output_file, 'w') as f:
            f.write(fixture_data)

        self.stdout.write(self.style.SUCCESS(f'✓ Exported {len(all_objects)} objects to {output_file}'))
