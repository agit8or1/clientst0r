"""
Management command to seed hardware vendor and equipment model data.
Populates the database with major hardware vendors and common equipment models.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from assets.models import Vendor, EquipmentModel


class Command(BaseCommand):
    help = 'Seed hardware vendor and equipment model data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing vendor data before seeding'
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write("Clearing existing vendor data...")
            EquipmentModel.objects.all().delete()
            Vendor.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("✓ Cleared"))

        self.stdout.write("Seeding vendor and equipment data...")

        vendors_created = 0
        equipment_created = 0

        # Seed vendors and their equipment
        vendors_created += self.seed_dell()
        vendors_created += self.seed_hp()
        vendors_created += self.seed_lenovo()
        vendors_created += self.seed_cisco()
        vendors_created += self.seed_cisco_meraki()
        vendors_created += self.seed_ubiquiti()
        vendors_created += self.seed_fortinet()
        vendors_created += self.seed_palo_alto()
        vendors_created += self.seed_sonicwall()
        vendors_created += self.seed_watchguard()
        vendors_created += self.seed_hp_aruba()
        vendors_created += self.seed_juniper()
        vendors_created += self.seed_ruckus()
        vendors_created += self.seed_grandstream()
        vendors_created += self.seed_yealink()
        vendors_created += self.seed_poly()
        vendors_created += self.seed_tp_link()

        equipment_created = EquipmentModel.objects.count()

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Seeding complete: {vendors_created} vendors, {equipment_created} equipment models"
        ))

    def seed_dell(self):
        """Seed Dell servers, workstations, and laptops - 194 models."""
        vendor, created = Vendor.objects.get_or_create(
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

        equipment = [
            {
                'model_name': 'PowerEdge R760',
                'model_number': 'R760',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 16x 2.5" or 8x 3.5" drives',
                    'power': '800W-2400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': '16th Gen 2U rack server for demanding workloads',
            }            ,
            {
                'model_name': 'PowerEdge R760xs',
                'model_number': 'R760xs',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 32x 2.5" drives',
                    'power': '1400W-2400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': '16th Gen 2U rack server with extreme storage density',
            }            ,
            {
                'model_name': 'PowerEdge R760xa',
                'model_number': 'R760xa',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 4x GPU slots',
                    'power': '1400W-2400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': '16th Gen 2U accelerated server for AI/ML workloads',
            }            ,
            {
                'model_name': 'PowerEdge R660',
                'model_number': 'R660',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '800W-1400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '16th Gen 1U rack server for density optimization',
            }            ,
            {
                'model_name': 'PowerEdge R660xs',
                'model_number': 'R660xs',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 20x 2.5" drives',
                    'power': '1100W-1400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '16th Gen 1U high-density storage server',
            }            ,
            {
                'model_name': 'PowerEdge R560',
                'model_number': 'R560',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Single Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 4TB DDR5',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '600W-1100W PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '16th Gen 2U single-socket server for SMB',
            }            ,
            {
                'model_name': 'PowerEdge R460',
                'model_number': 'R460',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon E-2400',
                    'memory': 'Up to 256GB DDR5',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '450W-750W PSU',
                    'network': '2x 1GbE, optional 10GbE',
                },
                'description': '16th Gen 1U entry server for edge deployments',
            }            ,
            {
                'model_name': 'PowerEdge R360',
                'model_number': 'R360',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Single Intel Xeon E-2400',
                    'memory': 'Up to 256GB DDR5',
                    'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
                    'power': '350W-750W PSU',
                    'network': '2x 1GbE, optional 10GbE',
                },
                'description': '16th Gen 1U entry rack server for SMB',
            }            ,
            {
                'model_name': 'PowerEdge R260',
                'model_number': 'R260',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Single Intel Xeon E-2400',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-600W PSU',
                    'network': '2x 1GbE',
                },
                'description': '16th Gen 1U compact server for remote offices',
            }            ,
            {
                'model_name': 'PowerEdge T560',
                'model_number': 'T560',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Single Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 4TB DDR5',
                    'storage': 'Up to 16x 3.5" drives',
                    'power': '600W-1100W PSU',
                    'form_factor': 'Tower',
                },
                'description': '16th Gen tower server with massive storage',
            }            ,
            {
                'model_name': 'PowerEdge T360',
                'model_number': 'T360',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Single Intel Xeon E-2400',
                    'memory': 'Up to 256GB DDR5',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '350W-750W PSU',
                    'form_factor': 'Tower',
                },
                'description': '16th Gen entry tower server for small office',
            }            ,
            {
                'model_name': 'PowerEdge R750',
                'model_number': 'R750',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 16x 2.5" or 8x 3.5" drives',
                    'power': '800W-2400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '15th Gen 2U rack server for virtualization',
            }            ,
            {
                'model_name': 'PowerEdge R750xs',
                'model_number': 'R750xs',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 24x 2.5" drives',
                    'power': '1400W-2400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '15th Gen 2U high-density storage server',
            }            ,
            {
                'model_name': 'PowerEdge R750xa',
                'model_number': 'R750xa',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 3x GPU slots',
                    'power': '1400W-2400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': '15th Gen 2U accelerated server for AI workloads',
            }            ,
            {
                'model_name': 'PowerEdge R650',
                'model_number': 'R650',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '800W-1400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '15th Gen 1U rack server for performance',
            }            ,
            {
                'model_name': 'PowerEdge R650xs',
                'model_number': 'R650xs',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '1100W-1400W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '15th Gen 1U high-density server',
            }            ,
            {
                'model_name': 'PowerEdge R550',
                'model_number': 'R550',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Single Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '600W-1100W PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': '15th Gen 2U single-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R450',
                'model_number': 'R450',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '450W-600W PSU',
                    'network': '2x 1GbE, optional 10GbE',
                },
                'description': '15th Gen 1U compact server for edge',
            }            ,
            {
                'model_name': 'PowerEdge R350',
                'model_number': 'R350',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Single Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
                    'power': '350W-600W PSU',
                    'network': '2x 1GbE',
                },
                'description': '15th Gen 1U entry rack server',
            }            ,
            {
                'model_name': 'PowerEdge R250',
                'model_number': 'R250',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Single Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-450W PSU',
                    'network': '2x 1GbE',
                },
                'description': '15th Gen 1U compact entry server',
            }            ,
            {
                'model_name': 'PowerEdge T550',
                'model_number': 'T550',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 16x 3.5" drives',
                    'power': '800W-1100W PSU',
                    'form_factor': 'Tower',
                },
                'description': '15th Gen tower server with storage expansion',
            }            ,
            {
                'model_name': 'PowerEdge T350',
                'model_number': 'T350',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Single Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '350W-600W PSU',
                    'form_factor': 'Tower',
                },
                'description': '15th Gen entry tower server',
            }            ,
            {
                'model_name': 'PowerEdge T150',
                'model_number': 'T150',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Intel Xeon E-2300 or Pentium/Core',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '300W-450W PSU',
                    'form_factor': 'Tower',
                },
                'description': '15th Gen compact tower server for micro offices',
            }            ,
            {
                'model_name': 'PowerEdge R740',
                'model_number': 'R740',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '750W-1400W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 2U rack server for virtualization',
            }            ,
            {
                'model_name': 'PowerEdge R740xd',
                'model_number': 'R740xd',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
                    'power': '750W-1600W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 2U storage-optimized server',
            }            ,
            {
                'model_name': 'PowerEdge R640',
                'model_number': 'R640',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '495W-750W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 1U rack server for density',
            }            ,
            {
                'model_name': 'PowerEdge R540',
                'model_number': 'R540',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '550W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 2U server for general workloads',
            }            ,
            {
                'model_name': 'PowerEdge R440',
                'model_number': 'R440',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '550W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '14th Gen 1U server for web hosting',
            }            ,
            {
                'model_name': 'PowerEdge R340',
                'model_number': 'R340',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Single Intel Xeon E-2200',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-550W PSU',
                    'network': '2x 1GbE',
                },
                'description': '14th Gen 1U entry server',
            }            ,
            {
                'model_name': 'PowerEdge R240',
                'model_number': 'R240',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Single Intel Xeon E-2200',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '250W-450W PSU',
                    'network': '2x 1GbE',
                },
                'description': '14th Gen 1U compact entry server',
            }            ,
            {
                'model_name': 'PowerEdge R840',
                'model_number': 'R840',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Quad Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 6TB DDR4',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '1100W-2400W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 2U 4-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R940',
                'model_number': 'R940',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Quad Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 12TB DDR4',
                    'storage': 'Up to 24x 2.5" drives',
                    'power': '1100W-2400W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 4U mission-critical server',
            }            ,
            {
                'model_name': 'PowerEdge R940xa',
                'model_number': 'R940xa',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Quad Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 12TB DDR4',
                    'storage': 'Up to 4x GPU slots',
                    'power': '1600W-2400W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '14th Gen 4U accelerated server',
            }            ,
            {
                'model_name': 'PowerEdge T640',
                'model_number': 'T640',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 16x 3.5" drives',
                    'power': '750W-1100W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '14th Gen tower server for SMB',
            }            ,
            {
                'model_name': 'PowerEdge T440',
                'model_number': 'T440',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '14th Gen mid-range tower server',
            }            ,
            {
                'model_name': 'PowerEdge T340',
                'model_number': 'T340',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Single Intel Xeon E-2200',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '365W-495W PSU',
                    'form_factor': 'Tower',
                },
                'description': '14th Gen entry tower server',
            }            ,
            {
                'model_name': 'PowerEdge T140',
                'model_number': 'T140',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Intel Xeon E-2200 or Pentium',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '365W PSU',
                    'form_factor': 'Tower',
                },
                'description': '14th Gen compact tower server',
            }            ,
            {
                'model_name': 'PowerEdge T40',
                'model_number': 'T40',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Intel Xeon E-2200 or Pentium',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 3x 3.5" drives',
                    'power': '300W PSU',
                    'form_factor': 'Tower',
                },
                'description': '14th Gen micro tower server for small offices',
            }            ,
            {
                'model_name': 'PowerEdge R730',
                'model_number': 'R730',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '495W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '13th Gen 2U rack server',
            }            ,
            {
                'model_name': 'PowerEdge R730xd',
                'model_number': 'R730xd',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 26x 2.5" or 12x 3.5" drives',
                    'power': '750W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '13th Gen 2U storage server',
            }            ,
            {
                'model_name': 'PowerEdge R630',
                'model_number': 'R630',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '495W-750W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '13th Gen 1U rack server',
            }            ,
            {
                'model_name': 'PowerEdge R530',
                'model_number': 'R530',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '13th Gen 2U general purpose server',
            }            ,
            {
                'model_name': 'PowerEdge R430',
                'model_number': 'R430',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 384GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '550W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '13th Gen 1U server for web',
            }            ,
            {
                'model_name': 'PowerEdge R330',
                'model_number': 'R330',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Single Intel Xeon E3-1200 v6',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-550W PSU',
                    'network': '2x 1GbE',
                },
                'description': '13th Gen 1U entry server',
            }            ,
            {
                'model_name': 'PowerEdge R230',
                'model_number': 'R230',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Single Intel Xeon E3-1200 v6',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '250W-450W PSU',
                    'network': '2x 1GbE',
                },
                'description': '13th Gen 1U compact server',
            }            ,
            {
                'model_name': 'PowerEdge R830',
                'model_number': 'R830',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Quad Intel Xeon E5-4600 v4',
                    'memory': 'Up to 6TB DDR4',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '750W-1600W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '13th Gen 2U 4-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R930',
                'model_number': 'R930',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Quad Intel Xeon E7-8800/4800 v4',
                    'memory': 'Up to 6TB DDR4',
                    'storage': 'Up to 24x 2.5" drives',
                    'power': '1100W-1600W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '13th Gen 4U mission-critical server',
            }            ,
            {
                'model_name': 'PowerEdge T630',
                'model_number': 'T630',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 18x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '13th Gen tower server for SMB',
            }            ,
            {
                'model_name': 'PowerEdge T430',
                'model_number': 'T430',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 384GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '13th Gen mid-range tower server',
            }            ,
            {
                'model_name': 'PowerEdge T330',
                'model_number': 'T330',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Single Intel Xeon E3-1200 v6',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '365W-495W PSU',
                    'form_factor': 'Tower',
                },
                'description': '13th Gen entry tower server',
            }            ,
            {
                'model_name': 'PowerEdge T130',
                'model_number': 'T130',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '13th Gen',
                    'processor': 'Intel Xeon E3-1200 v6',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '290W-365W PSU',
                    'form_factor': 'Tower',
                },
                'description': '13th Gen compact tower server',
            }            ,
            {
                'model_name': 'PowerEdge R720',
                'model_number': 'R720',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '495W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '12th Gen 2U rack server',
            }            ,
            {
                'model_name': 'PowerEdge R720xd',
                'model_number': 'R720xd',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 26x 2.5" or 12x 3.5" drives',
                    'power': '750W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '12th Gen 2U storage server',
            }            ,
            {
                'model_name': 'PowerEdge R620',
                'model_number': 'R620',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '495W-750W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '12th Gen 1U rack server',
            }            ,
            {
                'model_name': 'PowerEdge R520',
                'model_number': 'R520',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2400 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '12th Gen 2U general purpose server',
            }            ,
            {
                'model_name': 'PowerEdge R420',
                'model_number': 'R420',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2400 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '550W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '12th Gen 1U server',
            }            ,
            {
                'model_name': 'PowerEdge R320',
                'model_number': 'R320',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Single Intel Xeon E5-2400',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-550W PSU',
                    'network': '2x 1GbE',
                },
                'description': '12th Gen 1U entry server',
            }            ,
            {
                'model_name': 'PowerEdge R820',
                'model_number': 'R820',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Quad Intel Xeon E5-4600 v2',
                    'memory': 'Up to 1.5TB DDR3',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '750W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '12th Gen 2U 4-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R920',
                'model_number': 'R920',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Quad Intel Xeon E7-8800/4800 v2',
                    'memory': 'Up to 6TB DDR3',
                    'storage': 'Up to 24x 2.5" drives',
                    'power': '1100W-1600W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '12th Gen 4U mission-critical server',
            }            ,
            {
                'model_name': 'PowerEdge T620',
                'model_number': 'T620',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 16x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '12th Gen tower server for SMB',
            }            ,
            {
                'model_name': 'PowerEdge T420',
                'model_number': 'T420',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Dual Intel Xeon E5-2400 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '495W-750W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '12th Gen mid-range tower server',
            }            ,
            {
                'model_name': 'PowerEdge T320',
                'model_number': 'T320',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Single Intel Xeon E5-2400',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '350W-495W PSU',
                    'form_factor': 'Tower',
                },
                'description': '12th Gen entry tower server',
            }            ,
            {
                'model_name': 'PowerEdge T120',
                'model_number': 'T120',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '12th Gen',
                    'processor': 'Intel Xeon E3-1200 v3',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '290W PSU',
                    'form_factor': 'Tower',
                },
                'description': '12th Gen compact tower server',
            }            ,
            {
                'model_name': 'PowerEdge R710',
                'model_number': 'R710',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Dual Intel Xeon 5600',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 8x 2.5" or 6x 3.5" drives',
                    'power': '570W-870W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '11th Gen 2U rack server',
            }            ,
            {
                'model_name': 'PowerEdge R610',
                'model_number': 'R610',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Dual Intel Xeon 5600',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 6x 2.5" drives',
                    'power': '502W-717W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '11th Gen 1U rack server',
            }            ,
            {
                'model_name': 'PowerEdge R510',
                'model_number': 'R510',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Dual Intel Xeon 5600',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 12x 3.5" drives',
                    'power': '580W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '11th Gen 2U storage server',
            }            ,
            {
                'model_name': 'PowerEdge R410',
                'model_number': 'R410',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Dual Intel Xeon 5600',
                    'memory': 'Up to 128GB DDR3',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '480W-580W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '11th Gen 1U server',
            }            ,
            {
                'model_name': 'PowerEdge R810',
                'model_number': 'R810',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Quad Intel Xeon 7500',
                    'memory': 'Up to 1TB DDR3',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '870W-1100W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '11th Gen 2U 4-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R910',
                'model_number': 'R910',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Quad Intel Xeon 7500',
                    'memory': 'Up to 1TB DDR3',
                    'storage': 'Up to 16x 2.5" drives',
                    'power': '1100W-1570W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': '11th Gen 4U mission-critical server',
            }            ,
            {
                'model_name': 'PowerEdge T610',
                'model_number': 'T610',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Dual Intel Xeon 5600',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 16x 3.5" drives',
                    'power': '570W-870W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': '11th Gen tower server',
            }            ,
            {
                'model_name': 'PowerEdge T410',
                'model_number': 'T410',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Dual Intel Xeon 5600',
                    'memory': 'Up to 128GB DDR3',
                    'storage': 'Up to 6x 3.5" drives',
                    'power': '375W-525W PSU',
                    'form_factor': 'Tower',
                },
                'description': '11th Gen mid-range tower server',
            }            ,
            {
                'model_name': 'PowerEdge T110 II',
                'model_number': 'T110 II',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': '11th Gen',
                    'processor': 'Intel Xeon E3-1200',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '305W PSU',
                    'form_factor': 'Tower',
                },
                'description': '11th Gen entry tower server',
            }            ,
            {
                'model_name': 'PowerEdge MX750c',
                'model_number': 'MX750c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'MX Series',
                    'processor': 'Dual Intel Xeon Scalable 3rd/4th Gen',
                    'memory': 'Up to 4TB DDR4/DDR5',
                    'storage': 'M.2 NVMe or FC boot',
                    'form_factor': 'Modular blade for MX7000 chassis',
                    'network': 'Fabric integrated',
                },
                'description': 'High-density compute sled for MX7000',
            }            ,
            {
                'model_name': 'PowerEdge MX840c',
                'model_number': 'MX840c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'MX Series',
                    'processor': 'Quad Intel Xeon Scalable 3rd/4th Gen',
                    'memory': 'Up to 6TB DDR4/DDR5',
                    'storage': 'M.2 NVMe or FC boot',
                    'form_factor': 'Modular 4-socket blade for MX7000 chassis',
                    'network': 'Fabric integrated',
                },
                'description': 'High-performance 4-socket compute sled',
            }            ,
            {
                'model_name': 'PowerEdge C6420',
                'model_number': 'C6420',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen per node',
                    'memory': 'Up to 3TB DDR4 per node',
                    'storage': '2x 2.5" drives per node',
                    'form_factor': '4-node 2U rack server',
                    'network': 'Dual 10GbE per node',
                },
                'description': 'Ultra-dense 4-node 2U hyperscale server',
            }            ,
            {
                'model_name': 'PowerEdge C6520',
                'model_number': 'C6520',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen per node',
                    'memory': 'Up to 4TB DDR4 per node',
                    'storage': '2x 2.5" drives per node',
                    'form_factor': '4-node 2U rack server',
                    'network': 'Dual 10/25GbE per node',
                },
                'description': 'Ultra-dense 4-node 2U server',
            }            ,
            {
                'model_name': 'PowerEdge C6525',
                'model_number': 'C6525',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual AMD EPYC 7003 per node',
                    'memory': 'Up to 4TB DDR4 per node',
                    'storage': '2x 2.5" drives per node',
                    'form_factor': '4-node 2U rack server',
                    'network': 'Dual 10/25GbE per node',
                },
                'description': 'Ultra-dense 4-node AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge R6515',
                'model_number': 'R6515',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Single AMD EPYC 7002/7003',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '550W-1100W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': '1U single-socket AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge R6525',
                'model_number': 'R6525',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual AMD EPYC 7002/7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'network': '2x 1GbE, optional 10/25GbE',
                },
                'description': '1U dual-socket AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge R7515',
                'model_number': 'R7515',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Single AMD EPYC 7002/7003',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'network': '2x 1GbE, optional 10/25GbE',
                },
                'description': '2U single-socket AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge R7525',
                'model_number': 'R7525',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '14th Gen',
                    'processor': 'Dual AMD EPYC 7002/7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 16x 2.5" or 8x 3.5" drives',
                    'power': '800W-2000W redundant PSU',
                    'network': '2x 1GbE, optional 10/25/100GbE',
                },
                'description': '2U dual-socket AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge XE8545',
                'model_number': 'XE8545',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': 'XE Series',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 10x 2.5" NVMe',
                    'gpu': 'Up to 4x NVIDIA A100/H100 GPUs',
                    'power': '2400W+ redundant PSU',
                    'network': 'Dual 10/25GbE, InfiniBand ready',
                },
                'description': '4U AI/HPC server with 4x GPUs',
            }            ,
            {
                'model_name': 'PowerEdge XE8640',
                'model_number': 'XE8640',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': 'XE Series',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 10x 2.5" NVMe',
                    'gpu': 'Up to 4x NVIDIA A100/H100 GPUs',
                    'power': '2400W+ redundant PSU',
                    'network': 'Dual 10/25GbE, InfiniBand ready',
                },
                'description': '4U AI/HPC server with 4x GPUs',
            }            ,
            {
                'model_name': 'PowerEdge XE7420',
                'model_number': 'XE7420',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'XE Series',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 8x 2.5" NVMe',
                    'gpu': 'Up to 2x NVIDIA A100/A30 GPUs',
                    'power': '1400W-2000W redundant PSU',
                    'network': 'Dual 10/25GbE',
                },
                'description': '2U AI inference server with 2x GPUs',
            }            ,
            {
                'model_name': 'OptiPlex 7090 Tower',
                'model_number': '7090',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete up to RTX 3070',
                },
                'description': 'Premium tower business desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7090 SFF',
                'model_number': '7090 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium SFF business desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7090 MFF',
                'model_number': '7090 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact premium desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7080 Tower',
                'model_number': '7080',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Business tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7080 SFF',
                'model_number': '7080 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Business SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7080 MFF',
                'model_number': '7080 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7070 Tower',
                'model_number': '7070',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Business tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7070 SFF',
                'model_number': '7070 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Business SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7070 Ultra',
                'model_number': '7070 Ultra',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Modular (mounts to monitor)',
                    'graphics': 'Integrated',
                },
                'description': 'Modular all-in-one desktop solution',
            }            ,
            {
                'model_name': 'OptiPlex 7010 Tower',
                'model_number': '7010',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Latest generation premium tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7010 SFF',
                'model_number': '7010 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Latest generation SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7010 MFF',
                'model_number': '7010 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Latest generation ultra-compact desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7000 Tower',
                'model_number': '7000',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': '12th Gen premium tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7000 SFF',
                'model_number': '7000 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': '12th Gen SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7000 MFF',
                'model_number': '7000 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': '12th Gen ultra-compact desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5090 Tower',
                'model_number': '5090',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Mainstream tower business desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5090 SFF',
                'model_number': '5090 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Mainstream SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5090 MFF',
                'model_number': '5090 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Compact mainstream desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5080 Tower',
                'model_number': '5080',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Mainstream tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5080 SFF',
                'model_number': '5080 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Mainstream SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5080 MFF',
                'model_number': '5080 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Compact mainstream desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5070 Tower',
                'model_number': '5070',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Mainstream tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5070 SFF',
                'model_number': '5070 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Mainstream SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5000 Tower',
                'model_number': '5000',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD + HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': '12th Gen mainstream tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5000 SFF',
                'model_number': '5000 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': '12th Gen mainstream SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5000 MFF',
                'model_number': '5000 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': '12th Gen compact desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3090 Tower',
                'model_number': '3090',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential tower business desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3090 SFF',
                'model_number': '3090 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3090 MFF',
                'model_number': '3090 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Compact essential desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3080 Tower',
                'model_number': '3080',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3080 SFF',
                'model_number': '3080 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3080 MFF',
                'model_number': '3080 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Compact essential desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3070 Tower',
                'model_number': '3070',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3070 SFF',
                'model_number': '3070 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3070 MFF',
                'model_number': '3070 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Compact essential desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3000 Tower',
                'model_number': '3000',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': '12th Gen essential tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3000 SFF',
                'model_number': '3000 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': '12th Gen essential SFF desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3000 MFF',
                'model_number': '3000 MFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Micro Form Factor',
                    'graphics': 'Integrated',
                },
                'description': '12th Gen compact desktop',
            }            ,
            {
                'model_name': 'Precision 7960 Tower',
                'model_number': '7960',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon W or Xeon Scalable 4th Gen',
                    'memory': 'Up to 2TB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'Up to 3x NVIDIA RTX 6000/A6000',
                    'form_factor': 'Tower',
                },
                'description': 'Flagship dual-socket workstation',
            }            ,
            {
                'model_name': 'Precision 7920 Tower',
                'model_number': '7920',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'Up to 3x NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Extreme performance workstation',
            }            ,
            {
                'model_name': 'Precision 7910 Tower',
                'model_number': '7910',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 1TB DDR4',
                    'storage': 'Multiple SATA/SAS drives',
                    'graphics': 'Up to 3x NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Dual-socket workstation for CAD/CAE',
            }            ,
            {
                'model_name': 'Precision 5820 Tower',
                'model_number': '5820',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon W or Core X-series',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro/AMD Radeon Pro',
                    'form_factor': 'Tower',
                },
                'description': 'Entry professional workstation',
            }            ,
            {
                'model_name': 'Precision 5810 Tower',
                'model_number': '5810',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon E5-1600/2600 v4',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Multiple SATA drives',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation for CAD',
            }            ,
            {
                'model_name': 'Precision 3660 Tower',
                'model_number': '3660',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th/13th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX A-series up to RTX A5000',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Precision 3650 Tower',
                'model_number': '3650',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX A-series',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Precision 3640 Tower',
                'model_number': '3640',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Precision 3630 Tower',
                'model_number': '3630',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 8th/9th Gen or Xeon E',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Precision 3620 Tower',
                'model_number': '3620',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 6th/7th Gen or Xeon E3',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Multiple SATA drives',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation tower',
            }            ,
            {
                'model_name': 'Precision 3551 Tower',
                'model_number': '3551',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'graphics': 'NVIDIA Quadro up to T2000',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Precision 3540 Tower',
                'model_number': '3540',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Precision 3431 SFF',
                'model_number': '3431',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 9th Gen or Xeon E',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro P series',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Precision 3420 SFF',
                'model_number': '3420',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 6th/7th Gen or Xeon E3',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Entry compact workstation',
            }            ,
            {
                'model_name': 'Precision 7920 Rack',
                'model_number': '7920 Rack',
                'equipment_type': 'workstation',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'Up to 3x NVIDIA Quadro',
                    'form_factor': '2U Rackmount',
                },
                'description': '2U rack-mounted workstation',
            }            ,
            {
                'model_name': 'Precision 7820 Rack',
                'model_number': '7820 Rack',
                'equipment_type': 'workstation',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 1TB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'Up to 2x NVIDIA Quadro',
                    'form_factor': '2U Rackmount',
                },
                'description': '2U rack workstation',
            }            ,
            {
                'model_name': 'Latitude 9440',
                'model_number': '9440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen vPro',
                    'memory': 'Up to 64GB LPDDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD+/QHD+',
                    'battery': 'Up to 20 hours',
                    'weight': '2.8 lbs',
                },
                'description': 'Ultra-premium 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 9430',
                'model_number': '9430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen vPro',
                    'memory': 'Up to 32GB LPDDR5',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD+/QHD+',
                    'battery': 'Up to 18 hours',
                    'weight': '2.8 lbs',
                },
                'description': 'Ultra-premium 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 9420',
                'model_number': '9420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen vPro',
                    'memory': 'Up to 32GB LPDDR4x',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD/QHD',
                    'battery': 'Up to 16 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Premium 14" 2-in-1 business laptop',
            }            ,
            {
                'model_name': 'Latitude 9410',
                'model_number': '9410',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen vPro',
                    'memory': 'Up to 32GB LPDDR3',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD/QHD',
                    'battery': 'Up to 14 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'Premium 14" 2-in-1 laptop',
            }            ,
            {
                'model_name': 'Latitude 9510',
                'model_number': '9510',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen vPro',
                    'memory': 'Up to 32GB LPDDR3',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.0" FHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Premium 15" 2-in-1 laptop',
            }            ,
            {
                'model_name': 'Latitude 7440',
                'model_number': '7440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/QHD',
                    'battery': 'Up to 16 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'Premium 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 7430',
                'model_number': '7430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD/QHD',
                    'battery': 'Up to 14 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Premium 14" ultrabook',
            }            ,
            {
                'model_name': 'Latitude 7420',
                'model_number': '7420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD/QHD',
                    'battery': 'Up to 14 hours',
                    'weight': '3.1 lbs',
                },
                'description': 'Premium 14" laptop',
            }            ,
            {
                'model_name': 'Latitude 7410',
                'model_number': '7410',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD/QHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'Premium 14" laptop',
            }            ,
            {
                'model_name': 'Latitude 7400',
                'model_number': '7400',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Premium 14" 2-in-1 laptop',
            }            ,
            {
                'model_name': 'Latitude 7390',
                'model_number': '7390',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 512GB',
                    'display': '13.3" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '2.9 lbs',
                },
                'description': 'Premium 13" ultrabook',
            }            ,
            {
                'model_name': 'Latitude 5540',
                'model_number': '5540',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.9 lbs',
                },
                'description': 'Mainstream 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5530',
                'model_number': '5530',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'Mainstream 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5520',
                'model_number': '5520',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.9 lbs',
                },
                'description': 'Reliable 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5510',
                'model_number': '5510',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '4.0 lbs',
                },
                'description': 'Reliable 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5500',
                'model_number': '5500',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 512GB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '4.1 lbs',
                },
                'description': 'Reliable 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5490',
                'model_number': '5490',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 512GB',
                    'display': '14" FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '3.6 lbs',
                },
                'description': 'Mainstream 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5440',
                'model_number': '5440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.4 lbs',
                },
                'description': 'Versatile 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5430',
                'model_number': '5430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.4 lbs',
                },
                'description': 'Versatile 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5420',
                'model_number': '5420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 11 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Versatile 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5410',
                'model_number': '5410',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.6 lbs',
                },
                'description': 'Versatile 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 5400',
                'model_number': '5400',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 512GB',
                    'display': '14" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Versatile 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3540',
                'model_number': '3540',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.9 lbs',
                },
                'description': 'Essential 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3530',
                'model_number': '3530',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '4.0 lbs',
                },
                'description': 'Essential 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3520',
                'model_number': '3520',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 7 hours',
                    'weight': '4.0 lbs',
                },
                'description': 'Essential 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3510',
                'model_number': '3510',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'display': '15.6" FHD',
                    'battery': 'Up to 7 hours',
                    'weight': '4.1 lbs',
                },
                'description': 'Essential 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3500',
                'model_number': '3500',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'display': '15.6" FHD',
                    'battery': 'Up to 6 hours',
                    'weight': '4.2 lbs',
                },
                'description': 'Essential 15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3440',
                'model_number': '3440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.3 lbs',
                },
                'description': 'Essential 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3430',
                'model_number': '3430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.4 lbs',
                },
                'description': 'Essential 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3420',
                'model_number': '3420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'display': '14" FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '3.4 lbs',
                },
                'description': 'Essential 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3410',
                'model_number': '3410',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'display': '14" FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Essential 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3400',
                'model_number': '3400',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'display': '14" FHD',
                    'battery': 'Up to 7 hours',
                    'weight': '3.6 lbs',
                },
                'description': 'Essential 14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3340',
                'model_number': '3340',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 512GB',
                    'display': '13.3" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Essential 13" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3320',
                'model_number': '3320',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5 11th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 512GB',
                    'display': '13.3" FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Essential 13" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3310',
                'model_number': '3310',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5 10th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'storage': 'M.2 NVMe SSD or HDD',
                    'display': '13.3" HD/FHD',
                    'battery': 'Up to 8 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'Essential 13" business laptop',
            }            ,
            {
                'model_name': 'Precision 7780',
                'model_number': '7780',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 13th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA RTX A5500/5000 Ada',
                    'weight': '7.0 lbs',
                },
                'description': 'Ultimate 17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 7770',
                'model_number': '7770',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 12th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA RTX A5500/5000',
                    'weight': '6.8 lbs',
                },
                'description': 'Ultimate 17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 7760',
                'model_number': '7760',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 11th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA RTX A5000/A4000',
                    'weight': '7.0 lbs',
                },
                'description': 'High-performance 17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 7750',
                'model_number': '7750',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 10th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA Quadro RTX 5000',
                    'weight': '7.2 lbs',
                },
                'description': 'High-performance 17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 7740',
                'model_number': '7740',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 9th Gen or Xeon E',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA Quadro RTX 5000/3000',
                    'weight': '7.3 lbs',
                },
                'description': 'High-performance 17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 7730',
                'model_number': '7730',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 8th Gen or Xeon E',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA Quadro P5200/P4200',
                    'weight': '7.4 lbs',
                },
                'description': '17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 7720',
                'model_number': '7720',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/Xeon E3 7th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '17.3" FHD/UHD',
                    'graphics': 'NVIDIA Quadro P5000/P4000',
                    'weight': '7.5 lbs',
                },
                'description': '17" mobile workstation',
            }            ,
            {
                'model_name': 'Precision 5680',
                'model_number': '5680',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 13th Gen or Xeon W',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '16" FHD+/UHD+',
                    'graphics': 'NVIDIA RTX A3000/2000 Ada',
                    'weight': '4.5 lbs',
                },
                'description': 'Premium 16" mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5670',
                'model_number': '5670',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 12th Gen or Xeon W',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '16" FHD+/UHD+',
                    'graphics': 'NVIDIA RTX A2000/A1000',
                    'weight': '4.4 lbs',
                },
                'description': 'Premium 16" mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5570',
                'model_number': '5570',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 12th Gen or Xeon W',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '15.6" FHD/UHD+',
                    'graphics': 'NVIDIA RTX A2000/A1000',
                    'weight': '4.1 lbs',
                },
                'description': 'Mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5560',
                'model_number': '5560',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 11th Gen or Xeon W',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '15.6" FHD/UHD+',
                    'graphics': 'NVIDIA RTX A2000/A1000',
                    'weight': '4.3 lbs',
                },
                'description': 'Mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5550',
                'model_number': '5550',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 10th Gen or Xeon W',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '15.6" FHD/UHD+',
                    'graphics': 'NVIDIA Quadro T2000/T1000',
                    'weight': '4.4 lbs',
                },
                'description': 'Mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5540',
                'model_number': '5540',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 9th Gen or Xeon E',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/UHD',
                    'graphics': 'NVIDIA Quadro T2000/T1000',
                    'weight': '4.5 lbs',
                },
                'description': 'Mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5530',
                'model_number': '5530',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 8th Gen or Xeon E',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/UHD',
                    'graphics': 'NVIDIA Quadro P2000',
                    'weight': '4.6 lbs',
                },
                'description': 'Mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 5520',
                'model_number': '5520',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/Xeon E3 7th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD/UHD',
                    'graphics': 'NVIDIA Quadro M2200/M1200',
                    'weight': '4.8 lbs',
                },
                'description': 'Mobile workstation for creators',
            }            ,
            {
                'model_name': 'Precision 3581',
                'model_number': '3581',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA RTX A500/A1000',
                    'weight': '4.0 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'Precision 3571',
                'model_number': '3571',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA RTX A500/A1000',
                    'weight': '4.1 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'Precision 3561',
                'model_number': '3561',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA T600/T500',
                    'weight': '4.2 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'Precision 3551',
                'model_number': '3551',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA Quadro P620/P520',
                    'weight': '4.3 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'Precision 3541',
                'model_number': '3541',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 9th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA Quadro P620',
                    'weight': '4.4 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'Precision 3530',
                'model_number': '3530',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA Quadro P600',
                    'weight': '4.5 lbs',
                },
                'description': 'Entry mobile workstation',
            },
            {
                'model_name': 'PowerEdge R760 (4x 3.5" drives)',
                'model_number': 'R760-4LFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '4x 3.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '16th Gen 2U server - 4 LFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R760 (8x 2.5" drives)',
                'model_number': 'R760-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '8x 2.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '16th Gen 2U server - 8 SFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R760 (16x 2.5" NVMe)',
                'model_number': 'R760-16NVMe',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '16x 2.5" NVMe',
                    'power': '1100W-2400W redundant PSU',
                },
                'description': '16th Gen 2U server - all-NVMe configuration',
            }            ,
            {
                'model_name': 'PowerEdge R760 (24x 2.5" drives)',
                'model_number': 'R760-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                    'power': '1400W-2400W redundant PSU',
                },
                'description': '16th Gen 2U server - 24 drive high-density',
            }            ,
            {
                'model_name': 'PowerEdge R660 (4x 3.5" drives)',
                'model_number': 'R660-4LFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '4x 3.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '16th Gen 1U server - 4 LFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R660 (8x 2.5" drives)',
                'model_number': 'R660-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '8x 2.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '16th Gen 1U server - 8 SFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R660 (10x 2.5" NVMe)',
                'model_number': 'R660-10NVMe',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '10x 2.5" NVMe',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '16th Gen 1U server - all-NVMe configuration',
            }            ,
            {
                'model_name': 'PowerEdge R750 (4x 3.5" drives)',
                'model_number': 'R750-4LFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '4x 3.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '15th Gen 2U server - 4 LFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R750 (8x 2.5" drives)',
                'model_number': 'R750-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '8x 2.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '15th Gen 2U server - 8 SFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R750 (12x 3.5" drives)',
                'model_number': 'R750-12LFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '12x 3.5" SAS/SATA',
                    'power': '1100W-2400W redundant PSU',
                },
                'description': '15th Gen 2U server - 12 LFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R750 (16x 2.5" NVMe)',
                'model_number': 'R750-16NVMe',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '16x 2.5" NVMe',
                    'power': '1100W-2400W redundant PSU',
                },
                'description': '15th Gen 2U server - all-NVMe configuration',
            }            ,
            {
                'model_name': 'PowerEdge R750 (24x 2.5" drives)',
                'model_number': 'R750-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                    'power': '1400W-2400W redundant PSU',
                },
                'description': '15th Gen 2U server - 24 drive high-density',
            }            ,
            {
                'model_name': 'PowerEdge R750xa (4 GPU)',
                'model_number': 'R750xa-4GPU',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '4x 3.5" + 4x GPU slots',
                    'power': '1400W-2400W redundant PSU',
                    'gpu': 'Up to 4x NVIDIA A100',
                },
                'description': '15th Gen 2U GPU server for AI/ML',
            }            ,
            {
                'model_name': 'PowerEdge R750xa (3 GPU + Storage)',
                'model_number': 'R750xa-3GPU',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '8x 2.5" + 3x GPU slots',
                    'power': '1400W-2400W redundant PSU',
                    'gpu': 'Up to 3x NVIDIA A100',
                },
                'description': '15th Gen 2U GPU server with storage',
            }            ,
            {
                'model_name': 'PowerEdge R750xs (32x 2.5" drives)',
                'model_number': 'R750xs-32SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '32x 2.5" SAS/SATA/NVMe',
                    'power': '1400W-2400W redundant PSU',
                },
                'description': '15th Gen 2U extreme storage density',
            }            ,
            {
                'model_name': 'PowerEdge R650 (4x 3.5" drives)',
                'model_number': 'R650-4LFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '4x 3.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '15th Gen 1U server - 4 LFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R650 (8x 2.5" drives)',
                'model_number': 'R650-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '8x 2.5" SAS/SATA',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '15th Gen 1U server - 8 SFF configuration',
            }            ,
            {
                'model_name': 'PowerEdge R650 (10x 2.5" NVMe)',
                'model_number': 'R650-10NVMe',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '10x 2.5" NVMe',
                    'power': '800W-1400W redundant PSU',
                },
                'description': '15th Gen 1U server - all-NVMe',
            }            ,
            {
                'model_name': 'PowerEdge R650xs (24x 2.5" drives)',
                'model_number': 'R650xs-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                    'power': '1100W-1400W redundant PSU',
                },
                'description': '15th Gen 1U high-density storage',
            }            ,
            {
                'model_name': 'PowerEdge R7525 (8x 2.5" drives)',
                'model_number': 'R7525-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '8x 2.5" SAS/SATA',
                },
                'description': '15th Gen 2U AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge R7525 (12x 3.5" drives)',
                'model_number': 'R7525-12LFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '12x 3.5" SAS/SATA',
                },
                'description': '15th Gen 2U AMD EPYC - 12 LFF',
            }            ,
            {
                'model_name': 'PowerEdge R7525 (24x 2.5" drives)',
                'model_number': 'R7525-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                },
                'description': '15th Gen 2U AMD EPYC - 24 drive dense',
            }            ,
            {
                'model_name': 'PowerEdge R6525 (8x 2.5" drives)',
                'model_number': 'R6525-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '8x 2.5" SAS/SATA',
                },
                'description': '15th Gen 1U AMD EPYC server',
            }            ,
            {
                'model_name': 'PowerEdge R6525 (10x 2.5" NVMe)',
                'model_number': 'R6525-10NVMe',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': '10x 2.5" NVMe',
                },
                'description': '15th Gen 1U AMD EPYC all-NVMe',
            }            ,
            {
                'model_name': 'PowerEdge R7625 (8x 2.5" drives)',
                'model_number': 'R7625-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 6TB DDR5',
                    'storage': '8x 2.5" SAS/SATA/NVMe',
                },
                'description': '16th Gen 2U AMD EPYC 9004 server',
            }            ,
            {
                'model_name': 'PowerEdge R7625 (16x 2.5" drives)',
                'model_number': 'R7625-16SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 6TB DDR5',
                    'storage': '16x 2.5" SAS/SATA/NVMe',
                },
                'description': '16th Gen 2U AMD EPYC - 16 drive',
            }            ,
            {
                'model_name': 'PowerEdge R7625 (24x 2.5" drives)',
                'model_number': 'R7625-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 6TB DDR5',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                },
                'description': '16th Gen 2U AMD EPYC - 24 drive dense',
            }            ,
            {
                'model_name': 'PowerEdge R6625 (8x 2.5" drives)',
                'model_number': 'R6625-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 6TB DDR5',
                    'storage': '8x 2.5" SAS/SATA/NVMe',
                },
                'description': '16th Gen 1U AMD EPYC 9004 server',
            }            ,
            {
                'model_name': 'PowerEdge R6625 (10x 2.5" NVMe)',
                'model_number': 'R6625-10NVMe',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': '16th Gen',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 6TB DDR5',
                    'storage': '10x 2.5" NVMe',
                },
                'description': '16th Gen 1U AMD EPYC - all-NVMe',
            }            ,
            {
                'model_name': 'PowerEdge R850 (8x 2.5" drives)',
                'model_number': 'R850-8SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': '4x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 8TB DDR4',
                    'storage': '8x 2.5" SAS/SATA',
                },
                'description': '15th Gen 2U 4-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R850 (16x 2.5" drives)',
                'model_number': 'R850-16SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': '4x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 8TB DDR4',
                    'storage': '16x 2.5" SAS/SATA/NVMe',
                },
                'description': '15th Gen 2U 4-socket - 16 drives',
            }            ,
            {
                'model_name': 'PowerEdge R850 (24x 2.5" drives)',
                'model_number': 'R850-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': '4x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 8TB DDR4',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                },
                'description': '15th Gen 2U 4-socket - 24 drives',
            }            ,
            {
                'model_name': 'PowerEdge R950 (16x 2.5" drives)',
                'model_number': 'R950-16SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': '8x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 16TB DDR4',
                    'storage': '16x 2.5" SAS/SATA/NVMe',
                },
                'description': '15th Gen 4U 8-socket server',
            }            ,
            {
                'model_name': 'PowerEdge R950 (24x 2.5" drives)',
                'model_number': 'R950-24SFF',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': '8x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 16TB DDR4',
                    'storage': '24x 2.5" SAS/SATA/NVMe',
                },
                'description': '15th Gen 4U 8-socket - 24 drives',
            }            ,
            {
                'model_name': 'PowerEdge R950xa (GPU Server)',
                'model_number': 'R950xa',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': '15th Gen',
                    'processor': '8x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 16TB DDR4',
                    'storage': '8x 2.5" + 8x GPU slots',
                    'gpu': 'Up to 8x NVIDIA A100',
                },
                'description': '15th Gen 4U 8-socket GPU server',
            }            ,
            {
                'model_name': 'PowerEdge C6420 (4-node 2U)',
                'model_number': 'C6420',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'nodes': '4x dual-socket nodes in 2U',
                    'processor': 'Dual Intel Xeon Scalable per node',
                    'memory': 'Up to 3TB DDR4 per node',
                    'storage': '2x 2.5" per node',
                },
                'description': '2U 4-node dense compute platform',
            }            ,
            {
                'model_name': 'PowerEdge C6520 (4-node 2U)',
                'model_number': 'C6520',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'nodes': '4x dual-socket nodes in 2U',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen per node',
                    'memory': 'Up to 4TB DDR4 per node',
                },
                'description': '2U 4-node Gen 3 dense compute',
            }            ,
            {
                'model_name': 'PowerEdge C6525 (4-node 2U AMD)',
                'model_number': 'C6525',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'nodes': '4x dual-socket nodes in 2U',
                    'processor': 'Dual AMD EPYC 7003 per node',
                    'memory': 'Up to 4TB DDR4 per node',
                },
                'description': '2U 4-node AMD EPYC dense compute',
            }            ,
            {
                'model_name': 'PowerEdge C6620 (4-node 2U)',
                'model_number': 'C6620',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'nodes': '4x dual-socket nodes in 2U',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen per node',
                    'memory': 'Up to 8TB DDR5 per node',
                },
                'description': '2U 4-node Gen 4 with DDR5',
            }            ,
            {
                'model_name': 'PowerEdge C6615 (2-node 1U AMD)',
                'model_number': 'C6615',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'nodes': '2x single-socket nodes in 1U',
                    'processor': 'AMD EPYC 7003 per node',
                    'memory': 'Up to 2TB DDR4 per node',
                },
                'description': '1U 2-node AMD EPYC dense compute',
            }            ,
            {
                'model_name': 'PowerEdge C6625 (2-node 1U AMD)',
                'model_number': 'C6625',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'nodes': '2x single-socket nodes in 1U',
                    'processor': 'AMD EPYC 9004 per node',
                    'memory': 'Up to 3TB DDR5 per node',
                },
                'description': '1U 2-node AMD EPYC 9004 dense compute',
            }            ,
            {
                'model_name': 'PowerEdge C6680 (8-GPU Server)',
                'model_number': 'C6680',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': '8x 2.5" NVMe',
                    'gpu': 'Up to 8x NVIDIA H100/A100',
                    'power': '8000W',
                },
                'description': '4U 8-GPU server for large-scale AI',
            }            ,
            {
                'model_name': 'PowerEdge MX7000 Chassis',
                'model_number': 'MX7000',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 7,
                'specifications': {
                    'slots': '8x compute sled slots',
                    'networking': 'Modular fabric architecture',
                    'power': '3000W-6000W redundant',
                },
                'description': '7U modular infrastructure chassis',
            }            ,
            {
                'model_name': 'PowerEdge MX740c',
                'model_number': 'MX740c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 2nd/3rd Gen',
                    'memory': 'Up to 2TB DDR4',
                    'form_factor': 'MX7000 single-width sled',
                },
                'description': 'Single-width compute sled for MX7000',
            }            ,
            {
                'model_name': 'PowerEdge MX750c',
                'model_number': 'MX750c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'form_factor': 'MX7000 single-width sled',
                },
                'description': 'High-memory compute sled for MX7000',
            }            ,
            {
                'model_name': 'PowerEdge MX760c',
                'model_number': 'MX760c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'form_factor': 'MX7000 single-width sled',
                },
                'description': 'Latest gen compute sled with DDR5',
            }            ,
            {
                'model_name': 'PowerEdge MX840c',
                'model_number': 'MX840c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'processor': '4x Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 8TB DDR4',
                    'form_factor': 'MX7000 double-width sled',
                },
                'description': 'Double-width 4-socket compute sled',
            }            ,
            {
                'model_name': 'PowerEdge MX860c',
                'model_number': 'MX860c',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'processor': '4x Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 16TB DDR5',
                    'form_factor': 'MX7000 double-width sled',
                },
                'description': 'Double-width 4-socket sled with DDR5',
            }            ,
            {
                'model_name': 'PowerEdge XR11',
                'model_number': 'XR11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'processor': 'Intel Xeon D-1700',
                    'memory': 'Up to 256GB DDR4',
                    'temperature': '-5°C to 55°C',
                },
                'description': '1U rugged edge server',
            }            ,
            {
                'model_name': 'PowerEdge XR12',
                'model_number': 'XR12',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'processor': 'Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'temperature': '-5°C to 55°C',
                },
                'description': '1U short-depth edge server',
            }            ,
            {
                'model_name': 'PowerEdge XR4000',
                'model_number': 'XR4000',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 4TB DDR5',
                    'temperature': '-5°C to 55°C',
                },
                'description': '2U rugged server for extreme edge',
            }            ,
            {
                'model_name': 'Precision 3280 Compact',
                'model_number': '3280-CFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'graphics': 'NVIDIA RTX A2000',
                    'form_factor': 'Compact',
                },
                'description': 'Compact workstation',
            }            ,
            {
                'model_name': 'Precision 3280 SFF',
                'model_number': '3280-SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'graphics': 'NVIDIA RTX A4000',
                    'form_factor': 'SFF',
                },
                'description': 'Small form factor workstation',
            }            ,
            {
                'model_name': 'Precision 3680 Tower',
                'model_number': '3680',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'graphics': 'NVIDIA RTX A5000',
                    'form_factor': 'Tower',
                },
                'description': 'Tower workstation',
            }            ,
            {
                'model_name': 'Precision 5860 Tower',
                'model_number': '5860',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon W-3400',
                    'memory': 'Up to 512GB DDR5',
                    'graphics': 'NVIDIA RTX A6000',
                    'form_factor': 'Tower',
                },
                'description': 'High-end workstation',
            }            ,
            {
                'model_name': 'Precision 7960 Tower',
                'model_number': '7960',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon W-3400',
                    'memory': 'Up to 2TB DDR5 ECC',
                    'graphics': 'Up to 3x NVIDIA RTX 6000 Ada',
                    'form_factor': 'Tower',
                },
                'description': 'Ultimate performance workstation',
            }            ,
            {
                'model_name': 'Precision 7865 Tower',
                'model_number': '7865',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen Threadripper PRO',
                    'memory': 'Up to 512GB DDR5 ECC',
                    'graphics': 'Up to 3x NVIDIA RTX 6000 Ada',
                    'form_factor': 'Tower',
                },
                'description': 'AMD Threadripper PRO workstation',
            }            ,
            {
                'model_name': 'Precision 7920 Tower',
                'model_number': '7920',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 3TB DDR4 ECC',
                    'graphics': 'Up to 3x NVIDIA RTX A6000',
                    'form_factor': 'Tower',
                },
                'description': 'Dual-socket workstation',
            }            ,
            {
                'model_name': 'Precision Rack 7920',
                'model_number': '7920-Rack',
                'equipment_type': 'workstation',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 3TB DDR4 ECC',
                    'graphics': 'Up to 2x NVIDIA RTX A6000',
                },
                'description': '2U rackmount workstation',
            }            ,
            {
                'model_name': 'OptiPlex 3000 Micro',
                'model_number': '3000-Micro',
                'equipment_type': 'desktop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'form_factor': 'Micro (0.7L)',
                },
                'description': 'Ultra-compact desktop',
            }            ,
            {
                'model_name': 'OptiPlex 3000 Tower',
                'model_number': '3000-MT',
                'equipment_type': 'desktop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'form_factor': 'Mini Tower',
                },
                'description': 'Entry tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5000 Micro',
                'model_number': '5000-Micro',
                'equipment_type': 'desktop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'form_factor': 'Micro',
                },
                'description': 'Business micro desktop',
            }            ,
            {
                'model_name': 'OptiPlex 5000 Tower',
                'model_number': '5000-MT',
                'equipment_type': 'desktop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'form_factor': 'Mini Tower',
                },
                'description': 'Business tower desktop',
            }            ,
            {
                'model_name': 'OptiPlex 7000 Micro',
                'model_number': '7000-Micro',
                'equipment_type': 'desktop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'form_factor': 'Micro',
                },
                'description': 'Premium micro desktop with vPro',
            }            ,
            {
                'model_name': 'OptiPlex 7000 Tower',
                'model_number': '7000-MT',
                'equipment_type': 'desktop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 14th Gen vPro',
                    'memory': 'Up to 128GB DDR5',
                    'form_factor': 'Mini Tower',
                },
                'description': 'Premium tower desktop',
            }            ,
            {
                'model_name': 'Latitude 3320',
                'model_number': '3320',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen',
                    'memory': 'Up to 16GB DDR4',
                    'display': '13.3" HD/FHD',
                },
                'description': '13" education/business laptop',
            }            ,
            {
                'model_name': 'Latitude 3330',
                'model_number': '3330',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'display': '13.3" FHD',
                },
                'description': '13" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3420',
                'model_number': '3420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'display': '14" HD/FHD',
                },
                'description': '14" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3440',
                'model_number': '3440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th/14th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'display': '14" FHD/FHD+',
                },
                'description': '14" business laptop latest gen',
            }            ,
            {
                'model_name': 'Latitude 3520',
                'model_number': '3520',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'display': '15.6" HD/FHD',
                },
                'description': '15" business laptop',
            }            ,
            {
                'model_name': 'Latitude 3540',
                'model_number': '3540',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th/14th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'display': '15.6" FHD/FHD+',
                },
                'description': '15" business laptop latest gen',
            }            ,
            {
                'model_name': 'Latitude 5320',
                'model_number': '5320',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen vPro',
                    'memory': 'Up to 32GB DDR4',
                    'display': '13.3" FHD',
                },
                'description': '13" premium business laptop',
            }            ,
            {
                'model_name': 'Latitude 5330',
                'model_number': '5330',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 32GB DDR4',
                    'display': '13.3" FHD',
                },
                'description': '13" premium business laptop Gen 12',
            }            ,
            {
                'model_name': 'Latitude 5340',
                'model_number': '5340',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '13.3" FHD+',
                },
                'description': '13" premium business laptop Gen 13',
            }            ,
            {
                'model_name': 'Latitude 5420',
                'model_number': '5420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen vPro',
                    'memory': 'Up to 64GB DDR4',
                    'display': '14" FHD',
                },
                'description': '14" premium business laptop',
            }            ,
            {
                'model_name': 'Latitude 5430',
                'model_number': '5430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '14" FHD+',
                },
                'description': '14" premium business laptop Gen 12',
            }            ,
            {
                'model_name': 'Latitude 5440',
                'model_number': '5440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th/14th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '14" FHD+',
                },
                'description': '14" premium business laptop Gen 13/14',
            }            ,
            {
                'model_name': 'Latitude 5520',
                'model_number': '5520',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen vPro',
                    'memory': 'Up to 64GB DDR4',
                    'display': '15.6" FHD',
                },
                'description': '15" premium business laptop',
            }            ,
            {
                'model_name': 'Latitude 5530',
                'model_number': '5530',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '15.6" FHD+',
                },
                'description': '15" premium business laptop Gen 12',
            }            ,
            {
                'model_name': 'Latitude 5540',
                'model_number': '5540',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th/14th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '15.6" FHD+',
                },
                'description': '15" premium business laptop Gen 13/14',
            }            ,
            {
                'model_name': 'Latitude 7320',
                'model_number': '7320',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen vPro',
                    'memory': 'Up to 32GB DDR4',
                    'display': '13.3" FHD',
                },
                'description': '13" elite business laptop',
            }            ,
            {
                'model_name': 'Latitude 7330',
                'model_number': '7330',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 32GB DDR5',
                    'display': '13.3" FHD+',
                },
                'description': '13" elite business laptop Gen 12',
            }            ,
            {
                'model_name': 'Latitude 7340',
                'model_number': '7340',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '13.3" FHD+/QHD+',
                },
                'description': '13" elite business laptop Gen 13',
            }            ,
            {
                'model_name': 'Latitude 7420',
                'model_number': '7420',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 11th Gen vPro',
                    'memory': 'Up to 32GB DDR4',
                    'display': '14" FHD/QHD',
                },
                'description': '14" elite business laptop',
            }            ,
            {
                'model_name': 'Latitude 7430',
                'model_number': '7430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 32GB DDR5',
                    'display': '14" FHD+/QHD+',
                },
                'description': '14" elite business laptop Gen 12',
            }            ,
            {
                'model_name': 'Latitude 7440',
                'model_number': '7440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th/14th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'display': '14" FHD+/QHD+',
                },
                'description': '14" elite business laptop Gen 13/14',
            }            ,
            {
                'model_name': 'Latitude 9330',
                'model_number': '9330',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 32GB LPDDR5',
                    'display': '13.3" FHD+/QHD+',
                },
                'description': '13" flagship ultra-premium laptop',
            }            ,
            {
                'model_name': 'Latitude 9430',
                'model_number': '9430',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 12th Gen vPro',
                    'memory': 'Up to 32GB LPDDR5',
                    'display': '14" FHD+/QHD+',
                },
                'description': '14" flagship ultra-premium laptop',
            }            ,
            {
                'model_name': 'Latitude 9440',
                'model_number': '9440',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core 13th Gen vPro',
                    'memory': 'Up to 64GB LPDDR5',
                    'display': '14" FHD+/QHD+',
                },
                'description': '14" flagship ultra-premium Gen 13',
            }            ,
            {
                'model_name': 'Latitude 9450',
                'model_number': '9450',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core Ultra',
                    'memory': 'Up to 64GB LPDDR5X',
                    'display': '14" QHD+ OLED',
                },
                'description': '14" flagship AI PC',
            }            ,
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

    def seed_hp(self):
        """Seed HP/HPE servers, workstations, and laptops - 169 models."""
        vendor, created = Vendor.objects.get_or_create(
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

        equipment = [
            {
                'model_name': 'ProLiant DL380 Gen11',
                'model_number': 'DL380 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen or AMD EPYC 9004',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen11 flagship 2U rack server',
            }            ,
            {
                'model_name': 'ProLiant DL360 Gen11',
                'model_number': 'DL360 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen or AMD EPYC 9004',
                    'memory': 'Up to 4TB DDR5',
                    'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen11 high-density 1U rack server',
            }            ,
            {
                'model_name': 'ProLiant DL385 Gen11',
                'model_number': 'DL385 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 6TB DDR5',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '800W-2000W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen11 AMD EPYC 2U server',
            }            ,
            {
                'model_name': 'ProLiant DL365 Gen11',
                'model_number': 'DL365 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Dual AMD EPYC 9004',
                    'memory': 'Up to 4TB DDR5',
                    'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen11 AMD EPYC 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL345 Gen11',
                'model_number': 'DL345 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Single AMD EPYC 9004',
                    'memory': 'Up to 2TB DDR5',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '500W-1000W redundant PSU',
                    'network': '2x 1GbE, optional 10/25GbE',
                },
                'description': 'Gen11 single-socket AMD EPYC server',
            }            ,
            {
                'model_name': 'ProLiant DL325 Gen11',
                'model_number': 'DL325 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Single AMD EPYC 9004',
                    'memory': 'Up to 2TB DDR5',
                    'storage': 'Up to 8x 2.5" drives',
                    'power': '500W-800W redundant PSU',
                    'network': '2x 1GbE, optional 10GbE',
                },
                'description': 'Gen11 entry AMD EPYC server',
            }            ,
            {
                'model_name': 'ProLiant DL20 Gen11',
                'model_number': 'DL20 Gen11',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Intel Xeon E-2400',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Up to 4x 3.5" or 8x 2.5" drives',
                    'power': '290W-500W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen11 compact edge server',
            }            ,
            {
                'model_name': 'ProLiant ML350 Gen11',
                'model_number': 'ML350 Gen11',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 16x 3.5" or 24x 2.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen11 tower server with massive storage',
            }            ,
            {
                'model_name': 'ProLiant ML110 Gen11',
                'model_number': 'ML110 Gen11',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Single Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 2TB DDR5',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '500W-800W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen11 entry tower server',
            }            ,
            {
                'model_name': 'ProLiant ML30 Gen11',
                'model_number': 'ML30 Gen11',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen11',
                    'processor': 'Intel Xeon E-2400',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-500W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen11 compact tower server',
            }            ,
            {
                'model_name': 'ProLiant DL380 Gen10 Plus',
                'model_number': 'DL380 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen10 Plus',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen10 Plus flagship 2U server',
            }            ,
            {
                'model_name': 'ProLiant DL360 Gen10 Plus',
                'model_number': 'DL360 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10 Plus',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen10 Plus high-density 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL385 Gen10 Plus',
                'model_number': 'DL385 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen10 Plus',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen10 Plus AMD EPYC 2U server',
            }            ,
            {
                'model_name': 'ProLiant DL365 Gen10 Plus',
                'model_number': 'DL365 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10 Plus',
                    'processor': 'Dual AMD EPYC 7003',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
                    'power': '800W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25/100GbE',
                },
                'description': 'Gen10 Plus AMD EPYC 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL325 Gen10 Plus',
                'model_number': 'DL325 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10 Plus',
                    'processor': 'Single AMD EPYC 7003',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 8x 2.5" drives',
                    'power': '500W-800W redundant PSU',
                    'network': '2x 1GbE, optional 10GbE',
                },
                'description': 'Gen10 Plus entry AMD EPYC server',
            }            ,
            {
                'model_name': 'ProLiant DL20 Gen10 Plus',
                'model_number': 'DL20 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10 Plus',
                    'processor': 'Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 4x 3.5" or 8x 2.5" drives',
                    'power': '290W-500W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen10 Plus compact edge server',
            }            ,
            {
                'model_name': 'ProLiant DL380 Gen10',
                'model_number': 'DL380 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '500W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': 'Gen10 flagship 2U rack server',
            }            ,
            {
                'model_name': 'ProLiant DL360 Gen10',
                'model_number': 'DL360 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
                    'power': '500W-800W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': 'Gen10 high-density 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL385 Gen10',
                'model_number': 'DL385 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Dual AMD EPYC 7002',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '500W-1600W redundant PSU',
                    'network': '4x 1GbE, optional 10/25GbE',
                },
                'description': 'Gen10 AMD EPYC 2U server',
            }            ,
            {
                'model_name': 'ProLiant DL325 Gen10',
                'model_number': 'DL325 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Single AMD EPYC 7002',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '500W-800W redundant PSU',
                    'network': '2x 1GbE, optional 10GbE',
                },
                'description': 'Gen10 single-socket AMD EPYC server',
            }            ,
            {
                'model_name': 'ProLiant DL180 Gen10',
                'model_number': 'DL180 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 12x 3.5" or 24x 2.5" drives',
                    'power': '550W-800W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen10 2U storage-optimized server',
            }            ,
            {
                'model_name': 'ProLiant DL160 Gen10',
                'model_number': 'DL160 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
                    'power': '550W-800W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen10 1U entry server',
            }            ,
            {
                'model_name': 'ProLiant DL20 Gen10',
                'model_number': 'DL20 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Intel Xeon E-2200',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '290W-500W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen10 compact edge server',
            }            ,
            {
                'model_name': 'ProLiant ML350 Gen10',
                'model_number': 'ML350 Gen10',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
                    'power': '500W-1600W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen10 flagship tower server',
            }            ,
            {
                'model_name': 'ProLiant ML110 Gen10',
                'model_number': 'ML110 Gen10',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Single Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '350W-550W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen10 entry tower server',
            }            ,
            {
                'model_name': 'ProLiant ML30 Gen10',
                'model_number': 'ML30 Gen10',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen10',
                    'processor': 'Intel Xeon E-2200',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W-500W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen10 compact tower server',
            }            ,
            {
                'model_name': 'ProLiant DL380 Gen9',
                'model_number': 'DL380 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
                    'power': '500W-1400W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': 'Gen9 flagship 2U rack server',
            }            ,
            {
                'model_name': 'ProLiant DL360 Gen9',
                'model_number': 'DL360 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '500W-800W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': 'Gen9 high-density 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL180 Gen9',
                'model_number': 'DL180 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 512GB DDR4',
                    'storage': 'Up to 12x 3.5" drives',
                    'power': '550W-900W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen9 2U storage-optimized server',
            }            ,
            {
                'model_name': 'ProLiant DL160 Gen9',
                'model_number': 'DL160 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 512GB DDR4',
                    'storage': 'Up to 8x 2.5" drives',
                    'power': '550W-800W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen9 1U entry server',
            }            ,
            {
                'model_name': 'ProLiant DL120 Gen9',
                'model_number': 'DL120 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Single Intel Xeon E5-2600 v4',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
                    'power': '550W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen9 1U single-socket server',
            }            ,
            {
                'model_name': 'ProLiant DL80 Gen9',
                'model_number': 'DL80 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Single Intel Xeon E5-2600 v4',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '550W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen9 2U single-socket server',
            }            ,
            {
                'model_name': 'ProLiant DL60 Gen9',
                'model_number': 'DL60 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Single Intel Xeon E5-2600 v4',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '550W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen9 1U entry single-socket server',
            }            ,
            {
                'model_name': 'ProLiant DL20 Gen9',
                'model_number': 'DL20 Gen9',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Intel Xeon E3-1200 v6',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '290W-500W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen9 compact edge server',
            }            ,
            {
                'model_name': 'ProLiant ML350 Gen9',
                'model_number': 'ML350 Gen9',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
                    'power': '500W-1400W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen9 flagship tower server',
            }            ,
            {
                'model_name': 'ProLiant ML150 Gen9',
                'model_number': 'ML150 Gen9',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 768GB DDR4',
                    'storage': 'Up to 12x 3.5" drives',
                    'power': '550W-800W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen9 mid-range tower server',
            }            ,
            {
                'model_name': 'ProLiant ML110 Gen9',
                'model_number': 'ML110 Gen9',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Single Intel Xeon E5-2600 v4',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Up to 8x 3.5" drives',
                    'power': '350W-550W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen9 entry tower server',
            }            ,
            {
                'model_name': 'ProLiant ML30 Gen9',
                'model_number': 'ML30 Gen9',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen9',
                    'processor': 'Intel Xeon E3-1200 v6',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen9 compact tower server',
            }            ,
            {
                'model_name': 'ProLiant DL380p Gen8',
                'model_number': 'DL380p Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 25x 2.5" or 12x 3.5" drives',
                    'power': '460W-1200W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': 'Gen8 flagship 2U rack server',
            }            ,
            {
                'model_name': 'ProLiant DL380e Gen8',
                'model_number': 'DL380e Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2400 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 12x 3.5" drives',
                    'power': '460W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen8 cost-optimized 2U server',
            }            ,
            {
                'model_name': 'ProLiant DL360p Gen8',
                'model_number': 'DL360p Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '460W-750W redundant PSU',
                    'network': '4x 1GbE',
                },
                'description': 'Gen8 high-density 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL360e Gen8',
                'model_number': 'DL360e Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2400 v2',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 8x 2.5" drives',
                    'power': '460W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen8 cost-optimized 1U server',
            }            ,
            {
                'model_name': 'ProLiant DL320e Gen8',
                'model_number': 'DL320e Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Single Intel Xeon E5-2400',
                    'memory': 'Up to 192GB DDR3',
                    'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
                    'power': '350W-550W PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen8 1U single-socket server',
            }            ,
            {
                'model_name': 'ProLiant DL180 Gen8',
                'model_number': 'DL180 Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 12x 3.5" drives',
                    'power': '550W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen8 2U storage server',
            }            ,
            {
                'model_name': 'ProLiant DL160 Gen8',
                'model_number': 'DL160 Gen8',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 8x 2.5" drives',
                    'power': '460W-750W redundant PSU',
                    'network': '2x 1GbE',
                },
                'description': 'Gen8 1U entry server',
            }            ,
            {
                'model_name': 'ProLiant ML350p Gen8',
                'model_number': 'ML350p Gen8',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2600 v2',
                    'memory': 'Up to 768GB DDR3',
                    'storage': 'Up to 16x 3.5" drives',
                    'power': '460W-1200W redundant PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen8 flagship tower server',
            }            ,
            {
                'model_name': 'ProLiant ML350e Gen8',
                'model_number': 'ML350e Gen8',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Dual Intel Xeon E5-2400 v2',
                    'memory': 'Up to 384GB DDR3',
                    'storage': 'Up to 12x 3.5" drives',
                    'power': '460W-750W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen8 cost-optimized tower server',
            }            ,
            {
                'model_name': 'ProLiant ML310e Gen8',
                'model_number': 'ML310e Gen8',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'generation': 'Gen8',
                    'processor': 'Single Intel Xeon E3-1200 v2',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'Up to 4x 3.5" drives',
                    'power': '350W PSU',
                    'form_factor': 'Tower',
                },
                'description': 'Gen8 entry tower server',
            }            ,
            {
                'model_name': 'Apollo 4200 Gen10',
                'model_number': 'Apollo 4200 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 28x 3.5" drives',
                    'power': '800W-1600W redundant PSU',
                    'network': '2x 10GbE',
                },
                'description': 'Apollo high-density storage server',
            }            ,
            {
                'model_name': 'Apollo 4510 Gen10',
                'model_number': 'Apollo 4510 Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 3TB DDR4',
                    'storage': 'Up to 68x 3.5" drives',
                    'power': '1600W-2000W redundant PSU',
                    'network': '2x 10GbE',
                },
                'description': 'Apollo extreme-density storage server',
            }            ,
            {
                'model_name': 'Apollo 6500 Gen10 Plus',
                'model_number': 'Apollo 6500 Gen10 Plus',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'NVMe boot drives',
                    'gpu': 'Up to 8x NVIDIA A100 GPUs',
                    'power': '2000W+ redundant PSU',
                    'network': 'HDR InfiniBand',
                },
                'description': 'Apollo AI/HPC accelerated server',
            }            ,
            {
                'model_name': 'Apollo XL170r Gen10',
                'model_number': 'XL170r Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 4x 2.5" NVMe',
                    'power': 'Shared chassis power',
                    'network': 'FlexibleLOM',
                },
                'description': 'Apollo dense compute node',
            }            ,
            {
                'model_name': 'Apollo XL190r Gen10',
                'model_number': 'XL190r Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 6x 2.5" NVMe',
                    'gpu': 'Up to 2x NVIDIA GPUs',
                    'power': 'Shared chassis power',
                },
                'description': 'Apollo GPU compute node',
            }            ,
            {
                'model_name': 'Apollo XL230k Gen10',
                'model_number': 'XL230k Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Quad Intel Xeon Phi 7200',
                    'memory': 'Up to 384GB DDR4',
                    'storage': 'Up to 2x 2.5" NVMe',
                    'power': 'Shared chassis power',
                    'network': 'Omni-Path fabric',
                },
                'description': 'Apollo Xeon Phi compute node',
            }            ,
            {
                'model_name': 'Apollo XL270d Gen10',
                'model_number': 'XL270d Gen10',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'generation': 'Apollo',
                    'processor': 'Dual Intel Xeon Scalable 2nd Gen',
                    'memory': 'Up to 1.5TB DDR4',
                    'storage': 'Up to 16x 2.5" NVMe',
                    'power': 'Shared chassis power',
                    'network': 'FlexibleLOM',
                },
                'description': 'Apollo all-NVMe storage compute node',
            }            ,
            {
                'model_name': 'Z8 G5',
                'model_number': 'Z8 G5',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon W or Xeon Scalable 4th Gen',
                    'memory': 'Up to 2TB DDR5',
                    'storage': 'Up to 12x M.2 NVMe + SATA',
                    'graphics': 'Up to 3x NVIDIA RTX 6000 Ada',
                    'form_factor': 'Tower',
                },
                'description': 'Flagship dual-socket workstation',
            }            ,
            {
                'model_name': 'Z8 G4',
                'model_number': 'Z8 G4',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 2TB DDR4',
                    'storage': 'Up to 10x M.2 NVMe + SATA',
                    'graphics': 'Up to 3x NVIDIA RTX A6000',
                    'form_factor': 'Tower',
                },
                'description': 'Flagship dual-socket workstation',
            }            ,
            {
                'model_name': 'Z6 G5',
                'model_number': 'Z6 G5',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Single Intel Xeon W 3400 or 2400',
                    'memory': 'Up to 512GB DDR5',
                    'storage': 'Up to 8x M.2 NVMe + SATA',
                    'graphics': 'Up to 2x NVIDIA RTX 6000 Ada',
                    'form_factor': 'Tower',
                },
                'description': 'High-performance single-socket workstation',
            }            ,
            {
                'model_name': 'Z6 G4',
                'model_number': 'Z6 G4',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Single Intel Xeon W-3300',
                    'memory': 'Up to 512GB DDR4',
                    'storage': 'Up to 6x M.2 NVMe + SATA',
                    'graphics': 'Up to 2x NVIDIA RTX A6000',
                    'form_factor': 'Tower',
                },
                'description': 'High-performance single-socket workstation',
            }            ,
            {
                'model_name': 'Z4 G5',
                'model_number': 'Z4 G5',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon W-2400 or Core i9 13th Gen',
                    'memory': 'Up to 512GB DDR5',
                    'storage': 'Up to 6x M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX 6000 Ada',
                    'form_factor': 'Tower',
                },
                'description': 'Entry professional workstation',
            }            ,
            {
                'model_name': 'Z4 G4',
                'model_number': 'Z4 G4',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon W-1200/2200 or Core i9 10th Gen',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A6000',
                    'form_factor': 'Tower',
                },
                'description': 'Entry professional workstation',
            }            ,
            {
                'model_name': 'Z2 G9 Tower',
                'model_number': 'Z2 G9 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A5500',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Z2 G9 SFF',
                'model_number': 'Z2 G9 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A4000',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Z2 G8 Tower',
                'model_number': 'Z2 G8 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A5000',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Z2 G8 SFF',
                'model_number': 'Z2 G8 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A4000',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Z2 G5 Tower',
                'model_number': 'Z2 G5 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A5000',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Z2 G5 SFF',
                'model_number': 'Z2 G5 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro/RTX A series',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Z2 G4 Tower',
                'model_number': 'Z2 G4 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen or Xeon E',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro RTX 5000',
                    'form_factor': 'Tower',
                },
                'description': 'Mainstream workstation tower',
            }            ,
            {
                'model_name': 'Z2 G4 SFF',
                'model_number': 'Z2 G4 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen or Xeon E',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro P series',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact workstation SFF',
            }            ,
            {
                'model_name': 'Z1 G9 Tower',
                'model_number': 'Z1 G9 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A2000',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation tower',
            }            ,
            {
                'model_name': 'Z1 G8 Tower',
                'model_number': 'Z1 G8 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 12th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX up to RTX A2000',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation tower',
            }            ,
            {
                'model_name': 'Z1 G6',
                'model_number': 'Z1 G6',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'graphics': 'NVIDIA Quadro P series',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation tower',
            }            ,
            {
                'model_name': 'Z240 Tower',
                'model_number': 'Z240',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 6th/7th Gen or Xeon E3',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 + SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation',
            }            ,
            {
                'model_name': 'Z240 SFF',
                'model_number': 'Z240 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 6th/7th Gen or Xeon E3',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 + SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact entry workstation',
            }            ,
            {
                'model_name': 'Z440',
                'model_number': 'Z440',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon E5-1600 v4',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Multiple SATA + M.2',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Single-socket workstation',
            }            ,
            {
                'model_name': 'Z640',
                'model_number': 'Z640',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 256GB DDR4',
                    'storage': 'Multiple SATA + M.2',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Dual-socket workstation',
            }            ,
            {
                'model_name': 'Z840',
                'model_number': 'Z840',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon E5-2600 v4',
                    'memory': 'Up to 1TB DDR4',
                    'storage': 'Multiple SATA + M.2',
                    'graphics': 'Up to 3x NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'High-end dual-socket workstation',
            }            ,
            {
                'model_name': 'Z230 Tower',
                'model_number': 'Z230',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 4th Gen or Xeon E3 v3',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'Multiple SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation',
            }            ,
            {
                'model_name': 'Z230 SFF',
                'model_number': 'Z230 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 4th Gen or Xeon E3 v3',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact entry workstation',
            }            ,
            {
                'model_name': 'Z220 Tower',
                'model_number': 'Z220',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 3rd Gen or Xeon E3 v2',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'Multiple SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Tower',
                },
                'description': 'Entry workstation',
            }            ,
            {
                'model_name': 'Z220 SFF',
                'model_number': 'Z220 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 3rd Gen or Xeon E3 v2',
                    'memory': 'Up to 32GB DDR3',
                    'storage': 'SATA',
                    'graphics': 'NVIDIA Quadro',
                    'form_factor': 'Small Form Factor',
                },
                'description': 'Compact entry workstation',
            }            ,
            {
                'model_name': 'EliteDesk 800 G9 Tower',
                'model_number': '800 G9 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business tower desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G9 SFF',
                'model_number': '800 G9 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business SFF desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G9 Mini',
                'model_number': '800 G9 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact premium desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G8 Tower',
                'model_number': '800 G8 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business tower desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G8 SFF',
                'model_number': '800 G8 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business SFF desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G8 Mini',
                'model_number': '800 G8 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact premium desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G6 Tower',
                'model_number': '800 G6 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business tower desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G6 SFF',
                'model_number': '800 G6 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business SFF desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G6 Mini',
                'model_number': '800 G6 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact premium desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G5 Tower',
                'model_number': '800 G5 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business tower desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G5 SFF',
                'model_number': '800 G5 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business SFF desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G5 Mini',
                'model_number': '800 G5 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact premium desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G4 Tower',
                'model_number': '800 G4 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business tower desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G4 SFF',
                'model_number': '800 G4 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Premium business SFF desktop',
            }            ,
            {
                'model_name': 'EliteDesk 800 G4 Mini',
                'model_number': '800 G4 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Ultra-compact premium desktop',
            }            ,
            {
                'model_name': 'EliteDesk 705 G5 SFF',
                'model_number': '705 G5 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 PRO 3rd Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'AMD-based premium SFF desktop',
            }            ,
            {
                'model_name': 'EliteDesk 705 G5 Mini',
                'model_number': '705 G5 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 PRO 3rd Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'AMD-based ultra-compact desktop',
            }            ,
            {
                'model_name': 'EliteDesk 705 G4 Tower',
                'model_number': '705 G4 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 PRO 2nd Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'AMD-based business tower',
            }            ,
            {
                'model_name': 'EliteDesk 705 G4 SFF',
                'model_number': '705 G4 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 PRO 2nd Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'AMD-based business SFF',
            }            ,
            {
                'model_name': 'EliteDesk 705 G4 Mini',
                'model_number': '705 G4 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 PRO 2nd Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'AMD-based ultra-compact desktop',
            }            ,
            {
                'model_name': 'ProDesk 600 G6 Tower',
                'model_number': '600 G6 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Mainstream business tower',
            }            ,
            {
                'model_name': 'ProDesk 600 G6 SFF',
                'model_number': '600 G6 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Mainstream business SFF',
            }            ,
            {
                'model_name': 'ProDesk 600 G6 Mini',
                'model_number': '600 G6 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Compact mainstream desktop',
            }            ,
            {
                'model_name': 'ProDesk 600 G5 Tower',
                'model_number': '600 G5 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Mainstream business tower',
            }            ,
            {
                'model_name': 'ProDesk 600 G5 SFF',
                'model_number': '600 G5 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Mainstream business SFF',
            }            ,
            {
                'model_name': 'ProDesk 600 G5 Mini',
                'model_number': '600 G5 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Compact mainstream desktop',
            }            ,
            {
                'model_name': 'ProDesk 600 G4 Tower',
                'model_number': '600 G4 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete',
                },
                'description': 'Mainstream business tower',
            }            ,
            {
                'model_name': 'ProDesk 600 G4 SFF',
                'model_number': '600 G4 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Mainstream business SFF',
            }            ,
            {
                'model_name': 'ProDesk 600 G4 Mini',
                'model_number': '600 G4 Mini',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Mini Desktop',
                    'graphics': 'Integrated',
                },
                'description': 'Compact mainstream desktop',
            }            ,
            {
                'model_name': 'ProDesk 400 G7 Tower',
                'model_number': '400 G7 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business tower',
            }            ,
            {
                'model_name': 'ProDesk 400 G7 SFF',
                'model_number': '400 G7 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business SFF',
            }            ,
            {
                'model_name': 'ProDesk 400 G6 Tower',
                'model_number': '400 G6 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business tower',
            }            ,
            {
                'model_name': 'ProDesk 400 G6 SFF',
                'model_number': '400 G6 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 9th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business SFF',
            }            ,
            {
                'model_name': 'ProDesk 400 G5 Tower',
                'model_number': '400 G5 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business tower',
            }            ,
            {
                'model_name': 'ProDesk 400 G5 SFF',
                'model_number': '400 G5 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business SFF',
            }            ,
            {
                'model_name': 'ProDesk 400 G4 Tower',
                'model_number': '400 G4 Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 7th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business tower',
            }            ,
            {
                'model_name': 'ProDesk 400 G4 SFF',
                'model_number': '400 G4 SFF',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 7th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'SATA',
                    'form_factor': 'Small Form Factor',
                    'graphics': 'Integrated',
                },
                'description': 'Essential business SFF',
            }            ,
            {
                'model_name': 'EliteBook 840 G10',
                'model_number': '840 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/WUXGA',
                    'battery': 'Up to 16 hours',
                    'weight': '2.95 lbs',
                },
                'description': 'Premium 14" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 840 G9',
                'model_number': '840 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/WUXGA',
                    'battery': 'Up to 15 hours',
                    'weight': '2.95 lbs',
                },
                'description': 'Premium 14" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 840 G8',
                'model_number': '840 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen vPro',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/UHD',
                    'battery': 'Up to 14 hours',
                    'weight': '2.98 lbs',
                },
                'description': 'Premium 14" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 840 G7',
                'model_number': '840 G7',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen vPro',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD',
                    'battery': 'Up to 13 hours',
                    'weight': '2.98 lbs',
                },
                'description': 'Premium 14" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 840 G6',
                'model_number': '840 G6',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Premium 14" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 850 G10',
                'model_number': '850 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/UHD',
                    'battery': 'Up to 14 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Premium 15" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 850 G9',
                'model_number': '850 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/UHD',
                    'battery': 'Up to 13 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Premium 15" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 850 G8',
                'model_number': '850 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen vPro',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/UHD',
                    'battery': 'Up to 12 hours',
                    'weight': '3.5 lbs',
                },
                'description': 'Premium 15" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 850 G7',
                'model_number': '850 G7',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen vPro',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 11 hours',
                    'weight': '3.6 lbs',
                },
                'description': 'Premium 15" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 830 G10',
                'model_number': '830 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '13.3" FHD/WUXGA',
                    'battery': 'Up to 17 hours',
                    'weight': '2.75 lbs',
                },
                'description': 'Premium 13" ultrabook',
            }            ,
            {
                'model_name': 'EliteBook 830 G9',
                'model_number': '830 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '13.3" FHD/WUXGA',
                    'battery': 'Up to 16 hours',
                    'weight': '2.7 lbs',
                },
                'description': 'Premium 13" ultrabook',
            }            ,
            {
                'model_name': 'EliteBook 830 G8',
                'model_number': '830 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen vPro',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '13.3" FHD',
                    'battery': 'Up to 15 hours',
                    'weight': '2.7 lbs',
                },
                'description': 'Premium 13" ultrabook',
            }            ,
            {
                'model_name': 'EliteBook 860 G10',
                'model_number': '860 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '16" WUXGA',
                    'battery': 'Up to 14 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'Premium 16" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 860 G9',
                'model_number': '860 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '16" WUXGA',
                    'battery': 'Up to 13 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'Premium 16" business laptop',
            }            ,
            {
                'model_name': 'EliteBook 1050 G1',
                'model_number': '1050 G1',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 8th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/UHD',
                    'graphics': 'NVIDIA GeForce GTX 1050',
                    'weight': '4.5 lbs',
                },
                'description': 'Performance business laptop with GPU',
            }            ,
            {
                'model_name': 'EliteBook 1040 G10',
                'model_number': '1040 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/WUXGA touchscreen',
                    'battery': 'Up to 18 hours',
                    'weight': '2.9 lbs',
                },
                'description': 'Ultra-premium convertible laptop',
            }            ,
            {
                'model_name': 'EliteBook 1040 G9',
                'model_number': '1040 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen vPro',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/WUXGA touchscreen',
                    'battery': 'Up to 17 hours',
                    'weight': '2.9 lbs',
                },
                'description': 'Ultra-premium convertible laptop',
            }            ,
            {
                'model_name': 'EliteBook 1040 G8',
                'model_number': '1040 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen vPro',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/UHD touchscreen',
                    'battery': 'Up to 16 hours',
                    'weight': '3.0 lbs',
                },
                'description': 'Ultra-premium convertible laptop',
            }            ,
            {
                'model_name': 'ZBook Studio G10',
                'model_number': 'ZBook Studio G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 13th Gen or Xeon W',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '16" WUXGA/DreamColor',
                    'graphics': 'NVIDIA RTX A1000/A2000',
                    'weight': '4.0 lbs',
                },
                'description': 'Premium mobile workstation for creators',
            }            ,
            {
                'model_name': 'ZBook Studio G9',
                'model_number': 'ZBook Studio G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 12th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '16" WUXGA/DreamColor',
                    'graphics': 'NVIDIA RTX A1000/A2000',
                    'weight': '4.0 lbs',
                },
                'description': 'Premium mobile workstation for creators',
            }            ,
            {
                'model_name': 'ZBook Studio G8',
                'model_number': 'ZBook Studio G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD/DreamColor',
                    'graphics': 'NVIDIA RTX A2000/A3000',
                    'weight': '3.8 lbs',
                },
                'description': 'Premium mobile workstation for creators',
            }            ,
            {
                'model_name': 'ZBook Fury G10',
                'model_number': 'ZBook Fury G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 13th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '15.6" or 17.3" FHD/UHD/DreamColor',
                    'graphics': 'NVIDIA RTX A5500/A5000',
                    'weight': '5.5-7.0 lbs',
                },
                'description': 'Ultimate performance mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Fury G9',
                'model_number': 'ZBook Fury G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 12th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '15.6" or 17.3" FHD/UHD/DreamColor',
                    'graphics': 'NVIDIA RTX A5000/A4000',
                    'weight': '5.5-7.0 lbs',
                },
                'description': 'Ultimate performance mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Fury G8',
                'model_number': 'ZBook Fury G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 11th Gen or Xeon W',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '15.6" or 17.3" FHD/UHD/DreamColor',
                    'graphics': 'NVIDIA RTX A5000/A3000',
                    'weight': '5.5-7.0 lbs',
                },
                'description': 'Ultimate performance mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Power G10',
                'model_number': 'ZBook Power G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA RTX A500/A1000',
                    'weight': '4.6 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Power G9',
                'model_number': 'ZBook Power G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA T600/T1200',
                    'weight': '4.6 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Power G8',
                'model_number': 'ZBook Power G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA T600/T1200',
                    'weight': '4.7 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Power G7',
                'model_number': 'ZBook Power G7',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 10th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '15.6" FHD',
                    'graphics': 'NVIDIA Quadro T600/T1000',
                    'weight': '4.8 lbs',
                },
                'description': 'Entry mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Firefly G10',
                'model_number': 'ZBook Firefly G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" or 16" FHD/WUXGA',
                    'graphics': 'Intel Iris Xe or NVIDIA A500',
                    'weight': '3.0-3.8 lbs',
                },
                'description': 'Ultra-mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Firefly G9',
                'model_number': 'ZBook Firefly G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" or 16" FHD/WUXGA',
                    'graphics': 'Intel Iris Xe or NVIDIA T550',
                    'weight': '3.0-3.8 lbs',
                },
                'description': 'Ultra-mobile workstation',
            }            ,
            {
                'model_name': 'ZBook Firefly G8',
                'model_number': 'ZBook Firefly G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" or 15.6" FHD',
                    'graphics': 'Intel Iris Xe or NVIDIA T500',
                    'weight': '3.0-3.8 lbs',
                },
                'description': 'Ultra-mobile workstation',
            }            ,
            {
                'model_name': 'ProBook 450 G10',
                'model_number': '450 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'Mainstream 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 450 G9',
                'model_number': '450 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'Mainstream 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 450 G8',
                'model_number': '450 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.9 lbs',
                },
                'description': 'Mainstream 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 440 G10',
                'model_number': '440 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 11 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'Mainstream 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 440 G9',
                'model_number': '440 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'Mainstream 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 440 G8',
                'model_number': '440 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.3 lbs',
                },
                'description': 'Mainstream 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 640 G10',
                'model_number': '640 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 11 hours',
                    'weight': '3.3 lbs',
                },
                'description': 'Secure 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 640 G9',
                'model_number': '640 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.3 lbs',
                },
                'description': 'Secure 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 640 G8',
                'model_number': '640 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.4 lbs',
                },
                'description': 'Secure 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 650 G10',
                'model_number': '650 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '4.0 lbs',
                },
                'description': 'Secure 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 650 G9',
                'model_number': '650 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 12th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '4.0 lbs',
                },
                'description': 'Secure 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 650 G8',
                'model_number': '650 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 64GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '4.1 lbs',
                },
                'description': 'Secure 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 430 G8',
                'model_number': '430 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 11th Gen',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '13.3" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '2.9 lbs',
                },
                'description': 'Portable 13" business laptop',
            }            ,
            {
                'model_name': 'ProBook 435 G8',
                'model_number': '435 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 5000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '13.3" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '2.9 lbs',
                },
                'description': 'AMD-based 13" business laptop',
            }            ,
            {
                'model_name': 'ProBook 445 G10',
                'model_number': '445 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 7000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 11 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'AMD-based 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 445 G9',
                'model_number': '445 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 6000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.2 lbs',
                },
                'description': 'AMD-based 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 445 G8',
                'model_number': '445 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 5000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.3 lbs',
                },
                'description': 'AMD-based 14" business laptop',
            }            ,
            {
                'model_name': 'ProBook 455 G10',
                'model_number': '455 G10',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 7000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'AMD-based 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 455 G9',
                'model_number': '455 G9',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 6000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.8 lbs',
                },
                'description': 'AMD-based 15" business laptop',
            }            ,
            {
                'model_name': 'ProBook 455 G8',
                'model_number': '455 G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'AMD Ryzen 5/7 5000 series',
                    'memory': 'Up to 32GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '15.6" FHD',
                    'battery': 'Up to 9 hours',
                    'weight': '3.9 lbs',
                },
                'description': 'AMD-based 15" business laptop',
            }
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

    def seed_lenovo(self):
        """Seed Lenovo servers, workstations, and laptops."""
        vendor, created = Vendor.objects.get_or_create(
            name='Lenovo',
            defaults={
                'slug': slugify('Lenovo'),
                'website': 'https://www.lenovo.com',
                'support_url': 'https://support.lenovo.com',
                'support_phone': '1-855-253-6686',
                'description': 'Enterprise servers, workstations, and business computing',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
# === THINKSYSTEM SERVERS (70+ MODELS) ===

    # Mission Critical & Enterprise 4-Socket Servers
    {
        'model_name': 'ThinkSystem SR950',
        'model_number': 'SR950',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 4,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 24TB DDR4',
            'storage': 'Up to 24x 2.5" drives',
            'power': '1600W-2400W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '4U mission-critical 4-socket server'
    },
    {
        'model_name': 'ThinkSystem SR850 V3',
        'model_number': 'SR850-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 12TB DDR5',
            'storage': 'Up to 24x 2.5" drives',
            'power': '1400W-2400W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U enterprise 4-socket server'
    },
    {
        'model_name': 'ThinkSystem SR850 V2',
        'model_number': 'SR850-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 6TB DDR4',
            'storage': 'Up to 24x 2.5" drives',
            'power': '1400W-2400W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U 4-socket server for database workloads'
    },
    {
        'model_name': 'ThinkSystem SR850',
        'model_number': 'SR850',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 1st Gen',
            'memory': 'Up to 6TB DDR4',
            'storage': 'Up to 24x 2.5" drives',
            'power': '1100W-2400W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U scalable 4-socket server'
    },
    {
        'model_name': 'ThinkSystem SR860 V3',
        'model_number': 'SR860-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 16TB DDR5',
            'storage': 'Up to 32x 2.5" NVMe',
            'power': '1600W-2400W redundant PSU',
            'network': '4x 25GbE ports'
        },
        'description': '2U high-density 4-socket NVMe server'
    },
    {
        'model_name': 'ThinkSystem SR860 V2',
        'model_number': 'SR860-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 9TB DDR4',
            'storage': 'Up to 32x 2.5" NVMe',
            'power': '1400W-2400W redundant PSU',
            'network': '4x 10GbE ports'
        },
        'description': '2U 4-socket NVMe storage server'
    },
    {
        'model_name': 'ThinkSystem SR860 V1',
        'model_number': 'SR860-V1',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Up to 4x Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 6TB DDR4',
            'storage': 'Up to 32x 2.5" NVMe',
            'power': '1100W-2400W redundant PSU',
            'network': '4x 10GbE ports'
        },
        'description': '2U 4-socket NVMe server'
    },

    # 2-Socket Intel Scalable Servers - V3 (4th Gen)
    {
        'model_name': 'ThinkSystem SR650 V3',
        'model_number': 'SR650-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 8TB DDR5',
            'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
            'power': '750W-2000W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U enterprise server for virtualization'
    },
    {
        'model_name': 'ThinkSystem SR630 V3',
        'model_number': 'SR630-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 4TB DDR5',
            'storage': 'Up to 10x 2.5" drives',
            'power': '750W-1100W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U dense rack server for cloud'
    },

    # 2-Socket Intel Scalable Servers - V2 (3rd Gen)
    {
        'model_name': 'ThinkSystem SR650 V2',
        'model_number': 'SR650-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
            'power': '750W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U server for general workloads'
    },
    {
        'model_name': 'ThinkSystem SR630 V2',
        'model_number': 'SR630-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 10x 2.5" drives',
            'power': '750W-1100W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U rack server for data centers'
    },

    # 2-Socket Intel Scalable Servers - V1 (1st/2nd Gen)
    {
        'model_name': 'ThinkSystem SR650',
        'model_number': 'SR650',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
            'power': '750W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U versatile rack server'
    },
    {
        'model_name': 'ThinkSystem SR630',
        'model_number': 'SR630',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 10x 2.5" drives',
            'power': '750W-1100W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U general purpose server'
    },
    {
        'model_name': 'ThinkSystem SR550',
        'model_number': 'SR550',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 12x 3.5" drives',
            'power': '750W-1100W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U storage-optimized server'
    },
    {
        'model_name': 'ThinkSystem SR530',
        'model_number': 'SR530',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 1TB DDR4',
            'storage': 'Up to 8x 2.5" drives',
            'power': '550W-750W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U balanced rack server'
    },
    {
        'model_name': 'ThinkSystem SR570',
        'model_number': 'SR570',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 8x 2.5" drives',
            'power': '750W-1100W redundant PSU',
            'network': '4x 1GbE ports',
            'gpu': 'Up to 2x GPU'
        },
        'description': '1U GPU-enabled compute server'
    },
    {
        'model_name': 'ThinkSystem SR590',
        'model_number': 'SR590',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 32x 2.5" NVMe',
            'power': '1100W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U NVMe performance server'
    },

    # AMD EPYC Servers - Dual Socket
    {
        'model_name': 'ThinkSystem SR665 V3',
        'model_number': 'SR665-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual AMD EPYC 4th Gen (9004 series)',
            'memory': 'Up to 6TB DDR5',
            'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
            'power': '1100W-2000W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U AMD EPYC 4th Gen enterprise server'
    },
    {
        'model_name': 'ThinkSystem SR665',
        'model_number': 'SR665',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual AMD EPYC 2nd/3rd Gen (7002/7003)',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 24x 2.5" drives',
            'power': '1100W-2000W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U AMD EPYC dual-socket server'
    },
    {
        'model_name': 'ThinkSystem SR645 V3',
        'model_number': 'SR645-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual AMD EPYC 4th Gen (9004 series)',
            'memory': 'Up to 3TB DDR5',
            'storage': 'Up to 10x 2.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U AMD EPYC 4th Gen performance server'
    },
    {
        'model_name': 'ThinkSystem SR645',
        'model_number': 'SR645',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual AMD EPYC 2nd/3rd Gen (7002/7003)',
            'memory': 'Up to 2TB DDR4',
            'storage': 'Up to 10x 2.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U AMD dual-socket server'
    },
    {
        'model_name': 'ThinkSystem SR625',
        'model_number': 'SR625',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Dual AMD EPYC 2nd Gen (7002)',
            'memory': 'Up to 2TB DDR4',
            'storage': 'Up to 8x 2.5" drives',
            'power': '550W-1100W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U AMD compact dual-socket server'
    },

    # AMD EPYC Servers - Single Socket
    {
        'model_name': 'ThinkSystem SR655 V3',
        'model_number': 'SR655-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Single AMD EPYC 4th Gen (9004 series)',
            'memory': 'Up to 3TB DDR5',
            'storage': 'Up to 24x 2.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U AMD single-socket server'
    },
    {
        'model_name': 'ThinkSystem SR655',
        'model_number': 'SR655',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Single AMD EPYC 2nd/3rd Gen (7002/7003)',
            'memory': 'Up to 2TB DDR4',
            'storage': 'Up to 24x 2.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '2U AMD single-socket server'
    },
    {
        'model_name': 'ThinkSystem SR635 V3',
        'model_number': 'SR635-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single AMD EPYC 4th Gen (9004 series)',
            'memory': 'Up to 1.5TB DDR5',
            'storage': 'Up to 10x 2.5" drives',
            'power': '550W-1100W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U AMD single-socket server'
    },
    {
        'model_name': 'ThinkSystem SR635',
        'model_number': 'SR635',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single AMD EPYC 2nd/3rd Gen (7002/7003)',
            'memory': 'Up to 1TB DDR4',
            'storage': 'Up to 10x 2.5" drives',
            'power': '550W-800W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U AMD single-socket server'
    },
    {
        'model_name': 'ThinkSystem SR615',
        'model_number': 'SR615',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single AMD EPYC 2nd Gen (7002)',
            'memory': 'Up to 1TB DDR4',
            'storage': 'Up to 8x 2.5" drives',
            'power': '450W-550W redundant PSU',
            'network': '4x 1GbE ports'
        },
        'description': '1U AMD entry server'
    },

    # Entry Intel Xeon E Servers
    {
        'model_name': 'ThinkSystem SR250 V3',
        'model_number': 'SR250-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single Intel Xeon E-2400',
            'memory': 'Up to 128GB DDR5 ECC',
            'storage': 'Up to 8x 2.5" drives',
            'power': '350W-550W PSU',
            'network': '2x 1GbE ports'
        },
        'description': '1U entry server for SMB'
    },
    {
        'model_name': 'ThinkSystem SR250 V2',
        'model_number': 'SR250-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single Intel Xeon E-2300',
            'memory': 'Up to 128GB DDR4 ECC',
            'storage': 'Up to 8x 2.5" drives',
            'power': '300W-450W PSU',
            'network': '2x 1GbE ports'
        },
        'description': '1U affordable rack server'
    },
    {
        'model_name': 'ThinkSystem SR250',
        'model_number': 'SR250',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single Intel Xeon E-2100/2200',
            'memory': 'Up to 64GB DDR4 ECC',
            'storage': 'Up to 8x 2.5" drives',
            'power': '250W-450W PSU',
            'network': '2x 1GbE ports'
        },
        'description': '1U compact entry server'
    },
    {
        'model_name': 'ThinkSystem SR150',
        'model_number': 'SR150',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single Intel Xeon E-2100/2200',
            'memory': 'Up to 64GB DDR4 ECC',
            'storage': 'Up to 4x 3.5" drives',
            'power': '300W PSU',
            'network': '2x 1GbE ports'
        },
        'description': '1U small business server'
    },
    {
        'model_name': 'ThinkSystem SR158',
        'model_number': 'SR158',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'processor': 'Single Intel Xeon E-2100/2200',
            'memory': 'Up to 64GB DDR4 ECC',
            'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
            'power': '350W PSU',
            'network': '2x 1GbE ports'
        },
        'description': '1U versatile entry server'
    },

    # Tower Servers - Dual Socket
    {
        'model_name': 'ThinkSystem ST650 V3',
        'model_number': 'ST650-V3',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 8TB DDR5',
            'storage': 'Up to 16x 3.5" drives',
            'power': '1100W-1600W redundant PSU',
            'form_factor': 'Tower',
            'network': '4x 1GbE ports'
        },
        'description': 'Dual-socket tower server for offices'
    },
    {
        'model_name': 'ThinkSystem ST650 V2',
        'model_number': 'ST650-V2',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 14x 3.5" drives',
            'power': '750W-1100W redundant PSU',
            'form_factor': 'Tower',
            'network': '4x 1GbE ports'
        },
        'description': 'Tower server for office environments'
    },
    {
        'model_name': 'ThinkSystem ST550',
        'model_number': 'ST550',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 1st/2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 16x 3.5" drives',
            'power': '750W-1100W redundant PSU',
            'form_factor': 'Tower',
            'network': '4x 1GbE ports'
        },
        'description': 'Versatile dual-socket tower server'
    },

    # Tower Servers - Single Socket
    {
        'model_name': 'ThinkSystem ST250 V3',
        'model_number': 'ST250-V3',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Single Intel Xeon E-2400',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Up to 8x 3.5" drives',
            'power': '350W-550W PSU',
            'form_factor': 'Tower',
            'network': '2x 1GbE ports'
        },
        'description': 'Entry tower server'
    },
    {
        'model_name': 'ThinkSystem ST250 V2',
        'model_number': 'ST250-V2',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Single Intel Xeon E-2300',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Up to 8x 3.5" drives',
            'power': '300W-550W PSU',
            'form_factor': 'Tower',
            'network': '2x 1GbE ports'
        },
        'description': 'Entry tower server for small business'
    },
    {
        'model_name': 'ThinkSystem ST250',
        'model_number': 'ST250',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Single Intel Xeon E-2100/2200',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 8x 3.5" drives',
            'power': '250W-400W PSU',
            'form_factor': 'Tower',
            'network': '2x 1GbE ports'
        },
        'description': 'Compact tower server for SMB'
    },
    {
        'model_name': 'ThinkSystem ST50',
        'model_number': 'ST50',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon E-2100/2200 or Core i3',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4x 3.5" drives',
            'power': '250W PSU',
            'form_factor': 'Tower',
            'network': '2x 1GbE ports'
        },
        'description': 'Micro tower server for small offices'
    },

    # Dense & Liquid-Cooled Servers
    {
        'model_name': 'ThinkSystem SD650 V3',
        'model_number': 'SD650-V3',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 4th Gen per node',
            'memory': 'Up to 4TB DDR5 per node',
            'storage': 'Up to 8x 2.5" drives per node',
            'power': 'Shared PSU in chassis',
            'network': '2x 25GbE per node',
            'density': '2 nodes per 2U',
            'cooling': 'Direct liquid cooling'
        },
        'description': 'Dense liquid-cooled server node'
    },
    {
        'model_name': 'ThinkSystem SD650 V2',
        'model_number': 'SD650-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 3rd Gen per node',
            'memory': 'Up to 4TB DDR4 per node',
            'storage': 'Up to 8x 2.5" drives per node',
            'power': 'Shared PSU in chassis',
            'network': '2x 10GbE per node',
            'density': '2 nodes per 2U',
            'cooling': 'Direct liquid cooling'
        },
        'description': 'High-density liquid-cooled server'
    },
    {
        'model_name': 'ThinkSystem SD530',
        'model_number': 'SD530',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable per node',
            'memory': 'Up to 3TB DDR4 per node',
            'storage': 'Up to 6x 2.5" drives per node',
            'power': 'Shared PSU in chassis',
            'network': '2x 10GbE per node',
            'density': '2 nodes per 2U'
        },
        'description': 'Dense compute server node'
    },
    {
        'model_name': 'ThinkSystem SD650-N V2',
        'model_number': 'SD650-N-V2',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 3rd Gen per node',
            'memory': 'Up to 2TB DDR4 per node',
            'storage': 'Internal NVMe',
            'power': 'Shared PSU in chassis',
            'network': '2x 25GbE per node',
            'density': '4 nodes per 2U',
            'cooling': 'Direct liquid cooling'
        },
        'description': 'Ultra-dense liquid-cooled compute node'
    },

    # === THINKSTATION WORKSTATIONS (50+ MODELS) ===

    # ThinkStation P8/P7/P5 - Ultra High-End
    {
        'model_name': 'ThinkStation P8',
        'model_number': 'P8',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon W-3400 (Sapphire Rapids)',
            'memory': 'Up to 2TB DDR5 ECC',
            'storage': 'Multiple M.2 NVMe + U.2 NVMe + SATA',
            'graphics': 'Up to 4x NVIDIA RTX 6000 Ada (48GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 2000W',
            'expansion': '7x PCIe slots'
        },
        'description': 'Ultimate dual-socket workstation for AI/VFX'
    },
    {
        'model_name': 'ThinkStation P7',
        'model_number': 'P7',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon W-2400/W-3400',
            'memory': 'Up to 2TB DDR5 ECC',
            'storage': 'Multiple M.2 NVMe + U.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA RTX A6000 (48GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 1850W',
            'expansion': '7x PCIe slots'
        },
        'description': 'Dual-socket professional workstation'
    },
    {
        'model_name': 'ThinkStation P5',
        'model_number': 'P5',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon W-3300/W-2400',
            'memory': 'Up to 512GB DDR4 ECC',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA RTX A series',
            'form_factor': 'Tower',
            'psu': 'Up to 1400W',
            'expansion': '7x PCIe slots'
        },
        'description': 'High-performance single-socket workstation'
    },

    # ThinkStation P3 Series
    {
        'model_name': 'ThinkStation P3 Ultra',
        'model_number': 'P3-Ultra',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 13th Gen or Xeon W-1300',
            'memory': 'Up to 64GB DDR5',
            'storage': 'Up to 2x M.2 NVMe SSD',
            'graphics': 'NVIDIA RTX A2000/A5000 (24GB)',
            'form_factor': 'Ultra-compact (3.9L)',
            'psu': 'Up to 300W external',
            'weight': '13 lbs'
        },
        'description': 'Ultra-compact ISV-certified workstation'
    },
    {
        'model_name': 'ThinkStation P3 Tower',
        'model_number': 'P3-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon W-1300',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA RTX A5500 (24GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 500W',
            'expansion': '4x PCIe slots'
        },
        'description': 'Entry professional tower workstation'
    },

    # ThinkStation P360 Series
    {
        'model_name': 'ThinkStation P360 Ultra',
        'model_number': 'P360-Ultra',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen or Xeon W-1300',
            'memory': 'Up to 64GB DDR5',
            'storage': 'Up to 2x M.2 NVMe SSD',
            'graphics': 'Up to NVIDIA RTX A5000 (24GB)',
            'form_factor': 'Ultra-compact (3L)',
            'psu': 'Up to 300W external'
        },
        'description': 'Compact ISV-certified workstation'
    },
    {
        'model_name': 'ThinkStation P360 Tower',
        'model_number': 'P360-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen or Xeon W-1300',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA RTX A5000',
            'form_factor': 'Tower',
            'psu': 'Up to 500W',
            'expansion': '4x PCIe slots'
        },
        'description': 'Mid-range tower workstation'
    },
    {
        'model_name': 'ThinkStation P360 SFF',
        'model_number': 'P360-SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen',
            'memory': 'Up to 64GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA RTX A2000',
            'form_factor': 'Small Form Factor',
            'psu': 'Up to 260W'
        },
        'description': 'Space-saving workstation'
    },

    # ThinkStation P350 Series
    {
        'model_name': 'ThinkStation P350 Tower',
        'model_number': 'P350-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon W-1200',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA RTX A4000',
            'form_factor': 'Tower',
            'psu': 'Up to 500W'
        },
        'description': 'Entry-level tower workstation'
    },
    {
        'model_name': 'ThinkStation P350 SFF',
        'model_number': 'P350-SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P1000',
            'form_factor': 'Small Form Factor',
            'psu': 'Up to 260W'
        },
        'description': 'Compact professional workstation'
    },

    # ThinkStation P340 Series
    {
        'model_name': 'ThinkStation P340 Tower',
        'model_number': 'P340-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen or Xeon W-1200',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro RTX 4000',
            'form_factor': 'Tower',
            'psu': 'Up to 500W'
        },
        'description': 'Reliable tower workstation'
    },
    {
        'model_name': 'ThinkStation P340 SFF',
        'model_number': 'P340-SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P620',
            'form_factor': 'Small Form Factor',
            'psu': 'Up to 260W'
        },
        'description': 'Small form factor workstation'
    },
    {
        'model_name': 'ThinkStation P340 Tiny',
        'model_number': 'P340-Tiny',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'graphics': 'Intel UHD Graphics 630',
            'form_factor': 'Tiny (1L)',
            'psu': '135W adapter'
        },
        'description': 'Ultra-small workstation'
    },

    # ThinkStation P330 Gen2 Series
    {
        'model_name': 'ThinkStation P330 Gen2 Tower',
        'model_number': 'P330-G2-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen or Xeon E-2200',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P2200',
            'form_factor': 'Tower',
            'psu': 'Up to 310W'
        },
        'description': 'Mainstream tower workstation Gen 2'
    },
    {
        'model_name': 'ThinkStation P330 Gen2 SFF',
        'model_number': 'P330-G2-SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P620',
            'form_factor': 'Small Form Factor',
            'psu': '260W'
        },
        'description': 'Compact workstation Gen 2'
    },
    {
        'model_name': 'ThinkStation P330 Gen2 Tiny',
        'model_number': 'P330-G2-Tiny',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 9th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'graphics': 'Intel UHD Graphics 630',
            'form_factor': 'Tiny (1L)',
            'psu': '135W adapter'
        },
        'description': 'Tiny form factor workstation Gen 2'
    },

    # ThinkStation P330 Gen1 Series
    {
        'model_name': 'ThinkStation P330 Tower',
        'model_number': 'P330-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen or Xeon E-2100',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P2000',
            'form_factor': 'Tower',
            'psu': '310W'
        },
        'description': 'Entry workstation tower'
    },
    {
        'model_name': 'ThinkStation P330 SFF',
        'model_number': 'P330-SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P600',
            'form_factor': 'Small Form Factor',
            'psu': '260W'
        },
        'description': 'Small workstation'
    },
    {
        'model_name': 'ThinkStation P330 Tiny',
        'model_number': 'P330-Tiny',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'graphics': 'Intel UHD Graphics 630',
            'form_factor': 'Tiny (1L)',
            'psu': '135W adapter'
        },
        'description': 'Ultra-compact workstation'
    },

    # ThinkStation P320 Series
    {
        'model_name': 'ThinkStation P320 Tower',
        'model_number': 'P320-Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 7th Gen or Xeon E3-1200 v6',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P2000',
            'form_factor': 'Tower',
            'psu': '310W'
        },
        'description': 'Professional tower workstation'
    },
    {
        'model_name': 'ThinkStation P320 SFF',
        'model_number': 'P320-SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 7th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P600',
            'form_factor': 'Small Form Factor',
            'psu': '180W'
        },
        'description': 'Compact professional workstation'
    },
    {
        'model_name': 'ThinkStation P320 Tiny',
        'model_number': 'P320-Tiny',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 7th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'graphics': 'Intel HD Graphics 630',
            'form_factor': 'Tiny (1L)',
            'psu': '135W adapter'
        },
        'description': 'Tiny workstation'
    },

    # ThinkStation P920/P720/P520
    {
        'model_name': 'ThinkStation P920',
        'model_number': 'P920',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable (Bronze/Silver/Gold/Platinum)',
            'memory': 'Up to 1TB DDR4 ECC (12 channels)',
            'storage': 'Multiple M.2 NVMe + U.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA Quadro RTX 8000 (48GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 1400W redundant',
            'expansion': '7x PCIe slots'
        },
        'description': 'Dual-socket extreme workstation'
    },
    {
        'model_name': 'ThinkStation P720',
        'model_number': 'P720',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable (Bronze/Silver/Gold)',
            'memory': 'Up to 512GB DDR4 ECC',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA Quadro RTX 6000 (24GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 1125W',
            'expansion': '6x PCIe slots'
        },
        'description': 'Dual-socket high-performance workstation'
    },
    {
        'model_name': 'ThinkStation P520',
        'model_number': 'P520',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon W-2100/W-2200 series',
            'memory': 'Up to 256GB DDR4 ECC',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro RTX 5000 (16GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 900W',
            'expansion': '5x PCIe slots'
        },
        'description': 'Single-socket professional workstation'
    },

    # ThinkStation Rack Workstations
    {
        'model_name': 'ThinkStation P920 Rack',
        'model_number': 'P920-Rack',
        'equipment_type': 'workstation',
        'is_rackmount': True,
        'rack_units': 4,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable',
            'memory': 'Up to 1TB DDR4 ECC',
            'storage': 'Multiple M.2 NVMe + U.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA Quadro RTX 8000',
            'form_factor': 'Rack 4U',
            'psu': 'Up to 1400W redundant'
        },
        'description': 'Rack-mounted dual-socket workstation'
    },
    {
        'model_name': 'ThinkStation P720 Rack',
        'model_number': 'P720-Rack',
        'equipment_type': 'workstation',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable',
            'memory': 'Up to 512GB DDR4 ECC',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA Quadro RTX 6000',
            'form_factor': 'Rack 2U',
            'psu': 'Up to 1125W redundant'
        },
        'description': 'Rack workstation for data center'
    },

    # ThinkStation P620/P520c/P410
    {
        'model_name': 'ThinkStation P620',
        'model_number': 'P620',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen Threadripper PRO (16-64 cores)',
            'memory': 'Up to 1TB DDR4 ECC (8 channels)',
            'storage': 'Multiple M.2 NVMe + U.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA RTX A6000 (48GB)',
            'form_factor': 'Tower',
            'psu': 'Up to 1000W',
            'expansion': '7x PCIe 4.0 slots'
        },
        'description': 'AMD Threadripper PRO workstation'
    },
    {
        'model_name': 'ThinkStation P520c',
        'model_number': 'P520c',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon W-2100/W-2200 series',
            'memory': 'Up to 256GB DDR4 ECC',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P2200',
            'form_factor': 'Compact Tower',
            'psu': '450W'
        },
        'description': 'Compact professional workstation'
    },
    {
        'model_name': 'ThinkStation P410',
        'model_number': 'P410',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon W-1200 series',
            'memory': 'Up to 128GB DDR4 ECC',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'Up to NVIDIA Quadro P2200',
            'form_factor': 'Tower',
            'psu': 'Up to 500W'
        },
        'description': 'Entry-level professional workstation'
    },

    # === THINKCENTRE BUSINESS DESKTOPS (35+ MODELS) ===

    # ThinkCentre M90 Series - Gen 4
    {
        'model_name': 'ThinkCentre M90q Gen 4',
        'model_number': 'M90q-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen (up to i9-13900T)',
            'memory': 'Up to 64GB DDR5-4800',
            'storage': 'M.2 NVMe SSD up to 2TB',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics 770',
            'ports': 'USB-C, DisplayPort, HDMI'
        },
        'description': 'Ultra-small premium business desktop'
    },
    {
        'model_name': 'ThinkCentre M90t Gen 4',
        'model_number': 'M90t-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen (up to i9-13900)',
            'memory': 'Up to 128GB DDR5-4800',
            'storage': 'Multiple M.2 NVMe + SATA (up to 4TB total)',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete GPU',
            'expansion': 'PCIe x16, x4, x1 slots'
        },
        'description': 'Premium business tower desktop'
    },
    {
        'model_name': 'ThinkCentre M90s Gen 4',
        'model_number': 'M90s-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen',
            'memory': 'Up to 64GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete',
            'ports': 'Front USB-C, legacy ports'
        },
        'description': 'Premium SFF business desktop'
    },

    # ThinkCentre M90 Series - Gen 3
    {
        'model_name': 'ThinkCentre M90q Gen 3',
        'model_number': 'M90q-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen',
            'memory': 'Up to 64GB DDR4-3200',
            'storage': 'M.2 NVMe SSD up to 2TB',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics 730'
        },
        'description': 'Ultra-compact business desktop'
    },
    {
        'model_name': 'ThinkCentre M90t Gen 3',
        'model_number': 'M90t-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen',
            'memory': 'Up to 128GB DDR4-3200',
            'storage': 'Multiple M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete GPU'
        },
        'description': 'Tower business desktop'
    },
    {
        'model_name': 'ThinkCentre M90s Gen 3',
        'model_number': 'M90s-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'SFF business desktop'
    },

    # ThinkCentre M90 Series - Gen 2
    {
        'model_name': 'ThinkCentre M90q Gen 2',
        'model_number': 'M90q-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen',
            'memory': 'Up to 64GB DDR4-3200',
            'storage': 'M.2 NVMe SSD up to 1TB',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics 730'
        },
        'description': 'Tiny business desktop'
    },
    {
        'model_name': 'ThinkCentre M90t Gen 2',
        'model_number': 'M90t-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Multiple M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Business tower Gen 2'
    },
    {
        'model_name': 'ThinkCentre M90s Gen 2',
        'model_number': 'M90s-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'SFF business Gen 2'
    },

    # ThinkCentre M80 Series
    {
        'model_name': 'ThinkCentre M80q Gen 4',
        'model_number': 'M80q-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Compact business desktop'
    },
    {
        'model_name': 'ThinkCentre M80t Gen 4',
        'model_number': 'M80t-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Mid-range tower desktop'
    },
    {
        'model_name': 'ThinkCentre M80s Gen 4',
        'model_number': 'M80s-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'SFF mid-range desktop'
    },
    {
        'model_name': 'ThinkCentre M80q Gen 3',
        'model_number': 'M80q-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Tiny mid-range desktop'
    },
    {
        'model_name': 'ThinkCentre M80t Gen 3',
        'model_number': 'M80t-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Tower desktop Gen 3'
    },
    {
        'model_name': 'ThinkCentre M80s Gen 3',
        'model_number': 'M80s-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'SFF desktop Gen 3'
    },

    # ThinkCentre M70 Series
    {
        'model_name': 'ThinkCentre M70q Gen 4',
        'model_number': 'M70q-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Compact business desktop'
    },
    {
        'model_name': 'ThinkCentre M70t Gen 4',
        'model_number': 'M70t-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Mainstream business desktop'
    },
    {
        'model_name': 'ThinkCentre M70s Gen 4',
        'model_number': 'M70s-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'SFF mainstream desktop'
    },
    {
        'model_name': 'ThinkCentre M70q Gen 3',
        'model_number': 'M70q-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Tiny desktop Gen 3'
    },
    {
        'model_name': 'ThinkCentre M70t Gen 3',
        'model_number': 'M70t-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Tower desktop Gen 3'
    },
    {
        'model_name': 'ThinkCentre M70s Gen 3',
        'model_number': 'M70s-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'SFF desktop Gen 3'
    },
    {
        'model_name': 'ThinkCentre M70q Gen 2',
        'model_number': 'M70q-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Tiny desktop Gen 2'
    },
    {
        'model_name': 'ThinkCentre M70t Gen 2',
        'model_number': 'M70t-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Tower desktop Gen 2'
    },
    {
        'model_name': 'ThinkCentre M70s Gen 2',
        'model_number': 'M70s-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'SFF desktop Gen 2'
    },

    # ThinkCentre M75 Series (AMD)
    {
        'model_name': 'ThinkCentre M75q Gen 2',
        'model_number': 'M75q-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 5000 series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'AMD Radeon Graphics'
        },
        'description': 'AMD-based tiny desktop'
    },
    {
        'model_name': 'ThinkCentre M75t Gen 2',
        'model_number': 'M75t-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 5000 series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'AMD Radeon Graphics'
        },
        'description': 'AMD tower desktop'
    },
    {
        'model_name': 'ThinkCentre M75s Gen 2',
        'model_number': 'M75s-G2',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 5000 series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'AMD Radeon Graphics'
        },
        'description': 'AMD SFF desktop'
    },

    # ThinkCentre Neo Series
    {
        'model_name': 'ThinkCentre Neo 50q Gen 4',
        'model_number': 'Neo-50q-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Value tiny desktop'
    },
    {
        'model_name': 'ThinkCentre Neo 50t Gen 4',
        'model_number': 'Neo-50t-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Value tower desktop'
    },
    {
        'model_name': 'ThinkCentre Neo 50s Gen 4',
        'model_number': 'Neo-50s-G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Value SFF desktop'
    },
    {
        'model_name': 'ThinkCentre Neo 50q Gen 3',
        'model_number': 'Neo-50q-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD',
            'form_factor': 'Tiny (1L)',
            'graphics': 'Intel UHD Graphics'
        },
        'description': 'Value tiny desktop Gen 3'
    },
    {
        'model_name': 'ThinkCentre Neo 50t Gen 3',
        'model_number': 'Neo-50t-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Value tower desktop Gen 3'
    },
    {
        'model_name': 'ThinkCentre Neo 50s Gen 3',
        'model_number': 'Neo-50s-G3',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Value SFF desktop Gen 3'
    },

    # === X1 CARBON SERIES (Premium Ultrabooks) ===
    {
        'model_name': 'ThinkPad X1 Carbon Gen 11',
        'model_number': 'X1-Carbon-G11',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen (P/U series)',
            'memory': 'Up to 64GB LPDDR5-6400',
            'storage': 'M.2 NVMe PCIe 4.0 up to 2TB',
            'display': '14" FHD+/2.2K/2.8K OLED',
            'battery': 'Up to 16 hours (57Wh)',
            'weight': '2.48 lbs (1.12 kg)',
            'connectivity': 'WiFi 6E, 5G/LTE optional'
        },
        'description': 'Premium 14" ultrabook Gen 11'
    },
    {
        'model_name': 'ThinkPad X1 Carbon Gen 10',
        'model_number': 'X1-Carbon-G10',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen',
            'memory': 'Up to 32GB LPDDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD+/2.8K OLED',
            'battery': 'Up to 15 hours',
            'weight': '2.48 lbs'
        },
        'description': 'Premium 14" ultrabook Gen 10'
    },
    {
        'model_name': 'ThinkPad X1 Carbon Gen 9',
        'model_number': 'X1-Carbon-G9',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen',
            'memory': 'Up to 32GB LPDDR4X',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 16 hours',
            'weight': '2.49 lbs'
        },
        'description': 'Premium 14" ultrabook Gen 9'
    },
    {
        'model_name': 'ThinkPad X1 Carbon Gen 8',
        'model_number': 'X1-Carbon-G8',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 10th Gen',
            'memory': 'Up to 16GB LPDDR3',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 19.5 hours',
            'weight': '2.40 lbs'
        },
        'description': 'Premium 14" ultrabook Gen 8'
    },
    {
        'model_name': 'ThinkPad X1 Carbon Gen 7',
        'model_number': 'X1-Carbon-G7',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 16GB LPDDR3',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 18.3 hours',
            'weight': '2.40 lbs'
        },
        'description': 'Premium 14" ultrabook Gen 7'
    },
    {
        'model_name': 'ThinkPad X1 Carbon Gen 6',
        'model_number': 'X1-Carbon-G6',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 16GB LPDDR3',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD/WQHD/HDR',
            'battery': 'Up to 15 hours',
            'weight': '2.49 lbs'
        },
        'description': 'Premium 14" ultrabook Gen 6'
    },

    # === X1 YOGA SERIES (Convertible 2-in-1) ===
    {
        'model_name': 'ThinkPad X1 Yoga Gen 8',
        'model_number': 'X1-Yoga-G8',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen',
            'memory': 'Up to 64GB LPDDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD+/2.8K OLED touch',
            'battery': 'Up to 15 hours',
            'weight': '3.0 lbs',
            'features': '360° hinge, pen support'
        },
        'description': 'Convertible 2-in-1 business laptop Gen 8'
    },
    {
        'model_name': 'ThinkPad X1 Yoga Gen 7',
        'model_number': 'X1-Yoga-G7',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen',
            'memory': 'Up to 32GB LPDDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD+/UHD+ touch',
            'battery': 'Up to 14 hours',
            'weight': '3.0 lbs',
            'features': '360° hinge, pen support'
        },
        'description': 'Convertible 2-in-1 Gen 7'
    },
    {
        'model_name': 'ThinkPad X1 Yoga Gen 6',
        'model_number': 'X1-Yoga-G6',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen',
            'memory': 'Up to 16GB LPDDR4X',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD touch',
            'battery': 'Up to 15 hours',
            'weight': '3.0 lbs',
            'features': '360° hinge, pen support'
        },
        'description': 'Convertible 2-in-1 Gen 6'
    },
    {
        'model_name': 'ThinkPad X1 Yoga Gen 5',
        'model_number': 'X1-Yoga-G5',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 10th Gen',
            'memory': 'Up to 16GB LPDDR3',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD touch',
            'battery': 'Up to 18 hours',
            'weight': '3.0 lbs',
            'features': '360° hinge, pen support'
        },
        'description': 'Convertible 2-in-1 Gen 5'
    },

    # === X1 NANO SERIES (Ultra-lightweight) ===
    {
        'model_name': 'ThinkPad X1 Nano Gen 3',
        'model_number': 'X1-Nano-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen',
            'memory': 'Up to 32GB LPDDR5',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13" 2K (2160x1350)',
            'battery': 'Up to 13 hours',
            'weight': '2.13 lbs (967g)',
            'connectivity': '5G/LTE optional'
        },
        'description': 'Ultra-lightweight 13" business laptop'
    },
    {
        'model_name': 'ThinkPad X1 Nano Gen 2',
        'model_number': 'X1-Nano-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen',
            'memory': 'Up to 16GB LPDDR5',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13" 2K',
            'battery': 'Up to 12 hours',
            'weight': '2.13 lbs'
        },
        'description': 'Ultra-lightweight Gen 2'
    },
    {
        'model_name': 'ThinkPad X1 Nano Gen 1',
        'model_number': 'X1-Nano-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen',
            'memory': 'Up to 16GB LPDDR4X',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13" 2K',
            'battery': 'Up to 13 hours',
            'weight': '1.99 lbs'
        },
        'description': 'Ultra-lightweight Gen 1'
    },

    # === X1 EXTREME SERIES (High-Performance) ===
    {
        'model_name': 'ThinkPad X1 Extreme Gen 5',
        'model_number': 'X1-Extreme-G5',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 12th Gen H-series',
            'memory': 'Up to 64GB DDR5',
            'storage': 'Up to 8TB (2x M.2 NVMe)',
            'display': '16" WQXGA/4K OLED',
            'graphics': 'NVIDIA GeForce RTX 3060/3070 Ti/3080 Ti',
            'battery': 'Up to 10 hours (90Wh)',
            'weight': '4.14 lbs'
        },
        'description': 'High-performance 16" laptop'
    },
    {
        'model_name': 'ThinkPad X1 Extreme Gen 4',
        'model_number': 'X1-Extreme-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 11th Gen H-series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4TB (2x M.2 NVMe)',
            'display': '16" FHD+/4K',
            'graphics': 'NVIDIA GeForce RTX 3050 Ti/3060/3070/3080',
            'battery': 'Up to 10 hours',
            'weight': '4.10 lbs'
        },
        'description': 'High-performance Gen 4'
    },
    {
        'model_name': 'ThinkPad X1 Extreme Gen 3',
        'model_number': 'X1-Extreme-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 10th Gen H-series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4TB (2x M.2 NVMe)',
            'display': '15.6" FHD/4K OLED',
            'graphics': 'NVIDIA GeForce GTX 1650 Ti/RTX 2070/2080',
            'battery': 'Up to 16 hours',
            'weight': '3.99 lbs'
        },
        'description': 'High-performance Gen 3'
    },

    # === T14 SERIES (14" Mainstream Business) ===
    {
        'model_name': 'ThinkPad T14 Gen 4',
        'model_number': 'T14-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen or AMD Ryzen 7 PRO',
            'memory': 'Up to 48GB DDR5',
            'storage': 'M.2 NVMe SSD up to 2TB',
            'display': '14" FHD/WUXGA/2.2K',
            'battery': 'Up to 14 hours',
            'weight': '3.2 lbs'
        },
        'description': 'Mainstream 14" business laptop Gen 4'
    },
    {
        'model_name': 'ThinkPad T14s Gen 4',
        'model_number': 'T14s-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen',
            'memory': 'Up to 32GB LPDDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD+/2.8K OLED',
            'battery': 'Up to 16 hours',
            'weight': '2.67 lbs'
        },
        'description': 'Slim 14" business laptop'
    },
    {
        'model_name': 'ThinkPad T14 Gen 3',
        'model_number': 'T14-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen or AMD Ryzen 7 PRO',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/2.2K',
            'battery': 'Up to 13 hours',
            'weight': '3.2 lbs'
        },
        'description': 'Business laptop Gen 3'
    },
    {
        'model_name': 'ThinkPad T14s Gen 3',
        'model_number': 'T14s-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen',
            'memory': 'Up to 32GB LPDDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD+/2.8K',
            'battery': 'Up to 15 hours',
            'weight': '2.67 lbs'
        },
        'description': 'Slim business laptop Gen 3'
    },
    {
        'model_name': 'ThinkPad T14 Gen 2',
        'model_number': 'T14-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen or AMD Ryzen 5/7 PRO',
            'memory': 'Up to 48GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 11 hours',
            'weight': '3.26 lbs'
        },
        'description': 'Business laptop Gen 2'
    },
    {
        'model_name': 'ThinkPad T14s Gen 2',
        'model_number': 'T14s-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen',
            'memory': 'Up to 32GB LPDDR4X',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 13 hours',
            'weight': '2.8 lbs'
        },
        'description': 'Slim laptop Gen 2'
    },
    {
        'model_name': 'ThinkPad T14 Gen 1',
        'model_number': 'T14-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 10th Gen or AMD Ryzen 5/7 PRO',
            'memory': 'Up to 48GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 12 hours',
            'weight': '3.24 lbs'
        },
        'description': 'Business laptop Gen 1'
    },
    {
        'model_name': 'ThinkPad T14s Gen 1',
        'model_number': 'T14s-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 10th Gen',
            'memory': 'Up to 32GB LPDDR3',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '14" FHD/UHD',
            'battery': 'Up to 13 hours',
            'weight': '2.81 lbs'
        },
        'description': 'Slim laptop Gen 1'
    },

    # === T16 SERIES (16" Large Screen) ===
    {
        'model_name': 'ThinkPad T16 Gen 2',
        'model_number': 'T16-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen or AMD Ryzen 7 PRO',
            'memory': 'Up to 48GB DDR5',
            'storage': 'M.2 NVMe SSD up to 2TB',
            'display': '16" WUXGA/WQUXGA',
            'battery': 'Up to 12 hours',
            'weight': '4.2 lbs'
        },
        'description': 'Large-screen business laptop Gen 2'
    },
    {
        'model_name': 'ThinkPad T16 Gen 1',
        'model_number': 'T16-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen or AMD Ryzen 7 PRO',
            'memory': 'Up to 48GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '16" WUXGA',
            'battery': 'Up to 11 hours',
            'weight': '4.2 lbs'
        },
        'description': 'Large-screen laptop Gen 1'
    },

    # === T15 SERIES (15.6" Legacy) ===
    {
        'model_name': 'ThinkPad T15 Gen 2',
        'model_number': 'T15-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen',
            'memory': 'Up to 48GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '15.6" FHD/UHD',
            'battery': 'Up to 12 hours',
            'weight': '4.1 lbs'
        },
        'description': '15.6" business laptop Gen 2'
    },
    {
        'model_name': 'ThinkPad T15 Gen 1',
        'model_number': 'T15-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 10th Gen',
            'memory': 'Up to 48GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '15.6" FHD/UHD',
            'battery': 'Up to 12 hours',
            'weight': '4.1 lbs'
        },
        'description': '15.6" business laptop Gen 1'
    },

    # === T490/T480/T470 SERIES (Legacy) ===
    {
        'model_name': 'ThinkPad T490',
        'model_number': 'T490',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 48GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 13 hours',
            'weight': '3.23 lbs'
        },
        'description': '14" business laptop T490'
    },
    {
        'model_name': 'ThinkPad T490s',
        'model_number': 'T490s',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 24GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD/WQHD',
            'battery': 'Up to 15 hours',
            'weight': '2.81 lbs'
        },
        'description': 'Slim 14" laptop T490s'
    },
    {
        'model_name': 'ThinkPad T480',
        'model_number': 'T480',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe + 2.5" HDD/SSD',
            'display': '14" FHD',
            'battery': 'Up to 18 hours (dual battery)',
            'weight': '3.57 lbs'
        },
        'description': '14" business laptop T480'
    },
    {
        'model_name': 'ThinkPad T480s',
        'model_number': 'T480s',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 24GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD/WQHD',
            'battery': 'Up to 14 hours',
            'weight': '2.9 lbs'
        },
        'description': 'Slim 14" laptop T480s'
    },
    {
        'model_name': 'ThinkPad T470',
        'model_number': 'T470',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 7th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe + 2.5" HDD/SSD',
            'display': '14" FHD',
            'battery': 'Up to 17 hours',
            'weight': '3.48 lbs'
        },
        'description': '14" business laptop T470'
    },
    {
        'model_name': 'ThinkPad T470s',
        'model_number': 'T470s',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 7th Gen',
            'memory': 'Up to 24GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD/WQHD',
            'battery': 'Up to 13 hours',
            'weight': '2.9 lbs'
        },
        'description': 'Slim 14" laptop T470s'
    },

    # === L SERIES (Essential Business) ===
    {
        'model_name': 'ThinkPad L14 Gen 4',
        'model_number': 'L14-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe SSD up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 12 hours',
            'weight': '3.3 lbs'
        },
        'description': 'Essential 14" business laptop Gen 4'
    },
    {
        'model_name': 'ThinkPad L14 Gen 3',
        'model_number': 'L14-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 11 hours',
            'weight': '3.3 lbs'
        },
        'description': 'Essential laptop Gen 3'
    },
    {
        'model_name': 'ThinkPad L14 Gen 2',
        'model_number': 'L14-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 11 hours',
            'weight': '3.3 lbs'
        },
        'description': 'Essential laptop Gen 2'
    },
    {
        'model_name': 'ThinkPad L15 Gen 4',
        'model_number': 'L15-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '15.6" FHD',
            'battery': 'Up to 12 hours',
            'weight': '3.9 lbs'
        },
        'description': '15.6" essential laptop Gen 4'
    },
    {
        'model_name': 'ThinkPad L15 Gen 3',
        'model_number': 'L15-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '15.6" FHD',
            'battery': 'Up to 11 hours',
            'weight': '3.9 lbs'
        },
        'description': '15.6" essential Gen 3'
    },
    {
        'model_name': 'ThinkPad L15 Gen 2',
        'model_number': 'L15-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '15.6" FHD',
            'battery': 'Up to 11 hours',
            'weight': '3.9 lbs'
        },
        'description': '15.6" essential Gen 2'
    },
    {
        'model_name': 'ThinkPad L13 Gen 4',
        'model_number': 'L13-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13.3" FHD',
            'battery': 'Up to 10 hours',
            'weight': '2.9 lbs'
        },
        'description': '13.3" compact essential laptop'
    },
    {
        'model_name': 'ThinkPad L13 Gen 3',
        'model_number': 'L13-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13.3" FHD',
            'battery': 'Up to 10 hours',
            'weight': '2.9 lbs'
        },
        'description': '13.3" compact laptop Gen 3'
    },
    {
        'model_name': 'ThinkPad L13 Gen 2',
        'model_number': 'L13-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen',
            'memory': 'Up to 16GB DDR4',
            'storage': 'M.2 NVMe up to 512GB',
            'display': '13.3" FHD',
            'battery': 'Up to 10 hours',
            'weight': '2.9 lbs'
        },
        'description': '13.3" compact laptop Gen 2'
    },
    {
        'model_name': 'ThinkPad L13 Yoga Gen 4',
        'model_number': 'L13-Yoga-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13.3" FHD touch',
            'battery': 'Up to 10 hours',
            'weight': '3.1 lbs',
            'features': '360° hinge, pen support'
        },
        'description': '13.3" convertible 2-in-1 Gen 4'
    },
    {
        'model_name': 'ThinkPad L13 Yoga Gen 3',
        'model_number': 'L13-Yoga-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '13.3" FHD touch',
            'battery': 'Up to 10 hours',
            'weight': '3.1 lbs',
            'features': '360° hinge, pen support'
        },
        'description': '13.3" convertible Gen 3'
    },
    {
        'model_name': 'ThinkPad L13 Yoga Gen 2',
        'model_number': 'L13-Yoga-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen',
            'memory': 'Up to 16GB DDR4',
            'storage': 'M.2 NVMe up to 512GB',
            'display': '13.3" FHD touch',
            'battery': 'Up to 10 hours',
            'weight': '3.1 lbs',
            'features': '360° hinge, pen support'
        },
        'description': '13.3" convertible Gen 2'
    },

    # === E SERIES (Affordable Business) ===
    {
        'model_name': 'ThinkPad E14 Gen 5',
        'model_number': 'E14-G5',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen or AMD Ryzen 5/7',
            'memory': 'Up to 40GB DDR4',
            'storage': 'M.2 NVMe SSD up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 10 hours',
            'weight': '3.5 lbs'
        },
        'description': 'Affordable 14" business laptop Gen 5'
    },
    {
        'model_name': 'ThinkPad E14 Gen 4',
        'model_number': 'E14-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 40GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 10 hours',
            'weight': '3.5 lbs'
        },
        'description': 'Affordable laptop Gen 4'
    },
    {
        'model_name': 'ThinkPad E14 Gen 3',
        'model_number': 'E14-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen or AMD Ryzen 5/7',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '14" FHD',
            'battery': 'Up to 10 hours',
            'weight': '3.5 lbs'
        },
        'description': 'Affordable laptop Gen 3'
    },
    {
        'model_name': 'ThinkPad E15 Gen 5',
        'model_number': 'E15-G5',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 13th Gen or AMD Ryzen 5/7',
            'memory': 'Up to 40GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '15.6" FHD',
            'battery': 'Up to 10 hours',
            'weight': '3.9 lbs'
        },
        'description': '15.6" affordable laptop Gen 5'
    },
    {
        'model_name': 'ThinkPad E15 Gen 4',
        'model_number': 'E15-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 12th Gen',
            'memory': 'Up to 40GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '15.6" FHD',
            'battery': 'Up to 10 hours',
            'weight': '3.9 lbs'
        },
        'description': '15.6" affordable Gen 4'
    },
    {
        'model_name': 'ThinkPad E15 Gen 3',
        'model_number': 'E15-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 11th Gen or AMD Ryzen 5/7',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe up to 1TB',
            'display': '15.6" FHD',
            'battery': 'Up to 10 hours',
            'weight': '3.9 lbs'
        },
        'description': '15.6" affordable Gen 3'
    },
    {
        'model_name': 'ThinkPad E16 Gen 1',
        'model_number': 'E16-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen or AMD Ryzen 5/7',
            'memory': 'Up to 40GB DDR5',
            'storage': 'M.2 NVMe SSD up to 1TB',
            'display': '16" WUXGA (1920x1200)',
            'battery': 'Up to 10 hours',
            'weight': '4.2 lbs'
        },
        'description': 'Large affordable 16" business laptop'
    },

    # === P SERIES MOBILE WORKSTATIONS ===
    {
        'model_name': 'ThinkPad P1 Gen 6',
        'model_number': 'P1-G6',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 13th Gen H-series',
            'memory': 'Up to 64GB DDR5',
            'storage': 'M.2 NVMe SSD up to 4TB',
            'display': '16" WUXGA/WQXGA/4K OLED',
            'graphics': 'NVIDIA RTX A1000/A2000/A3000/A5500',
            'battery': 'Up to 10 hours',
            'weight': '4.0 lbs'
        },
        'description': 'Thin 16" mobile workstation Gen 6'
    },
    {
        'model_name': 'ThinkPad P1 Gen 5',
        'model_number': 'P1-G5',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 12th Gen H-series',
            'memory': 'Up to 64GB DDR5',
            'storage': 'M.2 NVMe up to 4TB',
            'display': '16" WUXGA/4K OLED',
            'graphics': 'NVIDIA RTX A1000/A2000/A5500',
            'battery': 'Up to 10 hours',
            'weight': '4.0 lbs'
        },
        'description': 'Thin mobile workstation Gen 5'
    },
    {
        'model_name': 'ThinkPad P1 Gen 4',
        'model_number': 'P1-G4',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 11th Gen H-series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe up to 4TB',
            'display': '16" FHD+/4K',
            'graphics': 'NVIDIA T1200/RTX A2000/A3000/A5000',
            'battery': 'Up to 10 hours',
            'weight': '4.0 lbs'
        },
        'description': 'Thin mobile workstation Gen 4'
    },
    {
        'model_name': 'ThinkPad P1 Gen 3',
        'model_number': 'P1-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 10th Gen H-series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe up to 4TB',
            'display': '15.6" FHD/4K OLED',
            'graphics': 'NVIDIA Quadro T1000/T2000/RTX 5000',
            'battery': 'Up to 11 hours',
            'weight': '3.99 lbs'
        },
        'description': 'Thin mobile workstation Gen 3'
    },
    {
        'model_name': 'ThinkPad P16s Gen 2',
        'model_number': 'P16s-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 13th Gen P-series',
            'memory': 'Up to 48GB DDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '16" WUXGA/WQUXGA',
            'graphics': 'NVIDIA RTX A500/A1000',
            'battery': 'Up to 12 hours',
            'weight': '4.0 lbs'
        },
        'description': 'Slim 16" mobile workstation Gen 2'
    },
    {
        'model_name': 'ThinkPad P16s Gen 1',
        'model_number': 'P16s-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen P-series',
            'memory': 'Up to 48GB DDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '16" WUXGA',
            'graphics': 'NVIDIA T550',
            'battery': 'Up to 12 hours',
            'weight': '4.0 lbs'
        },
        'description': 'Slim mobile workstation Gen 1'
    },
    {
        'model_name': 'ThinkPad P15v Gen 3',
        'model_number': 'P15v-G3',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 12th Gen H-series',
            'memory': 'Up to 64GB DDR5',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '15.6" FHD',
            'graphics': 'NVIDIA T600/T1200/RTX A2000',
            'battery': 'Up to 10 hours',
            'weight': '4.6 lbs'
        },
        'description': 'Entry mobile workstation Gen 3'
    },
    {
        'model_name': 'ThinkPad P15v Gen 2',
        'model_number': 'P15v-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 11th Gen H-series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '15.6" FHD',
            'graphics': 'NVIDIA T600/T1200',
            'battery': 'Up to 10 hours',
            'weight': '4.6 lbs'
        },
        'description': 'Entry mobile workstation Gen 2'
    },
    {
        'model_name': 'ThinkPad P15v Gen 1',
        'model_number': 'P15v-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 10th Gen H-series',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe up to 2TB',
            'display': '15.6" FHD',
            'graphics': 'NVIDIA Quadro P620/T600',
            'battery': 'Up to 10 hours',
            'weight': '4.6 lbs'
        },
        'description': 'Entry mobile workstation Gen 1'
    },
    {
        'model_name': 'ThinkPad P16 Gen 2',
        'model_number': 'P16-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 13th Gen HX or Xeon W',
            'memory': 'Up to 192GB DDR5 ECC',
            'storage': 'M.2 NVMe SSD up to 8TB',
            'display': '16" WUXGA/WQUXGA/4K',
            'graphics': 'NVIDIA RTX 1000/2000/3000/4000/5000 Ada',
            'battery': 'Up to 10 hours (94Wh)',
            'weight': '5.6 lbs'
        },
        'description': 'High-performance 16" mobile workstation Gen 2'
    },
    {
        'model_name': 'ThinkPad P16 Gen 1',
        'model_number': 'P16-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 12th Gen HX or Xeon W',
            'memory': 'Up to 128GB DDR5 ECC',
            'storage': 'M.2 NVMe up to 8TB',
            'display': '16" WUXGA/4K',
            'graphics': 'NVIDIA RTX A1000/A2000/A3000/A5500',
            'battery': 'Up to 10 hours',
            'weight': '5.6 lbs'
        },
        'description': 'High-performance workstation Gen 1'
    },
    {
        'model_name': 'ThinkPad P15 Gen 2',
        'model_number': 'P15-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 11th Gen H or Xeon W',
            'memory': 'Up to 128GB DDR4 ECC',
            'storage': 'M.2 NVMe up to 8TB',
            'display': '15.6" FHD/UHD',
            'graphics': 'NVIDIA RTX A2000/A3000/A4000/A5000',
            'battery': 'Up to 9 hours',
            'weight': '5.5 lbs'
        },
        'description': '15.6" mobile workstation Gen 2'
    },
    {
        'model_name': 'ThinkPad P15 Gen 1',
        'model_number': 'P15-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 10th Gen H or Xeon W',
            'memory': 'Up to 128GB DDR4 ECC',
            'storage': 'M.2 NVMe up to 6TB',
            'display': '15.6" FHD/UHD',
            'graphics': 'NVIDIA Quadro T1000/T2000/RTX 4000/5000',
            'battery': 'Up to 11 hours',
            'weight': '5.5 lbs'
        },
        'description': '15.6" mobile workstation Gen 1'
    },
    {
        'model_name': 'ThinkPad P17 Gen 2',
        'model_number': 'P17-G2',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 11th Gen H or Xeon W',
            'memory': 'Up to 128GB DDR4 ECC',
            'storage': 'M.2 NVMe up to 8TB',
            'display': '17.3" FHD/UHD',
            'graphics': 'NVIDIA RTX A3000/A4000/A5000',
            'battery': 'Up to 8 hours (94Wh)',
            'weight': '6.4 lbs'
        },
        'description': '17.3" large mobile workstation Gen 2'
    },
    {
        'model_name': 'ThinkPad P17 Gen 1',
        'model_number': 'P17-G1',
        'equipment_type': 'laptop',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i7/i9 10th Gen H or Xeon W',
            'memory': 'Up to 128GB DDR4 ECC',
            'storage': 'M.2 NVMe up to 6TB',
            'display': '17.3" FHD/UHD',
            'graphics': 'NVIDIA Quadro T1000/T2000/RTX 4000/5000',
            'battery': 'Up to 11 hours',
            'weight': '6.4 lbs'
        },
        'description': '17.3" large mobile workstation Gen 1'
    },
        
            # Meraki MS120 Series Switches - 10 models
            {'model_name': 'MS120-8', 'model_number': 'MS120-8', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1G', 'poe_budget': '124W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '8-port cloud switch'},
            {'model_name': 'MS120-8FP', 'model_number': 'MS120-8FP', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1G', 'poe_budget': '124W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '8-port PoE+ cloud switch'},
            {'model_name': 'MS120-8LP', 'model_number': 'MS120-8LP', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1G', 'poe_budget': '67W PoE', 'cloud': 'Meraki Dashboard'}, 'description': '8-port lite PoE cloud switch'},
            {'model_name': 'MS120-24', 'model_number': 'MS120-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 1G SFP', 'cloud': 'Meraki Dashboard'}, 'description': '24-port cloud switch'},
            {'model_name': 'MS120-24P', 'model_number': 'MS120-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 1G SFP', 'poe_budget': '370W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '24-port PoE+ cloud switch'},
            {'model_name': 'MS120-48', 'model_number': 'MS120-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 1G SFP', 'cloud': 'Meraki Dashboard'}, 'description': '48-port cloud switch'},
            {'model_name': 'MS120-48FP', 'model_number': 'MS120-48FP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 1G SFP', 'poe_budget': '740W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '48-port full PoE+ cloud switch'},
            {'model_name': 'MS120-48LP', 'model_number': 'MS120-48LP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 1G SFP', 'poe_budget': '370W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '48-port lite PoE+ cloud switch'},
            
            # Meraki MS125 Series - 8 models
            {'model_name': 'MS125-24', 'model_number': 'MS125-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': '24-port cloud switch with 10G'},
            {'model_name': 'MS125-24P', 'model_number': 'MS125-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '24-port PoE+ cloud switch with 10G'},
            {'model_name': 'MS125-48', 'model_number': 'MS125-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': '48-port cloud switch with 10G'},
            {'model_name': 'MS125-48FP', 'model_number': 'MS125-48FP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '740W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '48-port full PoE+ cloud switch with 10G'},
            {'model_name': 'MS125-48LP', 'model_number': 'MS125-48LP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'cloud': 'Meraki Dashboard'}, 'description': '48-port lite PoE+ cloud switch with 10G'},
            
            # Meraki MS210 Series - 8 models
            {'model_name': 'MS210-24', 'model_number': 'MS210-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 1G SFP', 'stacking': '40G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port stackable cloud switch'},
            {'model_name': 'MS210-24P', 'model_number': 'MS210-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 1G SFP', 'poe_budget': '370W PoE+', 'stacking': '40G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port PoE+ stackable cloud switch'},
            {'model_name': 'MS210-48', 'model_number': 'MS210-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 1G SFP', 'stacking': '40G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port stackable cloud switch'},
            {'model_name': 'MS210-48FP', 'model_number': 'MS210-48FP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 1G SFP', 'poe_budget': '740W PoE+', 'stacking': '40G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port full PoE+ stackable cloud switch'},
            {'model_name': 'MS210-48LP', 'model_number': 'MS210-48LP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 1G SFP', 'poe_budget': '370W PoE+', 'stacking': '40G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port lite PoE+ stackable cloud switch'},
            
            # Meraki MS225 Series - 8 models
            {'model_name': 'MS225-24', 'model_number': 'MS225-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port 10G uplink cloud switch'},
            {'model_name': 'MS225-24P', 'model_number': 'MS225-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port PoE+ 10G uplink cloud switch'},
            {'model_name': 'MS225-48', 'model_number': 'MS225-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port 10G uplink cloud switch'},
            {'model_name': 'MS225-48FP', 'model_number': 'MS225-48FP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '740W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port full PoE+ 10G uplink cloud switch'},
            {'model_name': 'MS225-48LP', 'model_number': 'MS225-48LP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port lite PoE+ 10G uplink cloud switch'},
            
            # Meraki MS250 Series - 10 models
            {'model_name': 'MS250-24', 'model_number': 'MS250-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port enterprise cloud switch'},
            {'model_name': 'MS250-24P', 'model_number': 'MS250-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port PoE+ enterprise cloud switch'},
            {'model_name': 'MS250-48', 'model_number': 'MS250-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port enterprise cloud switch'},
            {'model_name': 'MS250-48FP', 'model_number': 'MS250-48FP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '740W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port full PoE+ enterprise cloud switch'},
            {'model_name': 'MS250-48LP', 'model_number': 'MS250-48LP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1G', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port lite PoE+ enterprise cloud switch'},
            
            # Meraki MS350 Series - 10 models
            {'model_name': 'MS350-24', 'model_number': 'MS350-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '20x 1G, 4x 10G SFP+', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port hybrid 1G/10G cloud switch'},
            {'model_name': 'MS350-24P', 'model_number': 'MS350-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '20x 1G PoE+, 4x 10G SFP+', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port hybrid PoE+ cloud switch'},
            {'model_name': 'MS350-24X', 'model_number': 'MS350-24X', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10G SFP+', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port 10G cloud switch'},
            {'model_name': 'MS350-48', 'model_number': 'MS350-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '44x 1G, 4x 10G SFP+', 'uplinks': '4x 10G SFP+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port hybrid 1G/10G cloud switch'},
            {'model_name': 'MS350-48FP', 'model_number': 'MS350-48FP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '44x 1G PoE+, 4x 10G SFP+', 'uplinks': '4x 10G SFP+', 'poe_budget': '740W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port hybrid full PoE+ cloud switch'},
            {'model_name': 'MS350-48LP', 'model_number': 'MS350-48LP', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '44x 1G PoE+, 4x 10G SFP+', 'uplinks': '4x 10G SFP+', 'poe_budget': '370W PoE+', 'stacking': '80G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port hybrid lite PoE+ cloud switch'},
            
            # Meraki MS390 Series - 6 models
            {'model_name': 'MS390-24', 'model_number': 'MS390-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10G SFP+', 'uplinks': '4x 25G SFP28', 'stacking': '160G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port 10G core cloud switch'},
            {'model_name': 'MS390-24P', 'model_number': 'MS390-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10G mGig', 'uplinks': '4x 25G SFP28', 'poe_budget': '715W UPOE', 'stacking': '160G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port 10G PoE+ core cloud switch'},
            {'model_name': 'MS390-24U', 'model_number': 'MS390-24U', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10G mGig', 'uplinks': '4x 25G SFP28', 'poe_budget': '715W UPOE', 'stacking': '160G', 'cloud': 'Meraki Dashboard'}, 'description': '24-port 10G UPOE cloud switch'},
            {'model_name': 'MS390-48', 'model_number': 'MS390-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 10G SFP+', 'uplinks': '4x 25G SFP28', 'stacking': '160G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port 10G core cloud switch'},
            {'model_name': 'MS390-48P', 'model_number': 'MS390-48P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 10G mGig', 'uplinks': '4x 25G SFP28', 'poe_budget': '715W UPOE', 'stacking': '160G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port 10G PoE+ core cloud switch'},
            {'model_name': 'MS390-48U', 'model_number': 'MS390-48U', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 10G mGig', 'uplinks': '4x 25G SFP28', 'poe_budget': '1125W UPOE', 'stacking': '160G', 'cloud': 'Meraki Dashboard'}, 'description': '48-port 10G UPOE cloud switch'},
            
            # Meraki MX Security Appliances - 15 models
            {'model_name': 'MX64', 'model_number': 'MX64', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '250 Mbps', 'vpn_throughput': '100 Mbps', 'ports': '5x 1G', 'cloud': 'Meraki Dashboard'}, 'description': 'Small branch security appliance'},
            {'model_name': 'MX64W', 'model_number': 'MX64W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '250 Mbps', 'vpn_throughput': '100 Mbps', 'ports': '5x 1G', 'wireless': 'WiFi 5', 'cloud': 'Meraki Dashboard'}, 'description': 'Small branch security appliance with WiFi'},
            {'model_name': 'MX67', 'model_number': 'MX67', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '450 Mbps', 'vpn_throughput': '200 Mbps', 'ports': '10x 1G', 'cloud': 'Meraki Dashboard'}, 'description': 'Branch security appliance'},
            {'model_name': 'MX67W', 'model_number': 'MX67W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '450 Mbps', 'vpn_throughput': '200 Mbps', 'ports': '10x 1G', 'wireless': 'WiFi 5', 'cloud': 'Meraki Dashboard'}, 'description': 'Branch security appliance with WiFi'},
            {'model_name': 'MX68', 'model_number': 'MX68', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '450 Mbps', 'vpn_throughput': '200 Mbps', 'ports': '10x 1G', 'cloud': 'Meraki Dashboard'}, 'description': 'Branch security appliance'},
            {'model_name': 'MX68W', 'model_number': 'MX68W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '450 Mbps', 'vpn_throughput': '200 Mbps', 'ports': '10x 1G', 'wireless': 'WiFi 5', 'cloud': 'Meraki Dashboard'}, 'description': 'Branch security appliance with WiFi'},
            {'model_name': 'MX75', 'model_number': 'MX75', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '750 Mbps', 'vpn_throughput': '350 Mbps', 'ports': '8x 1G, 2x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'Mid-size security appliance'},
            {'model_name': 'MX84', 'model_number': 'MX84', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '500 Mbps', 'vpn_throughput': '250 Mbps', 'ports': '10x 1G, 2x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'Branch aggregation security appliance'},
            {'model_name': 'MX85', 'model_number': 'MX85', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '1 Gbps', 'vpn_throughput': '500 Mbps', 'ports': '8x 1G, 4x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'Enterprise security appliance'},
            {'model_name': 'MX95', 'model_number': 'MX95', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2 Gbps', 'vpn_throughput': '750 Mbps', 'ports': '8x 1G, 4x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'High-performance security appliance'},
            {'model_name': 'MX105', 'model_number': 'MX105', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3 Gbps', 'vpn_throughput': '1 Gbps', 'ports': '8x 1G, 4x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'High-end security appliance'},
            {'model_name': 'MX250', 'model_number': 'MX250', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '5 Gbps', 'vpn_throughput': '1.5 Gbps', 'ports': '8x 1G, 8x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'Large campus security appliance'},
            {'model_name': 'MX450', 'model_number': 'MX450', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '10 Gbps', 'vpn_throughput': '3 Gbps', 'ports': '8x 1G, 8x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'Enterprise campus security appliance'},
            {'model_name': 'MX750', 'model_number': 'MX750', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '20 Gbps', 'vpn_throughput': '5 Gbps', 'ports': '8x 1G, 12x 10G SFP+', 'cloud': 'Meraki Dashboard'}, 'description': 'Flagship security appliance'},
            
            # Meraki MR Wireless Access Points - 25 models
            {'model_name': 'MR20', 'model_number': 'MR20', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '867 Mbps', 'mimo': '2x2', 'poe': '802.3af', 'cloud': 'Meraki Dashboard'}, 'description': 'Entry cloud WiFi 5 AP'},
            {'model_name': 'MR28', 'model_number': 'MR28', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '1.7 Gbps', 'mimo': '2x2', 'poe': '802.3af', 'cloud': 'Meraki Dashboard'}, 'description': 'Standard cloud WiFi 5 AP'},
            {'model_name': 'MR30H', 'model_number': 'MR30H', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '1.9 Gbps', 'mimo': '2x2', 'poe': '802.3af', 'features': 'BLE, Z-Wave', 'cloud': 'Meraki Dashboard'}, 'description': 'Smart home cloud AP'},
            {'model_name': 'MR33', 'model_number': 'MR33', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '1.3 Gbps', 'mimo': '2x2', 'poe': '802.3af', 'cloud': 'Meraki Dashboard'}, 'description': 'Business cloud WiFi 5 AP'},
            {'model_name': 'MR36', 'model_number': 'MR36', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '3.9 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'Enterprise cloud WiFi 6 AP'},
            {'model_name': 'MR42', 'model_number': 'MR42', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '1.9 Gbps', 'mimo': '3x3', 'poe': '802.3af', 'cloud': 'Meraki Dashboard'}, 'description': 'Mid-range cloud WiFi 5 AP'},
            {'model_name': 'MR44', 'model_number': 'MR44', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '3.9 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'High-performance cloud WiFi 6 AP'},
            {'model_name': 'MR45', 'model_number': 'MR45', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '4.8 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'Advanced cloud WiFi 6 AP'},
            {'model_name': 'MR46', 'model_number': 'MR46', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '5.4 Gbps', 'mimo': '4x4', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'Premium cloud WiFi 6 AP'},
            {'model_name': 'MR46E', 'model_number': 'MR46E', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '7.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'Premium cloud WiFi 6E AP'},
            {'model_name': 'MR52', 'model_number': 'MR52', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '2.6 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'High-density cloud WiFi 5 AP'},
            {'model_name': 'MR53', 'model_number': 'MR53', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '3.5 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'Premium cloud WiFi 5 AP'},
            {'model_name': 'MR53E', 'model_number': 'MR53E', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '5.4 Gbps', 'mimo': '4x4', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'High-performance cloud WiFi 6 outdoor'},
            {'model_name': 'MR56', 'model_number': 'MR56', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '5.4 Gbps', 'mimo': '8x8', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'Flagship cloud WiFi 6 AP'},
            {'model_name': 'MR57', 'model_number': 'MR57', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '10.4 Gbps', 'mimo': '4x4', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'Enterprise cloud WiFi 6E AP'},
            {'model_name': 'MR70', 'model_number': 'MR70', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '1.7 Gbps', 'mimo': '2x2', 'poe': '802.3af', 'cloud': 'Meraki Dashboard'}, 'description': 'Outdoor cloud WiFi 5 AP'},
            {'model_name': 'MR74', 'model_number': 'MR74', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '2.6 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'Outdoor cloud WiFi 5 AP'},
            {'model_name': 'MR76', 'model_number': 'MR76', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '3.9 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'Outdoor cloud WiFi 6 AP'},
            {'model_name': 'MR78', 'model_number': 'MR78', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '7.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'Outdoor cloud WiFi 6E AP'},
            {'model_name': 'MR84', 'model_number': 'MR84', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 5', 'bands': 'Dual-band', 'max_rate': '3.5 Gbps', 'mimo': '4x4', 'poe': '802.3at', 'cloud': 'Meraki Dashboard'}, 'description': 'High-density outdoor cloud AP'},
            {'model_name': 'MR86', 'model_number': 'MR86', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual-band', 'max_rate': '5.4 Gbps', 'mimo': '8x8', 'poe': '802.3bt', 'cloud': 'Meraki Dashboard'}, 'description': 'Flagship outdoor cloud WiFi 6 AP'},

        
            # Additional ProLiant DL Servers - 100 models (various configs)
            {'model_name': 'ProLiant DL20 Gen10', 'model_number': 'P17078-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Intel Xeon E-2200', 'memory': 'Up to 64GB DDR4', 'storage': '4x 3.5\" LFF', 'power': '290W'}, 'description': '1U entry server'},
            {'model_name': 'ProLiant DL20 Gen10 Plus', 'model_number': 'P43732-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Intel Xeon E-2300', 'memory': 'Up to 128GB DDR4', 'storage': '4x 3.5\" LFF', 'power': '290W'}, 'description': '1U entry server Gen10+'},
            {'model_name': 'ProLiant DL325 Gen10 Plus (8 SFF)', 'model_number': 'P18606-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'AMD EPYC 7002/7003', 'memory': 'Up to 2TB DDR4', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '1U AMD server with 8 SFF bays'},
            {'model_name': 'ProLiant DL325 Gen10 Plus (10 NVMe)', 'model_number': 'P17200-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'AMD EPYC 7002/7003', 'memory': 'Up to 2TB DDR4', 'storage': '10x 2.5\" NVMe', 'power': '800W'}, 'description': '1U AMD NVMe server'},
            {'model_name': 'ProLiant DL360 Gen10 (4 SFF)', 'model_number': 'P03630-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '4x 2.5\" SFF', 'power': '800W'}, 'description': '1U server with 4 SFF bays'},
            {'model_name': 'ProLiant DL360 Gen10 (8 SFF)', 'model_number': 'P03631-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '1U server with 8 SFF bays'},
            {'model_name': 'ProLiant DL360 Gen10 (10 NVMe)', 'model_number': 'P23465-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '10x 2.5\" NVMe', 'power': '800W'}, 'description': '1U NVMe server'},
            {'model_name': 'ProLiant DL360 Gen10 Plus (4 SFF)', 'model_number': 'P23462-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable 2nd/3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '4x 2.5\" SFF', 'power': '800W'}, 'description': '1U Gen10+ server'},
            {'model_name': 'ProLiant DL360 Gen10 Plus (8 SFF)', 'model_number': 'P28948-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable 3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '1U Gen10+ with 8 SFF bays'},
            {'model_name': 'ProLiant DL360 Gen10 Plus (12 NVMe)', 'model_number': 'P28949-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable 3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '12x 2.5\" NVMe', 'power': '800W'}, 'description': '1U NVMe Gen10+ server'},
            {'model_name': 'ProLiant DL360 Gen11 (4 SFF)', 'model_number': 'P46129-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '4x 2.5\" SFF', 'power': '800W'}, 'description': '1U Gen11 server'},
            {'model_name': 'ProLiant DL360 Gen11 (8 SFF)', 'model_number': 'P46130-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '1U Gen11 with 8 SFF bays'},
            {'model_name': 'ProLiant DL360 Gen11 (10 NVMe)', 'model_number': 'P46131-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '10x 2.5\" NVMe', 'power': '800W'}, 'description': '1U NVMe Gen11 server'},
            {'model_name': 'ProLiant DL380 Gen10 (8 SFF)', 'model_number': 'P20174-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '2U server with 8 SFF bays'},
            {'model_name': 'ProLiant DL380 Gen10 (12 LFF)', 'model_number': 'P20175-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '12x 3.5\" LFF', 'power': '800W'}, 'description': '2U server with 12 LFF bays'},
            {'model_name': 'ProLiant DL380 Gen10 (24 SFF)', 'model_number': 'P20176-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '24x 2.5\" SFF', 'power': '1600W'}, 'description': '2U high-density storage server'},
            {'model_name': 'ProLiant DL380 Gen10 (20 NVMe)', 'model_number': 'P23463-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable', 'memory': 'Up to 3TB DDR4', 'storage': '20x 2.5\" NVMe', 'power': '1600W'}, 'description': '2U NVMe server'},
            {'model_name': 'ProLiant DL380 Gen10 Plus (8 SFF)', 'model_number': 'P28939-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 2nd/3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '2U Gen10+ server'},
            {'model_name': 'ProLiant DL380 Gen10 Plus (12 LFF)', 'model_number': 'P28940-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '12x 3.5\" LFF', 'power': '800W'}, 'description': '2U LFF Gen10+ server'},
            {'model_name': 'ProLiant DL380 Gen10 Plus (24 SFF)', 'model_number': 'P28941-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '24x 2.5\" SFF', 'power': '1600W'}, 'description': '2U high-density Gen10+'},
            {'model_name': 'ProLiant DL380 Gen10 Plus (20 NVMe)', 'model_number': 'P28942-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 3rd Gen', 'memory': 'Up to 4TB DDR4', 'storage': '20x 2.5\" NVMe', 'power': '1600W'}, 'description': '2U NVMe Gen10+ server'},
            {'model_name': 'ProLiant DL380 Gen11 (8 SFF)', 'model_number': 'P46132-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '2U Gen11 server'},
            {'model_name': 'ProLiant DL380 Gen11 (12 LFF)', 'model_number': 'P46133-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '12x 3.5\" LFF', 'power': '800W'}, 'description': '2U LFF Gen11 server'},
            {'model_name': 'ProLiant DL380 Gen11 (24 SFF)', 'model_number': 'P46134-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '24x 2.5\" SFF', 'power': '1600W'}, 'description': '2U high-density Gen11'},
            {'model_name': 'ProLiant DL380 Gen11 (28 NVMe)', 'model_number': 'P46135-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual Intel Xeon Scalable 4th Gen', 'memory': 'Up to 8TB DDR5', 'storage': '28x 2.5\" NVMe', 'power': '2000W'}, 'description': '2U ultra NVMe Gen11'},
            {'model_name': 'ProLiant DL385 Gen10 Plus (8 SFF)', 'model_number': 'P18382-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual AMD EPYC 7002/7003', 'memory': 'Up to 4TB DDR4', 'storage': '8x 2.5\" SFF', 'power': '800W'}, 'description': '2U AMD server'},
            {'model_name': 'ProLiant DL385 Gen10 Plus (12 LFF)', 'model_number': 'P18383-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual AMD EPYC 7002/7003', 'memory': 'Up to 4TB DDR4', 'storage': '12x 3.5\" LFF', 'power': '800W'}, 'description': '2U AMD LFF server'},
            {'model_name': 'ProLiant DL385 Gen10 Plus (24 SFF)', 'model_number': 'P18384-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual AMD EPYC 7002/7003', 'memory': 'Up to 4TB DDR4', 'storage': '24x 2.5\" SFF', 'power': '1600W'}, 'description': '2U AMD high-density'},
            {'model_name': 'ProLiant DL385 Gen10 Plus (20 NVMe)', 'model_number': 'P18385-B21', 'equipment_type': 'server', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'processor': 'Dual AMD EPYC 7002/7003', 'memory': 'Up to 4TB DDR4', 'storage': '20x 2.5\" NVMe', 'power': '1600W'}, 'description': '2U AMD NVMe server'},
            
            # EliteBook 600/800/1000 Series - 80 models
            {'model_name': 'EliteBook 630 G9', 'model_number': '5Y3P2UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '13.3\" FHD', 'weight': '2.86 lbs'}, 'description': '13.3\" business laptop'},
            {'model_name': 'EliteBook 630 G10', 'model_number': '816J5UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 13th Gen', 'memory': 'Up to 32GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '13.3\" FHD/WUXGA', 'weight': '2.76 lbs'}, 'description': '13.3\" Gen10 business laptop'},
            {'model_name': 'EliteBook 640 G9', 'model_number': '5Y3P8UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD', 'weight': '3.24 lbs'}, 'description': '14\" business laptop'},
            {'model_name': 'EliteBook 640 G10', 'model_number': '816K1UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 13th Gen', 'memory': 'Up to 64GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD/WUXGA', 'weight': '3.17 lbs'}, 'description': '14\" Gen10 business laptop'},
            {'model_name': 'EliteBook 650 G9', 'model_number': '5Y3R1UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD', 'weight': '3.75 lbs'}, 'description': '15.6\" business laptop'},
            {'model_name': 'EliteBook 650 G10', 'model_number': '816K6UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 13th Gen', 'memory': 'Up to 64GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD/WUXGA', 'weight': '3.68 lbs'}, 'description': '15.6\" Gen10 business laptop'},
            {'model_name': 'EliteBook 830 G7', 'model_number': '1J6G4UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 10th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '13.3\" FHD', 'weight': '2.75 lbs'}, 'description': '13.3\" premium business laptop'},
            {'model_name': 'EliteBook 830 G8', 'model_number': '336J2UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 11th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '13.3\" FHD', 'weight': '2.71 lbs'}, 'description': '13.3\" G8 premium business laptop'},
            {'model_name': 'EliteBook 830 G9', 'model_number': '5Y3T4UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '13.3\" FHD', 'weight': '2.68 lbs'}, 'description': '13.3\" G9 premium business laptop'},
            {'model_name': 'EliteBook 830 G10', 'model_number': '816L2UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7/i9 13th Gen', 'memory': 'Up to 64GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '13.3\" FHD/WUXGA/WQXGA', 'weight': '2.65 lbs'}, 'description': '13.3\" G10 premium business laptop'},
            {'model_name': 'EliteBook 840 G7', 'model_number': '1J6H3UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 10th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD', 'weight': '3.0 lbs'}, 'description': '14\" premium business laptop'},
            {'model_name': 'EliteBook 840 G8', 'model_number': '336K1UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 11th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD', 'weight': '2.95 lbs'}, 'description': '14\" G8 premium business laptop'},
            {'model_name': 'EliteBook 840 G9', 'model_number': '5Y3T9UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD', 'weight': '2.91 lbs'}, 'description': '14\" G9 premium business laptop'},
            {'model_name': 'EliteBook 840 G10', 'model_number': '816L7UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7/i9 13th Gen', 'memory': 'Up to 64GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD/WUXGA/2.8K OLED', 'weight': '2.87 lbs'}, 'description': '14\" G10 premium business laptop'},
            {'model_name': 'EliteBook 850 G7', 'model_number': '1J6J2UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 10th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD', 'weight': '3.68 lbs'}, 'description': '15.6\" premium business laptop'},
            {'model_name': 'EliteBook 850 G8', 'model_number': '336K8UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 11th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD', 'weight': '3.62 lbs'}, 'description': '15.6\" G8 premium business laptop'},
            {'model_name': 'EliteBook 850 G9', 'model_number': '5Y3V5UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD', 'weight': '3.58 lbs'}, 'description': '15.6\" G9 premium business laptop'},
            {'model_name': 'EliteBook 850 G10', 'model_number': '816M3UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7/i9 13th Gen', 'memory': 'Up to 64GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD/WUXGA', 'weight': '3.54 lbs'}, 'description': '15.6\" G10 premium business laptop'},
            {'model_name': 'EliteBook 1030 G3', 'model_number': '3JW94UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 8th Gen', 'memory': 'Up to 16GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '13.3\" FHD touchscreen', 'weight': '2.76 lbs'}, 'description': 'Ultra-premium convertible'},
            {'model_name': 'EliteBook 1040 G7', 'model_number': '1Q6A8UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 10th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD/4K', 'weight': '2.98 lbs'}, 'description': 'Flagship business laptop'},
            {'model_name': 'EliteBook 1040 G8', 'model_number': '336Y2UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 11th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD/4K', 'weight': '2.93 lbs'}, 'description': 'G8 flagship business laptop'},
            {'model_name': 'EliteBook 1040 G9', 'model_number': '5Y3X2UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 12th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD/4K', 'weight': '2.89 lbs'}, 'description': 'G9 flagship business laptop'},
            {'model_name': 'EliteBook 1040 G10', 'model_number': '816N5UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7/i9 13th Gen', 'memory': 'Up to 64GB DDR5', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD/WUXGA/2.8K OLED/4K', 'weight': '2.85 lbs'}, 'description': 'G10 flagship business laptop'},
            
            # ProBook Series - 40 models
            {'model_name': 'ProBook 440 G8', 'model_number': '27H74UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 11th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '14\" HD/FHD', 'weight': '3.2 lbs'}, 'description': 'Entry business laptop'},
            {'model_name': 'ProBook 440 G9', 'model_number': '5Y527UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 12th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '14\" HD/FHD', 'weight': '3.15 lbs'}, 'description': 'G9 entry business laptop'},
            {'model_name': 'ProBook 440 G10', 'model_number': '816P3UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 13th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '14\" HD/FHD', 'weight': '3.1 lbs'}, 'description': 'G10 entry business laptop'},
            {'model_name': 'ProBook 450 G8', 'model_number': '27H82UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 11th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '15.6\" HD/FHD', 'weight': '3.95 lbs'}, 'description': '15.6\" entry business laptop'},
            {'model_name': 'ProBook 450 G9', 'model_number': '5Y534UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 12th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '15.6\" HD/FHD', 'weight': '3.88 lbs'}, 'description': 'G9 15.6\" entry business laptop'},
            {'model_name': 'ProBook 450 G10', 'model_number': '816P9UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 13th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '15.6\" HD/FHD', 'weight': '3.82 lbs'}, 'description': 'G10 15.6\" entry business laptop'},
            {'model_name': 'ProBook 460 G9', 'model_number': '5Y541UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i3/i5/i7 12th Gen', 'memory': 'Up to 32GB DDR4', 'storage': 'Up to 1TB PCIe SSD', 'display': '16\" FHD', 'weight': '4.05 lbs'}, 'description': '16\" business laptop'},
            {'model_name': 'ProBook 640 G8', 'model_number': '250G4UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 11th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '14\" FHD', 'weight': '3.31 lbs'}, 'description': 'Business laptop with security'},
            {'model_name': 'ProBook 650 G8', 'model_number': '250H1UT', 'equipment_type': 'laptop', 'is_rackmount': False, 'specifications': {'processor': 'Intel Core i5/i7 11th Gen', 'memory': 'Up to 64GB DDR4', 'storage': 'Up to 2TB PCIe SSD', 'display': '15.6\" FHD', 'weight': '4.18 lbs'}, 'description': '15.6\" business laptop with security'},

        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"lenovo-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_cisco(self):
        """Seed Cisco networking equipment and VoIP phones."""
        vendor, created = Vendor.objects.get_or_create(
            name='Cisco',
            defaults={
                'slug': slugify('Cisco'),
                'website': 'https://www.cisco.com',
                'support_url': 'https://www.cisco.com/c/en/us/support/',
                'support_phone': '1-800-553-6387',
                'description': 'Enterprise networking equipment and solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Cisco Catalyst 9600 Series - Core/Aggregation Switches
            {
                'model_name': 'Catalyst 9600-LC-24C',
                'model_number': 'C9600-LC-24C',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 100G QSFP28',
                    'switching_capacity': '4.8 Tbps',
                    'forwarding_rate': '3571.4 Mpps',
                    'power': 'AC/DC options',
                },
                'description': 'Catalyst 9600 line card with 24x 100G ports'
            },
            {
                'model_name': 'Catalyst 9600-LC-48YL',
                'model_number': 'C9600-LC-48YL',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 25G SFP28',
                    'switching_capacity': '2.4 Tbps',
                    'forwarding_rate': '1785.7 Mpps',
                    'power': 'AC/DC options',
                },
                'description': 'Catalyst 9600 line card with 48x 25G ports'
            },
            {
                'model_name': 'Catalyst 9600-LC-48TX',
                'model_number': 'C9600-LC-48TX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 10GBASE-T',
                    'switching_capacity': '960 Gbps',
                    'forwarding_rate': '714.3 Mpps',
                    'power': 'AC/DC options',
                },
                'description': 'Catalyst 9600 line card with 48x 10GBASE-T ports'
            },

            # Cisco Catalyst 9500 Series - Core/Distribution Switches
            {
                'model_name': 'Catalyst 9500-12Q',
                'model_number': 'C9500-12Q',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '12x 40G QSFP+',
                    'switching_capacity': '960 Gbps',
                    'forwarding_rate': '714.3 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '12-port 40G modular switch'
            },
            {
                'model_name': 'Catalyst 9500-16X',
                'model_number': 'C9500-16X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '16x 10G SFP+',
                    'switching_capacity': '320 Gbps',
                    'forwarding_rate': '238.1 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '16-port 10G compact core switch'
            },
            {
                'model_name': 'Catalyst 9500-24Y4C',
                'model_number': 'C9500-24Y4C',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 25G SFP28, 4x 100G QSFP28',
                    'switching_capacity': '1.6 Tbps',
                    'forwarding_rate': '1190.5 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '24-port 25G with 4x 100G uplinks'
            },
            {
                'model_name': 'Catalyst 9500-32C',
                'model_number': 'C9500-32C',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '32x 100G QSFP28',
                    'switching_capacity': '6.4 Tbps',
                    'forwarding_rate': '4761.9 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '32-port 100G high-performance core switch'
            },
            {
                'model_name': 'Catalyst 9500-32QC',
                'model_number': 'C9500-32QC',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '32x 40G QSFP+',
                    'switching_capacity': '2.56 Tbps',
                    'forwarding_rate': '1904.8 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '32-port 40G aggregation switch'
            },
            {
                'model_name': 'Catalyst 9500-40X',
                'model_number': 'C9500-40X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '40x 10G SFP+',
                    'switching_capacity': '800 Gbps',
                    'forwarding_rate': '595.2 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '40-port 10G distribution switch'
            },
            {
                'model_name': 'Catalyst 9500-48Y4C',
                'model_number': 'C9500-48Y4C',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 25G SFP28, 4x 100G QSFP28',
                    'switching_capacity': '2.4 Tbps',
                    'forwarding_rate': '1785.7 Mpps',
                    'stacking_bandwidth': '80 Gbps',
                },
                'description': '48-port 25G with 4x 100G uplinks'
            },

            # Cisco Catalyst 9400 Series - Modular Campus Switches
            {
                'model_name': 'Catalyst 9404R',
                'model_number': 'C9404R',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 7,
                'specifications': {
                    'slots': '4 line card slots',
                    'switching_capacity': 'Up to 2.4 Tbps',
                    'forwarding_rate': 'Up to 1785.7 Mpps',
                    'redundancy': 'Redundant supervisor, PSU',
                },
                'description': '4-slot modular campus switch chassis'
            },
            {
                'model_name': 'Catalyst 9407R',
                'model_number': 'C9407R',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 10,
                'specifications': {
                    'slots': '7 line card slots',
                    'switching_capacity': 'Up to 4.2 Tbps',
                    'forwarding_rate': 'Up to 3125 Mpps',
                    'redundancy': 'Redundant supervisor, PSU',
                },
                'description': '7-slot modular campus switch chassis'
            },
            {
                'model_name': 'Catalyst 9410R',
                'model_number': 'C9410R',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 14,
                'specifications': {
                    'slots': '10 line card slots',
                    'switching_capacity': 'Up to 6 Tbps',
                    'forwarding_rate': 'Up to 4464.3 Mpps',
                    'redundancy': 'Redundant supervisor, PSU, fan',
                },
                'description': '10-slot modular campus switch chassis'
            },

            # Cisco Catalyst 9300 Series - Access Switches
            {
                'model_name': 'Catalyst 9300-24U',
                'model_number': 'C9300-24U',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x mGig (100M/1G/2.5G/5G/10G)',
                    'uplinks': 'UPOE+ 4x 10G/25G',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '448 Gbps',
                    'forwarding_rate': '333.3 Mpps'
                },
                'description': '24-port mGig UPOE+ access switch'
            },
            {
                'model_name': 'Catalyst 9300-24UX',
                'model_number': 'C9300-24UX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x mGig (100M/1G/2.5G/5G/10G)',
                    'uplinks': '8x 10G/25G SFP28',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '560 Gbps',
                    'forwarding_rate': '416.7 Mpps'
                },
                'description': '24-port mGig with 8x 25G uplinks'
            },
            {
                'model_name': 'Catalyst 9300-48U',
                'model_number': 'C9300-48U',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x mGig (100M/1G/2.5G/5G/10G)',
                    'uplinks': 'UPOE+ 4x 10G/25G',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '688 Gbps',
                    'forwarding_rate': '511.9 Mpps'
                },
                'description': '48-port mGig UPOE+ access switch'
            },
            {
                'model_name': 'Catalyst 9300-48UX',
                'model_number': 'C9300-48UX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x mGig (100M/1G/2.5G/5G/10G)',
                    'uplinks': '8x 10G/25G SFP28',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '800 Gbps',
                    'forwarding_rate': '595.2 Mpps'
                },
                'description': '48-port mGig with 8x 25G uplinks'
            },
            {
                'model_name': 'Catalyst 9300-24T',
                'model_number': 'C9300-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '4x 10G SFP+',
                    'switching_capacity': '208 Gbps',
                    'forwarding_rate': '154.8 Mpps',
                },
                'description': '24-port 1G access switch'
            },
            {
                'model_name': 'Catalyst 9300-48T',
                'model_number': 'C9300-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 10G SFP+',
                    'switching_capacity': '208 Gbps',
                    'forwarding_rate': '154.8 Mpps',
                },
                'description': '48-port 1G access switch'
            },
            {
                'model_name': 'Catalyst 9300-24P',
                'model_number': 'C9300-24P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '435W',
                    'switching_capacity': '208 Gbps',
                    'forwarding_rate': '154.8 Mpps'
                },
                'description': '24-port 1G PoE+ access switch'
            },
            {
                'model_name': 'Catalyst 9300-48P',
                'model_number': 'C9300-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '715W',
                    'switching_capacity': '208 Gbps',
                    'forwarding_rate': '154.8 Mpps'
                },
                'description': '48-port 1G PoE+ access switch'
            },
            {
                'model_name': 'Catalyst 9300L-24T',
                'model_number': 'C9300L-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G compact access switch'
            },
            {
                'model_name': 'Catalyst 9300L-24P',
                'model_number': 'C9300L-24P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G PoE+ compact switch'
            },
            {
                'model_name': 'Catalyst 9300L-48T',
                'model_number': 'C9300L-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G compact access switch'
            },
            {
                'model_name': 'Catalyst 9300L-48P',
                'model_number': 'C9300L-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G PoE+ compact switch'
            },

            # Cisco Catalyst 9200 Series - Access Switches
            {
                'model_name': 'Catalyst 9200-24T',
                'model_number': 'C9200-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G access layer switch'
            },
            {
                'model_name': 'Catalyst 9200-24P',
                'model_number': 'C9200-24P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G PoE+ access switch'
            },
            {
                'model_name': 'Catalyst 9200-48T',
                'model_number': 'C9200-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G access layer switch'
            },
            {
                'model_name': 'Catalyst 9200-48P',
                'model_number': 'C9200-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '740W',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G PoE+ access switch'
            },
            {
                'model_name': 'Catalyst 9200L-24T',
                'model_number': 'C9200L-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G budget access switch'
            },
            {
                'model_name': 'Catalyst 9200L-24P',
                'model_number': 'C9200L-24P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G PoE+ budget switch'
            },
            {
                'model_name': 'Catalyst 9200L-48T',
                'model_number': 'C9200L-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G budget access switch'
            },
            {
                'model_name': 'Catalyst 9200L-48P',
                'model_number': 'C9200L-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G PoE+ budget switch'
            },

            # Cisco Catalyst 3850 Series
            {
                'model_name': 'Catalyst 3850-12S',
                'model_number': 'WS-C3850-12S',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '12x 1G SFP',
                    'uplinks': '4x 10G SFP+',
                    'switching_capacity': '160 Gbps',
                    'stacking_bandwidth': '480 Gbps',
                },
                'description': '12-port SFP stackable switch'
            },
            {
                'model_name': 'Catalyst 3850-12X48U',
                'model_number': 'WS-C3850-12X48U',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x mGig, 12x 10G SFP+',
                    'poe_budget': '1100W UPOE',
                    'switching_capacity': '440 Gbps',
                    'stacking_bandwidth': '480 Gbps',
                },
                'description': '48-port mGig with 12x 10G SFP+'
            },
            {
                'model_name': 'Catalyst 3850-24T',
                'model_number': 'WS-C3850-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '160 Gbps',
                    'stacking_bandwidth': '480 Gbps',
                },
                'description': '24-port 1G stackable switch'
            },
            {
                'model_name': 'Catalyst 3850-24P',
                'model_number': 'WS-C3850-24P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '435W',
                    'switching_capacity': '160 Gbps',
                    'stacking_bandwidth': '480 Gbps',
                },
                'description': '24-port 1G PoE+ stackable switch'
            },
            {
                'model_name': 'Catalyst 3850-48T',
                'model_number': 'WS-C3850-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '176 Gbps',
                    'stacking_bandwidth': '480 Gbps',
                },
                'description': '48-port 1G stackable switch'
            },
            {
                'model_name': 'Catalyst 3850-48P',
                'model_number': 'WS-C3850-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '715W',
                    'switching_capacity': '176 Gbps',
                    'stacking_bandwidth': '480 Gbps',
                },
                'description': '48-port 1G PoE+ stackable switch'
            },

            # Cisco Catalyst 3650 Series
            {
                'model_name': 'Catalyst 3650-24TD',
                'model_number': 'WS-C3650-24TD',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '2x 10G SFP+',
                    'switching_capacity': '88 Gbps',
                    'stacking_bandwidth': '160 Gbps',
                },
                'description': '24-port 1G with 2x 10G uplinks'
            },
            {
                'model_name': 'Catalyst 3650-24PD',
                'model_number': 'WS-C3650-24PD',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '2x 10G SFP+',
                    'poe_budget': '435W',
                    'switching_capacity': '88 Gbps',
                    'stacking_bandwidth': '160 Gbps',
                },
                'description': '24-port 1G PoE+ with 2x 10G uplinks'
            },
            {
                'model_name': 'Catalyst 3650-48TD',
                'model_number': 'WS-C3650-48TD',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '2x 10G SFP+',
                    'switching_capacity': '176 Gbps',
                    'stacking_bandwidth': '160 Gbps',
                },
                'description': '48-port 1G with 2x 10G uplinks'
            },
            {
                'model_name': 'Catalyst 3650-48PD',
                'model_number': 'WS-C3650-48PD',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '2x 10G SFP+',
                    'poe_budget': '715W',
                    'switching_capacity': '176 Gbps',
                    'stacking_bandwidth': '160 Gbps',
                },
                'description': '48-port 1G PoE+ with 2x 10G uplinks'
            },

            # Cisco Catalyst 2960-X Series
            {
                'model_name': 'Catalyst 2960X-24TS-L',
                'model_number': 'WS-C2960X-24TS-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G access switch'
            },
            {
                'model_name': 'Catalyst 2960X-24PS-L',
                'model_number': 'WS-C2960X-24PS-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '56 Gbps',
                    'forwarding_rate': '41.7 Mpps',
                },
                'description': '24-port 1G PoE+ access switch'
            },
            {
                'model_name': 'Catalyst 2960X-48TS-L',
                'model_number': 'WS-C2960X-48TS-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 1G SFP',
                    'switching_capacity': '104 Gbps',
                    'forwarding_rate': '77.4 Mpps',
                },
                'description': '48-port 1G access switch'
            },
            {
                'model_name': 'Catalyst 2960X-48FPS-L',
                'model_number': 'WS-C2960X-48FPS-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '2x 10G SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '216 Gbps',
                    'forwarding_rate': '160.7 Mpps',
                },
                'description': '48-port 1G PoE+ with 10G uplinks'
            },

            # Cisco Catalyst 9300X Series - Enhanced Access Switches
            {
                'model_name': 'Catalyst 9300X-12Y',
                'model_number': 'C9300X-12Y',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '12x 25G SFP28',
                    'uplinks': '8x 25G SFP28',
                    'switching_capacity': '400 Gbps',
                    'forwarding_rate': '297.6 Mpps',
                },
                'description': '12-port 25G uplink switch'
            },
            {
                'model_name': 'Catalyst 9300X-24Y',
                'model_number': 'C9300X-24Y',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 25G SFP28',
                    'uplinks': '8x 25G SFP28',
                    'switching_capacity': '640 Gbps',
                    'forwarding_rate': '476.2 Mpps',
                },
                'description': '24-port 25G uplink switch'
            },
            {
                'model_name': 'Catalyst 9300X-24HX',
                'model_number': 'C9300X-24HX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x mGig (1G/2.5G/5G/10G)',
                    'uplinks': '8x 10G/25G SFP28',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '480 Gbps',
                    'forwarding_rate': '357.1 Mpps',
                },
                'description': '24-port mGig UPOE+ with 8x 25G uplinks'
            },

            # Cisco Catalyst 1000 Series
            {
                'model_name': 'Catalyst 1000-16T-2G-L',
                'model_number': 'C1000-16T-2G-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '16x 1GbE',
                    'uplinks': '2x 1G SFP',
                    'switching_capacity': '36 Gbps',
                    'forwarding_rate': '26.8 Mpps',
                },
                'description': 'Entry-level 16-port switch'
            },
            {
                'model_name': 'Catalyst 1000-16P-2G-L',
                'model_number': 'C1000-16P-2G-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '16x 1GbE PoE+',
                    'uplinks': '2x 1G SFP',
                    'poe_budget': '120W',
                    'switching_capacity': '36 Gbps',
                    'forwarding_rate': '26.8 Mpps',
                },
                'description': 'Entry-level 16-port PoE+ switch'
            },

            # Cisco Nexus 9000 Data Center Switches
            {
                'model_name': 'Nexus 9300-48T',
                'model_number': 'N9K-C9300-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 10GBASE-T',
                    'uplinks': '6x 40/100G QSFP28',
                    'switching_capacity': '2.16 Tbps',
                    'forwarding_rate': '1607.1 Mpps',
                },
                'description': 'Nexus 9300 48-port 10GBASE-T data center switch'
            },

            # Cisco ISR 4000 Series Routers
            {
                'model_name': 'ISR 4461',
                'model_number': 'ISR4461',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '10 Gbps',
                    'ports': '3x 1GbE',
                    'wan_slots': '4x NIM',
                    'services': 'SD-WAN, security, unified communications',
                    'memory': '16GB DRAM',
                },
                'description': 'High-performance ISR for large branch'
            },
            {
                'model_name': 'ISR 4451',
                'model_number': 'ISR4451',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '5 Gbps',
                    'ports': '3x 1GbE',
                    'wan_slots': '4x NIM, 3x SM',
                    'services': 'SD-WAN, security, unified communications',
                    'memory': '8GB DRAM',
                },
                'description': 'Enterprise ISR for large deployments'
            },
            {
                'model_name': 'ISR 4431',
                'model_number': 'ISR4431',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '3.5 Gbps',
                    'ports': '3x 1GbE',
                    'wan_slots': '4x NIM, 2x SM',
                    'services': 'SD-WAN, security, routing',
                    'memory': '4GB DRAM',
                },
                'description': 'Mid-range ISR for campus/branch'
            },
            {
                'model_name': 'ISR 4351',
                'model_number': 'ISR4351',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '2.5 Gbps',
                    'ports': '3x 1GbE',
                    'wan_slots': '4x NIM, 2x SM',
                    'services': 'SD-WAN, security, routing',
                    'memory': '4GB DRAM',
                },
                'description': 'Branch office ISR with services'
            },
            {
                'model_name': 'ISR 4331',
                'model_number': 'ISR4331',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '2 Gbps',
                    'ports': '3x 1GbE',
                    'wan_slots': '4x NIM, 1x SM',
                    'services': 'SD-WAN, security, routing',
                    'memory': '4GB DRAM',
                },
                'description': 'Compact ISR for medium branch'
            },
            {
                'model_name': 'ISR 4321',
                'model_number': 'ISR4321',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '1.5 Gbps',
                    'ports': '2x 1GbE',
                    'wan_slots': '3x NIM',
                    'services': 'SD-WAN, security, routing',
                    'memory': '4GB DRAM',
                },
                'description': 'Small branch ISR'
            },
            {
                'model_name': 'ISR 4221',
                'model_number': 'ISR4221',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '500 Mbps',
                    'ports': '2x 1GbE',
                    'wan_slots': '2x NIM',
                    'services': 'SD-WAN, security, routing',
                    'memory': '4GB DRAM',
                },
                'description': 'Entry-level ISR for small sites'
            },

            # Cisco ISR 1000 Series Routers
            {
                'model_name': 'ISR 1100-8P',
                'model_number': 'ISR1100-8P',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '1 Gbps',
                    'ports': '8x 1GbE with PoE+',
                    'poe_budget': '120W',
                    'features': 'SD-WAN, integrated switch, WiFi ready',
                    'memory': '4GB DRAM',
                },
                'description': 'Compact SD-WAN router with PoE switch'
            },
            {
                'model_name': 'ISR 1100-6G',
                'model_number': 'ISR1100-6G',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '1 Gbps',
                    'ports': '5x 1GbE, 1x 10G SFP+',
                    'features': 'SD-WAN, integrated services',
                    'memory': '4GB DRAM',
                },
                'description': 'SD-WAN router with 10G uplink'
            },
            {
                'model_name': 'ISR 1100-4G',
                'model_number': 'ISR1100-4G',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '1 Gbps',
                    'ports': '4x 1GbE',
                    'features': 'SD-WAN, integrated services',
                    'memory': '4GB DRAM',
                },
                'description': 'Compact SD-WAN router'
            },
            {
                'model_name': 'ISR 1100-4GLTE',
                'model_number': 'ISR1100-4GLTE',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '1 Gbps',
                    'ports': '4x 1GbE',
                    'cellular': 'Dual LTE Advanced Pro',
                    'features': 'SD-WAN, 5G ready, failover',
                    'memory': '4GB DRAM',
                },
                'description': 'SD-WAN router with dual LTE'
            },
            {
                'model_name': 'ISR 1109-2P',
                'model_number': 'ISR1109-2P',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '500 Mbps',
                    'ports': '2x 1GbE PoE+',
                    'poe_budget': '60W',
                    'features': 'SD-WAN, IoT ready, WiFi ready',
                    'memory': '4GB DRAM',
                },
                'description': 'Ruggedized compact router with PoE'
            },
            {
                'model_name': 'ISR 1109-4P',
                'model_number': 'ISR1109-4P',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '500 Mbps',
                    'ports': '4x 1GbE PoE+',
                    'poe_budget': '90W',
                    'features': 'SD-WAN, IoT ready, WiFi ready',
                    'memory': '4GB DRAM',
                },
                'description': 'Ruggedized router with 4-port PoE'
            },

            # Cisco ASR 1000 Series Routers
            {
                'model_name': 'ASR 1001-X',
                'model_number': 'ASR1001-X',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '20 Gbps',
                    'ports': '6x 1GbE, 2x 10GbE SFP+',
                    'services': 'Aggregation, VPN, QoS',
                    'memory': '8GB DRAM',
                },
                'description': 'Compact edge/aggregation router'
            },
            {
                'model_name': 'ASR 1001-HX',
                'model_number': 'ASR1001-HX',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '40 Gbps',
                    'ports': '8x 1GbE, 4x 10GbE SFP+',
                    'services': 'HyperScale aggregation, VPN, QoS',
                    'memory': '16GB DRAM',
                },
                'description': 'High-performance edge router'
            },
            {
                'model_name': 'ASR 1002-X',
                'model_number': 'ASR1002-X',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '36 Gbps',
                    'ports': '6x 1GbE, 4x 10GbE SFP+',
                    'services': 'Aggregation, VPN, QoS',
                    'memory': '8GB DRAM',
                },
                'description': 'Mid-range aggregation router'
            },
            {
                'model_name': 'ASR 1002-HX',
                'model_number': 'ASR1002-HX',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '100 Gbps',
                    'ports': '8x 1GbE, 6x 10GbE SFP+',
                    'services': 'HyperScale aggregation, VPN, QoS',
                    'memory': '32GB DRAM',
                },
                'description': 'High-performance aggregation router'
            },
            {
                'model_name': 'ASR 1004',
                'model_number': 'ASR1004',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 4,
                'specifications': {
                    'throughput': '100 Gbps',
                    'slots': '4 module slots',
                    'services': 'Aggregation, WAN edge, data center',
                    'redundancy': 'Dual RP, dual PSU',
                },
                'description': '4-slot modular aggregation router'
            },
            {
                'model_name': 'ASR 1006-X',
                'model_number': 'ASR1006-X',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 6,
                'specifications': {
                    'throughput': '160 Gbps',
                    'slots': '6 module slots',
                    'services': 'WAN edge, data center, carrier',
                    'redundancy': 'Dual RP, dual PSU',
                },
                'description': '6-slot modular enterprise router'
            },
            {
                'model_name': 'ASR 1009-X',
                'model_number': 'ASR1009-X',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 9,
                'specifications': {
                    'throughput': '240 Gbps',
                    'slots': '9 module slots',
                    'services': 'Service provider edge, data center',
                    'redundancy': 'Dual RP, dual PSU, dual fan',
                },
                'description': '9-slot modular carrier router'
            },
            {
                'model_name': 'ASR 1013',
                'model_number': 'ASR1013',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 13,
                'specifications': {
                    'throughput': '400 Gbps',
                    'slots': '13 module slots',
                    'services': 'Service provider core/edge, DC interconnect',
                    'redundancy': 'Full N+1 redundancy',
                },
                'description': '13-slot modular carrier-grade router'
            },

            # Cisco IP Phones 8800 Series
            {
                'model_name': 'IP Phone 8865',
                'model_number': '8865',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" WVGA color touchscreen',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD video 720p, Bluetooth, WiFi, USB',
                    'codec': 'G.711, G.722, G.729, Opus',
                },
                'description': 'Executive IP phone with HD video'
            },
            {
                'model_name': 'IP Phone 8861',
                'model_number': '8861',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" WVGA color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, Bluetooth, WiFi, USB',
                    'codec': 'G.711, G.722, G.729, Opus',
                },
                'description': 'Premium business IP phone'
            },
            {
                'model_name': 'IP Phone 8851',
                'model_number': '8851',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" WVGA color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, USB',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Mid-range color IP phone'
            },
            {
                'model_name': 'IP Phone 8845',
                'model_number': '8845',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" WVGA color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, Bluetooth, USB',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Business IP phone with Bluetooth'
            },
            {
                'model_name': 'IP Phone 8841',
                'model_number': '8841',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" WVGA color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Standard business IP phone'
            },
            {
                'model_name': 'IP Phone 8832',
                'model_number': '8832',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '1 line',
                    'type': 'Conference phone',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, daisy-chain mics, Bluetooth',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Premium conference phone with HD audio'
            },
            {
                'model_name': 'IP Phone 8831',
                'model_number': '8831',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '1 line',
                    'type': 'Conference phone',
                    'network': 'Single 10/100/1000 port',
                    'poe': '802.3af',
                    'features': 'HD audio, 360-degree coverage',
                    'codec': 'G.711, G.722',
                },
                'description': 'Conference phone for small to mid rooms'
            },
            {
                'model_name': 'IP Phone 8821',
                'model_number': '8821',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 lines',
                    'type': 'Wireless phone',
                    'display': '2.4" QVGA color display',
                    'wireless': '802.11a/b/g/n/ac',
                    'features': 'HD audio, ruggedized, 10+ hours battery',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Wireless IP phone for mobility'
            },
            {
                'model_name': 'IP Phone 8811',
                'model_number': '8811',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': 'Grayscale 396x162 display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Value IP phone with grayscale display'
            },

            # Cisco IP Phones 7800 Series
            {
                'model_name': 'IP Phone 7861',
                'model_number': '7861',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 lines',
                    'display': 'Grayscale 396x162 display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'Full-duplex speakerphone, USB',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Mid-range IP phone'
            },
            {
                'model_name': 'IP Phone 7841',
                'model_number': '7841',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 lines',
                    'display': 'Grayscale 396x162 display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'Full-duplex speakerphone',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Standard business IP phone'
            },
            {
                'model_name': 'IP Phone 7832',
                'model_number': '7832',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '1 line',
                    'type': 'Conference phone',
                    'display': 'Monochrome display',
                    'network': 'Single 10/100 port',
                    'poe': '802.3af',
                    'features': '360-degree coverage, daisy-chain',
                    'codec': 'G.711, G.722',
                },
                'description': 'Conference phone for mid-size rooms'
            },
            {
                'model_name': 'IP Phone 7821',
                'model_number': '7821',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '2 lines',
                    'display': 'Grayscale 396x162 display',
                    'network': 'Dual 10/100 ports',
                    'poe': '802.3af',
                    'features': 'Half-duplex speakerphone',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Entry-level IP phone'
            },
            {
                'model_name': 'IP Phone 7811',
                'model_number': '7811',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '1 line',
                    'display': 'Grayscale 396x162 display',
                    'network': 'Single 10/100 port',
                    'poe': '802.3af',
                    'features': 'Fixed keys',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Basic single-line IP phone'
            },

            # Cisco IP Phones 6800 Series
            {
                'model_name': 'IP Phone 6871',
                'model_number': '6871',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '3.5" QVGA color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, Bluetooth, WiFi, USB',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Premium multiplatform IP phone'
            },
            {
                'model_name': 'IP Phone 6861',
                'model_number': '6861',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '3.5" QVGA color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, USB',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Mid-range multiplatform IP phone'
            },
            {
                'model_name': 'IP Phone 6851',
                'model_number': '6851',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': 'Grayscale display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Standard multiplatform IP phone'
            },
            {
                'model_name': 'IP Phone 6841',
                'model_number': '6841',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 lines',
                    'display': 'Grayscale display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio',
                    'codec': 'G.711, G.722, G.729',
                },
                'description': 'Entry multiplatform IP phone'
            },
            {
                'model_name': 'IP Phone 6821',
                'model_number': '6821',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '2 lines',
                    'display': 'Monochrome display',
                    'network': 'Dual 10/100 ports',
                    'poe': '802.3af',
                    'features': 'Basic audio',
                    'codec': 'G.711, G.722',
                },
                'description': 'Basic multiplatform IP phone'
            },

            # Cisco Webex Devices
            {
                'model_name': 'Webex Desk Pro',
                'model_number': 'Desk Pro',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'All-in-one collaboration device',
                    'display': '24" 1920x1080 touchscreen',
                    'camera': '4K ultra HD camera with AI',
                    'audio': 'Integrated speakers and microphone array',
                    'network': 'WiFi 6, Bluetooth, Ethernet',
                    'features': 'Webex, MS Teams, Zoom certified',
                },
                'description': 'Premium all-in-one collaboration device'
            },
            {
                'model_name': 'Webex Desk',
                'model_number': 'Desk',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Personal collaboration device',
                    'display': '15.6" 1920x1080 touchscreen',
                    'camera': '1080p HD camera',
                    'audio': 'Integrated speakers and microphone',
                    'network': 'WiFi 6, Bluetooth, Ethernet',
                    'features': 'Webex, digital signage',
                },
                'description': 'Personal collaboration device for desk'
            },
            {
                'model_name': 'Webex Desk Mini',
                'model_number': 'Desk Mini',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Compact collaboration device',
                    'display': '10.1" 1280x800 touchscreen',
                    'camera': '720p HD camera',
                    'audio': 'Integrated speakers and microphone',
                    'network': 'WiFi, Bluetooth, Ethernet',
                    'features': 'Webex, hot desking',
                },
                'description': 'Compact desk collaboration device'
            },
            {
                'model_name': 'Webex Desk Limited Edition',
                'model_number': 'Desk Limited Edition',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Premium personal device',
                    'display': '24" 4K touchscreen',
                    'camera': '4K ultra HD camera with AI',
                    'audio': 'Premium audio with noise cancellation',
                    'network': 'WiFi 6, Bluetooth 5.0, Ethernet',
                    'features': 'Webex, MS Teams, executive features',
                },
                'description': 'Executive collaboration device'
            },
            {
                'model_name': 'Webex Room Kit',
                'model_number': 'Room Kit',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Room collaboration system',
                    'camera': '4K ultra HD camera with 5x zoom',
                    'codec': 'Integrated codec',
                    'audio': 'Microphone array, integrated speakers',
                    'network': 'Ethernet',
                    'features': 'Webex, MS Teams, AI tracking',
                },
                'description': 'All-in-one room collaboration system'
            },
            {
                'model_name': 'Webex Room Kit Mini',
                'model_number': 'Room Kit Mini',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Small room system',
                    'camera': '4K ultra HD camera with 120-degree FOV',
                    'codec': 'Integrated codec',
                    'audio': 'Microphone array, external speakers',
                    'network': 'Ethernet',
                    'features': 'Webex, MS Teams, huddle rooms',
                },
                'description': 'Compact room system for small spaces'
            },
            {
                'model_name': 'Webex Room 55',
                'model_number': 'Room 55',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Integrated room system',
                    'display': '55" 4K display',
                    'camera': '4K ultra HD camera',
                    'codec': 'Integrated codec',
                    'audio': 'Integrated speakers and microphone array',
                    'features': 'Webex, MS Teams, medium rooms',
                },
                'description': '55-inch integrated room system'
            },
            {
                'model_name': 'Webex Room 70',
                'model_number': 'Room 70',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'type': 'Large room system',
                    'display': 'Dual 70" 4K displays or single 85"',
                    'camera': '4K ultra HD camera with AI',
                    'codec': 'Integrated codec',
                    'audio': 'Premium speakers and microphone array',
                    'features': 'Webex, MS Teams, large conference rooms',
                },
                'description': '70-inch integrated large room system'
            },

            # Catalyst 9200 Series - Access Switches
            {
                'model_name': 'Catalyst 9200-24P',
                'model_number': 'C9200-24P-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '440W PoE+',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                    'stacking': 'StackWise-160',
                },
                'description': '24-port Gigabit switch with 440W PoE+'
            },
            {
                'model_name': 'Catalyst 9200-24P (Enhanced)',
                'model_number': 'C9200-24P-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '740W PoE+',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                    'stacking': 'StackWise-160',
                },
                'description': '24-port Gigabit switch with 740W PoE+'
            },
            {
                'model_name': 'Catalyst 9200-24T',
                'model_number': 'C9200-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': 'None',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                    'stacking': 'StackWise-160',
                },
                'description': '24-port Gigabit switch without PoE'
            },
            {
                'model_name': 'Catalyst 9200-48P',
                'model_number': 'C9200-48P-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '440W PoE+',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                    'stacking': 'StackWise-160',
                },
                'description': '48-port Gigabit switch with 440W PoE+'
            },
            {
                'model_name': 'Catalyst 9200-48P (Enhanced)',
                'model_number': 'C9200-48P-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '740W PoE+',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                    'stacking': 'StackWise-160',
                },
                'description': '48-port Gigabit switch with 740W PoE+'
            },
            {
                'model_name': 'Catalyst 9200-48T',
                'model_number': 'C9200-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': 'None',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                    'stacking': 'StackWise-160',
                },
                'description': '48-port Gigabit switch without PoE'
            },
            {
                'model_name': 'Catalyst 9200L-24P-4G',
                'model_number': 'C9200L-24P-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                },
                'description': '24-port Gigabit lite switch with 370W PoE+'
            },
            {
                'model_name': 'Catalyst 9200L-24P-4X',
                'model_number': 'C9200L-24P-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '128 Gbps',
                    'throughput': '95.2 Mpps',
                },
                'description': '24-port Gigabit lite switch with 10G uplinks'
            },
            {
                'model_name': 'Catalyst 9200L-24T-4G',
                'model_number': 'C9200L-24T-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': 'None',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                },
                'description': '24-port Gigabit lite switch without PoE'
            },
            {
                'model_name': 'Catalyst 9200L-24T-4X',
                'model_number': 'C9200L-24T-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': 'None',
                    'switching_capacity': '128 Gbps',
                    'throughput': '95.2 Mpps',
                },
                'description': '24-port Gigabit lite switch with 10G uplinks'
            },
            {
                'model_name': 'Catalyst 9200L-48P-4G',
                'model_number': 'C9200L-48P-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                },
                'description': '48-port Gigabit lite switch with 370W PoE+'
            },
            {
                'model_name': 'Catalyst 9200L-48P-4X',
                'model_number': 'C9200L-48P-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '176 Gbps',
                    'throughput': '131 Mpps',
                },
                'description': '48-port Gigabit lite switch with 10G uplinks'
            },
            {
                'model_name': 'Catalyst 9200L-48T-4G',
                'model_number': 'C9200L-48T-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': 'None',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                },
                'description': '48-port Gigabit lite switch without PoE'
            },
            {
                'model_name': 'Catalyst 9200L-48T-4X',
                'model_number': 'C9200L-48T-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': 'None',
                    'switching_capacity': '176 Gbps',
                    'throughput': '131 Mpps',
                },
                'description': '48-port Gigabit lite switch with 10G uplinks'
            },

            # Catalyst 9300 Series - Distribution/Access Switches
            {
                'model_name': 'Catalyst 9300-24P (440W PoE)',
                'model_number': 'C9300-24P-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '440W PoE+',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port Gigabit switch with 440W PoE+'
            },
            {
                'model_name': 'Catalyst 9300-24P (740W PoE)',
                'model_number': 'C9300-24P-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '740W PoE+',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port Gigabit switch with 740W PoE+'
            },
            {
                'model_name': 'Catalyst 9300-24T',
                'model_number': 'C9300-24T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': 'None',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port Gigabit switch without PoE'
            },
            {
                'model_name': 'Catalyst 9300-24U (435W UPOE)',
                'model_number': 'C9300-24U-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G mGig',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '435W UPOE',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port multigigabit switch with 435W UPOE'
            },
            {
                'model_name': 'Catalyst 9300-24U (715W UPOE)',
                'model_number': 'C9300-24U-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G mGig',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '715W UPOE',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port multigigabit switch with 715W UPOE'
            },
            {
                'model_name': 'Catalyst 9300-24UX (715W UPOE+)',
                'model_number': 'C9300-24UX-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 10G mGig',
                    'uplinks': '4x 25G SFP28',
                    'poe_budget': '715W UPOE+',
                    'switching_capacity': '464 Gbps',
                    'throughput': '345.2 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port 10G multigigabit switch with 715W UPOE+'
            },
            {
                'model_name': 'Catalyst 9300-24UX (1125W UPOE+)',
                'model_number': 'C9300-24UX-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 10G mGig',
                    'uplinks': '4x 25G SFP28',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '464 Gbps',
                    'throughput': '345.2 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '24-port 10G multigigabit switch with 1125W UPOE+'
            },
            {
                'model_name': 'Catalyst 9300-48P (440W PoE)',
                'model_number': 'C9300-48P-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '440W PoE+',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port Gigabit switch with 440W PoE+'
            },
            {
                'model_name': 'Catalyst 9300-48P (740W PoE)',
                'model_number': 'C9300-48P-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '740W PoE+',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port Gigabit switch with 740W PoE+'
            },
            {
                'model_name': 'Catalyst 9300-48T',
                'model_number': 'C9300-48T',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': 'None',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port Gigabit switch without PoE'
            },
            {
                'model_name': 'Catalyst 9300-48U (435W UPOE)',
                'model_number': 'C9300-48U-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G mGig',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '435W UPOE',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port multigigabit switch with 435W UPOE'
            },
            {
                'model_name': 'Catalyst 9300-48U (715W UPOE)',
                'model_number': 'C9300-48U-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G mGig',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '715W UPOE',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port multigigabit switch with 715W UPOE'
            },
            {
                'model_name': 'Catalyst 9300-48UX (715W UPOE+)',
                'model_number': 'C9300-48UX-A',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 10G mGig',
                    'uplinks': '4x 25G SFP28',
                    'poe_budget': '715W UPOE+',
                    'switching_capacity': '880 Gbps',
                    'throughput': '654.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port 10G multigigabit switch with 715W UPOE+'
            },
            {
                'model_name': 'Catalyst 9300-48UX (1125W UPOE+)',
                'model_number': 'C9300-48UX-E',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 10G mGig',
                    'uplinks': '4x 25G SFP28',
                    'poe_budget': '1125W UPOE+',
                    'switching_capacity': '880 Gbps',
                    'throughput': '654.8 Mpps',
                    'stacking': 'StackWise-480',
                },
                'description': '48-port 10G multigigabit switch with 1125W UPOE+'
            },
            {
                'model_name': 'Catalyst 9300L-24P-4G',
                'model_number': 'C9300L-24P-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                },
                'description': '24-port Gigabit lite switch with 370W PoE+'
            },
            {
                'model_name': 'Catalyst 9300L-24P-4X',
                'model_number': 'C9300L-24P-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                },
                'description': '24-port Gigabit lite switch with 10G uplinks'
            },
            {
                'model_name': 'Catalyst 9300L-24T-4G',
                'model_number': 'C9300L-24T-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': 'None',
                    'switching_capacity': '56 Gbps',
                    'throughput': '41.7 Mpps',
                },
                'description': '24-port Gigabit lite switch without PoE'
            },
            {
                'model_name': 'Catalyst 9300L-24T-4X',
                'model_number': 'C9300L-24T-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': 'None',
                    'switching_capacity': '208 Gbps',
                    'throughput': '154.8 Mpps',
                },
                'description': '24-port Gigabit lite switch with 10G uplinks'
            },
            {
                'model_name': 'Catalyst 9300L-48P-4G',
                'model_number': 'C9300L-48P-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                },
                'description': '48-port Gigabit lite switch with 370W PoE+'
            },
            {
                'model_name': 'Catalyst 9300L-48P-4X',
                'model_number': 'C9300L-48P-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '370W PoE+',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                },
                'description': '48-port Gigabit lite switch with 10G uplinks'
            },
            {
                'model_name': 'Catalyst 9300L-48T-4G',
                'model_number': 'C9300L-48T-4G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 1G',
                    'poe_budget': 'None',
                    'switching_capacity': '104 Gbps',
                    'throughput': '77.4 Mpps',
                },
                'description': '48-port Gigabit lite switch without PoE'
            },
            {
                'model_name': 'Catalyst 9300L-48T-4X',
                'model_number': 'C9300L-48T-4X',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1G',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': 'None',
                    'switching_capacity': '368 Gbps',
                    'throughput': '273.8 Mpps',
                },
                'description': '48-port Gigabit lite switch with 10G uplinks'
            },

            # Additional Nexus 9300 Series
            {
                'model_name': 'Nexus 93180YC-FX',
                'model_number': 'N9K-C93180YC-FX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1/10/25G SFP28, 6x 40/100G QSFP28',
                    'switching_capacity': '3.6 Tbps',
                    'latency': '< 2 microseconds',
                },
                'description': 'Nexus 9300 FX 25G ToR switch'
            },
            {
                'model_name': 'Nexus 93180YC-EX',
                'model_number': 'N9K-C93180YC-EX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1/10/25G SFP28, 6x 40/100G QSFP28',
                    'switching_capacity': '3.6 Tbps',
                },
                'description': 'Nexus 9300 EX 25G ToR switch'
            },
            {
                'model_name': 'Nexus 93240YC-FX2',
                'model_number': 'N9K-C93240YC-FX2',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1/10/25G SFP28, 12x 40/100G QSFP28',
                    'switching_capacity': '5.76 Tbps',
                },
                'description': 'Nexus 9300 FX2 high-density 25G'
            },
            {
                'model_name': 'Nexus 93360YC-FX2',
                'model_number': 'N9K-C93360YC-FX2',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '96x 1/10/25G SFP28, 12x 40/100G QSFP28',
                    'switching_capacity': '7.2 Tbps',
                },
                'description': 'Nexus 9300 ultra-high-density 25G'
            },
            {
                'model_name': 'Nexus 93108TC-FX',
                'model_number': 'N9K-C93108TC-FX',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 10GBASE-T, 6x 40/100G QSFP28',
                    'switching_capacity': '2.16 Tbps',
                },
                'description': 'Nexus 9300 10GBASE-T ToR'
            },
        
            # Additional Cisco ISR Routers - 35 models
            {
                'model_name': 'ISR 1100-4G',
                'model_number': 'C1111-4G',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {'wan': '2x GE', 'lan': '4x GE', 'throughput': '1 Gbps'},
                'description': 'Compact branch router'
            },
            {
                'model_name': 'ISR 1100-8P',
                'model_number': 'C1111-8P',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {'wan': '2x GE', 'lan': '8x GE PoE+', 'throughput': '1 Gbps', 'poe': '120W'},
                'description': 'Branch router with PoE+'
            },
            {
                'model_name': 'ISR 1100-4P',
                'model_number': 'C1111-4P',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {'wan': '2x GE', 'lan': '4x GE PoE+', 'throughput': '1 Gbps', 'poe': '60W'},
                'description': 'Branch router with 4P PoE+'
            },
            {
                'model_name': 'ISR 1100-4PLTELA',
                'model_number': 'C1111-4PLTELA',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {'wan': '2x GE, LTE', 'lan': '4x GE PoE+', 'throughput': '1 Gbps', 'poe': '60W'},
                'description': 'Branch router with LTE'
            },
            {
                'model_name': 'ISR 1100-8PLTELA',
                'model_number': 'C1111-8PLTELA',
                'equipment_type': 'router',
                'is_rackmount': False,
                'specifications': {'wan': '2x GE, LTE', 'lan': '8x GE PoE+', 'throughput': '1 Gbps', 'poe': '120W'},
                'description': 'Branch router with 8P PoE+ and LTE'
            },
            {
                'model_name': 'ISR 1117-4P',
                'model_number': 'C1117-4P',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '2x GE', 'lan': '4x GE PoE+', 'throughput': '2 Gbps', 'poe': '60W'},
                'description': '1RU branch router with PoE+'
            },
            {
                'model_name': 'ISR 1117-4PM',
                'model_number': 'C1117-4PM',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '2x GE, LTE', 'lan': '4x GE PoE+', 'throughput': '2 Gbps', 'poe': '120W'},
                'description': '1RU branch router with LTE'
            },
            {
                'model_name': 'ISR 1117-4PLTELA',
                'model_number': 'C1117-4PLTELA',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '2x GE, LTE', 'lan': '4x GE PoE+', 'throughput': '2 Gbps', 'poe': '60W'},
                'description': '1RU industrial router with LTE'
            },
            {
                'model_name': 'ISR 1161-8P',
                'model_number': 'C1161-8P',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '2x GE', 'lan': '8x GE PoE+', 'throughput': '4 Gbps', 'poe': '240W'},
                'description': 'Industrial router with high PoE'
            },
            {
                'model_name': 'ISR 1161X-8P',
                'model_number': 'C1161X-8P',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '2x GE, 5G', 'lan': '8x GE PoE+', 'throughput': '4 Gbps', 'poe': '240W'},
                'description': 'Industrial router with 5G'
            },
            {
                'model_name': 'ISR 4221',
                'model_number': 'ISR4221/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '3x GE', 'throughput': '2 Gbps', 'modules': '2 NIM, 1 SM'},
                'description': 'Entry ISR 4000 router'
            },
            {
                'model_name': 'ISR 4221X',
                'model_number': 'ISR4221X/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '3x GE', 'throughput': '2 Gbps', 'modules': '2 NIM, 2 SM'},
                'description': 'Enhanced ISR 4221'
            },
            {
                'model_name': 'ISR 4321',
                'model_number': 'ISR4321/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '3x GE', 'throughput': '4 Gbps', 'modules': '3 NIM, 2 SM'},
                'description': 'Mid-range ISR 4000 router'
            },
            {
                'model_name': 'ISR 4331',
                'model_number': 'ISR4331/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {'wan': '3x GE', 'throughput': '4 Gbps', 'modules': '3 NIM, 2 SM, 1 ISC'},
                'description': 'Performance ISR 4000 router'
            },
            {
                'model_name': 'ISR 4351',
                'model_number': 'ISR4351/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {'wan': '3x GE', 'throughput': '10 Gbps', 'modules': '3 NIM, 3 SM, 2 ISC'},
                'description': 'High-performance ISR 4000'
            },
            {
                'model_name': 'ISR 4431',
                'model_number': 'ISR4431/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {'wan': '3x GE', 'throughput': '10 Gbps', 'modules': '3 NIM, 3 SM, 2 ISC'},
                'description': 'Enterprise ISR 4000 router'
            },
            {
                'model_name': 'ISR 4451-X',
                'model_number': 'ISR4451-X/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 3,
                'specifications': {'wan': '3x GE', 'throughput': '20 Gbps', 'modules': '3 NIM, 4 SM, 3 ISC'},
                'description': 'High-end ISR 4000 router'
            },
            {
                'model_name': 'ISR 4461',
                'model_number': 'ISR4461/K9',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 3,
                'specifications': {'wan': '3x GE', 'throughput': '20 Gbps', 'modules': '3 NIM, 4 SM, 3 ISC'},
                'description': 'Flagship ISR 4000 router'
            },

        
            # Cisco IP Phones 6800/7800/8800 Series - 16 models
            {'model_name': 'IP Phone 6821', 'model_number': 'CP-6821-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '2', 'display': '3.5\" grayscale', 'poe': '802.3af'}, 'description': 'Entry IP phone'},
            {'model_name': 'IP Phone 6841', 'model_number': 'CP-6841-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '4', 'display': '3.5\" grayscale', 'poe': '802.3af'}, 'description': 'Standard IP phone'},
            {'model_name': 'IP Phone 6851', 'model_number': 'CP-6851-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '10', 'display': '3.5\" color', 'poe': '802.3af'}, 'description': 'Mid-range IP phone'},
            {'model_name': 'IP Phone 6861', 'model_number': 'CP-6861-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '16', 'display': '5\" VGA', 'poe': '802.3af'}, 'description': 'Advanced IP phone'},
            {'model_name': 'IP Phone 6871', 'model_number': 'CP-6871-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '24', 'display': '5\" VGA', 'poe': '802.3af'}, 'description': 'Premium IP phone'},
            {'model_name': 'IP Phone 7811', 'model_number': 'CP-7811-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '1', 'display': '3.5\" grayscale', 'poe': '802.3af'}, 'description': 'Basic IP phone'},
            {'model_name': 'IP Phone 7821', 'model_number': 'CP-7821-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '2', 'display': '3.5\" grayscale', 'poe': '802.3af'}, 'description': 'Entry dual-line phone'},
            {'model_name': 'IP Phone 7841', 'model_number': 'CP-7841-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '4', 'display': '3.5\" grayscale', 'poe': '802.3af'}, 'description': 'Mid-range phone'},
            {'model_name': 'IP Phone 7861', 'model_number': 'CP-7861-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '16', 'display': '5\" WVGA', 'poe': '802.3af'}, 'description': 'Advanced phone'},
            {'model_name': 'IP Phone 8811', 'model_number': 'CP-8811-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af'}, 'description': 'Executive phone'},
            {'model_name': 'IP Phone 8841', 'model_number': 'CP-8841-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af', 'features': 'Bluetooth'}, 'description': 'Executive phone with BT'},
            {'model_name': 'IP Phone 8845', 'model_number': 'CP-8845-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af', 'features': 'Video, Bluetooth'}, 'description': 'Video IP phone'},
            {'model_name': 'IP Phone 8851', 'model_number': 'CP-8851-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af', 'features': 'WiFi'}, 'description': 'WiFi IP phone'},
            {'model_name': 'IP Phone 8861', 'model_number': 'CP-8861-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af', 'features': 'WiFi, Bluetooth'}, 'description': 'Premium IP phone'},
            {'model_name': 'IP Phone 8865', 'model_number': 'CP-8865-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af', 'features': 'Video, WiFi, Bluetooth'}, 'description': 'Flagship video phone'},
            {'model_name': 'IP Phone 8865NR', 'model_number': 'CP-8865NR-K9', 'equipment_type': 'phone', 'is_rackmount': False, 'specifications': {'lines': '5', 'display': '5\" WVGA', 'poe': '802.3af', 'features': 'Video, WiFi, Bluetooth, NFC'}, 'description': 'Flagship phone with NFC'},
            
            # Catalyst 9100 Wireless APs - 25 models
            {'model_name': 'Catalyst 9105AXI', 'model_number': 'C9105AXI-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '1.5 Gbps', 'mimo': '2x2', 'poe': '802.3at'}, 'description': 'WiFi 6 indoor AP'},
            {'model_name': 'Catalyst 9105AXE', 'model_number': 'C9105AXE-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '1.5 Gbps', 'mimo': '2x2', 'poe': '802.3at'}, 'description': 'WiFi 6 external AP'},
            {'model_name': 'Catalyst 9105AXW', 'model_number': 'C9105AXW-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '1.5 Gbps', 'mimo': '2x2', 'poe': '802.3at'}, 'description': 'WiFi 6 wall AP'},
            {'model_name': 'Catalyst 9115AXI', 'model_number': 'C9115AXI-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '3.9 Gbps', 'mimo': '4x4', 'poe': '802.3at'}, 'description': 'WiFi 6 high-perf indoor'},
            {'model_name': 'Catalyst 9115AXE', 'model_number': 'C9115AXE-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '3.9 Gbps', 'mimo': '4x4', 'poe': '802.3at'}, 'description': 'WiFi 6 high-perf external'},
            {'model_name': 'Catalyst 9115AXW', 'model_number': 'C9115AXW-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '3.9 Gbps', 'mimo': '4x4', 'poe': '802.3at'}, 'description': 'WiFi 6 high-perf wall'},
            {'model_name': 'Catalyst 9117AXI', 'model_number': 'C9117AXI-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '4.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'Enterprise WiFi 6 indoor'},
            {'model_name': 'Catalyst 9117AXE', 'model_number': 'C9117AXE-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '4.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'Enterprise WiFi 6 external'},
            {'model_name': 'Catalyst 9117AXW', 'model_number': 'C9117AXW-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '4.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'Enterprise WiFi 6 wall'},
            {'model_name': 'Catalyst 9120AXI', 'model_number': 'C9120AXI-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '5.4 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'Premium WiFi 6 indoor'},
            {'model_name': 'Catalyst 9120AXE', 'model_number': 'C9120AXE-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '5.4 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'Premium WiFi 6 external'},
            {'model_name': 'Catalyst 9120AXP', 'model_number': 'C9120AXP-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6', 'bands': 'Dual', 'max_rate': '5.4 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'Premium WiFi 6 plenum'},
            {'model_name': 'Catalyst 9124AXI', 'model_number': 'C9124AXI-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '7.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'WiFi 6E indoor AP'},
            {'model_name': 'Catalyst 9124AXE', 'model_number': 'C9124AXE-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '7.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'WiFi 6E external AP'},
            {'model_name': 'Catalyst 9124AXD', 'model_number': 'C9124AXD-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '7.8 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'WiFi 6E directional AP'},
            {'model_name': 'Catalyst 9130AXI', 'model_number': 'C9130AXI-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '10.4 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'Premium WiFi 6E indoor'},
            {'model_name': 'Catalyst 9130AXE', 'model_number': 'C9130AXE-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '10.4 Gbps', 'mimo': '4x4', 'poe': '802.3bt'}, 'description': 'Premium WiFi 6E external'},
            {'model_name': 'Catalyst 9136I', 'model_number': 'C9136I-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '15.7 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'Flagship WiFi 6E indoor'},
            {'model_name': 'Catalyst 9136E', 'model_number': 'C9136E-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '15.7 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'Flagship WiFi 6E external'},
            {'model_name': 'Catalyst 9162I', 'model_number': 'C9162I-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 6E', 'bands': 'Tri-band', 'max_rate': '18 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'Ultra-high-density WiFi 6E'},
            {'model_name': 'Catalyst 9164I', 'model_number': 'C9164I-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 7', 'bands': 'Tri-band', 'max_rate': '23 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'WiFi 7 flagship indoor'},
            {'model_name': 'Catalyst 9164E', 'model_number': 'C9164E-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 7', 'bands': 'Tri-band', 'max_rate': '23 Gbps', 'mimo': '8x8', 'poe': '802.3bt'}, 'description': 'WiFi 7 flagship external'},
            {'model_name': 'Catalyst 9166I', 'model_number': 'C9166I-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 7', 'bands': 'Tri-band', 'max_rate': '30 Gbps', 'mimo': '16x16', 'poe': '802.3bt'}, 'description': 'WiFi 7 ultra-capacity'},
            {'model_name': 'Catalyst 9166E', 'model_number': 'C9166E-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 7', 'bands': 'Tri-band', 'max_rate': '30 Gbps', 'mimo': '16x16', 'poe': '802.3bt'}, 'description': 'WiFi 7 ultra-cap external'},
            {'model_name': 'Catalyst 9178I', 'model_number': 'C9178I-A', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'radio': 'WiFi 7', 'bands': 'Tri-band', 'max_rate': '40 Gbps', 'mimo': '16x16', 'poe': '802.3bt'}, 'description': 'Next-gen WiFi 7 indoor'},

        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"cisco-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_ubiquiti(self):
        """Seed Ubiquiti networking equipment."""
        vendor, created = Vendor.objects.get_or_create(
            name='Ubiquiti',
            defaults={
                'slug': slugify('Ubiquiti'),
                'website': 'https://www.ui.com',
                'support_url': 'https://help.ui.com',
                'description': 'Affordable enterprise networking and wireless solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            {
                'model_name': 'UniFi Switch Pro 48 PoE',
                'model_number': 'USW-Pro-48-POE',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '600W',
                    'switching_capacity': '120 Gbps'
                },
                'description': 'Layer 3 managed switch with PoE+'
            },
            {
                'model_name': 'UniFi Switch 24 PoE',
                'model_number': 'USW-24-POE',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '2x 1GbE SFP',
                    'poe_budget': '95W',
                    'switching_capacity': '52 Gbps'
                },
                'description': 'Managed switch with PoE+ for SMB'
            },
            {
                'model_name': 'Dream Machine Pro',
                'model_number': 'UDM-Pro',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '3.5 Gbps',
                    'ports': '1x WAN, 1x SFP+ WAN, 8x 1GbE LAN, 1x SFP+ LAN',
                    'features': 'Built-in controller, IPS/IDS, VPN'
                },
                'description': 'All-in-one security gateway and controller'
            },
            {
                'model_name': 'UniFi AP-AC-Pro',
                'model_number': 'UAP-AC-PRO',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': '802.11ac Wave 2',
                    'throughput': '1.7 Gbps',
                    'clients': '200+ concurrent',
                    'poe': '802.3af'
                },
                'description': 'Dual-band wireless access point'
            },

            # UniFi Dream Machine Series
            {'model_name': 'UniFi Dream Machine', 'model_number': 'UDM', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '850 Mbps', 'switching': '4x 1GbE', 'wifi': 'Wi-Fi 5'}, 'description': 'All-in-one gateway'},
            {'model_name': 'UniFi Dream Machine Pro', 'model_number': 'UDM-Pro', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3.5 Gbps', 'switching': '8x 1GbE, 2x 10GbE SFP+'}, 'description': 'Pro rackmount gateway'},
            {'model_name': 'UniFi Dream Machine SE', 'model_number': 'UDM-SE', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3.5 Gbps', 'switching': '8x 2.5GbE, 2x 10GbE SFP+'}, 'description': 'Special Edition gateway'},
            {'model_name': 'UniFi Dream Machine Pro Max', 'model_number': 'UDM-Pro-Max', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '10 Gbps', 'switching': '8x 2.5GbE, 2x 10GbE SFP+'}, 'description': 'Maximum UDM'},
            {'model_name': 'UniFi Dream Wall', 'model_number': 'UDW', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'switching': '4x 1GbE', 'wifi': 'Wi-Fi 6', 'poe': 'Yes'}, 'description': 'Wall-mount gateway'},
            # UniFi Gateways
            {'model_name': 'UniFi Security Gateway', 'model_number': 'USG', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1 Gbps', 'ports': '3x 1GbE'}, 'description': 'Basic gateway'},
            {'model_name': 'UniFi Security Gateway Pro', 'model_number': 'USG-Pro-4', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2 Gbps', 'ports': '2x 1GbE WAN, 2x 1GbE LAN, 2x SFP'}, 'description': 'Pro gateway'},
            {'model_name': 'UXG-Pro', 'model_number': 'UXG-Pro', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '10 Gbps', 'ports': '2x 10GbE SFP+, 1x 1GbE'}, 'description': 'Next-gen gateway'},
            {'model_name': 'UXG-Lite', 'model_number': 'UXG-Lite', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1 Gbps', 'ports': '2x 1GbE'}, 'description': 'Compact gateway'},
            {'model_name': 'UXG-Max', 'model_number': 'UXG-Max', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '25 Gbps', 'ports': '2x 25GbE SFP28, 8x 2.5GbE'}, 'description': 'Maximum gateway'},
            # UniFi Switches - Standard
            {'model_name': 'USW-Lite-8-PoE', 'model_number': 'USW-Lite-8-PoE', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1GbE PoE+', 'uplinks': '2x 1GbE', 'poe_budget': '52W'}, 'description': '8-port lite PoE'},
            {'model_name': 'USW-Lite-16-PoE', 'model_number': 'USW-Lite-16-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '16x 1GbE PoE+', 'uplinks': '2x 1GbE SFP', 'poe_budget': '45W'}, 'description': '16-port lite PoE'},
            {'model_name': 'USW-24', 'model_number': 'USW-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '2x 1GbE SFP'}, 'description': '24-port managed'},
            {'model_name': 'USW-24-PoE', 'model_number': 'USW-24-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'uplinks': '2x 1GbE SFP', 'poe_budget': '95W'}, 'description': '24-port PoE'},
            {'model_name': 'USW-48', 'model_number': 'USW-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '2x 1GbE SFP, 2x 10GbE SFP+'}, 'description': '48-port managed'},
            {'model_name': 'USW-48-PoE', 'model_number': 'USW-48-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'uplinks': '2x 1GbE SFP, 2x 10GbE SFP+', 'poe_budget': '200W'}, 'description': '48-port PoE'},
            # UniFi Switches - Pro
            {'model_name': 'USW-Pro-24', 'model_number': 'USW-Pro-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '2x 10GbE SFP+'}, 'description': '24-port pro'},
            {'model_name': 'USW-Pro-24-PoE', 'model_number': 'USW-Pro-24-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'uplinks': '2x 10GbE SFP+', 'poe_budget': '400W'}, 'description': '24-port pro PoE'},
            {'model_name': 'USW-Pro-48', 'model_number': 'USW-Pro-48', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 10GbE SFP+'}, 'description': '48-port pro'},
            {'model_name': 'USW-Pro-48-PoE', 'model_number': 'USW-Pro-48-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'uplinks': '4x 10GbE SFP+', 'poe_budget': '600W'}, 'description': '48-port pro PoE'},
            {'model_name': 'USW-Pro-Max-24', 'model_number': 'USW-Pro-Max-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 2.5GbE', 'uplinks': '2x 10GbE SFP+'}, 'description': '24-port 2.5G'},
            {'model_name': 'USW-Pro-Max-24-PoE', 'model_number': 'USW-Pro-Max-24-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 2.5GbE PoE++', 'uplinks': '2x 10GbE SFP+', 'poe_budget': '400W'}, 'description': '24-port 2.5G PoE++'},
            {'model_name': 'USW-Pro-Max-48-PoE', 'model_number': 'USW-Pro-Max-48-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 2.5GbE PoE++', 'uplinks': '4x 10GbE SFP+', 'poe_budget': '720W'}, 'description': '48-port 2.5G PoE++'},
            # UniFi Switches - Aggregation
            {'model_name': 'USW-Aggregation', 'model_number': 'USW-Aggregation', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '8x 10GbE SFP+'}, 'description': '8-port 10G aggregation'},
            {'model_name': 'USW-Aggregation-Pro', 'model_number': 'USW-Agg-Pro', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '28x 10GbE SFP+'}, 'description': '28-port 10G aggregation'},
            {'model_name': 'USW-Enterprise-8-PoE', 'model_number': 'USW-Enterprise-8-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '8x 2.5GbE PoE++', 'uplinks': '2x 10GbE SFP+', 'poe_budget': '120W'}, 'description': '8-port enterprise PoE++'},
            {'model_name': 'USW-Enterprise-24-PoE', 'model_number': 'USW-Enterprise-24-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 2.5GbE PoE++', 'uplinks': '2x 25GbE SFP28', 'poe_budget': '400W'}, 'description': '24-port enterprise PoE++'},
            {'model_name': 'USW-Enterprise-48-PoE', 'model_number': 'USW-Enterprise-48-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 2.5GbE PoE++', 'uplinks': '4x 25GbE SFP28', 'poe_budget': '720W'}, 'description': '48-port enterprise PoE++'},
            {'model_name': 'USW-Enterprise-XG-24', 'model_number': 'USW-Enterprise-XG-24', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10GbE SFP+', 'uplinks': '2x 25GbE SFP28'}, 'description': '24-port 10G enterprise'},
            # UniFi Access Points - Wi-Fi 6
            {'model_name': 'U6-Lite', 'model_number': 'U6-Lite', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '1.5 Gbps', 'radios': 'Dual-radio 2x2'}, 'description': 'Wi-Fi 6 lite AP'},
            {'model_name': 'U6-LR', 'model_number': 'U6-LR', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '3 Gbps', 'radios': 'Dual-radio 2x2', 'range': 'Long range'}, 'description': 'Wi-Fi 6 long range'},
            {'model_name': 'U6-Pro', 'model_number': 'U6-Pro', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '5.3 Gbps', 'radios': 'Tri-radio 4x4'}, 'description': 'Wi-Fi 6 professional'},
            {'model_name': 'U6-Enterprise', 'model_number': 'U6-Enterprise', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '7.2 Gbps', 'radios': 'Tri-radio 4x4', 'poe': '802.3bt'}, 'description': 'Wi-Fi 6 enterprise'},
            {'model_name': 'U6-Enterprise-IW', 'model_number': 'U6-Enterprise-IW', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '7.2 Gbps', 'mounting': 'In-wall'}, 'description': 'In-wall Wi-Fi 6 enterprise'},
            {'model_name': 'U6-Mesh', 'model_number': 'U6-Mesh', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '3 Gbps', 'deployment': 'Outdoor mesh'}, 'description': 'Outdoor mesh Wi-Fi 6'},
            {'model_name': 'U6-Extender', 'model_number': 'U6-Extender', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '1.5 Gbps', 'form': 'Plug-in'}, 'description': 'Plug-in extender'},
            # UniFi Access Points - Wi-Fi 7
            {'model_name': 'U7-Pro', 'model_number': 'U7-Pro', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 7', 'max_throughput': '9.3 Gbps', 'radios': 'Tri-radio'}, 'description': 'Wi-Fi 7 professional'},
            {'model_name': 'U7-Pro-Max', 'model_number': 'U7-Pro-Max', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 7', 'max_throughput': '12 Gbps', 'radios': 'Tri-radio 4x4'}, 'description': 'Maximum Wi-Fi 7'},
            # UniFi Access Points - Wi-Fi 5 Legacy
            {'model_name': 'UAP-AC-Lite', 'model_number': 'UAP-AC-Lite', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.2 Gbps', 'radios': 'Dual-radio 2x2'}, 'description': 'Wi-Fi 5 lite'},
            {'model_name': 'UAP-AC-LR', 'model_number': 'UAP-AC-LR', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.2 Gbps', 'range': 'Long range'}, 'description': 'Wi-Fi 5 long range'},
            {'model_name': 'UAP-AC-Pro', 'model_number': 'UAP-AC-Pro', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.75 Gbps', 'radios': 'Dual-radio 3x3'}, 'description': 'Wi-Fi 5 professional'},
            {'model_name': 'UAP-AC-HD', 'model_number': 'UAP-AC-HD', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '2.5 Gbps', 'radios': 'Dual-radio 4x4'}, 'description': 'Wi-Fi 5 high density'},
            {'model_name': 'UAP-AC-SHD', 'model_number': 'UAP-AC-SHD', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '2.5 Gbps', 'radios': 'Dual-radio 4x4'}, 'description': 'Wi-Fi 5 super HD'},
            {'model_name': 'UAP-nanoHD', 'model_number': 'UAP-nanoHD', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '2.2 Gbps', 'radios': 'Dual-radio 4x4'}, 'description': 'Compact Wi-Fi 5 HD'},
            {'model_name': 'UAP-Beacon-HD', 'model_number': 'UAP-Beacon-HD', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.7 Gbps', 'form': 'Plug-in'}, 'description': 'Plug-in HD beacon'},
            # UniFi Outdoor APs
            {'model_name': 'UAP-AC-M', 'model_number': 'UAP-AC-M', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'deployment': 'Outdoor', 'max_throughput': '1.2 Gbps'}, 'description': 'Outdoor mesh'},
            {'model_name': 'UAP-AC-M-Pro', 'model_number': 'UAP-AC-M-Pro', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'deployment': 'Outdoor', 'max_throughput': '1.75 Gbps'}, 'description': 'Outdoor mesh pro'},
            {'model_name': 'UAP-FlexHD', 'model_number': 'UAP-FlexHD', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'deployment': 'Indoor/Outdoor', 'max_throughput': '2.2 Gbps'}, 'description': 'Flexible HD AP'},
            {'model_name': 'U6-LR-EA', 'model_number': 'U6-LR-EA', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'deployment': 'Outdoor', 'max_throughput': '3 Gbps'}, 'description': 'Outdoor Wi-Fi 6 LR'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"ubiquiti-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_fortinet(self):
        """Seed Fortinet firewalls."""
        vendor, created = Vendor.objects.get_or_create(
            name='Fortinet',
            defaults={
                'slug': slugify('Fortinet'),
                'website': 'https://www.fortinet.com',
                'support_url': 'https://support.fortinet.com',
                'support_phone': '1-866-648-4638',
                'description': 'Enterprise network security and firewall solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            {
                'model_name': 'FortiGate 60F',
                'model_number': 'FG-60F',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '10 Gbps',
                    'firewall_throughput': '2 Gbps',
                    'ips_throughput': '600 Mbps',
                    'interfaces': '10x 1GbE, 2x WAN',
                    'vpn': 'SSL, IPSec'
                },
                'description': 'Next-generation firewall for small business'
            },
            {
                'model_name': 'FortiGate 100F',
                'model_number': 'FG-100F',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '20 Gbps',
                    'firewall_throughput': '5 Gbps',
                    'ips_throughput': '1.8 Gbps',
                    'interfaces': '16x 1GbE, 2x 10GbE SFP+'
                },
                'description': 'NGFW for mid-size enterprises'
            },
            {
                'model_name': 'FortiGate 200F',
                'model_number': 'FG-200F',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '30 Gbps',
                    'firewall_throughput': '9 Gbps',
                    'ips_throughput': '3.4 Gbps',
                    'interfaces': '18x 1GbE, 2x 10GbE SFP+'
                },
                'description': 'High-performance NGFW for large enterprises'
            },

            # Extended FortiGate F-Series
            {'model_name': 'FortiGate 40F', 'model_number': 'FG-40F', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '5 Gbps', 'firewall_throughput': '1 Gbps', 'ips_throughput': '300 Mbps'}, 'description': 'Entry NGFW'},
            {'model_name': 'FortiGate 60E', 'model_number': 'FG-60E', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '7 Gbps', 'firewall_throughput': '1.5 Gbps'}, 'description': 'SMB NGFW'},
            {'model_name': 'FortiGate 70F', 'model_number': 'FG-70F', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '12 Gbps', 'firewall_throughput': '3 Gbps'}, 'description': 'SMB security gateway'},
            {'model_name': 'FortiGate 80F', 'model_number': 'FG-80F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '15 Gbps', 'firewall_throughput': '4 Gbps'}, 'description': 'Mid-range NGFW'},
            {'model_name': 'FortiGate 90G', 'model_number': 'FG-90G', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '18 Gbps', '5g_support': 'Yes'}, 'description': 'SD-WAN 5G firewall'},
            {'model_name': 'FortiGate 100E', 'model_number': 'FG-100E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '15 Gbps'}, 'description': 'Mid-size enterprise'},
            {'model_name': 'FortiGate 200E', 'model_number': 'FG-200E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '25 Gbps'}, 'description': 'Enterprise NGFW'},
            {'model_name': 'FortiGate 300E', 'model_number': 'FG-300E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '52 Gbps'}, 'description': 'High-performance enterprise'},
            {'model_name': 'FortiGate 400F', 'model_number': 'FG-400F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '60 Gbps'}, 'description': 'Large enterprise NGFW'},
            {'model_name': 'FortiGate 500E', 'model_number': 'FG-500E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '94 Gbps'}, 'description': 'Carrier-grade'},
            {'model_name': 'FortiGate 600F', 'model_number': 'FG-600F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '80 Gbps'}, 'description': 'Data center firewall'},
            {'model_name': 'FortiGate 800F', 'model_number': 'FG-800F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '120 Gbps'}, 'description': 'Enterprise data center'},
            {'model_name': 'FortiGate 1000F', 'model_number': 'FG-1000F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '150 Gbps'}, 'description': 'Large-scale data center'},
            {'model_name': 'FortiGate 1100E', 'model_number': 'FG-1100E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '165 Gbps'}, 'description': 'Hyperscale data center'},
            {'model_name': 'FortiGate 1200D', 'model_number': 'FG-1200D', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '180 Gbps'}, 'description': 'High-density'},
            {'model_name': 'FortiGate 1500D', 'model_number': 'FG-1500D', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '220 Gbps'}, 'description': 'Carrier-class'},
            {'model_name': 'FortiGate 1800F', 'model_number': 'FG-1800F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '260 Gbps'}, 'description': 'Hyperscale gateway'},
            {'model_name': 'FortiGate 2000E', 'model_number': 'FG-2000E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '310 Gbps'}, 'description': 'Service provider'},
            {'model_name': 'FortiGate 2200E', 'model_number': 'FG-2200E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '360 Gbps'}, 'description': 'High-end SP'},
            {'model_name': 'FortiGate 2500E', 'model_number': 'FG-2500E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '420 Gbps'}, 'description': 'Hyperscale SP'},
            {'model_name': 'FortiGate 3000F', 'model_number': 'FG-3000F', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 3, 'specifications': {'throughput': '520 Gbps'}, 'description': 'Carrier hyperscale'},
            {'model_name': 'FortiGate 3100D', 'model_number': 'FG-3100D', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 3, 'specifications': {'throughput': '580 Gbps'}, 'description': 'High-capacity carrier'},
            {'model_name': 'FortiGate 3200D', 'model_number': 'FG-3200D', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 3, 'specifications': {'throughput': '640 Gbps'}, 'description': 'Massive-scale SP'},
            {'model_name': 'FortiGate 3400E', 'model_number': 'FG-3400E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 3, 'specifications': {'throughput': '720 Gbps'}, 'description': 'Maximum capacity'},
            {'model_name': 'FortiGate 3600E', 'model_number': 'FG-3600E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 4, 'specifications': {'throughput': '920 Gbps'}, 'description': 'Flagship platform'},
            {'model_name': 'FortiGate 3700D', 'model_number': 'FG-3700D', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 4, 'specifications': {'throughput': '1 Tbps'}, 'description': 'Terabit gateway'},
            {'model_name': 'FortiGate 3960E', 'model_number': 'FG-3960E', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 4, 'specifications': {'throughput': '1.2 Tbps'}, 'description': 'Maximum performance'},
            # FortiGate VM Series
            {'model_name': 'FortiGate VM01', 'model_number': 'FG-VM01', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '100 Mbps', 'vcpu': '1'}, 'description': 'Virtual - Small'},
            {'model_name': 'FortiGate VM02', 'model_number': 'FG-VM02', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '500 Mbps', 'vcpu': '2'}, 'description': 'Virtual - SMB'},
            {'model_name': 'FortiGate VM04', 'model_number': 'FG-VM04', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '1 Gbps', 'vcpu': '4'}, 'description': 'Virtual - Branch'},
            {'model_name': 'FortiGate VM08', 'model_number': 'FG-VM08', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '2 Gbps', 'vcpu': '8'}, 'description': 'Virtual - Mid-size'},
            {'model_name': 'FortiGate VM16', 'model_number': 'FG-VM16', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '5 Gbps', 'vcpu': '16'}, 'description': 'Virtual - Enterprise'},
            {'model_name': 'FortiGate VM32', 'model_number': 'FG-VM32', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '10 Gbps', 'vcpu': '32'}, 'description': 'Virtual - High-perf'},
            {'model_name': 'FortiGate VM-UL', 'model_number': 'FG-VM-UL', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': 'Unlimited'}, 'description': 'Virtual - Unlimited'},
            # FortiSwitch Series
            {'model_name': 'FortiSwitch 108E', 'model_number': 'FS-108E', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1GbE', 'poe_budget': '60W'}, 'description': '8-port desktop PoE'},
            {'model_name': 'FortiSwitch 108F', 'model_number': 'FS-108F', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1GbE', 'poe_budget': '70W'}, 'description': '8-port desktop PoE'},
            {'model_name': 'FortiSwitch 108F-POE', 'model_number': 'FS-108F-POE', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1GbE PoE+', 'poe_budget': '95W'}, 'description': '8-port desktop PoE+'},
            {'model_name': 'FortiSwitch 124F', 'model_number': 'FS-124F', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 10GbE SFP+'}, 'description': '24-port managed'},
            {'model_name': 'FortiSwitch 124F-POE', 'model_number': 'FS-124F-POE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '370W'}, 'description': '24-port PoE+'},
            {'model_name': 'FortiSwitch 148F', 'model_number': 'FS-148F', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 10GbE SFP+'}, 'description': '48-port managed'},
            {'model_name': 'FortiSwitch 148F-POE', 'model_number': 'FS-148F-POE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '740W'}, 'description': '48-port PoE+'},
            {'model_name': 'FortiSwitch 224E', 'model_number': 'FS-224E', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE'}, 'description': '24-port enterprise'},
            {'model_name': 'FortiSwitch 224E-POE', 'model_number': 'FS-224E-POE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '370W'}, 'description': '24-port enterprise PoE'},
            {'model_name': 'FortiSwitch 248E-POE', 'model_number': 'FS-248E-POE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '740W'}, 'description': '48-port enterprise PoE+'},
            {'model_name': 'FortiSwitch 424E', 'model_number': 'FS-424E', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'stacking': 'Yes'}, 'description': '24-port stackable'},
            {'model_name': 'FortiSwitch 424E-POE', 'model_number': 'FS-424E-POE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '370W', 'stacking': 'Yes'}, 'description': '24-port stackable PoE+'},
            {'model_name': 'FortiSwitch 448E-POE', 'model_number': 'FS-448E-POE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '740W', 'stacking': 'Yes'}, 'description': '48-port stackable PoE+'},
            {'model_name': 'FortiSwitch 524D', 'model_number': 'FS-524D', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10GbE SFP+', 'uplinks': '4x 40GbE QSFP+'}, 'description': '24-port 10G aggregation'},
            {'model_name': 'FortiSwitch 548D', 'model_number': 'FS-548D', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 10GbE SFP+', 'uplinks': '6x 40GbE QSFP+'}, 'description': '48-port 10G aggregation'},
            {'model_name': 'FortiSwitch 1024E', 'model_number': 'FS-1024E', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 10GbE SFP+'}, 'description': '24-port 10G enterprise'},
            {'model_name': 'FortiSwitch 1048E', 'model_number': 'FS-1048E', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 10GbE SFP+'}, 'description': '48-port 10G enterprise'},
            {'model_name': 'FortiSwitch 3032E', 'model_number': 'FS-3032E', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '32x 40GbE QSFP+'}, 'description': '32-port 40G core'},
            # FortiAP Series
            {'model_name': 'FortiAP 231F', 'model_number': 'FAP-231F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '1.775 Gbps'}, 'description': 'Wi-Fi 6 indoor AP'},
            {'model_name': 'FortiAP 234F', 'model_number': 'FAP-234F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '3.55 Gbps'}, 'description': 'High-performance Wi-Fi 6'},
            {'model_name': 'FortiAP 431F', 'model_number': 'FAP-431F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '5.95 Gbps', 'radios': 'Tri-radio'}, 'description': 'Tri-radio Wi-Fi 6'},
            {'model_name': 'FortiAP 432F', 'model_number': 'FAP-432F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '7.8 Gbps', 'radios': 'Tri-radio'}, 'description': 'High-density Wi-Fi 6'},
            {'model_name': 'FortiAP 221E', 'model_number': 'FAP-221E', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.167 Gbps'}, 'description': 'Wi-Fi 5 indoor AP'},
            {'model_name': 'FortiAP 223E', 'model_number': 'FAP-223E', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.733 Gbps'}, 'description': 'Wi-Fi 5 enterprise'},
            {'model_name': 'FortiAP 224E', 'model_number': 'FAP-224E', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '2.533 Gbps'}, 'description': 'High-performance Wi-Fi 5'},
            {'model_name': 'FortiAP 321C', 'model_number': 'FAP-321C', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'deployment': 'Outdoor'}, 'description': 'Outdoor Wi-Fi 5 AP'},
            {'model_name': 'FortiAP 421E', 'model_number': 'FAP-421E', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '4.3 Gbps', 'radios': 'Tri-radio'}, 'description': 'Tri-radio Wi-Fi 5'},
            {'model_name': 'FortiAP 831F', 'model_number': 'FAP-831F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6E', 'max_throughput': '10.8 Gbps', '6ghz_support': 'Yes'}, 'description': 'Wi-Fi 6E high-density'},
            {'model_name': 'FortiAP U431F', 'model_number': 'FAP-U431F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '3.5 Gbps'}, 'description': 'Universal Wi-Fi 6 AP'},
            {'model_name': 'FortiAP U433F', 'model_number': 'FAP-U433F', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '5.4 Gbps', 'radios': 'Tri-radio'}, 'description': 'Universal tri-radio Wi-Fi 6'},
            {'model_name': 'FortiAP 441K', 'model_number': 'FAP-441K', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '7.8 Gbps', 'radios': 'Quad-radio'}, 'description': 'Quad-radio high-capacity'},
            {'model_name': 'FortiAP 231G', 'model_number': 'FAP-231G', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '2.4 Gbps', '5g_support': 'Yes'}, 'description': 'Wi-Fi 6 + 5G AP'},
            {'model_name': 'FortiAP 433G', 'model_number': 'FAP-433G', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '6.0 Gbps', '5g_support': 'Yes'}, 'description': 'Tri-radio Wi-Fi 6 + 5G'},
            {'model_name': 'FortiExtender 201F', 'model_number': 'FX-201F', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'connectivity': '4G LTE', 'wan_ports': '2', 'lan_ports': '4'}, 'description': '4G LTE extender'},
            {'model_name': 'FortiExtender 511F', 'model_number': 'FX-511F', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'connectivity': '5G', 'wan_ports': '2', 'lan_ports': '4'}, 'description': '5G SD-WAN extender'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"fortinet-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_sonicwall(self):
        """Seed SonicWall firewalls."""
        vendor, created = Vendor.objects.get_or_create(
            name='SonicWall',
            defaults={
                'slug': slugify('SonicWall'),
                'website': 'https://www.sonicwall.com',
                'support_url': 'https://www.sonicwall.com/support/',
                'support_phone': '1-800-680-9800',
                'description': 'Network security and firewall solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            {
                'model_name': 'TZ350',
                'model_number': 'TZ350',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '1.4 Gbps',
                    'firewall_throughput': '900 Mbps',
                    'ips_throughput': '600 Mbps',
                    'interfaces': '8x 1GbE, 2x USB',
                    'vpn': '10 VPN tunnels included'
                },
                'description': 'Security firewall for small offices'
            },
            {
                'model_name': 'TZ470',
                'model_number': 'TZ470',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '2.0 Gbps',
                    'firewall_throughput': '1.4 Gbps',
                    'ips_throughput': '800 Mbps',
                    'interfaces': '8x 1GbE, 2x USB'
                },
                'description': 'Mid-range firewall for branch offices'
            },
            {
                'model_name': 'NSa 3700',
                'model_number': 'NSa-3700',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '7.5 Gbps',
                    'firewall_throughput': '3.5 Gbps',
                    'ips_throughput': '2.0 Gbps',
                    'interfaces': '8x 1GbE, 4x 10GbE SFP+'
                },
                'description': 'Enterprise firewall for medium businesses'
            },

            # TZ Series - Extended Range
            {'model_name': 'TZ270', 'model_number': 'TZ270', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.5 Gbps', 'firewall_throughput': '750 Mbps', 'interfaces': '5x 1GbE'}, 'description': 'SMB firewall'},
            {'model_name': 'TZ270W', 'model_number': 'TZ270W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.5 Gbps', 'wireless': 'Wi-Fi 6'}, 'description': 'SMB wireless firewall'},
            {'model_name': 'TZ370', 'model_number': 'TZ370', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '2 Gbps', 'firewall_throughput': '1 Gbps', 'interfaces': '8x 1GbE'}, 'description': 'Mid-size SMB firewall'},
            {'model_name': 'TZ370W', 'model_number': 'TZ370W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '2 Gbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Mid-size wireless'},
            {'model_name': 'TZ470', 'model_number': 'TZ470', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3 Gbps', 'firewall_throughput': '1.5 Gbps', 'interfaces': '8x 1GbE, 2x 10GbE'}, 'description': 'Distributed enterprise'},
            {'model_name': 'TZ470W', 'model_number': 'TZ470W', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3 Gbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Distributed wireless'},
            {'model_name': 'TZ570', 'model_number': 'TZ570', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '4 Gbps', 'firewall_throughput': '2 Gbps', 'interfaces': '10x 1GbE, 2x 10GbE'}, 'description': 'High-performance SMB'},
            {'model_name': 'TZ570W', 'model_number': 'TZ570W', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '4 Gbps', 'wireless': 'Wi-Fi 6'}, 'description': 'High-perf wireless'},
            {'model_name': 'TZ570P', 'model_number': 'TZ570P', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '4 Gbps', 'poe': 'PoE+ support'}, 'description': 'PoE-enabled firewall'},
            {'model_name': 'TZ670', 'model_number': 'TZ670', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '5 Gbps', 'firewall_throughput': '2.5 Gbps', 'interfaces': '12x 1GbE, 2x 10GbE'}, 'description': 'Maximum TZ series'},
            # NSa Series - Mid-Range
            {'model_name': 'NSa 2700', 'model_number': 'NSa2700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '6 Gbps', 'firewall_throughput': '3 Gbps', 'interfaces': '12x 1GbE, 4x 10GbE SFP+'}, 'description': 'Mid-range enterprise'},
            {'model_name': 'NSa 3700', 'model_number': 'NSa3700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '9 Gbps', 'firewall_throughput': '4.5 Gbps', 'interfaces': '16x 1GbE, 4x 10GbE SFP+'}, 'description': 'High-perf enterprise'},
            {'model_name': 'NSa 4700', 'model_number': 'NSa4700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '12 Gbps', 'firewall_throughput': '6 Gbps', 'interfaces': '16x 1GbE, 8x 10GbE SFP+'}, 'description': 'Enterprise data center'},
            {'model_name': 'NSa 5700', 'model_number': 'NSa5700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '16 Gbps', 'firewall_throughput': '8 Gbps', 'interfaces': '16x 1GbE, 8x 10GbE SFP+'}, 'description': 'High-capacity DC'},
            {'model_name': 'NSa 6700', 'model_number': 'NSa6700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '20 Gbps', 'firewall_throughput': '10 Gbps', 'interfaces': '20x 1GbE, 12x 10GbE SFP+'}, 'description': 'Maximum NSa series'},
            # NSsp Series - Service Provider
            {'model_name': 'NSsp 10700', 'model_number': 'NSsp10700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '30 Gbps', 'firewall_throughput': '15 Gbps'}, 'description': 'SP-class firewall'},
            {'model_name': 'NSsp 11700', 'model_number': 'NSsp11700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '40 Gbps', 'firewall_throughput': '20 Gbps'}, 'description': 'High-perf SP'},
            {'model_name': 'NSsp 12400', 'model_number': 'NSsp12400', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '50 Gbps', 'firewall_throughput': '25 Gbps'}, 'description': 'Enterprise SP'},
            {'model_name': 'NSsp 12800', 'model_number': 'NSsp12800', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '60 Gbps', 'firewall_throughput': '30 Gbps'}, 'description': 'High-capacity SP'},
            {'model_name': 'NSsp 13700', 'model_number': 'NSsp13700', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 3, 'specifications': {'throughput': '80 Gbps', 'firewall_throughput': '40 Gbps'}, 'description': 'Maximum SP firewall'},
            # NSv Virtual Series
            {'model_name': 'NSv 10', 'model_number': 'NSv10', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '50 Mbps', 'vcpu': '1'}, 'description': 'Virtual - Micro'},
            {'model_name': 'NSv 25', 'model_number': 'NSv25', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '100 Mbps', 'vcpu': '2'}, 'description': 'Virtual - Small'},
            {'model_name': 'NSv 50', 'model_number': 'NSv50', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '150 Mbps', 'vcpu': '2'}, 'description': 'Virtual - Medium'},
            {'model_name': 'NSv 100', 'model_number': 'NSv100', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '200 Mbps', 'vcpu': '4'}, 'description': 'Virtual - Large'},
            {'model_name': 'NSv 200', 'model_number': 'NSv200', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '400 Mbps', 'vcpu': '4'}, 'description': 'Virtual - Enterprise'},
            {'model_name': 'NSv 270', 'model_number': 'NSv270', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '1 Gbps', 'vcpu': '8'}, 'description': 'Virtual - High-perf'},
            {'model_name': 'NSv 470', 'model_number': 'NSv470', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '2 Gbps', 'vcpu': '8'}, 'description': 'Virtual - Maximum'},
            # Additional TZ Models
            {'model_name': 'TZ300', 'model_number': 'TZ300', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.3 Gbps', 'interfaces': '5x 1GbE'}, 'description': 'Legacy SMB firewall'},
            {'model_name': 'TZ300W', 'model_number': 'TZ300W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.3 Gbps', 'wireless': 'Wi-Fi 5'}, 'description': 'Legacy wireless SMB'},
            {'model_name': 'TZ300P', 'model_number': 'TZ300P', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.3 Gbps', 'poe': 'PoE support'}, 'description': 'Legacy PoE SMB'},
            {'model_name': 'TZ400', 'model_number': 'TZ400', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.5 Gbps', 'interfaces': '8x 1GbE'}, 'description': 'Legacy mid-range'},
            {'model_name': 'TZ500', 'model_number': 'TZ500', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2 Gbps', 'interfaces': '8x 1GbE'}, 'description': 'Legacy enterprise'},
            {'model_name': 'TZ500W', 'model_number': 'TZ500W', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2 Gbps', 'wireless': 'Wi-Fi 5'}, 'description': 'Legacy wireless enterprise'},
            {'model_name': 'TZ600', 'model_number': 'TZ600', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3 Gbps', 'interfaces': '12x 1GbE'}, 'description': 'Legacy maximum TZ'},
            {'model_name': 'TZ600P', 'model_number': 'TZ600P', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3 Gbps', 'poe': 'PoE+ support'}, 'description': 'Legacy PoE+ max'},
            # SOHO Series
            {'model_name': 'SOHO 250', 'model_number': 'SOHO250', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '800 Mbps', 'interfaces': '5x 1GbE'}, 'description': 'Home office firewall'},
            {'model_name': 'SOHO 250W', 'model_number': 'SOHO250W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '800 Mbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Wireless home office'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"sonicwall-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_grandstream(self):
        """Seed Grandstream VoIP phones."""
        vendor, created = Vendor.objects.get_or_create(
            name='Grandstream',
            defaults={
                'slug': slugify('Grandstream'),
                'website': 'https://www.grandstream.com',
                'support_url': 'https://www.grandstream.com/support',
                'description': 'VoIP phones and unified communications',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            {
                'model_name': 'GXP2170',
                'model_number': 'GXP2170',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 SIP accounts',
                    'display': '4.3" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'HD audio, Bluetooth, WiFi'
                },
                'description': 'High-end IP phone for executives'
            },
            {
                'model_name': 'GXP1630',
                'model_number': 'GXP1630',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '3 SIP accounts',
                    'display': '132x64 backlit LCD',
                    'network': 'Dual 10/100 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, EHS support'
                },
                'description': 'Basic IP phone for small offices'
            },
            {
                'model_name': 'GRP2614',
                'model_number': 'GRP2614',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 SIP accounts',
                    'display': '2.8" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'Carrier-grade, HD audio, WiFi'
                },
                'description': 'Carrier-grade IP phone'
            },
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"grandstream-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_tp_link(self):
        """Seed TP-Link networking equipment."""
        vendor, created = Vendor.objects.get_or_create(
            name='TP-Link',
            defaults={
                'slug': slugify('TP-Link'),
                'website': 'https://www.tp-link.com',
                'support_url': 'https://www.tp-link.com/us/support/',
                'support_phone': '1-866-225-8139',
                'description': 'Affordable networking equipment for SMB',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            {
                'model_name': 'TL-SG3452P',
                'model_number': 'TL-SG3452P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '384W',
                    'switching_capacity': '104 Gbps'
                },
                'description': 'JetStream managed switch with PoE+'
            },
            {
                'model_name': 'TL-SG3428',
                'model_number': 'TL-SG3428',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE, 4x 1GbE SFP',
                    'switching_capacity': '56 Gbps',
                    'features': 'Layer 2+, VLAN, QoS'
                },
                'description': 'JetStream L2+ managed switch'
            },
            {
                'model_name': 'EAP660 HD',
                'model_number': 'EAP660-HD',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '3.5 Gbps',
                    'clients': '1024 concurrent',
                    'poe': '802.3at'
                },
                'description': 'WiFi 6 access point with high density'
            },
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"tp-link-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_cisco_meraki(self):
        """Seed Cisco Meraki cloud-managed networking equipment."""
        vendor, created = Vendor.objects.get_or_create(
            name='Cisco Meraki',
            defaults={
                'slug': slugify('Cisco Meraki'),
                'website': 'https://meraki.cisco.com',
                'support_url': 'https://documentation.meraki.com',
                'support_phone': '1-888-637-2542',
                'description': 'Cloud-managed networking and security solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Meraki Switches
            {
                'model_name': 'MS390-48UX2',
                'model_number': 'MS390-48UX2',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x mGig (100M/1G/2.5G/5G/10G) PoE++',
                    'uplinks': '2x 40G QSFP+',
                    'poe_budget': '1440W',
                    'switching_capacity': '960 Gbps'
                },
                'description': 'High-power mGig cloud-managed switch'
            },
            {
                'model_name': 'MS425-32',
                'model_number': 'MS425-32',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '32x 10GbE SFP+',
                    'uplinks': 'Stacking',
                    'switching_capacity': '640 Gbps'
                },
                'description': 'Aggregation cloud-managed switch'
            },
            {
                'model_name': 'MS250-48FP',
                'model_number': 'MS250-48FP',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Access layer PoE+ cloud switch'
            },
            {
                'model_name': 'MS225-48FP',
                'model_number': 'MS225-48FP',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10G SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Compact access PoE+ switch'
            },
            {
                'model_name': 'MS120-48FP',
                'model_number': 'MS120-48FP',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '104 Gbps'
                },
                'description': 'Entry-level PoE+ cloud switch'
            },

            # Meraki Security Appliances (Firewalls)
            {
                'model_name': 'MX450',
                'model_number': 'MX450',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '2 Gbps',
                    'firewall_throughput': '2 Gbps',
                    'vpn_throughput': '500 Mbps',
                    'ports': '8x 1GbE, 2x 10GbE SFP+'
                },
                'description': 'Enterprise cloud-managed security appliance'
            },
            {
                'model_name': 'MX250',
                'model_number': 'MX250',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '1 Gbps',
                    'firewall_throughput': '1 Gbps',
                    'vpn_throughput': '300 Mbps',
                    'ports': '8x 1GbE, 2x 10GbE SFP+'
                },
                'description': 'Branch security appliance'
            },
            {
                'model_name': 'MX85',
                'model_number': 'MX85',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '500 Mbps',
                    'firewall_throughput': '500 Mbps',
                    'vpn_throughput': '200 Mbps',
                    'ports': '10x 1GbE, 2x 10GbE SFP+'
                },
                'description': 'Mid-size branch security appliance'
            },
            {
                'model_name': 'MX68',
                'model_number': 'MX68',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '450 Mbps',
                    'firewall_throughput': '450 Mbps',
                    'vpn_throughput': '100 Mbps',
                    'ports': '5x 1GbE'
                },
                'description': 'Small branch security appliance'
            },

            # Meraki Wireless Access Points
            {
                'model_name': 'MR57',
                'model_number': 'MR57',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6E (802.11ax)',
                    'throughput': '5.4 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x 5Gbps Ethernet'
                },
                'description': 'WiFi 6E cloud-managed access point'
            },
            {
                'model_name': 'MR46',
                'model_number': 'MR46',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '3.0 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x mGig Ethernet'
                },
                'description': 'WiFi 6 indoor access point'
            },
            {
                'model_name': 'MR36',
                'model_number': 'MR36',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '1.8 Gbps',
                    'clients': '256 concurrent',
                    'poe': '802.3at',
                    'ports': '1x 1Gbps Ethernet'
                },
                'description': 'Compact WiFi 6 access point'
            },
            {
                'model_name': 'MR44',
                'model_number': 'MR44',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 5 (802.11ac Wave 2)',
                    'throughput': '1.7 Gbps',
                    'clients': '256 concurrent',
                    'poe': '802.3at'
                },
                'description': 'WiFi 5 cloud-managed access point'
            },
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"meraki-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_palo_alto(self):
        """Seed Palo Alto Networks firewalls."""
        vendor, created = Vendor.objects.get_or_create(
            name='Palo Alto Networks',
            defaults={
                'slug': slugify('Palo Alto Networks'),
                'website': 'https://www.paloaltonetworks.com',
                'support_url': 'https://support.paloaltonetworks.com',
                'support_phone': '1-866-898-9087',
                'description': 'Advanced network security and next-generation firewalls',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Palo Alto PA-Series Firewalls
            {
                'model_name': 'PA-5450',
                'model_number': 'PA-5450',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '64 Gbps',
                    'firewall_throughput': '30 Gbps',
                    'threat_prevention': '18.5 Gbps',
                    'ipsec_vpn': '25 Gbps',
                    'interfaces': '16x 10GbE SFP+, 4x 40GbE QSFP+'
                },
                'description': 'High-end datacenter firewall'
            },
            {
                'model_name': 'PA-5410',
                'model_number': 'PA-5410',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '52 Gbps',
                    'firewall_throughput': '26 Gbps',
                    'threat_prevention': '16 Gbps',
                    'ipsec_vpn': '20 Gbps',
                    'interfaces': '16x 10GbE SFP+, 2x 40GbE QSFP+'
                },
                'description': 'Datacenter firewall'
            },
            {
                'model_name': 'PA-3440',
                'model_number': 'PA-3440',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '16 Gbps',
                    'firewall_throughput': '8.2 Gbps',
                    'threat_prevention': '5.9 Gbps',
                    'ipsec_vpn': '7.5 Gbps',
                    'interfaces': '16x 1GbE, 4x 10GbE SFP+'
                },
                'description': 'Enterprise branch firewall'
            },
            {
                'model_name': 'PA-3420',
                'model_number': 'PA-3420',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '12 Gbps',
                    'firewall_throughput': '6.5 Gbps',
                    'threat_prevention': '4.8 Gbps',
                    'ipsec_vpn': '6.0 Gbps',
                    'interfaces': '16x 1GbE, 4x 10GbE SFP+'
                },
                'description': 'Mid-range enterprise firewall'
            },
            {
                'model_name': 'PA-1420',
                'model_number': 'PA-1420',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '3 Gbps',
                    'firewall_throughput': '1.5 Gbps',
                    'threat_prevention': '900 Mbps',
                    'ipsec_vpn': '1.2 Gbps',
                    'interfaces': '8x 1GbE, 4x 1GbE SFP'
                },
                'description': 'Branch office firewall'
            },
            {
                'model_name': 'PA-1410',
                'model_number': 'PA-1410',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '2 Gbps',
                    'firewall_throughput': '1 Gbps',
                    'threat_prevention': '650 Mbps',
                    'ipsec_vpn': '1 Gbps',
                    'interfaces': '8x 1GbE'
                },
                'description': 'Small branch firewall'
            },
            {
                'model_name': 'PA-850',
                'model_number': 'PA-850',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '2 Gbps',
                    'firewall_throughput': '1.3 Gbps',
                    'threat_prevention': '870 Mbps',
                    'ipsec_vpn': '1.5 Gbps',
                    'interfaces': '8x 1GbE, 4x 1GbE SFP'
                },
                'description': 'Compact branch firewall'
            },
            {
                'model_name': 'PA-460',
                'model_number': 'PA-460',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '1.5 Gbps',
                    'firewall_throughput': '750 Mbps',
                    'threat_prevention': '500 Mbps',
                    'ipsec_vpn': '800 Mbps',
                    'interfaces': '8x 1GbE'
                },
                'description': 'Small office firewall'
            },
            {
                'model_name': 'PA-440',
                'model_number': 'PA-440',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '1 Gbps',
                    'firewall_throughput': '500 Mbps',
                    'threat_prevention': '350 Mbps',
                    'ipsec_vpn': '600 Mbps',
                    'interfaces': '8x 1GbE'
                },
                'description': 'Entry-level firewall'
            },

            # Extended PA-Series Physical Firewalls
            {'model_name': 'PA-220', 'model_number': 'PA-220', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1 Gbps', 'firewall_throughput': '400 Mbps', 'interfaces': '8x 1GbE'}, 'description': 'Entry NGFW'},
            {'model_name': 'PA-440', 'model_number': 'PA-440', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '4 Gbps', 'firewall_throughput': '1.5 Gbps', 'interfaces': '8x 1GbE, 4x SFP'}, 'description': 'SMB NGFW'},
            {'model_name': 'PA-450', 'model_number': 'PA-450', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '5 Gbps', 'firewall_throughput': '2 Gbps', 'interfaces': '12x 1GbE, 4x SFP'}, 'description': 'Branch NGFW'},
            {'model_name': 'PA-460', 'model_number': 'PA-460', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '6 Gbps', 'firewall_throughput': '2.5 Gbps'}, 'description': 'Enhanced branch'},
            {'model_name': 'PA-850', 'model_number': 'PA-850', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '9 Gbps', 'firewall_throughput': '3.4 Gbps', 'interfaces': '16x 1GbE, 4x 10GbE SFP+'}, 'description': 'Mid-range NGFW'},
            {'model_name': 'PA-1410', 'model_number': 'PA-1410', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '14 Gbps', 'firewall_throughput': '5 Gbps'}, 'description': 'Enterprise firewall'},
            {'model_name': 'PA-1420', 'model_number': 'PA-1420', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '16 Gbps', 'firewall_throughput': '6 Gbps'}, 'description': 'Enhanced enterprise'},
            {'model_name': 'PA-1430', 'model_number': 'PA-1430', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '18 Gbps', 'firewall_throughput': '7 Gbps'}, 'description': 'High-performance enterprise'},
            {'model_name': 'PA-3220', 'model_number': 'PA-3220', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '22 Gbps', 'firewall_throughput': '8 Gbps'}, 'description': 'Data center NGFW'},
            {'model_name': 'PA-3250', 'model_number': 'PA-3250', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '28 Gbps', 'firewall_throughput': '10 Gbps'}, 'description': 'Enhanced data center'},
            {'model_name': 'PA-3260', 'model_number': 'PA-3260', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '32 Gbps', 'firewall_throughput': '12 Gbps'}, 'description': 'High-capacity data center'},
            {'model_name': 'PA-3410', 'model_number': 'PA-3410', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '34 Gbps', 'firewall_throughput': '13 Gbps'}, 'description': 'Next-gen data center'},
            {'model_name': 'PA-3420', 'model_number': 'PA-3420', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '38 Gbps', 'firewall_throughput': '14 Gbps'}, 'description': 'Enhanced next-gen DC'},
            {'model_name': 'PA-3430', 'model_number': 'PA-3430', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '42 Gbps', 'firewall_throughput': '16 Gbps'}, 'description': 'High-perf next-gen DC'},
            {'model_name': 'PA-3440', 'model_number': 'PA-3440', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '46 Gbps', 'firewall_throughput': '18 Gbps'}, 'description': 'Maximum next-gen DC'},
            {'model_name': 'PA-5220', 'model_number': 'PA-5220', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '52 Gbps', 'firewall_throughput': '20 Gbps'}, 'description': 'Enterprise DC firewall'},
            {'model_name': 'PA-5250', 'model_number': 'PA-5250', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '62 Gbps', 'firewall_throughput': '25 Gbps'}, 'description': 'Enhanced enterprise DC'},
            {'model_name': 'PA-5260', 'model_number': 'PA-5260', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '72 Gbps', 'firewall_throughput': '30 Gbps'}, 'description': 'High-capacity enterprise DC'},
            {'model_name': 'PA-5280', 'model_number': 'PA-5280', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '82 Gbps', 'firewall_throughput': '35 Gbps'}, 'description': 'Maximum enterprise DC'},
            {'model_name': 'PA-5410', 'model_number': 'PA-5410', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '90 Gbps', 'firewall_throughput': '40 Gbps'}, 'description': 'Service provider NGFW'},
            {'model_name': 'PA-5420', 'model_number': 'PA-5420', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '100 Gbps', 'firewall_throughput': '45 Gbps'}, 'description': 'Enhanced SP NGFW'},
            {'model_name': 'PA-5430', 'model_number': 'PA-5430', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '110 Gbps', 'firewall_throughput': '50 Gbps'}, 'description': 'High-perf SP NGFW'},
            {'model_name': 'PA-5440', 'model_number': 'PA-5440', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '120 Gbps', 'firewall_throughput': '55 Gbps'}, 'description': 'Maximum SP NGFW'},
            {'model_name': 'PA-5450', 'model_number': 'PA-5450', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '130 Gbps', 'firewall_throughput': '60 Gbps'}, 'description': 'Flagship SP NGFW'},
            {'model_name': 'PA-7050', 'model_number': 'PA-7050', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 11, 'specifications': {'throughput': '360 Gbps', 'firewall_throughput': '120 Gbps'}, 'description': 'Hyperscale chassis'},
            {'model_name': 'PA-7080', 'model_number': 'PA-7080', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 13, 'specifications': {'throughput': '480 Gbps', 'firewall_throughput': '160 Gbps'}, 'description': 'Maximum chassis firewall'},
            # VM-Series Virtual Firewalls
            {'model_name': 'VM-50', 'model_number': 'VM-50', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '200 Mbps', 'vcpu': '2'}, 'description': 'Virtual - Small'},
            {'model_name': 'VM-100', 'model_number': 'VM-100', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '1 Gbps', 'vcpu': '4'}, 'description': 'Virtual - Medium'},
            {'model_name': 'VM-200', 'model_number': 'VM-200', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '2 Gbps', 'vcpu': '8'}, 'description': 'Virtual - Large'},
            {'model_name': 'VM-300', 'model_number': 'VM-300', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '4 Gbps', 'vcpu': '16'}, 'description': 'Virtual - Enterprise'},
            {'model_name': 'VM-500', 'model_number': 'VM-500', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '10 Gbps', 'vcpu': '32'}, 'description': 'Virtual - High-perf'},
            {'model_name': 'VM-700', 'model_number': 'VM-700', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '20 Gbps', 'vcpu': '64'}, 'description': 'Virtual - Maximum'},
            {'model_name': 'VM-1000-HV', 'model_number': 'VM-1000-HV', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '60 Gbps', 'vcpu': '96'}, 'description': 'Virtual - Hyperscale'},
            {'model_name': 'CN-Series K8s', 'model_number': 'CN-SERIES', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Container', 'platform': 'Kubernetes'}, 'description': 'Container NGFW'},
            {'model_name': 'PA-220R', 'model_number': 'PA-220R', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1 Gbps', 'rugged': 'Yes', 'temperature': '-40°C to 70°C'}, 'description': 'Ruggedized entry NGFW'},
            {'model_name': 'PA-410', 'model_number': 'PA-410', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3 Gbps', 'firewall_throughput': '1.2 Gbps'}, 'description': 'IoT-focused NGFW'},
            {'model_name': 'PA-415', 'model_number': 'PA-415', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3.5 Gbps', 'firewall_throughput': '1.4 Gbps', '5g': 'Yes'}, 'description': '5G IoT NGFW'},
            {'model_name': 'PA-415-5G', 'model_number': 'PA-415-5G', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3.5 Gbps', '5g_built_in': 'Yes'}, 'description': 'Integrated 5G NGFW'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"palo-alto-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_watchguard(self):
        """Seed WatchGuard firewalls."""
        vendor, created = Vendor.objects.get_or_create(
            name='WatchGuard',
            defaults={
                'slug': slugify('WatchGuard'),
                'website': 'https://www.watchguard.com',
                'support_url': 'https://www.watchguard.com/support',
                'support_phone': '1-800-734-9905',
                'description': 'Network security and firewall solutions for SMB',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # WatchGuard Firebox Appliances
            {
                'model_name': 'Firebox M5800',
                'model_number': 'M5800',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '100 Gbps',
                    'firewall_throughput': '60 Gbps',
                    'ips_throughput': '40 Gbps',
                    'vpn_throughput': '34 Gbps',
                    'interfaces': '20x 1GbE, 12x 10GbE SFP+'
                },
                'description': 'Enterprise-grade firewall'
            },
            {
                'model_name': 'Firebox M4800',
                'model_number': 'M4800',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '63 Gbps',
                    'firewall_throughput': '40 Gbps',
                    'ips_throughput': '27 Gbps',
                    'vpn_throughput': '20 Gbps',
                    'interfaces': '12x 1GbE, 8x 10GbE SFP+'
                },
                'description': 'High-performance firewall'
            },
            {
                'model_name': 'Firebox M470',
                'model_number': 'M470',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '8 Gbps',
                    'firewall_throughput': '5.5 Gbps',
                    'ips_throughput': '2.6 Gbps',
                    'vpn_throughput': '2.5 Gbps',
                    'interfaces': '8x 1GbE, 4x 1GbE SFP'
                },
                'description': 'Mid-size business firewall'
            },
            {
                'model_name': 'Firebox M370',
                'model_number': 'M370',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '6 Gbps',
                    'firewall_throughput': '3.8 Gbps',
                    'ips_throughput': '1.8 Gbps',
                    'vpn_throughput': '2 Gbps',
                    'interfaces': '6x 1GbE, 2x 1GbE SFP'
                },
                'description': 'SMB firewall'
            },
            {
                'model_name': 'Firebox M270',
                'model_number': 'M270',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '3.3 Gbps',
                    'firewall_throughput': '2.2 Gbps',
                    'ips_throughput': '1.1 Gbps',
                    'vpn_throughput': '1 Gbps',
                    'interfaces': '5x 1GbE'
                },
                'description': 'Small business firewall'
            },
            {
                'model_name': 'Firebox T85',
                'model_number': 'T85',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '1.6 Gbps',
                    'firewall_throughput': '1 Gbps',
                    'ips_throughput': '590 Mbps',
                    'vpn_throughput': '700 Mbps',
                    'interfaces': '5x 1GbE'
                },
                'description': 'Desktop firewall for branch offices'
            },
            {
                'model_name': 'Firebox T45',
                'model_number': 'T45',
                'equipment_type': 'firewall',
                'is_rackmount': False,
                'specifications': {
                    'throughput': '940 Mbps',
                    'firewall_throughput': '600 Mbps',
                    'ips_throughput': '350 Mbps',
                    'vpn_throughput': '460 Mbps',
                    'interfaces': '5x 1GbE'
                },
                'description': 'Entry-level desktop firewall'
            },

            # Firebox T Series - Extended
            {'model_name': 'Firebox T15', 'model_number': 'T15', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '350 Mbps', 'firewall_throughput': '150 Mbps', 'interfaces': '5x 1GbE'}, 'description': 'Micro branch firewall'},
            {'model_name': 'Firebox T15-W', 'model_number': 'T15-W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '350 Mbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Wireless micro branch'},
            {'model_name': 'Firebox T25', 'model_number': 'T25', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '500 Mbps', 'firewall_throughput': '200 Mbps', 'interfaces': '5x 1GbE'}, 'description': 'Small branch firewall'},
            {'model_name': 'Firebox T25-W', 'model_number': 'T25-W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '500 Mbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Wireless small branch'},
            {'model_name': 'Firebox T35', 'model_number': 'T35', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '800 Mbps', 'firewall_throughput': '350 Mbps', 'interfaces': '8x 1GbE'}, 'description': 'SMB firewall'},
            {'model_name': 'Firebox T35-W', 'model_number': 'T35-W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '800 Mbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Wireless SMB'},
            {'model_name': 'Firebox T35-R', 'model_number': 'T35-R', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '800 Mbps', 'interfaces': '8x 1GbE'}, 'description': 'Rackmount SMB'},
            {'model_name': 'Firebox T45', 'model_number': 'T45', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.2 Gbps', 'firewall_throughput': '500 Mbps', 'interfaces': '8x 1GbE'}, 'description': 'Mid-size SMB'},
            {'model_name': 'Firebox T45-W', 'model_number': 'T45-W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.2 Gbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Wireless mid-size'},
            {'model_name': 'Firebox T55', 'model_number': 'T55', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '1.8 Gbps', 'firewall_throughput': '750 Mbps', 'interfaces': '12x 1GbE, 2x SFP'}, 'description': 'Distributed enterprise'},
            {'model_name': 'Firebox T55-W', 'model_number': 'T55-W', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '1.8 Gbps', 'wireless': 'Wi-Fi 6'}, 'description': 'Wireless enterprise'},
            {'model_name': 'Firebox T70', 'model_number': 'T70', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2.5 Gbps', 'firewall_throughput': '1 Gbps', 'interfaces': '12x 1GbE, 2x 10GbE SFP+'}, 'description': 'High-perf branch'},
            {'model_name': 'Firebox T85', 'model_number': 'T85', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '3.5 Gbps', 'firewall_throughput': '1.5 Gbps', 'interfaces': '12x 1GbE, 4x 10GbE SFP+'}, 'description': 'Maximum T series'},
            # Firebox M Series - Enterprise
            {'model_name': 'Firebox M270', 'model_number': 'M270', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '4 Gbps', 'firewall_throughput': '2 Gbps', 'interfaces': '14x 1GbE, 4x 10GbE SFP+'}, 'description': 'Enterprise firewall'},
            {'model_name': 'Firebox M370', 'model_number': 'M370', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '6 Gbps', 'firewall_throughput': '3 Gbps', 'interfaces': '16x 1GbE, 4x 10GbE SFP+'}, 'description': 'High-perf enterprise'},
            {'model_name': 'Firebox M470', 'model_number': 'M470', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '9 Gbps', 'firewall_throughput': '4.5 Gbps', 'interfaces': '16x 1GbE, 8x 10GbE SFP+'}, 'description': 'Enterprise data center'},
            {'model_name': 'Firebox M570', 'model_number': 'M570', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '13 Gbps', 'firewall_throughput': '6.5 Gbps', 'interfaces': '20x 1GbE, 8x 10GbE SFP+'}, 'description': 'High-capacity DC'},
            {'model_name': 'Firebox M670', 'model_number': 'M670', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '18 Gbps', 'firewall_throughput': '9 Gbps', 'interfaces': '20x 1GbE, 12x 10GbE SFP+'}, 'description': 'Large enterprise DC'},
            {'model_name': 'Firebox M690', 'model_number': 'M690', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '24 Gbps', 'firewall_throughput': '12 Gbps', 'interfaces': '24x 1GbE, 12x 10GbE SFP+'}, 'description': 'Maximum M series'},
            {'model_name': 'Firebox M4800', 'model_number': 'M4800', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '32 Gbps', 'firewall_throughput': '16 Gbps'}, 'description': 'Carrier-class firewall'},
            {'model_name': 'Firebox M5800', 'model_number': 'M5800', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '40 Gbps', 'firewall_throughput': '20 Gbps'}, 'description': 'Flagship firewall'},
            # Firebox Cloud Virtual
            {'model_name': 'Firebox Cloud S', 'model_number': 'FBC-S', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '50 Mbps', 'vcpu': '1'}, 'description': 'Virtual - Small'},
            {'model_name': 'Firebox Cloud M', 'model_number': 'FBC-M', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '100 Mbps', 'vcpu': '2'}, 'description': 'Virtual - Medium'},
            {'model_name': 'Firebox Cloud L', 'model_number': 'FBC-L', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '250 Mbps', 'vcpu': '4'}, 'description': 'Virtual - Large'},
            {'model_name': 'Firebox Cloud XL', 'model_number': 'FBC-XL', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '500 Mbps', 'vcpu': '8'}, 'description': 'Virtual - Extra Large'},
            {'model_name': 'Firebox Cloud XXL', 'model_number': 'FBC-XXL', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '1 Gbps', 'vcpu': '16'}, 'description': 'Virtual - XXL'},
            # Legacy Models
            {'model_name': 'Firebox T10', 'model_number': 'T10', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '250 Mbps', 'interfaces': '5x 1GbE'}, 'description': 'Legacy micro firewall'},
            {'model_name': 'Firebox T30', 'model_number': 'T30', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '650 Mbps', 'interfaces': '5x 1GbE'}, 'description': 'Legacy small branch'},
            {'model_name': 'Firebox T30-W', 'model_number': 'T30-W', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '650 Mbps', 'wireless': 'Wi-Fi 5'}, 'description': 'Legacy wireless'},
            {'model_name': 'Firebox T50', 'model_number': 'T50', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '1 Gbps', 'interfaces': '8x 1GbE'}, 'description': 'Legacy mid-range'},
            {'model_name': 'Firebox T50-W', 'model_number': 'T50-W', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '1 Gbps', 'wireless': 'Wi-Fi 5'}, 'description': 'Legacy wireless mid-range'},
            {'model_name': 'Firebox T80', 'model_number': 'T80', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2 Gbps', 'interfaces': '12x 1GbE'}, 'description': 'Legacy high-perf'},
            {'model_name': 'Firebox M200', 'model_number': 'M200', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '2.5 Gbps', 'interfaces': '12x 1GbE'}, 'description': 'Legacy enterprise'},
            {'model_name': 'Firebox M300', 'model_number': 'M300', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '4 Gbps', 'interfaces': '12x 1GbE, 4x SFP+'}, 'description': 'Legacy high-perf enterprise'},
            {'model_name': 'Firebox M400', 'model_number': 'M400', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '5 Gbps', 'interfaces': '16x 1GbE, 4x SFP+'}, 'description': 'Legacy data center'},
            {'model_name': 'Firebox M500', 'model_number': 'M500', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '7 Gbps', 'interfaces': '16x 1GbE, 8x SFP+'}, 'description': 'Legacy large DC'},
            {'model_name': 'Firebox M600', 'model_number': 'M600', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '10 Gbps', 'interfaces': '20x 1GbE, 8x SFP+'}, 'description': 'Legacy maximum'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"watchguard-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_hp_aruba(self):
        """Seed HP Aruba networking equipment."""
        vendor, created = Vendor.objects.get_or_create(
            name='HP Aruba',
            defaults={
                'slug': slugify('HP Aruba'),
                'website': 'https://www.arubanetworks.com',
                'support_url': 'https://www.arubanetworks.com/support-services/',
                'support_phone': '1-800-943-4526',
                'description': 'Enterprise wireless and wired networking solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Aruba Switches
            {
                'model_name': 'CX 6300 48G',
                'model_number': 'CX6300-48G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 10GbE SFP+',
                    'switching_capacity': '176 Gbps',
                    'features': 'Layer 3, VSX, cloud-managed'
                },
                'description': 'Stackable access switch'
            },
            {
                'model_name': 'CX 6200 48G',
                'model_number': 'CX6200-48G',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE',
                    'uplinks': '4x 10GbE SFP+',
                    'poe_budget': '740W (PoE version)',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Smart-managed access switch'
            },
            {
                'model_name': '2930F 48G PoE+ 4SFP+',
                'model_number': '2930F-48G-PoE+',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10GbE SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Stackable PoE+ switch'
            },
            {
                'model_name': '2930M 48G PoE+',
                'model_number': '2930M-48G-PoE+',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10GbE SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Intelligent edge switch with PoE+'
            },

            # Aruba Wireless Access Points
            {
                'model_name': 'AP-655',
                'model_number': 'AP-655',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6E (802.11ax)',
                    'throughput': '5.9 Gbps',
                    'clients': '1024 concurrent',
                    'poe': '802.3at',
                    'ports': '1x mGig Ethernet'
                },
                'description': 'WiFi 6E indoor access point'
            },
            {
                'model_name': 'AP-635',
                'model_number': 'AP-635',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6E (802.11ax)',
                    'throughput': '4.8 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x mGig Ethernet'
                },
                'description': 'WiFi 6E compact access point'
            },
            {
                'model_name': 'AP-555',
                'model_number': 'AP-555',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '3.9 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x mGig Ethernet'
                },
                'description': 'WiFi 6 indoor access point'
            },
            {
                'model_name': 'AP-515',
                'model_number': 'AP-515',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '2.97 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x 1GbE'
                },
                'description': 'WiFi 6 compact access point'
            },
            {
                'model_name': 'AP-505',
                'model_number': 'AP-505',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '1.77 Gbps',
                    'clients': '256 concurrent',
                    'poe': '802.3af',
                    'ports': '1x 1GbE'
                },
                'description': 'Entry WiFi 6 access point'
            },
            {
                'model_name': 'AP-345',
                'model_number': 'AP-345',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 5 (802.11ac Wave 2)',
                    'throughput': '1.7 Gbps',
                    'clients': '256 concurrent',
                    'poe': '802.3af'
                },
                'description': 'WiFi 5 indoor access point'
            },

            # Aruba CX 6000 Series - Expanded
            {'model_name': 'Aruba CX 6100-24G', 'model_number': 'CX6100-24G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1/10GbE SFP/SFP+'}, 'description': '24-port stackable'},
            {'model_name': 'Aruba CX 6100-24G-PoE4', 'model_number': 'CX6100-24G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'uplinks': '4x 1/10GbE SFP/SFP+', 'poe_budget': '370W'}, 'description': '24-port PoE+ stackable'},
            {'model_name': 'Aruba CX 6100-48G', 'model_number': 'CX6100-48G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 1/10GbE SFP/SFP+'}, 'description': '48-port stackable'},
            {'model_name': 'Aruba CX 6100-48G-PoE4', 'model_number': 'CX6100-48G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'uplinks': '4x 1/10GbE SFP/SFP+', 'poe_budget': '740W'}, 'description': '48-port PoE+ stackable'},
            {'model_name': 'Aruba CX 6200F-24G', 'model_number': 'CX6200F-24G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1/10/25GbE SFP28'}, 'description': '24-port access'},
            {'model_name': 'Aruba CX 6200F-24G-PoE4', 'model_number': 'CX6200F-24G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '370W'}, 'description': '24-port PoE+ access'},
            {'model_name': 'Aruba CX 6200F-48G', 'model_number': 'CX6200F-48G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 1/10/25GbE SFP28'}, 'description': '48-port access'},
            {'model_name': 'Aruba CX 6200F-48G-PoE4', 'model_number': 'CX6200F-48G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '740W'}, 'description': '48-port PoE+ access'},
            {'model_name': 'Aruba CX 6300F-24G', 'model_number': 'CX6300F-24G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1/10/25GbE SFP28', 'stacking': 'VSF'}, 'description': '24-port stackable'},
            {'model_name': 'Aruba CX 6300F-24G-PoE4', 'model_number': 'CX6300F-24G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '370W', 'stacking': 'VSF'}, 'description': '24-port PoE+ stackable'},
            {'model_name': 'Aruba CX 6300F-48G', 'model_number': 'CX6300F-48G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 1/10/25GbE SFP28', 'stacking': 'VSF'}, 'description': '48-port stackable'},
            {'model_name': 'Aruba CX 6300F-48G-PoE4', 'model_number': 'CX6300F-48G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '740W', 'stacking': 'VSF'}, 'description': '48-port PoE+ stackable'},
            {'model_name': 'Aruba CX 6400-24G', 'model_number': 'CX6400-24G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1/10/25GbE SFP28'}, 'description': '24-port modular'},
            {'model_name': 'Aruba CX 6400-48G', 'model_number': 'CX6400-48G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 1/10/25GbE SFP28'}, 'description': '48-port modular'},
            {'model_name': 'Aruba CX 6400-24G-PoE4', 'model_number': 'CX6400-24G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '370W'}, 'description': '24-port PoE+ modular'},
            {'model_name': 'Aruba CX 6400-48G-PoE4', 'model_number': 'CX6400-48G-PoE4', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '740W'}, 'description': '48-port PoE+ modular'},
            # Aruba CX 8000 Series - Aggregation
            {'model_name': 'Aruba CX 8320-32C', 'model_number': 'CX8320-32C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '32x 100GbE QSFP28'}, 'description': '32-port 100G aggregation'},
            {'model_name': 'Aruba CX 8320-48Y', 'model_number': 'CX8320-48Y', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 25GbE SFP28', 'uplinks': '6x 100GbE QSFP28'}, 'description': '48-port 25G aggregation'},
            {'model_name': 'Aruba CX 8325-32C', 'model_number': 'CX8325-32C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '32x 100GbE QSFP28'}, 'description': '32-port 100G campus core'},
            {'model_name': 'Aruba CX 8325-48Y8C', 'model_number': 'CX8325-48Y8C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 25GbE SFP28', 'uplinks': '8x 100GbE QSFP28'}, 'description': '48-port 25G campus core'},
            {'model_name': 'Aruba CX 8360-16Y2C', 'model_number': 'CX8360-16Y2C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '16x 25GbE SFP28', 'uplinks': '2x 100GbE QSFP28'}, 'description': '16-port 25G compact'},
            {'model_name': 'Aruba CX 8360-32Y4C', 'model_number': 'CX8360-32Y4C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '32x 25GbE SFP28', 'uplinks': '4x 100GbE QSFP28'}, 'description': '32-port 25G aggregation'},
            {'model_name': 'Aruba CX 8360-48Y6C', 'model_number': 'CX8360-48Y6C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 25GbE SFP28', 'uplinks': '6x 100GbE QSFP28'}, 'description': '48-port 25G aggregation'},
            {'model_name': 'Aruba CX 8400', 'model_number': 'CX8400', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 6, 'specifications': {'capacity': 'Modular chassis', 'throughput': '19.2 Tbps', 'slots': '8'}, 'description': 'Modular campus core'},
            # Aruba Instant On Series
            {'model_name': 'Aruba Instant On 1430-8G', 'model_number': 'ION-1430-8G', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1GbE'}, 'description': '8-port unmanaged'},
            {'model_name': 'Aruba Instant On 1430-16G', 'model_number': 'ION-1430-16G', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '16x 1GbE'}, 'description': '16-port unmanaged'},
            {'model_name': 'Aruba Instant On 1830-8G', 'model_number': 'ION-1830-8G', 'equipment_type': 'switch', 'is_rackmount': False, 'specifications': {'ports': '8x 1GbE', 'management': 'Smart-managed'}, 'description': '8-port smart-managed'},
            {'model_name': 'Aruba Instant On 1830-24G', 'model_number': 'ION-1830-24G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1GbE SFP'}, 'description': '24-port smart-managed'},
            {'model_name': 'Aruba Instant On 1930-24G', 'model_number': 'ION-1930-24G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1/10GbE SFP/SFP+'}, 'description': '24-port managed'},
            {'model_name': 'Aruba Instant On 1930-24G-PoE', 'model_number': 'ION-1930-24G-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'poe_budget': '195W'}, 'description': '24-port PoE+ managed'},
            {'model_name': 'Aruba Instant On 1930-48G', 'model_number': 'ION-1930-48G', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 1/10GbE SFP/SFP+'}, 'description': '48-port managed'},
            {'model_name': 'Aruba Instant On 1930-48G-PoE', 'model_number': 'ION-1930-48G-PoE', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'poe_budget': '370W'}, 'description': '48-port PoE+ managed'},
            # Aruba 500/600 Series APs - Extended
            {'model_name': 'Aruba AP-505', 'model_number': 'AP-505', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '1.77 Gbps', 'radios': 'Dual 2x2'}, 'description': 'Wi-Fi 6 entry AP'},
            {'model_name': 'Aruba AP-515', 'model_number': 'AP-515', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '2.97 Gbps', 'radios': 'Tri-radio'}, 'description': 'Wi-Fi 6 indoor AP'},
            {'model_name': 'Aruba AP-535', 'model_number': 'AP-535', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '3.9 Gbps', 'radios': 'Tri-radio 4x4'}, 'description': 'Wi-Fi 6 high-density'},
            {'model_name': 'Aruba AP-555', 'model_number': 'AP-555', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '5.95 Gbps', 'radios': 'Tri-radio 4x4'}, 'description': 'Wi-Fi 6 maximum indoor'},
            {'model_name': 'Aruba AP-565', 'model_number': 'AP-565', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '5.4 Gbps', 'deployment': 'Outdoor'}, 'description': 'Outdoor Wi-Fi 6'},
            {'model_name': 'Aruba AP-575', 'model_number': 'AP-575', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '7.8 Gbps', 'deployment': 'Outdoor', 'radios': 'Tri-radio'}, 'description': 'Maximum outdoor Wi-Fi 6'},
            {'model_name': 'Aruba AP-585', 'model_number': 'AP-585', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '10.8 Gbps', 'deployment': 'Indoor/Outdoor', 'radios': 'Quad-radio'}, 'description': 'Maximum performance AP'},
            {'model_name': 'Aruba AP-605', 'model_number': 'AP-605', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6E', 'max_throughput': '3.9 Gbps', '6ghz': 'Yes'}, 'description': 'Wi-Fi 6E entry'},
            {'model_name': 'Aruba AP-615', 'model_number': 'AP-615', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6E', 'max_throughput': '5.95 Gbps', '6ghz': 'Yes', 'radios': 'Tri-radio'}, 'description': 'Wi-Fi 6E indoor'},
            {'model_name': 'Aruba AP-635', 'model_number': 'AP-635', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6E', 'max_throughput': '7.8 Gbps', '6ghz': 'Yes', 'radios': 'Tri-radio 4x4'}, 'description': 'Wi-Fi 6E high-density'},
            {'model_name': 'Aruba AP-655', 'model_number': 'AP-655', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6E', 'max_throughput': '10.8 Gbps', '6ghz': 'Yes', 'radios': 'Tri-radio 4x4'}, 'description': 'Wi-Fi 6E maximum indoor'},
            {'model_name': 'Aruba AP-715', 'model_number': 'AP-715', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 7', 'max_throughput': '9.2 Gbps', 'radios': 'Tri-radio'}, 'description': 'Wi-Fi 7 professional'},
            {'model_name': 'Aruba AP-735', 'model_number': 'AP-735', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 7', 'max_throughput': '13 Gbps', 'radios': 'Tri-radio 4x4'}, 'description': 'Wi-Fi 7 enterprise'},
            # Aruba Instant On APs
            {'model_name': 'Aruba Instant On AP11', 'model_number': 'ION-AP11', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '867 Mbps'}, 'description': 'Entry Wi-Fi 5 AP'},
            {'model_name': 'Aruba Instant On AP11D', 'model_number': 'ION-AP11D', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '867 Mbps', 'downlink': '4x 1GbE'}, 'description': 'Wi-Fi 5 with downlink'},
            {'model_name': 'Aruba Instant On AP12', 'model_number': 'ION-AP12', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.2 Gbps'}, 'description': 'Standard Wi-Fi 5 AP'},
            {'model_name': 'Aruba Instant On AP15', 'model_number': 'ION-AP15', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.75 Gbps', 'deployment': 'Outdoor'}, 'description': 'Outdoor Wi-Fi 5'},
            {'model_name': 'Aruba Instant On AP17', 'model_number': 'ION-AP17', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 5', 'max_throughput': '1.75 Gbps', 'mounting': 'Wall-plate'}, 'description': 'Wall-plate Wi-Fi 5'},
            {'model_name': 'Aruba Instant On AP22', 'model_number': 'ION-AP22', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '1.77 Gbps'}, 'description': 'Entry Wi-Fi 6 AP'},
            {'model_name': 'Aruba Instant On AP25', 'model_number': 'ION-AP25', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '2.97 Gbps', 'deployment': 'Outdoor'}, 'description': 'Outdoor Wi-Fi 6'},
            {'model_name': 'Aruba Instant On AP27', 'model_number': 'ION-AP27', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6', 'max_throughput': '1.77 Gbps', 'mounting': 'Wall-plate'}, 'description': 'Wall-plate Wi-Fi 6'},
            {'model_name': 'Aruba Instant On AP32', 'model_number': 'ION-AP32', 'equipment_type': 'access_point', 'is_rackmount': False, 'specifications': {'wifi_standard': 'Wi-Fi 6E', 'max_throughput': '3.9 Gbps', '6ghz': 'Yes'}, 'description': 'Wi-Fi 6E SMB AP'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"aruba-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_juniper(self):
        """Seed Juniper networking equipment."""
        vendor, created = Vendor.objects.get_or_create(
            name='Juniper Networks',
            defaults={
                'slug': slugify('Juniper Networks'),
                'website': 'https://www.juniper.net',
                'support_url': 'https://support.juniper.net',
                'support_phone': '1-888-586-4737',
                'description': 'Enterprise routing, switching, and security solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Juniper EX Series Switches
            {
                'model_name': 'EX4400-48P',
                'model_number': 'EX4400-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '8x 10GbE SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '1.44 Tbps'
                },
                'description': 'Enterprise access switch with PoE+'
            },
            {
                'model_name': 'EX4400-24P',
                'model_number': 'EX4400-24P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '8x 10GbE SFP+',
                    'poe_budget': '370W',
                    'switching_capacity': '720 Gbps'
                },
                'description': 'Compact access switch with PoE+'
            },
            {
                'model_name': 'EX3400-48P',
                'model_number': 'EX3400-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 10GbE SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Stackable access switch'
            },
            {
                'model_name': 'EX2300-48P',
                'model_number': 'EX2300-48P',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1GbE SFP',
                    'poe_budget': '740W',
                    'switching_capacity': '128 Gbps'
                },
                'description': 'Affordable PoE+ access switch'
            },

            # Juniper SRX Series Firewalls/Routers
            {
                'model_name': 'SRX4600',
                'model_number': 'SRX4600',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '80 Gbps',
                    'firewall_throughput': '40 Gbps',
                    'ips_throughput': '18 Gbps',
                    'vpn_throughput': '30 Gbps',
                    'interfaces': '16x 10GbE SFP+'
                },
                'description': 'High-performance services gateway'
            },
            {
                'model_name': 'SRX1500',
                'model_number': 'SRX1500',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '15 Gbps',
                    'firewall_throughput': '8 Gbps',
                    'ips_throughput': '3.5 Gbps',
                    'vpn_throughput': '5 Gbps',
                    'interfaces': '16x 1GbE, 4x 10GbE SFP+'
                },
                'description': 'Branch services gateway'
            },
            {
                'model_name': 'SRX550',
                'model_number': 'SRX550',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '3 Gbps',
                    'firewall_throughput': '1.5 Gbps',
                    'ips_throughput': '900 Mbps',
                    'vpn_throughput': '1.2 Gbps',
                    'interfaces': '8x 1GbE, 4x 1GbE SFP'
                },
                'description': 'SMB security gateway'
            },
            {
                'model_name': 'SRX380',
                'model_number': 'SRX380',
                'equipment_type': 'firewall',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '2 Gbps',
                    'firewall_throughput': '1 Gbps',
                    'ips_throughput': '600 Mbps',
                    'vpn_throughput': '800 Mbps',
                    'interfaces': '8x 1GbE'
                },
                'description': 'Small branch firewall'
            },

            # Juniper MX Series Routers
            {
                'model_name': 'MX204',
                'model_number': 'MX204',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '400 Gbps',
                    'ports': '4x 100GbE QSFP28, 8x 10GbE SFP+',
                    'routing': 'Full BGP table support'
                },
                'description': 'Universal routing platform'
            },
            {
                'model_name': 'MX104',
                'model_number': 'MX104',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '80 Gbps',
                    'ports': '4x 10GbE SFP+',
                    'routing': 'Enterprise edge router'
                },
                'description': 'Compact universal edge router'
            },

            # EX Series Switches - Extended
            {'model_name': 'EX2300-24P', 'model_number': 'EX2300-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'uplinks': '4x 1GbE/10GbE SFP/SFP+', 'poe_budget': '405W'}, 'description': '24-port PoE+ access'},
            {'model_name': 'EX2300-24T', 'model_number': 'EX2300-24T', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 1GbE/10GbE SFP/SFP+'}, 'description': '24-port access'},
            {'model_name': 'EX2300-48P', 'model_number': 'EX2300-48P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'uplinks': '4x 1GbE/10GbE SFP/SFP+', 'poe_budget': '740W'}, 'description': '48-port PoE+ access'},
            {'model_name': 'EX2300-48T', 'model_number': 'EX2300-48T', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 1GbE/10GbE SFP/SFP+'}, 'description': '48-port access'},
            {'model_name': 'EX3400-24P', 'model_number': 'EX3400-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'uplinks': '4x 10GbE SFP+', 'poe_budget': '405W', 'stacking': 'Yes'}, 'description': '24-port stackable PoE+'},
            {'model_name': 'EX3400-24T', 'model_number': 'EX3400-24T', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 10GbE SFP+', 'stacking': 'Yes'}, 'description': '24-port stackable'},
            {'model_name': 'EX3400-48P', 'model_number': 'EX3400-48P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'uplinks': '4x 10GbE SFP+', 'poe_budget': '740W', 'stacking': 'Yes'}, 'description': '48-port stackable PoE+'},
            {'model_name': 'EX3400-48T', 'model_number': 'EX3400-48T', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 10GbE SFP+', 'stacking': 'Yes'}, 'description': '48-port stackable'},
            {'model_name': 'EX4300-24P', 'model_number': 'EX4300-24P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE PoE+', 'uplinks': '4x 10GbE SFP+', 'poe_budget': '405W'}, 'description': '24-port enterprise PoE+'},
            {'model_name': 'EX4300-24T', 'model_number': 'EX4300-24T', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE', 'uplinks': '4x 10GbE SFP+'}, 'description': '24-port enterprise'},
            {'model_name': 'EX4300-32F', 'model_number': 'EX4300-32F', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE SFP', 'uplinks': '8x 10GbE SFP+'}, 'description': '32-port fiber'},
            {'model_name': 'EX4300-48P', 'model_number': 'EX4300-48P', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE PoE+', 'uplinks': '4x 10GbE SFP+', 'poe_budget': '740W'}, 'description': '48-port enterprise PoE+'},
            {'model_name': 'EX4300-48T', 'model_number': 'EX4300-48T', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 1GbE', 'uplinks': '4x 10GbE SFP+'}, 'description': '48-port enterprise'},
            {'model_name': 'EX4600-40F', 'model_number': 'EX4600-40F', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '24x 1GbE/10GbE SFP/SFP+', 'uplinks': '16x 40GbE QSFP+'}, 'description': '40-port aggregation'},
            {'model_name': 'EX4650-48Y', 'model_number': 'EX4650-48Y', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 10GbE/25GbE SFP28', 'uplinks': '8x 40GbE/100GbE QSFP28'}, 'description': '48-port 25G aggregation'},
            {'model_name': 'EX9200-15C', 'model_number': 'EX9200-15C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 13, 'specifications': {'capacity': 'Modular chassis', 'throughput': '13.2 Tbps', 'slots': '15'}, 'description': 'Modular core switch'},
            {'model_name': 'EX9200-8C', 'model_number': 'EX9200-8C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 8, 'specifications': {'capacity': 'Modular chassis', 'throughput': '9.6 Tbps', 'slots': '8'}, 'description': 'Compact modular core'},
            # SRX Series Firewalls - Extended
            {'model_name': 'SRX300', 'model_number': 'SRX300', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1 Gbps', 'firewall_throughput': '750 Mbps', 'interfaces': '8x 1GbE'}, 'description': 'Branch firewall'},
            {'model_name': 'SRX320', 'model_number': 'SRX320', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.2 Gbps', 'firewall_throughput': '1 Gbps', 'interfaces': '8x 1GbE'}, 'description': 'Enhanced branch'},
            {'model_name': 'SRX340', 'model_number': 'SRX340', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '1.5 Gbps', 'firewall_throughput': '1.2 Gbps', 'interfaces': '16x 1GbE'}, 'description': 'High-perf branch'},
            {'model_name': 'SRX345', 'model_number': 'SRX345', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '2 Gbps', 'firewall_throughput': '1.5 Gbps', 'interfaces': '16x 1GbE, 4x SFP'}, 'description': 'Maximum branch'},
            {'model_name': 'SRX380', 'model_number': 'SRX380', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'throughput': '2.5 Gbps', 'firewall_throughput': '2 Gbps', 'interfaces': '16x 1GbE, 8x SFP'}, 'description': 'Distributed enterprise'},
            {'model_name': 'SRX550', 'model_number': 'SRX550', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '5 Gbps', 'firewall_throughput': '3 Gbps', 'interfaces': '16x 1GbE, 8x 10GbE SFP+'}, 'description': 'Mid-range enterprise'},
            {'model_name': 'SRX550-645DP', 'model_number': 'SRX550-645DP', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '5 Gbps', 'poe': 'PoE++ support'}, 'description': 'PoE enterprise firewall'},
            {'model_name': 'SRX1500', 'model_number': 'SRX1500', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '10 Gbps', 'firewall_throughput': '5 Gbps', 'interfaces': '16x 1GbE, 8x 10GbE SFP+'}, 'description': 'Enterprise data center'},
            {'model_name': 'SRX4100', 'model_number': 'SRX4100', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '40 Gbps', 'firewall_throughput': '20 Gbps'}, 'description': 'High-capacity DC'},
            {'model_name': 'SRX4200', 'model_number': 'SRX4200', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '60 Gbps', 'firewall_throughput': '30 Gbps'}, 'description': 'Large enterprise DC'},
            {'model_name': 'SRX4600', 'model_number': 'SRX4600', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '80 Gbps', 'firewall_throughput': '40 Gbps'}, 'description': 'Maximum SRX series'},
            {'model_name': 'SRX5400', 'model_number': 'SRX5400', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 10, 'specifications': {'capacity': 'Modular chassis', 'throughput': '120 Gbps'}, 'description': 'Modular service provider'},
            {'model_name': 'SRX5600', 'model_number': 'SRX5600', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 10, 'specifications': {'capacity': 'Modular chassis', 'throughput': '160 Gbps'}, 'description': 'High-capacity modular'},
            {'model_name': 'SRX5800', 'model_number': 'SRX5800', 'equipment_type': 'firewall', 'is_rackmount': True, 'rack_units': 14, 'specifications': {'capacity': 'Modular chassis', 'throughput': '200 Gbps'}, 'description': 'Maximum modular SP'},
            # vSRX Virtual Firewalls
            {'model_name': 'vSRX', 'model_number': 'vSRX', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '1 Gbps', 'vcpu': '4'}, 'description': 'Virtual firewall - Standard'},
            {'model_name': 'vSRX3.0', 'model_number': 'vSRX3', 'equipment_type': 'firewall', 'is_rackmount': False, 'specifications': {'deployment': 'Virtual', 'throughput': '100 Gbps', 'vcpu': 'Up to 24'}, 'description': 'Virtual firewall - High-perf'},
            # MX Series Routers
            {'model_name': 'MX204', 'model_number': 'MX204', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'throughput': '400 Gbps', 'ports': '4x 100GbE QSFP28'}, 'description': 'Compact universal router'},
            {'model_name': 'MX304', 'model_number': 'MX304', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'throughput': '800 Gbps', 'ports': '8x 100GbE QSFP28'}, 'description': 'Universal router'},
            {'model_name': 'MX480', 'model_number': 'MX480', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 7, 'specifications': {'capacity': 'Modular', 'throughput': '2.4 Tbps', 'slots': '4'}, 'description': 'Modular edge router'},
            {'model_name': 'MX960', 'model_number': 'MX960', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 13, 'specifications': {'capacity': 'Modular', 'throughput': '10 Tbps', 'slots': '12'}, 'description': 'Enterprise core router'},
            {'model_name': 'MX2008', 'model_number': 'MX2008', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 8, 'specifications': {'capacity': 'Modular', 'throughput': '8 Tbps'}, 'description': 'Compact modular router'},
            {'model_name': 'MX2010', 'model_number': 'MX2010', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 5, 'specifications': {'throughput': '16 Tbps'}, 'description': 'High-density edge router'},
            {'model_name': 'MX2020', 'model_number': 'MX2020', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 10, 'specifications': {'throughput': '24 Tbps'}, 'description': 'Service provider router'},
            {'model_name': 'MX10003', 'model_number': 'MX10003', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 3, 'specifications': {'throughput': '4.8 Tbps', 'ports': '48x 100GbE'}, 'description': 'Universal routing platform'},
            {'model_name': 'MX10008', 'model_number': 'MX10008', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 8, 'specifications': {'capacity': 'Modular', 'throughput': '19.2 Tbps'}, 'description': 'Modular universal platform'},
            {'model_name': 'MX10016', 'model_number': 'MX10016', 'equipment_type': 'router', 'is_rackmount': True, 'rack_units': 16, 'specifications': {'capacity': 'Modular', 'throughput': '38.4 Tbps'}, 'description': 'Maximum universal platform'},
            # QFX Series Data Center Switches
            {'model_name': 'QFX5120-48Y', 'model_number': 'QFX5120-48Y', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '48x 25GbE SFP28', 'uplinks': '8x 100GbE QSFP28'}, 'description': 'ToR 25G switch'},
            {'model_name': 'QFX5120-32C', 'model_number': 'QFX5120-32C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '32x 100GbE QSFP28'}, 'description': 'Spine 100G switch'},
            {'model_name': 'QFX5200-32C', 'model_number': 'QFX5200-32C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 1, 'specifications': {'ports': '32x 100GbE QSFP28'}, 'description': 'DC spine switch'},
            {'model_name': 'QFX5210-64C', 'model_number': 'QFX5210-64C', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'ports': '64x 100GbE QSFP28'}, 'description': 'High-density DC switch'},
            {'model_name': 'QFX10002-36Q', 'model_number': 'QFX10002-36Q', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'ports': '36x 40GbE QSFP+'}, 'description': 'Core fabric switch'},
            {'model_name': 'QFX10002-72Q', 'model_number': 'QFX10002-72Q', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 2, 'specifications': {'ports': '72x 40GbE QSFP+'}, 'description': 'High-density core'},
            {'model_name': 'QFX10008', 'model_number': 'QFX10008', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 14, 'specifications': {'capacity': 'Modular chassis', 'throughput': '128 Tbps'}, 'description': 'Modular core switch'},
            {'model_name': 'QFX10016', 'model_number': 'QFX10016', 'equipment_type': 'switch', 'is_rackmount': True, 'rack_units': 21, 'specifications': {'capacity': 'Modular chassis', 'throughput': '256 Tbps'}, 'description': 'Maximum modular core'},
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"juniper-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_ruckus(self):
        """Seed Ruckus wireless access points."""
        vendor, created = Vendor.objects.get_or_create(
            name='Ruckus',
            defaults={
                'slug': slugify('Ruckus'),
                'website': 'https://www.ruckusnetworks.com',
                'support_url': 'https://support.ruckuswireless.com',
                'description': 'Enterprise wireless and wired networking solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Ruckus Access Points
            {
                'model_name': 'R770',
                'model_number': 'R770',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6E (802.11ax)',
                    'throughput': '10.8 Gbps',
                    'clients': '1024 concurrent',
                    'poe': '802.3bt (PoE++)',
                    'ports': '1x 10Gbps Ethernet'
                },
                'description': 'High-performance WiFi 6E access point'
            },
            {
                'model_name': 'R750',
                'model_number': 'R750',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '5.4 Gbps',
                    'clients': '1024 concurrent',
                    'poe': '802.3bt (PoE++)',
                    'ports': '1x 5Gbps mGig Ethernet'
                },
                'description': 'WiFi 6 indoor access point'
            },
            {
                'model_name': 'R730',
                'model_number': 'R730',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '3.9 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x 2.5Gbps Ethernet'
                },
                'description': 'WiFi 6 access point'
            },
            {
                'model_name': 'R650',
                'model_number': 'R650',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 6 (802.11ax)',
                    'throughput': '2.98 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at',
                    'ports': '1x 2.5Gbps Ethernet'
                },
                'description': 'Compact WiFi 6 access point'
            },
            {
                'model_name': 'R610',
                'model_number': 'R610',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 5 (802.11ac Wave 2)',
                    'throughput': '1.77 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at'
                },
                'description': 'WiFi 5 indoor access point'
            },
            {
                'model_name': 'R550',
                'model_number': 'R550',
                'equipment_type': 'access_point',
                'is_rackmount': False,
                'specifications': {
                    'speed': 'WiFi 5 (802.11ac Wave 2)',
                    'throughput': '1.73 Gbps',
                    'clients': '512 concurrent',
                    'poe': '802.3at'
                },
                'description': 'WiFi 5 access point'
            },
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"ruckus-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_yealink(self):
        """Seed Yealink VoIP phones."""
        vendor, created = Vendor.objects.get_or_create(
            name='Yealink',
            defaults={
                'slug': slugify('Yealink'),
                'website': 'https://www.yealink.com',
                'support_url': 'https://support.yealink.com',
                'description': 'Business VoIP phones and video conferencing solutions',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Yealink T5 Series
            {
                'model_name': 'T58W Pro',
                'model_number': 'T58W',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 SIP accounts',
                    'display': '7" touchscreen',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'WiFi, Bluetooth, USB, HD audio'
                },
                'description': 'Executive touchscreen IP phone'
            },
            {
                'model_name': 'T57W',
                'model_number': 'T57W',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 SIP accounts',
                    'display': '7" touchscreen',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'WiFi, Bluetooth, USB, HD audio'
                },
                'description': 'Premium touchscreen IP phone'
            },
            {
                'model_name': 'T54W',
                'model_number': 'T54W',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 SIP accounts',
                    'display': '4.3" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'WiFi, Bluetooth, USB, HD audio'
                },
                'description': 'Mid-range IP phone with WiFi'
            },
            {
                'model_name': 'T53W',
                'model_number': 'T53W',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 SIP accounts',
                    'display': '3.7" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'WiFi, Bluetooth, HD audio'
                },
                'description': 'Business IP phone with WiFi'
            },

            # Yealink T4 Series
            {
                'model_name': 'T48S',
                'model_number': 'T48S',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 SIP accounts',
                    'display': '7" color touchscreen',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'USB, Bluetooth, HD audio'
                },
                'description': 'Color touchscreen IP phone'
            },
            {
                'model_name': 'T46S',
                'model_number': 'T46S',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 SIP accounts',
                    'display': '4.3" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'USB, HD audio'
                },
                'description': 'Color display IP phone'
            },
            {
                'model_name': 'T43U',
                'model_number': 'T43U',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 SIP accounts',
                    'display': '3.7" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'USB, HD audio'
                },
                'description': 'Mid-level IP phone'
            },
            {
                'model_name': 'T42S',
                'model_number': 'T42S',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 SIP accounts',
                    'display': '2.7" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Standard business IP phone'
            },
            {
                'model_name': 'T41S',
                'model_number': 'T41S',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '6 SIP accounts',
                    'display': '2.7" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Entry business IP phone'
            },

            # Yealink T3 Series
            {
                'model_name': 'T34W',
                'model_number': 'T34W',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 SIP accounts',
                    'display': '2.4" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'WiFi, Bluetooth, HD audio'
                },
                'description': 'Compact WiFi IP phone'
            },
            {
                'model_name': 'T33G',
                'model_number': 'T33G',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 SIP accounts',
                    'display': '2.4" color LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Essential IP phone'
            },
            {
                'model_name': 'T31G',
                'model_number': 'T31G',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '2 SIP accounts',
                    'display': '2.3" LCD',
                    'network': 'Dual Gigabit ports',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Entry-level IP phone'
            },
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"yealink-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0

    def seed_poly(self):
        """Seed Poly VoIP phones."""
        vendor, created = Vendor.objects.get_or_create(
            name='Poly',
            defaults={
                'slug': slugify('Poly'),
                'website': 'https://www.poly.com',
                'support_url': 'https://www.poly.com/us/en/support',
                'support_phone': '1-800-765-9669',
                'description': 'Professional VoIP phones and communication devices',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(f"  Created vendor: {vendor.name}")

        equipment = [
            # Poly VVX Series
            {
                'model_name': 'VVX 601',
                'model_number': 'VVX-601',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 lines',
                    'display': '4.3" color touchscreen',
                    'network': 'Dual Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio, USB, Bluetooth, WiFi'
                },
                'description': 'Executive touchscreen business phone'
            },
            {
                'model_name': 'VVX 501',
                'model_number': 'VVX-501',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 lines',
                    'display': '3.5" color touchscreen',
                    'network': 'Dual Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio, USB, Bluetooth'
                },
                'description': 'Premium touchscreen business phone'
            },
            {
                'model_name': 'VVX 450',
                'model_number': 'VVX-450',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 lines',
                    'display': '4.3" color LCD',
                    'network': 'Dual Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio, USB'
                },
                'description': 'Color business phone'
            },
            {
                'model_name': 'VVX 401',
                'model_number': 'VVX-401',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '12 lines',
                    'display': '3.5" color LCD',
                    'network': 'Dual Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio, USB'
                },
                'description': 'Mid-range color IP phone'
            },
            {
                'model_name': 'VVX 350',
                'model_number': 'VVX-350',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '6 lines',
                    'display': '3.5" color LCD',
                    'network': 'Dual Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Standard business IP phone'
            },
            {
                'model_name': 'VVX 250',
                'model_number': 'VVX-250',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '4 lines',
                    'display': '2.8" color LCD',
                    'network': 'Dual Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Entry-level color IP phone'
            },
            {
                'model_name': 'VVX 150',
                'model_number': 'VVX-150',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '2 lines',
                    'display': 'Backlit LCD',
                    'network': 'Dual 10/100 Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Basic business IP phone'
            },

            # Poly CCX Series
            {
                'model_name': 'CCX 700',
                'model_number': 'CCX-700',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': 'Teams/Zoom native',
                    'display': '7" touchscreen',
                    'network': 'Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'Video, HD audio, Android, WiFi, Bluetooth'
                },
                'description': 'Premium collaboration phone with video'
            },
            {
                'model_name': 'CCX 600',
                'model_number': 'CCX-600',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': 'Teams/Zoom native',
                    'display': '7" touchscreen',
                    'network': 'Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio, Android, WiFi, Bluetooth'
                },
                'description': 'Collaboration phone with touchscreen'
            },
            {
                'model_name': 'CCX 500',
                'model_number': 'CCX-500',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': 'Teams/Zoom native',
                    'display': '5" touchscreen',
                    'network': 'Gigabit Ethernet',
                    'poe': '802.3af',
                    'features': 'HD audio, Android'
                },
                'description': 'Compact collaboration phone'
            },
        ]

        for eq_data in equipment:
            eq, created = EquipmentModel.objects.get_or_create(
                vendor=vendor,
                model_name=eq_data['model_name'],
                defaults={
                    **eq_data,
                    'slug': slugify(f"poly-{eq_data['model_name']}")
                }
            )
            if created:
                self.stdout.write(f"    Created equipment: {eq}")

        return 1 if created else 0
