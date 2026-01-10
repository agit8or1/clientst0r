"""
Django management command to populate sample data for testing
Usage: python manage.py populate_sample_data --org-id 1
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from core.models import Organization, Tag
from assets.models import Asset, Contact
from vault.models import Password
from docs.models import Document, DocumentCategory
from monitoring.models import WebsiteMonitor, Expiration, Rack, RackDevice, Subnet, IPAddress
import random


class Command(BaseCommand):
    help = 'Populate sample data for an organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id',
            type=int,
            required=True,
            help='Organization ID to populate data for',
        )
        parser.add_argument(
            '--admin-user',
            type=str,
            default='admin',
            help='Admin username (default: admin)',
        )

    def handle(self, *args, **options):
        org_id = options['org_id']
        admin_username = options['admin_user']

        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Organization with ID {org_id} not found"))
            return

        try:
            admin_user = User.objects.get(username=admin_username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User {admin_username} not found"))
            return

        self.stdout.write(f"Populating sample data for organization: {org.name}")

        # Create tags
        self.stdout.write("Creating tags...")
        tags = []
        for tag_name in ['Production', 'Development', 'Critical', 'Internal', 'External']:
            tag, _ = Tag.objects.get_or_create(
                organization=org,
                name=tag_name,
                defaults={'color': self.random_color()}
            )
            tags.append(tag)

        # Create categories
        self.stdout.write("Creating document categories...")
        categories = []
        for cat_name in ['Procedures', 'Policies', 'Guides', 'Reference']:
            cat, _ = DocumentCategory.objects.get_or_create(
                organization=org,
                name=cat_name,
                defaults={'slug': cat_name.lower()}
            )
            categories.append(cat)

        # Create contacts
        self.stdout.write("Creating contacts...")
        contacts = []
        contact_data = [
            {'first_name': 'John', 'last_name': 'Smith', 'email': 'john.smith@example.com', 'phone': '555-0101', 'title': 'IT Manager'},
            {'first_name': 'Sarah', 'last_name': 'Johnson', 'email': 'sarah.j@example.com', 'phone': '555-0102', 'title': 'Network Admin'},
            {'first_name': 'Mike', 'last_name': 'Davis', 'email': 'mike.d@example.com', 'phone': '555-0103', 'title': 'Security Lead'},
            {'first_name': 'Lisa', 'last_name': 'Chen', 'email': 'lisa.c@example.com', 'phone': '555-0104', 'title': 'DevOps Engineer'},
        ]
        for data in contact_data:
            contact, _ = Contact.objects.get_or_create(
                organization=org,
                email=data['email'],
                defaults=data
            )
            contacts.append(contact)

        # Create assets
        self.stdout.write("Creating assets...")
        assets = []
        asset_data = [
            {'name': 'Primary Domain Controller', 'asset_type': 'server', 'serial_number': 'SRV-DC01-2024'},
            {'name': 'File Server', 'asset_type': 'server', 'serial_number': 'SRV-FS01-2024'},
            {'name': 'Firewall - Main', 'asset_type': 'network', 'serial_number': 'FW-001-2024'},
            {'name': 'Core Switch', 'asset_type': 'network', 'serial_number': 'SW-CORE-001'},
            {'name': 'Backup Server', 'asset_type': 'server', 'serial_number': 'SRV-BK01-2024'},
        ]
        for data in asset_data:
            asset, _ = Asset.objects.get_or_create(
                organization=org,
                name=data['name'],
                defaults=data
            )
            asset.tags.add(random.choice(tags))
            assets.append(asset)

        # Create passwords
        self.stdout.write("Creating password entries...")
        password_data = [
            {'title': 'Domain Admin Account', 'username': 'administrator', 'url': ''},
            {'title': 'Firewall Admin', 'username': 'admin', 'url': 'https://firewall.example.com'},
            {'title': 'Server Root Password', 'username': 'root', 'url': ''},
            {'title': 'Backup System', 'username': 'backup_admin', 'url': 'https://backup.example.com'},
        ]
        for data in password_data:
            pwd, created = Password.objects.get_or_create(
                organization=org,
                title=data['title'],
                defaults={
                    **data,
                    'created_by': admin_user,
                    'last_modified_by': admin_user,
                }
            )
            if created:
                pwd.set_password(f'SamplePassword123!{random.randint(1000,9999)}')
                pwd.save()
                pwd.tags.add(random.choice(tags))

        # Create documents
        self.stdout.write("Creating documents...")
        doc_data = [
            {'title': 'Network Documentation', 'slug': 'network-documentation',
             'body': '<h1>Network Overview</h1><p>This document contains our network infrastructure details.</p>'},
            {'title': 'Backup Procedures', 'slug': 'backup-procedures',
             'body': '<h1>Backup Procedures</h1><p>Daily backup procedures and recovery steps.</p>'},
            {'title': 'Security Policy', 'slug': 'security-policy',
             'body': '<h1>Security Policy</h1><p>Company-wide security policies and requirements.</p>'},
        ]
        for data in doc_data:
            doc, _ = Document.objects.get_or_create(
                organization=org,
                slug=data['slug'],
                defaults={
                    **data,
                    'category': random.choice(categories),
                    'is_published': True,
                    'created_by': admin_user,
                    'last_modified_by': admin_user,
                }
            )
            doc.tags.add(random.choice(tags))

        # Create website monitors
        self.stdout.write("Creating website monitors...")
        monitor_data = [
            {'name': 'Company Website', 'url': 'https://mspreboot.com'},
            {'name': 'Internal Portal', 'url': 'https://portal.example.com'},
            {'name': 'API Endpoint', 'url': 'https://api.example.com'},
        ]
        for data in monitor_data:
            WebsiteMonitor.objects.get_or_create(
                organization=org,
                url=data['url'],
                defaults={
                    'name': data['name'],
                    'is_enabled': True,
                    'check_interval_minutes': 15,
                    'notify_on_down': True,
                }
            )

        # Create expirations
        self.stdout.write("Creating expiration tracking...")
        expiration_data = [
            {'name': 'SSL Certificate - Main Site', 'expiration_type': 'ssl_cert', 'days': 90},
            {'name': 'Domain Registration', 'expiration_type': 'domain', 'days': 180},
            {'name': 'Microsoft 365 License', 'expiration_type': 'license', 'days': 365},
            {'name': 'Support Contract - Firewall', 'expiration_type': 'contract', 'days': 120},
        ]
        for data in expiration_data:
            Expiration.objects.get_or_create(
                organization=org,
                name=data['name'],
                defaults={
                    'expiration_type': data['expiration_type'],
                    'expires_at': timezone.now() + timedelta(days=data['days']),
                    'warning_days': 30,
                    'auto_renew': False,
                }
            )

        # Create racks
        self.stdout.write("Creating rack infrastructure...")
        rack, _ = Rack.objects.get_or_create(
            organization=org,
            name='Rack A1',
            defaults={
                'location': 'Data Center - Row 1',
                'units': 42,
                'power_capacity_watts': 5000,
                'cooling_capacity_btu': 10000,
            }
        )

        # Create rack devices
        device_data = [
            {'name': 'Core Switch', 'start_unit': 40, 'units': 2, 'power_draw_watts': 150, 'color': '#0d6efd'},
            {'name': 'Firewall', 'start_unit': 38, 'units': 1, 'power_draw_watts': 100, 'color': '#dc3545'},
            {'name': 'Server 1', 'start_unit': 35, 'units': 2, 'power_draw_watts': 400, 'color': '#198754'},
            {'name': 'Server 2', 'start_unit': 33, 'units': 2, 'power_draw_watts': 400, 'color': '#198754'},
            {'name': 'UPS', 'start_unit': 1, 'units': 4, 'power_draw_watts': 200, 'color': '#ffc107'},
        ]
        for data in device_data:
            RackDevice.objects.get_or_create(
                rack=rack,
                start_unit=data['start_unit'],
                defaults=data
            )

        # Create subnets
        self.stdout.write("Creating IPAM subnets...")
        subnet_data = [
            {'name': 'Management VLAN', 'network': '10.0.1.0/24', 'vlan_id': 10, 'vlan_name': 'MGMT', 'gateway': '10.0.1.1'},
            {'name': 'Server VLAN', 'network': '10.0.10.0/24', 'vlan_id': 10, 'vlan_name': 'SERVERS', 'gateway': '10.0.10.1'},
            {'name': 'User VLAN', 'network': '10.0.100.0/24', 'vlan_id': 100, 'vlan_name': 'USERS', 'gateway': '10.0.100.1'},
        ]
        for data in subnet_data:
            subnet, _ = Subnet.objects.get_or_create(
                organization=org,
                network=data['network'],
                defaults=data
            )

            # Add some IP addresses
            if data['name'] == 'Server VLAN':
                ip_data = [
                    {'ip': '10.0.10.10', 'hostname': 'dc01', 'status': 'assigned'},
                    {'ip': '10.0.10.11', 'hostname': 'fs01', 'status': 'assigned'},
                    {'ip': '10.0.10.50', 'hostname': '', 'status': 'available'},
                    {'ip': '10.0.10.51', 'hostname': '', 'status': 'available'},
                ]
                for ip in ip_data:
                    IPAddress.objects.get_or_create(
                        subnet=subnet,
                        ip_address=ip['ip'],
                        defaults={
                            'hostname': ip['hostname'],
                            'status': ip['status'],
                        }
                    )

        self.stdout.write(self.style.SUCCESS('Sample data populated successfully!'))
        self.stdout.write(f"Organization: {org.name}")
        self.stdout.write(f"- {Tag.objects.filter(organization=org).count()} tags")
        self.stdout.write(f"- {Contact.objects.filter(organization=org).count()} contacts")
        self.stdout.write(f"- {Asset.objects.filter(organization=org).count()} assets")
        self.stdout.write(f"- {Password.objects.filter(organization=org).count()} passwords")
        self.stdout.write(f"- {Document.objects.filter(organization=org).count()} documents")
        self.stdout.write(f"- {WebsiteMonitor.objects.filter(organization=org).count()} website monitors")
        self.stdout.write(f"- {Expiration.objects.filter(organization=org).count()} expirations")
        self.stdout.write(f"- {Rack.objects.filter(organization=org).count()} racks")
        self.stdout.write(f"- {Subnet.objects.filter(organization=org).count()} subnets")

    def random_color(self):
        """Generate random hex color"""
        colors = ['#0d6efd', '#198754', '#ffc107', '#dc3545', '#0dcaf0', '#6f42c1']
        return random.choice(colors)
