"""
Seed demo data for testing
Creates: org, admin user, sample asset, doc, password, and integration connection
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django_otp.plugins.otp_totp.models import TOTPDevice
from core.models import Organization, Tag
from accounts.models import Membership, Role
from assets.models import Asset, Contact
from vault.models import Password
from docs.models import Document
from integrations.models import PSAConnection
import os


class Command(BaseCommand):
    help = 'Seed demo data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Seeding demo data...')

        # Create organization
        org, created = Organization.objects.get_or_create(
            slug='demo-org',
            defaults={
                'name': 'Demo Organization',
                'description': 'Demo organization for testing'
            }
        )
        self.stdout.write(f'Organization: {org.name} ({"created" if created else "exists"})')

        # Create admin user
        user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@example.com',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            user.set_password('admin')
            user.save()
            self.stdout.write(f'User: admin (created, password: admin)')
        else:
            self.stdout.write(f'User: admin (exists)')

        # Create membership
        membership, created = Membership.objects.get_or_create(
            user=user,
            organization=org,
            defaults={
                'role': Role.OWNER,
                'is_active': True,
            }
        )
        self.stdout.write(f'Membership: admin in {org.name} ({"created" if created else "exists"})')

        # Create tags
        tag1, _ = Tag.objects.get_or_create(
            organization=org,
            slug='production',
            defaults={'name': 'Production', 'color': '#dc3545'}
        )
        tag2, _ = Tag.objects.get_or_create(
            organization=org,
            slug='critical',
            defaults={'name': 'Critical', 'color': '#ffc107'}
        )

        # Create contact
        contact, _ = Contact.objects.get_or_create(
            organization=org,
            email='john.doe@example.com',
            defaults={
                'first_name': 'John',
                'last_name': 'Doe',
                'phone': '555-0100',
                'title': 'IT Manager',
            }
        )
        self.stdout.write(f'Contact: {contact.full_name}')

        # Create asset
        asset, created = Asset.objects.get_or_create(
            organization=org,
            name='Demo Server',
            defaults={
                'asset_type': 'server',
                'asset_tag': 'SRV-001',
                'serial_number': 'SN123456789',
                'manufacturer': 'Dell',
                'model': 'PowerEdge R740',
                'primary_contact': contact,
                'created_by': user,
                'custom_fields': {
                    'ip_address': '192.168.1.10',
                    'location': 'Data Center A',
                },
            }
        )
        if created:
            asset.tags.add(tag1, tag2)
        self.stdout.write(f'Asset: {asset.name} ({"created" if created else "exists"})')

        # Create document
        doc, created = Document.objects.get_or_create(
            organization=org,
            slug='demo-document',
            defaults={
                'title': 'Demo Document',
                'body': '''# Demo Documentation

This is a **demo document** with markdown formatting.

## Features
- Markdown support
- Version history
- Full-text search

## Code Example
```python
def hello_world():
    print("Hello, World!")
```

Connect this doc to assets via relationships!
''',
                'is_published': True,
                'created_by': user,
                'last_modified_by': user,
            }
        )
        if created:
            doc.tags.add(tag1)
        self.stdout.write(f'Document: {doc.title} ({"created" if created else "exists"})')

        # Create password
        password_obj, created = Password.objects.get_or_create(
            organization=org,
            title='Demo Server Root Password',
            defaults={
                'username': 'root',
                'url': 'ssh://192.168.1.10',
                'notes': 'Root access to demo server',
                'created_by': user,
                'last_modified_by': user,
            }
        )
        if created:
            password_obj.set_password('SuperSecretPassword123!')
            password_obj.save()
            password_obj.tags.add(tag2)
        self.stdout.write(f'Password: {password_obj.title} ({"created" if created else "exists"})')

        # Create dummy PSA connection (not functional, just for demo)
        connection, created = PSAConnection.objects.get_or_create(
            organization=org,
            name='Demo ConnectWise',
            defaults={
                'provider_type': 'connectwise_manage',
                'base_url': 'https://demo.connectwise.com',
                'sync_enabled': False,
                'is_active': False,
            }
        )
        if created:
            # Set dummy credentials (encrypted)
            connection.set_credentials({
                'company_id': 'demo',
                'public_key': 'demo_key',
                'private_key': 'demo_secret',
                'client_id': 'itdocs',
            })
            connection.save()
        self.stdout.write(f'PSA Connection: {connection.name} ({"created" if created else "exists"})')

        self.stdout.write(self.style.SUCCESS('\nDemo data seeded successfully!'))
        self.stdout.write('\nLogin credentials:')
        self.stdout.write('  Username: admin')
        self.stdout.write('  Password: admin')
        self.stdout.write('\nNote: 2FA is enforced. Set up TOTP on first login.')
