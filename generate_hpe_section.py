#!/usr/bin/env python3
"""Generate the complete HPE section for seed_vendor_data.py"""

import sys
sys.path.insert(0, '/home/administrator')

from hpe_servers import HPE_SERVERS
from hpe_workstations import HPE_WORKSTATIONS
from hpe_laptops import HPE_LAPTOPS

# Combine all HPE equipment
all_hpe_equipment = HPE_SERVERS + HPE_WORKSTATIONS + HPE_LAPTOPS

print(f"    def seed_hp(self):")
print(f'        """Seed HP/HPE servers, workstations, and laptops - {len(all_hpe_equipment)} models."""')
print("""        vendor, created = Vendor.objects.get_or_create(
            name='HP/HPE',
            defaults={
                'slug': slugify('HP-HPE'),
                'website': 'https://www.hpe.com',
                'support_url': 'https://support.hpe.com',
                'support_phone': '1-800-633-3600',
                'description': 'Leading provider of enterprise servers, workstations, and business PCs',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [""")

# Print all equipment
for i, eq in enumerate(all_hpe_equipment):
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
                    'slug': slugify(f"hp-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    {eq.model_name}")

        return 1
""")
