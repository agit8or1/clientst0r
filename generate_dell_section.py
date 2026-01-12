#!/usr/bin/env python3
"""Generate the complete Dell section for seed_vendor_data.py"""

# Import the equipment lists
import sys
sys.path.insert(0, '/home/administrator')

from dell_expansion import DELL_EQUIPMENT
from dell_laptops import DELL_LAPTOPS

# Combine all Dell equipment
all_dell_equipment = DELL_EQUIPMENT + DELL_LAPTOPS

print(f"    def seed_dell(self):")
print(f'        """Seed Dell servers, workstations, and laptops - {len(all_dell_equipment)} models."""')
print("""        vendor, created = Vendor.objects.get_or_create(
            name='Dell',
            defaults={
                'slug': slugify('Dell'),
                'website': 'https://www.dell.com',
                'support_url': 'https://www.dell.com/support',
                'support_phone': '1-800-624-9896',
                'description': 'Leading provider of servers, workstations, and enterprise hardware',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [""")

# Print all equipment
for i, eq in enumerate(all_dell_equipment):
    if i > 0:
        print("            ,")
    print("            {")
    for key, value in eq.items():
        if key == 'specifications':
            print(f"                '{key}': {{")
            for spec_key, spec_value in value.items():
                print(f"                    '{spec_key}': '{spec_value}',")
            print("                },")
        else:
            if isinstance(value, str):
                # Escape single quotes in strings
                value = value.replace("'", "\\'")
                print(f"                '{key}': '{value}',")
            elif isinstance(value, bool):
                print(f"                '{key}': {value},")
            elif isinstance(value, (int, float)):
                print(f"                '{key}': {value},")
    print("            }", end='')

print("""
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"dell-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    {eq.model_name}")

        return 1
""")
