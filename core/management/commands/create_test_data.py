"""
Management command to create comprehensive test data for screenshots
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from core.models import Organization
from accounts.models import Membership
from assets.models import Asset, Contact
from vault.models import Password, PasswordFolder
from docs.models import Document, DocumentTemplate
from monitoring.models import WebsiteMonitor, Rack, RackDevice
from integrations.models import Integration

User = get_user_model()


class Command(BaseCommand):
    help = 'Create comprehensive test data for screenshot generation'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('\n📸 Creating test data for screenshots...\n'))

        # Create organization
        org, _ = Organization.objects.get_or_create(
            slug='demo',
            defaults={'name': 'Demo Company'}
        )
        self.stdout.write(f'  ✓ Organization: {org.name}')

        # Create users
        user, created = User.objects.get_or_create(
            username='screenshot_user',
            defaults={
                'email': 'screenshots@demo.com',
                'first_name': 'Demo',
                'last_name': 'User',
                'is_active': True,
            }
        )

        if created:
            user.set_password('Screenshot123!')
            user.save()

        # Add to organization
        Membership.objects.get_or_create(
            user=user,
            organization=org,
            defaults={'role': 'owner'}
        )
        self.stdout.write(f'  ✓ User: {user.username}')

        # Create contacts
        contacts = []
        for i in range(5):
            contact, _ = Contact.objects.get_or_create(
                organization=org,
                email=f'contact{i+1}@demo.com',
                defaults={
                    'name': f'Contact {i+1}',
                    'phone': f'555-010{i}',
                    'title': ['CTO', 'IT Manager', 'System Admin', 'DevOps Lead', 'Security Officer'][i],
                    'notes': f'Test contact {i+1} for screenshots'
                }
            )
            contacts.append(contact)
        self.stdout.write(f'  ✓ Contacts: {len(contacts)}')

        # Create assets
        assets = []
        asset_types = [
            ('server', 'Production Web Server', 'Ubuntu 24.04 LTS'),
            ('server', 'Database Server', 'PostgreSQL 15'),
            ('workstation', 'Admin Workstation', 'Windows 11 Pro'),
            ('network', 'Core Switch', 'Cisco Catalyst 9300'),
            ('laptop', 'Executive Laptop', 'MacBook Pro M3'),
        ]

        for asset_type, name, notes in asset_types:
            asset, _ = Asset.objects.get_or_create(
                organization=org,
                name=name,
                defaults={
                    'asset_type': asset_type,
                    'status': 'active',
                    'serial_number': f'SN{hash(name) % 10000:04d}',
                    'location': 'Data Center A',
                    'notes': notes,
                    'json_fields': {
                        'ip_address': f'10.0.1.{len(assets)+1}',
                        'warranty_expires': '2027-12-31'
                    }
                }
            )
            assets.append(asset)
        self.stdout.write(f'  ✓ Assets: {len(assets)}')

        # Create password folders
        folders = []
        for folder_name in ['Servers', 'Network Equipment', 'Cloud Services']:
            folder, _ = PasswordFolder.objects.get_or_create(
                organization=org,
                name=folder_name,
                defaults={'description': f'Credentials for {folder_name.lower()}'}
            )
            folders.append(folder)
        self.stdout.write(f'  ✓ Password Folders: {len(folders)}')

        # Create passwords
        passwords = []
        password_data = [
            ('website', 'AWS Console', 'admin@demo.com', folders[2]),
            ('database', 'Production Database', 'postgres', folders[0]),
            ('ssh', 'Web Server SSH', 'root', folders[0]),
            ('network', 'Core Switch Admin', 'admin', folders[1]),
            ('email', 'Company Email', 'admin@demo.com', folders[2]),
        ]

        for pwd_type, title, username, folder in password_data:
            password, _ = Password.objects.get_or_create(
                organization=org,
                title=title,
                defaults={
                    'password_type': pwd_type,
                    'username': username,
                    'url': f'https://{title.lower().replace(" ", "-")}.demo.com',
                    'folder': folder,
                    'notes': f'Test {pwd_type} credential',
                    'expires_at': timezone.now() + timedelta(days=90)
                }
            )
            passwords.append(password)
        self.stdout.write(f'  ✓ Passwords: {len(passwords)}')

        # Create document templates
        templates = []
        template_data = [
            ('Server Documentation', 'IT Procedures', 'markdown', '# Server: {{server_name}}\n\n## Overview\n\n## Configuration\n\n## Maintenance'),
            ('Incident Report', 'IT Procedures', 'markdown', '# Incident Report\n\n**Date:** {{date}}\n\n## Description\n\n## Impact\n\n## Resolution'),
        ]

        for name, category, content_type, content in template_data:
            template, _ = DocumentTemplate.objects.get_or_create(
                name=name,
                defaults={
                    'category': category,
                    'content_type': content_type,
                    'content': content,
                    'is_active': True
                }
            )
            templates.append(template)
        self.stdout.write(f'  ✓ Document Templates: {len(templates)}')

        # Create documents
        documents = []
        document_data = [
            ('Network Documentation', 'Network Documentation', '# Network Infrastructure\n\n## Overview\n\nOur network consists of...'),
            ('Backup Procedures', 'IT Procedures', '# Backup Procedures\n\n## Daily Backups\n\n## Weekly Backups'),
            ('Security Policy', 'Company Policies', '# Information Security Policy\n\n## Purpose\n\n## Scope'),
        ]

        for title, category, content in document_data:
            doc, _ = Document.objects.get_or_create(
                organization=org,
                title=title,
                defaults={
                    'category': category,
                    'content_type': 'markdown',
                    'content': content,
                    'is_published': True,
                    'author': user
                }
            )
            documents.append(doc)
        self.stdout.write(f'  ✓ Documents: {len(documents)}')

        # Create website monitors
        monitors = []
        monitor_data = [
            ('Company Website', 'https://www.demo.com', 300, 'up'),
            ('Customer Portal', 'https://portal.demo.com', 300, 'up'),
            ('API Endpoint', 'https://api.demo.com', 180, 'up'),
        ]

        for name, url, interval, status in monitor_data:
            monitor, _ = WebsiteMonitor.objects.get_or_create(
                organization=org,
                name=name,
                defaults={
                    'url': url,
                    'check_interval': interval,
                    'status': status,
                    'is_active': True,
                    'last_checked_at': timezone.now(),
                    'response_time': 150
                }
            )
            monitors.append(monitor)
        self.stdout.write(f'  ✓ Website Monitors: {len(monitors)}')

        # Create racks
        racks = []
        rack, _ = Rack.objects.get_or_create(
            organization=org,
            name='Rack A1',
            defaults={
                'location': 'Data Center A',
                'units': 42,
                'power_capacity_watts': 5000
            }
        )
        racks.append(rack)

        # Add devices to rack
        devices = []
        device_data = [
            ('Web Server 1', 1, 2, 300, '#4CAF50'),
            ('Database Server', 3, 4, 500, '#2196F3'),
            ('Firewall', 5, 6, 200, '#F44336'),
        ]

        for name, start_u, end_u, power, color in device_data:
            device, _ = RackDevice.objects.get_or_create(
                rack=rack,
                name=name,
                defaults={
                    'start_unit': start_u,
                    'end_unit': end_u,
                    'power_draw_watts': power,
                    'color': color
                }
            )
            devices.append(device)
        self.stdout.write(f'  ✓ Rack Devices: {len(devices)}')

        # Create integrations (examples)
        integrations = []
        integration_data = [
            ('ConnectWise Manage', 'connectwise', 'https://connectwise.demo.com', 'inactive'),
            ('Autotask PSA', 'autotask', 'https://autotask.aem.autotask.net', 'inactive'),
        ]

        for name, provider_type, base_url, status in integration_data:
            integration, _ = Integration.objects.get_or_create(
                organization=org,
                name=name,
                defaults={
                    'provider_type': provider_type,
                    'base_url': base_url,
                    'status': status,
                    'is_active': False
                }
            )
            integrations.append(integration)
        self.stdout.write(f'  ✓ Integrations: {len(integrations)}')

        self.stdout.write(self.style.SUCCESS('\n✅ Test data created successfully!\n'))
        self.stdout.write(self.style.SUCCESS(f'Login credentials:'))
        self.stdout.write(f'  Username: screenshot_user')
        self.stdout.write(f'  Password: Screenshot123!')
        self.stdout.write('')
