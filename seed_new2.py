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
            }
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
            # Lenovo ThinkSystem Servers
            {
                'model_name': 'ThinkSystem SR650 V3',
                'model_number': 'SR650-V3',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 4th Gen',
                    'memory': 'Up to 8TB DDR5',
                    'storage': 'Up to 24x 2.5" drives',
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
                'description': '1U dense rack server'
            },
            {
                'model_name': 'ThinkSystem SR650 V2',
                'model_number': 'SR650-V2',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable 3rd Gen',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 24x 2.5" drives',
                    'power': '750W-1600W redundant PSU'
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
                    'power': '750W-1100W redundant PSU'
                },
                'description': '1U rack server for data centers'
            },
            {
                'model_name': 'ThinkSystem SR250 V2',
                'model_number': 'SR250-V2',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'processor': 'Single Intel Xeon E-2300',
                    'memory': 'Up to 128GB DDR4',
                    'storage': 'Up to 8x 2.5" drives',
                    'power': '300W-450W PSU'
                },
                'description': '1U entry server for SMB'
            },
            {
                'model_name': 'ThinkSystem SR665 V3',
                'model_number': 'SR665-V3',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'processor': 'Dual AMD EPYC 4th Gen',
                    'memory': 'Up to 6TB DDR5',
                    'storage': 'Up to 24x 2.5" drives',
                    'power': '1100W-2000W redundant PSU'
                },
                'description': '2U AMD-based server'
            },
            {
                'model_name': 'ThinkSystem SR645 V3',
                'model_number': 'SR645-V3',
                'equipment_type': 'server',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'processor': 'Dual AMD EPYC 4th Gen',
                    'memory': 'Up to 3TB DDR5',
                    'storage': 'Up to 10x 2.5" drives',
                    'power': '800W-1600W redundant PSU'
                },
                'description': '1U AMD performance server'
            },
            {
                'model_name': 'ThinkSystem ST650 V2',
                'model_number': 'ST650-V2',
                'equipment_type': 'server',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 4TB DDR4',
                    'storage': 'Up to 14x 3.5" drives',
                    'power': '750W-1100W redundant PSU',
                    'form_factor': 'Tower'
                },
                'description': 'Tower server for office environments'
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
                    'form_factor': 'Tower'
                },
                'description': 'Entry tower server for small business'
            },

            # Lenovo ThinkCentre Desktops
            {
                'model_name': 'ThinkCentre M90q Gen 4',
                'model_number': 'M90q-G4',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'form_factor': 'Tiny (1L)',
                    'graphics': 'Integrated'
                },
                'description': 'Ultra-small business desktop'
            },
            {
                'model_name': 'ThinkCentre M90t Gen 4',
                'model_number': 'M90t-G4',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7/i9 13th Gen',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'form_factor': 'Tower',
                    'graphics': 'Integrated or discrete'
                },
                'description': 'Premium business tower desktop'
            },
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
                    'graphics': 'Integrated'
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

            # Lenovo ThinkStation Workstations
            {
                'model_name': 'ThinkStation P360 Ultra',
                'model_number': 'P360-Ultra',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD',
                    'graphics': 'NVIDIA RTX A series',
                    'form_factor': 'Ultra-compact'
                },
                'description': 'Compact professional workstation'
            },
            {
                'model_name': 'ThinkStation P3 Tower',
                'model_number': 'P3-Tower',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 or Xeon W',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'NVIDIA RTX/Quadro',
                    'form_factor': 'Tower'
                },
                'description': 'Entry professional workstation'
            },
            {
                'model_name': 'ThinkStation P5',
                'model_number': 'P5',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Xeon W-3300',
                    'memory': 'Up to 512GB DDR4',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'Up to 2x NVIDIA RTX A series',
                    'form_factor': 'Tower'
                },
                'description': 'High-performance workstation'
            },
            {
                'model_name': 'ThinkStation P7',
                'model_number': 'P7',
                'equipment_type': 'workstation',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Dual Intel Xeon Scalable',
                    'memory': 'Up to 2TB DDR5',
                    'storage': 'Multiple M.2 NVMe + SATA',
                    'graphics': 'Up to 2x NVIDIA RTX A series',
                    'form_factor': 'Tower'
                },
                'description': 'Ultimate dual-socket workstation'
            },

            # Lenovo ThinkPad Laptops
            {
                'model_name': 'ThinkPad X1 Carbon Gen 11',
                'model_number': 'X1-Carbon-G11',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB LPDDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/WUXGA/2.8K OLED',
                    'battery': 'Up to 16 hours',
                    'weight': '2.48 lbs'
                },
                'description': 'Premium 14" ultrabook'
            },
            {
                'model_name': 'ThinkPad X1 Yoga Gen 8',
                'model_number': 'X1-Yoga-G8',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 64GB LPDDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" WUXGA/2.8K OLED touch',
                    'battery': 'Up to 15 hours',
                    'weight': '3.0 lbs'
                },
                'description': 'Convertible 2-in-1 business laptop'
            },
            {
                'model_name': 'ThinkPad T14 Gen 4',
                'model_number': 'T14-G4',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 48GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '14" FHD/WUXGA',
                    'battery': 'Up to 14 hours',
                    'weight': '3.2 lbs'
                },
                'description': 'Mainstream 14" business laptop'
            },
            {
                'model_name': 'ThinkPad T16 Gen 2',
                'model_number': 'T16-G2',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 48GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 2TB',
                    'display': '16" WUXGA',
                    'battery': 'Up to 12 hours',
                    'weight': '4.2 lbs'
                },
                'description': 'Large-screen business laptop'
            },
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
                'description': 'Essential 14" business laptop'
            },
            {
                'model_name': 'ThinkPad E14 Gen 5',
                'model_number': 'E14-G5',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i3/i5/i7 13th Gen',
                    'memory': 'Up to 40GB DDR4',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '14" FHD',
                    'battery': 'Up to 10 hours',
                    'weight': '3.5 lbs'
                },
                'description': 'Affordable business laptop'
            },
            {
                'model_name': 'ThinkPad E16 Gen 1',
                'model_number': 'E16-G1',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i5/i7 13th Gen',
                    'memory': 'Up to 40GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 1TB',
                    'display': '16" WUXGA',
                    'battery': 'Up to 10 hours',
                    'weight': '4.2 lbs'
                },
                'description': 'Large affordable business laptop'
            },

            # Lenovo ThinkPad P Series Mobile Workstations
            {
                'model_name': 'ThinkPad P1 Gen 6',
                'model_number': 'P1-G6',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 13th Gen',
                    'memory': 'Up to 64GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 4TB',
                    'display': '16" WUXGA/4K OLED',
                    'graphics': 'NVIDIA RTX A series',
                    'weight': '4.0 lbs'
                },
                'description': 'Thin mobile workstation'
            },
            {
                'model_name': 'ThinkPad P16 Gen 2',
                'model_number': 'P16-G2',
                'equipment_type': 'laptop',
                'is_rackmount': False,
                'specifications': {
                    'processor': 'Intel Core i7/i9 13th Gen or Xeon',
                    'memory': 'Up to 128GB DDR5',
                    'storage': 'M.2 NVMe SSD up to 8TB',
                    'display': '16" WUXGA/4K',
                    'graphics': 'NVIDIA RTX A series',
                    'weight': '5.6 lbs'
                },
                'description': 'High-performance mobile workstation'
            },
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
            # Cisco Catalyst Switches
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
                'description': 'Enterprise-grade stackable switch with PoE+'
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
                    'switching_capacity': '208 Gbps'
                },
                'description': '24-port enterprise switch with PoE+'
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
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Access layer switch with PoE+'
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
                    'switching_capacity': '128 Gbps'
                },
                'description': 'Compact access switch with PoE+'
            },
            {
                'model_name': 'Catalyst 2960X-48FPS-L',
                'model_number': '2960X-48FPS-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '2x 10G SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '176 Gbps'
                },
                'description': 'Stackable access switch with PoE+'
            },
            {
                'model_name': 'Catalyst 2960X-24PS-L',
                'model_number': '2960X-24PS-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '2x 10G SFP+',
                    'poe_budget': '370W',
                    'switching_capacity': '108 Gbps'
                },
                'description': '24-port access switch with PoE+'
            },
            {
                'model_name': 'Catalyst 2960-X-48FPD-L',
                'model_number': '2960-X-48FPD-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '2x 10G SFP+',
                    'poe_budget': '740W',
                    'switching_capacity': '216 Gbps'
                },
                'description': 'Access switch with PoE+ and uplinks'
            },
            {
                'model_name': 'Catalyst 1000-48P-4G-L',
                'model_number': 'C1000-48P-4G-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '48x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '370W',
                    'switching_capacity': '104 Gbps'
                },
                'description': 'SMB switch with PoE+'
            },
            {
                'model_name': 'Catalyst 1000-24P-4G-L',
                'model_number': 'C1000-24P-4G-L',
                'equipment_type': 'switch',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'ports': '24x 1GbE PoE+',
                    'uplinks': '4x 1G SFP',
                    'poe_budget': '195W',
                    'switching_capacity': '56 Gbps'
                },
                'description': 'Small business switch with PoE+'
            },
            {
                'model_name': 'Catalyst 1000-8P-2G-L',
                'model_number': 'C1000-8P-2G-L',
                'equipment_type': 'switch',
                'is_rackmount': False,
                'specifications': {
                    'ports': '8x 1GbE PoE+',
                    'uplinks': '2x 1G SFP',
                    'poe_budget': '67W',
                    'switching_capacity': '20 Gbps'
                },
                'description': 'Desktop switch with PoE+'
            },

            # Cisco Routers
            {
                'model_name': 'ISR 4461',
                'model_number': 'ISR4461',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 2,
                'specifications': {
                    'throughput': '10 Gbps',
                    'ports': '3x 1GbE',
                    'wan_slots': '4x',
                    'services': 'Integrated security, routing, and SD-WAN'
                },
                'description': 'High-performance branch router'
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
                    'wan_slots': '4x',
                    'services': 'Integrated security and routing'
                },
                'description': 'Mid-range integrated services router'
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
                    'wan_slots': '4x',
                    'services': 'Integrated security and routing'
                },
                'description': 'Branch office router with security'
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
                    'wan_slots': '4x',
                    'services': 'Integrated security and routing'
                },
                'description': 'Integrated services router for branch offices'
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
                    'wan_slots': '3x',
                    'services': 'Integrated security and routing'
                },
                'description': 'Small branch router'
            },
            {
                'model_name': 'ISR 1100-8P',
                'model_number': 'ISR1100-8P',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '500 Mbps',
                    'ports': '8x 1GbE with PoE',
                    'features': 'SD-WAN, integrated switch'
                },
                'description': 'Compact branch router with switch'
            },
            {
                'model_name': 'ASR 1001-X',
                'model_number': 'ASR1001-X',
                'equipment_type': 'router',
                'is_rackmount': True,
                'rack_units': 1,
                'specifications': {
                    'throughput': '20 Gbps',
                    'ports': '6x 1GbE, 2x 10GbE SFP+',
                    'services': 'Aggregation services router'
                },
                'description': 'Enterprise aggregation router'
            },

            # Cisco IP Phones 7800 Series
            {
                'model_name': 'IP Phone 7861',
                'model_number': '7861',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '16 lines',
                    'display': 'Grayscale display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'Full-duplex speakerphone'
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
                    'display': 'Grayscale display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'Full-duplex speakerphone'
                },
                'description': 'Standard business IP phone'
            },
            {
                'model_name': 'IP Phone 7821',
                'model_number': '7821',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '2 lines',
                    'display': 'Grayscale display',
                    'network': 'Dual 10/100 ports',
                    'poe': '802.3af',
                    'features': 'Half-duplex speakerphone'
                },
                'description': 'Entry-level IP phone'
            },

            # Cisco IP Phones 8800 Series
            {
                'model_name': 'IP Phone 8865',
                'model_number': '8865',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" color touchscreen',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD video, Bluetooth, WiFi, USB'
                },
                'description': 'Executive IP phone with video'
            },
            {
                'model_name': 'IP Phone 8861',
                'model_number': '8861',
                'equipment_type': 'phone',
                'is_rackmount': False,
                'specifications': {
                    'lines': '5 lines',
                    'display': '5" color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, Bluetooth, USB'
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
                    'display': '5" color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio'
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
                    'display': '5" color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio, Bluetooth'
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
                    'display': '5" color display',
                    'network': 'Dual 10/100/1000 ports',
                    'poe': '802.3af',
                    'features': 'HD audio'
                },
                'description': 'Standard business IP phone'
            },
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
