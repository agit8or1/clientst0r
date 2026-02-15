"""
Management command to seed demo data for a demo company.

Usage:
    python manage.py seed_demo_data

This creates:
- Demo organization
- Demo users (admin, editor, viewer)
- Sample assets (servers, workstations, network equipment)
- Sample documents
- Sample passwords
- Sample processes
- Sample diagrams
- Sample contacts
- Sample website monitors
- Sample tags
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.utils import timezone
from datetime import timedelta
import random

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed demo data for demo company'

    def __init__(self):
        super().__init__()
        self.demo_org = None
        self.demo_users = {}
        self.demo_tags = []
        self.demo_assets = []
        self.demo_documents = []
        self.demo_passwords = []

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting demo data seeding...'))

        # Import models here to avoid import errors
        from accounts.models import Organization, Membership, Role
        from assets.models import Asset, AssetType, Contact
        from docs.models import Document, Diagram
        from vault.models import Password, PasswordFolder
        from processes.models import Process, ProcessStage
        from core.models import Tag
        from monitoring.models import WebsiteMonitor

        # Step 1: Create or get demo organization
        self.stdout.write('Creating demo organization...')
        self.demo_org, created = Organization.objects.get_or_create(
            name='Acme Corporation',
            defaults={
                'description': 'Demo company for testing Client St0r features',
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created organization: {self.demo_org.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'! Organization already exists: {self.demo_org.name}'))

        # Step 2: Create demo users
        self.stdout.write('\nCreating demo users...')
        self._create_demo_users()

        # Step 3: Create tags
        self.stdout.write('\nCreating tags...')
        self._create_tags()

        # Step 4: Create asset types
        self.stdout.write('\nCreating asset types...')
        self._create_asset_types()

        # Step 5: Create assets
        self.stdout.write('\nCreating assets...')
        self._create_assets()

        # Step 6: Create documents
        self.stdout.write('\nCreating documents...')
        self._create_documents()

        # Step 7: Create password folders and passwords
        self.stdout.write('\nCreating password vault...')
        self._create_passwords()

        # Step 8: Create processes
        self.stdout.write('\nCreating processes...')
        self._create_processes()

        # Step 9: Create diagrams
        self.stdout.write('\nCreating diagrams...')
        self._create_diagrams()

        # Step 10: Create contacts
        self.stdout.write('\nCreating contacts...')
        self._create_contacts()

        # Step 11: Create website monitors
        self.stdout.write('\nCreating website monitors...')
        self._create_website_monitors()

        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('Demo data seeding completed!'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'\nOrganization: {self.demo_org.name}')
        self.stdout.write(f'Users created: {len(self.demo_users)}')
        self.stdout.write(f'Assets created: {len(self.demo_assets)}')
        self.stdout.write(f'Documents created: {len(self.demo_documents)}')
        self.stdout.write(f'Passwords created: {len(self.demo_passwords)}')
        self.stdout.write('\nDemo users:')
        for username, user in self.demo_users.items():
            self.stdout.write(f'  - {username} (password: demo123)')

    def _create_demo_users(self):
        """Create demo users with different roles"""
        from accounts.models import Membership, Role

        users_data = [
            {'username': 'demo.admin', 'email': 'admin@acme.demo', 'first_name': 'Admin', 'last_name': 'User', 'role': Role.ADMIN},
            {'username': 'demo.editor', 'email': 'editor@acme.demo', 'first_name': 'Editor', 'last_name': 'User', 'role': Role.EDITOR},
            {'username': 'demo.viewer', 'email': 'viewer@acme.demo', 'first_name': 'Viewer', 'last_name': 'User', 'role': Role.READONLY},
        ]

        for user_data in users_data:
            username = user_data['username']
            role = user_data['role']

            # Create or get user
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': user_data['email'],
                    'first_name': user_data['first_name'],
                    'last_name': user_data['last_name'],
                    'is_staff': False,
                }
            )

            if created:
                user.set_password('demo123')
                user.save()
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created user: {username}'))
            else:
                self.stdout.write(self.style.WARNING(f'  ! User already exists: {username}'))

            self.demo_users[username] = user

            # Create membership
            membership, created = Membership.objects.get_or_create(
                user=user,
                organization=self.demo_org,
                defaults={'role': role}
            )

    def _create_tags(self):
        """Create sample tags"""
        from core.models import Tag

        tags_data = [
            'Production', 'Development', 'Staging', 'Critical', 'Monitoring',
            'Network', 'Security', 'Backup', 'Database', 'Web Server',
            'Email', 'VPN', 'Firewall', 'Cloud', 'On-Premise'
        ]

        for tag_name in tags_data:
            tag, created = Tag.objects.get_or_create(
                name=tag_name,
                organization=self.demo_org,
                defaults={'slug': slugify(tag_name)}
            )
            if created:
                self.stdout.write(f'  ✓ Created tag: {tag_name}')
            self.demo_tags.append(tag)

    def _create_asset_types(self):
        """Asset types are predefined in the Asset model"""
        pass

    def _create_assets(self):
        """Create sample assets"""
        from assets.models import Asset

        assets_data = [
            # Servers
            {
                'name': 'prod-web-01',
                'asset_type': 'server',
                'manufacturer': 'Dell',
                'model': 'PowerEdge R740',
                'serial_number': 'SRV-WEB-001',
                'hostname': 'prod-web-01.acme.demo',
                'ip_address': '10.0.1.10',
                'custom_fields': {
                    'location': 'Datacenter Rack A1',
                    'status': 'active',
                    'description': 'Production web server',
                },
                'notes': 'Primary production web server',
                'tags': ['Production', 'Web Server', 'Critical'],
            },
            {
                'name': 'prod-db-01',
                'asset_type': 'server',
                'manufacturer': 'Dell',
                'model': 'PowerEdge R740xd',
                'serial_number': 'SRV-DB-001',
                'hostname': 'prod-db-01.acme.demo',
                'ip_address': '10.0.1.20',
                'custom_fields': {
                    'location': 'Datacenter Rack A2',
                    'status': 'active',
                    'description': 'Production database server',
                },
                'notes': 'PostgreSQL production database',
                'tags': ['Production', 'Database', 'Critical'],
            },
            {
                'name': 'prod-app-01',
                'asset_type': 'server',
                'manufacturer': 'HPE',
                'model': 'ProLiant DL380 Gen10',
                'serial_number': 'SRV-APP-001',
                'hostname': 'prod-app-01.acme.demo',
                'ip_address': '10.0.1.30',
                'custom_fields': {
                    'location': 'Datacenter Rack A3',
                    'status': 'active',
                    'description': 'Production application server',
                },
                'notes': 'Main application server',
                'tags': ['Production', 'Critical'],
            },
            {
                'name': 'dev-web-01',
                'asset_type': 'server',
                'manufacturer': 'Dell',
                'model': 'PowerEdge R640',
                'serial_number': 'SRV-WEB-DEV-001',
                'hostname': 'dev-web-01.acme.demo',
                'ip_address': '10.0.2.10',
                'custom_fields': {
                    'location': 'Datacenter Rack B1',
                    'status': 'active',
                    'description': 'Development web server',
                },
                'notes': 'Development environment',
                'tags': ['Development', 'Web Server'],
            },
            {
                'name': 'backup-srv-01',
                'asset_type': 'server',
                'manufacturer': 'Synology',
                'model': 'RS3621xs+',
                'serial_number': 'BCK-001',
                'hostname': 'backup-01.acme.demo',
                'ip_address': '10.0.1.100',
                'custom_fields': {
                    'location': 'Datacenter Rack C1',
                    'status': 'active',
                    'description': 'Backup server',
                },
                'notes': 'Centralized backup system',
                'tags': ['Backup', 'Critical'],
            },
            # Network Devices
            {
                'name': 'core-switch-01',
                'asset_type': 'network',
                'manufacturer': 'Cisco',
                'model': 'Catalyst 9300',
                'serial_number': 'NET-SW-001',
                'hostname': 'switch-core-01',
                'ip_address': '10.0.0.1',
                'custom_fields': {
                    'location': 'Datacenter Rack D1',
                    'status': 'active',
                    'description': 'Core network switch',
                },
                'notes': '48-port gigabit switch',
                'tags': ['Network', 'Critical'],
            },
            {
                'name': 'edge-firewall-01',
                'asset_type': 'network',
                'manufacturer': 'Fortinet',
                'model': 'FortiGate 600E',
                'serial_number': 'FW-001',
                'hostname': 'firewall-edge-01',
                'ip_address': '10.0.0.254',
                'custom_fields': {
                    'location': 'Datacenter Rack D1',
                    'status': 'active',
                    'description': 'Edge firewall',
                },
                'notes': 'Primary security appliance',
                'tags': ['Network', 'Security', 'Critical', 'Firewall'],
            },
            # Workstations
            {
                'name': 'ws-admin-01',
                'asset_type': 'workstation',
                'manufacturer': 'Dell',
                'model': 'OptiPlex 7090',
                'serial_number': 'WS-ADM-001',
                'hostname': 'ws-admin-01',
                'ip_address': '10.0.10.50',
                'custom_fields': {
                    'location': 'Office - IT Room',
                    'status': 'active',
                    'description': 'Admin workstation',
                },
                'notes': 'IT administrator workstation',
                'tags': ['On-Premise'],
            },
        ]

        admin_user = self.demo_users.get('demo.admin')

        for asset_data in assets_data:
            tags = asset_data.pop('tags', [])
            asset, created = Asset.objects.get_or_create(
                name=asset_data['name'],
                organization=self.demo_org,
                defaults={
                    **asset_data,
                    'created_by': admin_user,
                }
            )

            if created:
                # Add tags
                for tag_name in tags:
                    tag = next((t for t in self.demo_tags if t.name == tag_name), None)
                    if tag:
                        asset.tags.add(tag)

                self.stdout.write(f'  ✓ Created asset: {asset.name}')
                self.demo_assets.append(asset)

    def _create_documents(self):
        """Create sample documents"""
        from docs.models import Document

        admin_user = self.demo_users.get('demo.admin')

        documents_data = [
            {
                'title': 'Network Architecture Overview',
                'body': '''# Network Architecture Overview

## Network Topology

Our network is divided into multiple VLANs for security and performance:

- **VLAN 10 (10.0.1.0/24)** - Production Servers
- **VLAN 20 (10.0.2.0/24)** - Development Servers
- **VLAN 50 (10.0.10.0/24)** - Workstations
- **VLAN 100 (10.0.100.0/24)** - Guest Network

## Core Infrastructure

### Firewall Rules
- Production servers only accessible from management VLAN
- All external traffic filtered through edge firewall
- VPN required for remote access

### Monitoring
All critical infrastructure monitored 24/7 via monitoring system.
''',
                'content_type': 'markdown',
                'tags': ['Network', 'Production'],
            },
            {
                'title': 'Backup Procedures',
                'body': '''# Backup Procedures

## Daily Backups

All production servers backed up daily at 2:00 AM EST.

### Backup Schedule

| System | Frequency | Retention | Location |
|--------|-----------|-----------|----------|
| Production DB | Daily | 30 days | backup-srv-01 |
| Web Servers | Daily | 14 days | backup-srv-01 |
| Config Files | Daily | 90 days | backup-srv-01 |

## Recovery Testing

Backup recovery tested monthly on the first Sunday.

## Contact

Contact IT Admin for backup restoration requests.
''',
                'content_type': 'markdown',
                'tags': ['Backup', 'Critical'],
            },
            {
                'title': 'Server Access Policy',
                'body': '''# Server Access Policy

## Access Requirements

All server access must be:
1. Approved by IT Admin
2. Logged in audit system
3. Use SSH keys (no password auth)
4. Via VPN only

## SSH Keys

SSH keys managed centrally. Request access via IT support portal.

## Audit

All access logged and reviewed weekly.
''',
                'content_type': 'markdown',
                'tags': ['Security', 'Production'],
            },
            {
                'title': 'Development Environment Setup',
                'body': '''# Development Environment Setup

## Requirements

- Git
- Docker
- Node.js 18+
- Python 3.12+

## Getting Started

1. Clone repository
2. Copy `.env.example` to `.env`
3. Run `docker-compose up`
4. Access at http://localhost:8000

## Database

Development uses PostgreSQL in Docker container.

**Connection String:** `postgresql://dev:devpass@localhost:5432/acme_dev`
''',
                'content_type': 'markdown',
                'tags': ['Development'],
            },
            {
                'title': 'Incident Response Plan',
                'body': '''# Incident Response Plan

## Severity Levels

- **P1 (Critical)** - System down, data loss
- **P2 (High)** - Major functionality impaired
- **P3 (Medium)** - Minor functionality impaired
- **P4 (Low)** - Cosmetic issues

## Response Times

| Priority | Response Time | Resolution Target |
|----------|---------------|-------------------|
| P1 | 15 minutes | 4 hours |
| P2 | 1 hour | 24 hours |
| P3 | 4 hours | 1 week |
| P4 | 1 week | As scheduled |

## Contact Chain

1. On-call engineer (via PagerDuty)
2. IT Manager
3. CTO

## Post-Incident

Post-mortem required for all P1 and P2 incidents within 48 hours.
''',
                'content_type': 'markdown',
                'tags': ['Critical', 'Security'],
            },
        ]

        for doc_data in documents_data:
            tags = doc_data.pop('tags', [])
            doc, created = Document.objects.get_or_create(
                title=doc_data['title'],
                organization=self.demo_org,
                defaults={
                    **doc_data,
                    'created_by': admin_user,
                    'slug': slugify(doc_data['title']),
                    'is_published': True,
                }
            )

            if created:
                # Add tags
                for tag_name in tags:
                    tag = next((t for t in self.demo_tags if t.name == tag_name), None)
                    if tag:
                        doc.tags.add(tag)

                self.stdout.write(f'  ✓ Created document: {doc.title}')
                self.demo_documents.append(doc)

    def _create_passwords(self):
        """Create sample password vault items"""
        from vault.models import Password, PasswordFolder
        from cryptography.fernet import Fernet
        from django.conf import settings
        import base64

        admin_user = self.demo_users.get('demo.admin')

        # Create folders
        folders_data = [
            {'name': 'Production Servers', 'description': 'Production server credentials'},
            {'name': 'Network Devices', 'description': 'Network equipment passwords'},
            {'name': 'Cloud Services', 'description': 'Cloud platform credentials'},
        ]

        folders = {}
        for folder_data in folders_data:
            folder, created = PasswordFolder.objects.get_or_create(
                name=folder_data['name'],
                organization=self.demo_org,
                defaults={
                    'description': folder_data['description'],
                }
            )
            folders[folder_data['name']] = folder
            if created:
                self.stdout.write(f'  ✓ Created folder: {folder.name}')

        # Create passwords
        passwords_data = [
            {
                'title': 'prod-web-01 Root',
                'username': 'root',
                'password': 'DemoPassword123!',
                'url': 'ssh://10.0.1.10',
                'folder': 'Production Servers',
                'notes': 'Root access to production web server',
            },
            {
                'title': 'prod-db-01 Database',
                'username': 'dbadmin',
                'password': 'DbSecure456!',
                'url': 'postgresql://10.0.1.20:5432',
                'folder': 'Production Servers',
                'notes': 'PostgreSQL admin credentials',
            },
            {
                'title': 'Edge Firewall Admin',
                'username': 'admin',
                'password': 'FirewallPass789!',
                'url': 'https://10.0.0.254',
                'folder': 'Network Devices',
                'notes': 'Fortinet firewall admin access',
            },
            {
                'title': 'Core Switch Management',
                'username': 'netadmin',
                'password': 'SwitchSecure321!',
                'url': 'https://10.0.0.1',
                'folder': 'Network Devices',
                'notes': 'Cisco switch management',
            },
            {
                'title': 'AWS Console',
                'username': 'admin@acme.demo',
                'password': 'AwsDemo999!',
                'url': 'https://console.aws.amazon.com',
                'folder': 'Cloud Services',
                'notes': 'AWS root account (demo purposes only)',
            },
        ]

        # Encrypt passwords
        cipher = Fernet(settings.APP_MASTER_KEY.encode() if isinstance(settings.APP_MASTER_KEY, str) else settings.APP_MASTER_KEY)

        for pwd_data in passwords_data:
            folder_name = pwd_data.pop('folder')
            folder = folders.get(folder_name)
            password_text = pwd_data.pop('password')

            # Encrypt password
            encrypted_password = cipher.encrypt(password_text.encode()).decode()

            pwd, created = Password.objects.get_or_create(
                title=pwd_data['title'],
                organization=self.demo_org,
                defaults={
                    **pwd_data,
                    'encrypted_password': encrypted_password,
                    'folder': folder,
                    'created_by': admin_user,
                }
            )

            if created:
                self.stdout.write(f'  ✓ Created password: {pwd.title}')
                self.demo_passwords.append(pwd)

    def _create_processes(self):
        """Create sample processes"""
        from processes.models import Process, ProcessStage
        from docs.models import Document
        from assets.models import Asset

        admin_user = self.demo_users.get('demo.admin')

        # Get some existing documents and assets for linking
        backup_doc = Document.objects.filter(
            organization=self.demo_org,
            title__icontains='Backup'
        ).first()

        web_server = Asset.objects.filter(
            organization=self.demo_org,
            name='prod-web-01'
        ).first()

        processes_data = [
            {
                'title': 'New Server Deployment',
                'description': 'Standard process for deploying new servers',
                'stages': [
                    {
                        'title': 'Review server documentation',
                        'description': 'Review architecture and requirements',
                        'order': 1,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Provision hardware',
                        'description': 'Order or allocate hardware resources',
                        'order': 2,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Install operating system',
                        'description': 'Install and configure base OS',
                        'order': 3,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Configure networking',
                        'description': 'Set up network configuration and firewall rules',
                        'order': 4,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Install monitoring agents',
                        'description': 'Deploy monitoring and alerting',
                        'order': 5,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Configure backups',
                        'description': 'Set up backup schedule and test restore',
                        'order': 6,
                        'requires_confirmation': True,
                    },
                ],
            },
            {
                'title': 'Monthly Security Patching',
                'description': 'Monthly security update process',
                'stages': [
                    {
                        'title': 'Review available patches',
                        'description': 'Check for security updates',
                        'order': 1,
                        'requires_confirmation': False,
                    },
                    {
                        'title': 'Test in development',
                        'description': 'Apply patches to dev environment',
                        'order': 2,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Schedule maintenance window',
                        'description': 'Coordinate with stakeholders',
                        'order': 3,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Create backup',
                        'description': 'Backup all systems before patching',
                        'order': 4,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Apply patches',
                        'description': 'Deploy security updates',
                        'order': 5,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Verify systems',
                        'description': 'Test all critical functionality',
                        'order': 6,
                        'requires_confirmation': True,
                    },
                ],
            },
            {
                'title': 'Offboard Employee',
                'description': 'Employee offboarding checklist',
                'stages': [
                    {
                        'title': 'Disable AD account',
                        'description': 'Disable Active Directory user account',
                        'order': 1,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Revoke VPN access',
                        'description': 'Remove VPN certificates and access',
                        'order': 2,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Remove from email groups',
                        'description': 'Remove from all distribution lists',
                        'order': 3,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Collect equipment',
                        'description': 'Retrieve laptop, phone, badge, keys',
                        'order': 4,
                        'requires_confirmation': True,
                    },
                    {
                        'title': 'Archive email',
                        'description': 'Export and archive email mailbox',
                        'order': 5,
                        'requires_confirmation': True,
                    },
                ],
            },
        ]

        for proc_data in processes_data:
            stages_data = proc_data.pop('stages', [])

            process, created = Process.objects.get_or_create(
                title=proc_data['title'],
                organization=self.demo_org,
                defaults={
                    **proc_data,
                    'slug': slugify(proc_data['title']),
                    'created_by': admin_user,
                    'is_published': True,
                }
            )

            if created:
                # Create stages
                for stage_data in stages_data:
                    ProcessStage.objects.create(
                        process=process,
                        **stage_data
                    )

                self.stdout.write(f'  ✓ Created process: {process.title} ({len(stages_data)} stages)')

    def _create_diagrams(self):
        """Create sample diagrams"""
        from docs.models import Diagram

        admin_user = self.demo_users.get('demo.admin')

        # Simple network diagram XML
        network_diagram_xml = '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="internet" value="Internet" style="ellipse;shape=cloud;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="340" y="40" width="140" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="firewall" value="Edge Firewall&#xa;10.0.0.254" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="350" y="160" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="switch" value="Core Switch&#xa;10.0.0.1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="350" y="260" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="web" value="prod-web-01&#xa;10.0.1.10" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="200" y="380" width="100" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="app" value="prod-app-01&#xa;10.0.1.30" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="360" y="380" width="100" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="db" value="prod-db-01&#xa;10.0.1.20" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="520" y="380" width="100" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="internet" target="firewall">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="firewall" target="switch">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge3" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="switch" target="web">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge4" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="switch" target="app">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge5" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="switch" target="db">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>'''

        diagrams_data = [
            {
                'title': 'Acme Corporation Network',
                'description': 'Main network topology diagram',
                'diagram_type': 'network',
                'diagram_xml': network_diagram_xml,
                'tags': ['Network', 'Production'],
            },
        ]

        for diag_data in diagrams_data:
            tags = diag_data.pop('tags', [])

            diagram, created = Diagram.objects.get_or_create(
                title=diag_data['title'],
                organization=self.demo_org,
                defaults={
                    **diag_data,
                    'slug': slugify(diag_data['title']),
                    'created_by': admin_user,
                    'is_published': True,
                }
            )

            if created:
                # Add tags
                for tag_name in tags:
                    tag = next((t for t in self.demo_tags if t.name == tag_name), None)
                    if tag:
                        diagram.tags.add(tag)

                self.stdout.write(f'  ✓ Created diagram: {diagram.title}')

    def _create_contacts(self):
        """Create sample contacts"""
        from assets.models import Contact

        admin_user = self.demo_users.get('demo.admin')

        contacts_data = [
            {
                'first_name': 'John',
                'last_name': 'Smith',
                'email': 'john.smith@acme.demo',
                'phone': '+1-555-0101',
                'title': 'IT Director',
                'notes': 'Primary IT contact - Information Technology department',
            },
            {
                'first_name': 'Sarah',
                'last_name': 'Johnson',
                'email': 'sarah.johnson@acme.demo',
                'phone': '+1-555-0102',
                'title': 'Network Administrator',
                'notes': 'Handles network infrastructure - Information Technology department',
            },
            {
                'first_name': 'Mike',
                'last_name': 'Williams',
                'email': 'mike.williams@acme.demo',
                'phone': '+1-555-0103',
                'title': 'Security Analyst',
                'notes': 'Security and compliance - Information Security department',
            },
        ]

        for contact_data in contacts_data:
            contact, created = Contact.objects.get_or_create(
                email=contact_data['email'],
                organization=self.demo_org,
                defaults={
                    **contact_data,
                }
            )

            if created:
                self.stdout.write(f'  ✓ Created contact: {contact.first_name} {contact.last_name}')

    def _create_website_monitors(self):
        """Create sample website monitors"""
        from monitoring.models import WebsiteMonitor

        admin_user = self.demo_users.get('demo.admin')

        monitors_data = [
            {
                'name': 'Production Website',
                'url': 'https://www.acme.demo',
                'check_interval_minutes': 5,
                'is_enabled': True,
            },
            {
                'name': 'API Endpoint',
                'url': 'https://api.acme.demo/health',
                'check_interval_minutes': 5,
                'is_enabled': True,
            },
            {
                'name': 'Admin Portal',
                'url': 'https://admin.acme.demo',
                'check_interval_minutes': 10,
                'is_enabled': True,
            },
        ]

        for monitor_data in monitors_data:
            monitor, created = WebsiteMonitor.objects.get_or_create(
                name=monitor_data['name'],
                organization=self.demo_org,
                defaults={
                    **monitor_data,
                }
            )

            if created:
                self.stdout.write(f'  ✓ Created monitor: {monitor.name}')
