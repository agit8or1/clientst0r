"""
Management command to import Acme Corporation demo data.

This command imports a complete demo company with:
- Documents (procedures, policies, runbooks)
- Diagrams (network, rack, process flowcharts)
- Assets (workstations, servers, network equipment)
- Passwords (various types and categories)
- Global KB articles
- Processes with execution history
"""
import json
import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.db import transaction

from core.models import Organization
from docs.models import Document, DocumentCategory, Diagram
from assets.models import Asset
from vault.models import Password
from processes.models import Process, ProcessExecution


class Command(BaseCommand):
    help = 'Import Acme Corporation demo data with complete organizational setup'

    def add_arguments(self, parser):
        parser.add_argument(
            '--organization',
            type=str,
            required=True,
            help='Organization name or ID to import data into'
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Username to assign as creator (defaults to first superuser)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete existing demo data before importing (WARNING: Destructive!)'
        )

    def handle(self, *args, **options):
        org_identifier = options['organization']
        username = options.get('user')

        self.stdout.write(
            self.style.WARNING(
                'Importing Acme Corporation demo data...'
            )
        )

        # Get organization
        try:
            if org_identifier.isdigit():
                organization = Organization.objects.get(id=int(org_identifier))
            else:
                organization = Organization.objects.get(name__iexact=org_identifier)
        except Organization.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f'Organization "{org_identifier}" not found. '
                    f'Please create it first or use an existing organization.'
                )
            )
            return

        # Get user
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
                return
        else:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                self.stdout.write(self.style.ERROR('No superuser found'))
                return

        self.stdout.write(f'Importing into organization: {organization.name}')
        self.stdout.write(f'Created by user: {user.username}')

        # Validate APP_MASTER_KEY is configured for password encryption
        from django.conf import settings
        master_key = os.getenv('APP_MASTER_KEY', '')
        if not master_key or len(master_key) < 40:
            self.stdout.write(
                self.style.ERROR(
                    '\n✗ ERROR: APP_MASTER_KEY is not configured or invalid!\n'
                    '\n'
                    'Demo data import requires a valid APP_MASTER_KEY for encrypting passwords.\n'
                    '\n'
                    'To fix this:\n'
                    '1. Generate a secure key:\n'
                    '   python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"\n'
                    '\n'
                    '2. Add to your .env file:\n'
                    '   APP_MASTER_KEY=<generated-key-here>\n'
                    '\n'
                    '3. Restart your application\n'
                    '\n'
                    '4. Re-run this import\n'
                )
            )
            return

        # Check if data already exists
        existing_docs = organization.documents.filter(
            title__in=['Network Infrastructure Overview', 'Backup and Recovery Procedures', 'Security Policy', 'Server Maintenance Runbook', 'New Employee Onboarding']
        ).count()

        if existing_docs > 0:
            if options.get('force'):
                self.stdout.write(self.style.WARNING(
                    f'Found {existing_docs} existing demo documents. Deleting all demo data due to --force flag...'
                ))
                # Delete existing demo data
                organization.documents.all().delete()
                organization.assets.all().delete()
                organization.passwords.all().delete()
                Diagram.objects.filter(organization=organization).all().delete()
                organization.processes.all().delete()
                self.stdout.write(self.style.SUCCESS('✓ Existing data deleted'))
            else:
                self.stdout.write(self.style.WARNING(
                    f'⚠️  Demo data already exists in {organization.name} ({existing_docs} demo documents found).'
                ))
                self.stdout.write(
                    'Run with --force to delete existing data and re-import, or import into a different organization.'
                )
                return

        try:
            with transaction.atomic():
                stats = {
                    'documents': 0,
                    'diagrams': 0,
                    'assets': 0,
                    'passwords': 0,
                    'kb_articles': 0,
                    'processes': 0,
                    'vendors': 0,
                    'equipment_models': 0,
                }

                # Import equipment catalog first (global, not org-specific)
                self.stdout.write('Importing equipment catalog...')
                equipment_stats = self._import_equipment_catalog()
                stats['vendors'] = equipment_stats['vendors']
                stats['equipment_models'] = equipment_stats['equipment_models']

                # Import categories first
                self.stdout.write('Creating document categories...')
                categories = self._create_categories(organization)

                # Import documents
                self.stdout.write('Importing documents...')
                documents = self._create_documents(organization, user, categories)
                stats['documents'] = len(documents)

                # Import diagrams
                self.stdout.write('Importing diagrams...')
                diagrams = self._create_diagrams(organization, user)
                stats['diagrams'] = len(diagrams)

                # Import assets
                self.stdout.write('Importing assets...')
                assets = self._create_assets(organization, user)
                stats['assets'] = len(assets)

                # Import passwords
                self.stdout.write('Importing passwords...')
                passwords = self._create_passwords(organization, user)
                stats['passwords'] = len(passwords)

                # Import processes/workflows
                self.stdout.write('Importing workflows...')
                processes = self._create_processes(organization, user, documents, passwords)
                stats['processes'] = len(processes)

                # Skip KB articles - no KB model exists yet
                stats['kb_articles'] = 0

                self.stdout.write(
                    self.style.SUCCESS(
                        '\n✓ Successfully imported Acme Corporation demo data:'
                    )
                )
                self.stdout.write(f'  • Vendors: {stats["vendors"]}')
                self.stdout.write(f'  • Equipment Models: {stats["equipment_models"]}')
                self.stdout.write(f'  • Documents: {stats["documents"]}')
                self.stdout.write(f'  • Diagrams: {stats["diagrams"]}')
                self.stdout.write(f'  • Assets: {stats["assets"]}')
                self.stdout.write(f'  • Passwords: {stats["passwords"]}')
                self.stdout.write(f'  • KB Articles: {stats["kb_articles"]}')
                self.stdout.write(f'  • Processes: {stats["processes"]}')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Import failed: {e}')
            )
            import traceback
            traceback.print_exc()
            raise

    def _import_equipment_catalog(self):
        """Import equipment catalog from JSON file."""
        from assets.models import Vendor, EquipmentModel
        from django.conf import settings
        from pathlib import Path
        import json

        stats = {'vendors': 0, 'equipment_models': 0}

        # Check if catalog already has data
        vendor_count = Vendor.objects.filter(is_active=True).count()
        if vendor_count > 0:
            self.stdout.write(f'  ✓ Equipment catalog already populated ({vendor_count} vendors)')
            stats['vendors'] = vendor_count
            stats['equipment_models'] = EquipmentModel.objects.filter(is_active=True).count()
            return stats

        # Load equipment catalog JSON
        catalog_path = Path(settings.BASE_DIR) / 'data' / 'equipment_updates.json'
        if not catalog_path.exists():
            self.stdout.write(
                self.style.WARNING(f'  ⚠ Equipment catalog file not found: {catalog_path}')
            )
            return stats

        try:
            with open(catalog_path, 'r') as f:
                data = json.load(f)

            vendors_data = data.get('vendors', [])
            for vendor_data in vendors_data:
                vendor, created = Vendor.objects.get_or_create(
                    name=vendor_data['name'],
                    defaults={
                        'slug': slugify(vendor_data['name']),
                        'website': vendor_data.get('website', ''),
                        'support_url': vendor_data.get('support_url', ''),
                        'support_phone': vendor_data.get('support_phone', ''),
                        'description': vendor_data.get('description', ''),
                        'is_active': True,
                    }
                )
                if created:
                    stats['vendors'] += 1

                # Create equipment models for this vendor
                for equip_data in vendor_data.get('equipment', []):
                    equipment, created = EquipmentModel.objects.get_or_create(
                        vendor=vendor,
                        model_name=equip_data['model_name'],
                        defaults={
                            'slug': slugify(f"{vendor.name}-{equip_data['model_name']}"),
                            'model_number': equip_data.get('model_number', ''),
                            'equipment_type': equip_data.get('equipment_type', 'other'),
                            'description': equip_data.get('description', ''),
                            'is_rackmount': equip_data.get('is_rackmount', False),
                            'rack_units': equip_data.get('rack_units'),
                            'specifications': equip_data.get('specifications', {}),
                            'datasheet_url': equip_data.get('datasheet_url', ''),
                            'is_active': True,
                        }
                    )
                    if created:
                        stats['equipment_models'] += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Imported {stats["vendors"]} vendors and {stats["equipment_models"]} equipment models'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'  ⚠ Failed to import equipment catalog: {e}')
            )

        return stats

    def _create_categories(self, organization):
        """Create document categories."""
        categories = {}
        category_names = [
            'IT Procedures',
            'Security Policies',
            'Network Documentation',
            'Server Documentation',
            'User Guides',
            'Runbooks',
            'Disaster Recovery',
        ]

        for name in category_names:
            category, created = DocumentCategory.objects.get_or_create(
                organization=organization,
                name=name
            )
            categories[name] = category
            if created:
                self.stdout.write(f'  Created category: {name}')

        return categories

    def _create_documents(self, organization, user, categories):
        """Create demo documents."""
        documents_data = [
            {
                'title': 'Network Infrastructure Overview',
                'category': 'Network Documentation',
                'body': '''<h2>Network Overview</h2>
<p>Acme Corporation's network infrastructure consists of:</p>
<ul>
<li>Core Network: Dual Cisco switches in HA configuration</li>
<li>WAN: 1Gbps fiber connection with backup DSL</li>
<li>Wireless: Unifi AP Pro access points</li>
<li>Firewall: pfSense with IDS/IPS enabled</li>
<li>VPN: OpenVPN for remote access</li>
</ul>
<h3>Network Segmentation</h3>
<ul>
<li>VLAN 10: Management (10.0.10.0/24)</li>
<li>VLAN 20: Workstations (10.0.20.0/24)</li>
<li>VLAN 30: Servers (10.0.30.0/24)</li>
<li>VLAN 40: Guest (10.0.40.0/24)</li>
</ul>'''
            },
            {
                'title': 'Backup and Recovery Procedures',
                'category': 'IT Procedures',
                'body': '''<h2>Backup Procedures</h2>
<p>Acme Corporation uses a 3-2-1 backup strategy:</p>
<ul>
<li>3 copies of data</li>
<li>2 different media types</li>
<li>1 offsite copy</li>
</ul>
<h3>Backup Schedule</h3>
<p><strong>Daily:</strong> Incremental backups at 2:00 AM</p>
<p><strong>Weekly:</strong> Full backups every Sunday at 1:00 AM</p>
<p><strong>Monthly:</strong> Full backup to tape (stored offsite)</p>
<h3>Recovery Testing</h3>
<p>Perform quarterly recovery tests to verify backup integrity.</p>'''
            },
            {
                'title': 'Password Policy',
                'category': 'Security Policies',
                'body': '''<h2>Password Requirements</h2>
<ul>
<li>Minimum 12 characters</li>
<li>Must contain uppercase, lowercase, numbers, and symbols</li>
<li>Changed every 90 days</li>
<li>Cannot reuse last 12 passwords</li>
<li>Account locks after 5 failed attempts</li>
</ul>
<h3>Password Manager</h3>
<p>All employees must use the company password manager for storing credentials.</p>'''
            },
            {
                'title': 'Server Maintenance Runbook',
                'category': 'Runbooks',
                'body': '''<h2>Monthly Server Maintenance</h2>
<h3>Prerequisites</h3>
<ul>
<li>Change control approval</li>
<li>Maintenance window scheduled</li>
<li>Backups verified</li>
</ul>
<h3>Steps</h3>
<ol>
<li>Review server health and logs</li>
<li>Apply security patches</li>
<li>Update antivirus definitions</li>
<li>Clear temporary files and logs</li>
<li>Verify backup completion</li>
<li>Reboot if required</li>
<li>Test critical services</li>
<li>Document any issues</li>
</ol>'''
            },
            {
                'title': 'New Employee Onboarding',
                'category': 'IT Procedures',
                'body': '''<h2>New Employee IT Setup</h2>
<h3>Before First Day</h3>
<ul>
<li>Create AD account</li>
<li>Assign to appropriate security groups</li>
<li>Provision email account</li>
<li>Order laptop/equipment</li>
<li>Create accounts in required systems</li>
</ul>
<h3>First Day Setup</h3>
<ol>
<li>Provide laptop and peripherals</li>
<li>Set up workstation</li>
<li>Configure email and MFA</li>
<li>Install required applications</li>
<li>Provide credentials securely</li>
<li>Review security policies</li>
</ol>'''
            }
        ]

        documents = []
        for data in documents_data:
            category = categories.get(data['category'])
            document = Document.objects.create(
                organization=organization,
                title=data['title'],
                slug=data['title'].lower().replace(' ', '-'),
                body=data['body'],
                content_type='html',
                category=category,
                is_published=True,
                created_by=user,
            )
            documents.append(document)
            self.stdout.write(f'  Created document: {document.title}')

        return documents

    def _create_diagrams(self, organization, user):
        """Create demo diagrams."""

        # Network diagram with visual topology
        network_diagram_xml = '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="internet" value="Internet" style="ellipse;shape=cloud;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="340" y="40" width="140" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="firewall" value="pfSense Firewall&#xa;10.0.10.1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="350" y="160" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="switch1" value="Core Switch 1&#xa;10.0.10.2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="250" y="260" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="switch2" value="Core Switch 2&#xa;10.0.10.3" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="450" y="260" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="dc" value="Domain Controller&#xa;ACME-DC-01&#xa;10.0.30.10" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="140" y="380" width="120" height="70" as="geometry"/>
    </mxCell>
    <mxCell id="fileserver" value="File Server&#xa;ACME-FILE-01&#xa;10.0.30.11" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="350" y="380" width="120" height="70" as="geometry"/>
    </mxCell>
    <mxCell id="workstations" value="Workstations&#xa;VLAN 20&#xa;10.0.20.0/24" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;" vertex="1" parent="1">
      <mxGeometry x="560" y="380" width="120" height="70" as="geometry"/>
    </mxCell>
    <mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="internet" target="firewall">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="firewall" target="switch1">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge3" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="firewall" target="switch2">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge4" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="switch1" target="dc">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge5" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="switch2" target="fileserver">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge6" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;" edge="1" parent="1" source="switch2" target="workstations">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>'''

        # Rack diagram showing equipment layout
        rack_diagram_xml = '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="600" pageHeight="900">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="rack" value="42U Server Rack" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;verticalAlign=top;fontStyle=1;" vertex="1" parent="1">
      <mxGeometry x="200" y="50" width="200" height="700" as="geometry"/>
    </mxCell>
    <mxCell id="pdu1" value="1U - PDU 1" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="210" y="60" width="180" height="20" as="geometry"/>
    </mxCell>
    <mxCell id="switch1" value="2U - Switch CORE-01" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="210" y="85" width="180" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="switch2" value="2U - Switch CORE-02" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="210" y="130" width="180" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="patch" value="1U - Patch Panel" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;" vertex="1" parent="1">
      <mxGeometry x="210" y="175" width="180" height="20" as="geometry"/>
    </mxCell>
    <mxCell id="blank1" value="1U - Blank" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontColor=#999999;" vertex="1" parent="1">
      <mxGeometry x="210" y="200" width="180" height="20" as="geometry"/>
    </mxCell>
    <mxCell id="dc" value="4U - SRV-001-DC&#xa;Dell PowerEdge R740&#xa;Domain Controller" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="210" y="225" width="180" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="file" value="4U - SRV-002-FILE&#xa;Dell PowerEdge R740&#xa;File Server" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="210" y="310" width="180" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="ups" value="3U - UPS Battery Backup" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="210" y="680" width="180" height="60" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>'''

        # Flowchart for ticket resolution process
        flowchart_diagram_xml = '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="start" value="New Ticket Received" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;arcSize=50;" vertex="1" parent="1">
      <mxGeometry x="340" y="40" width="140" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="review" value="Review Ticket Details" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="340" y="140" width="140" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="priority" value="High Priority?" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="350" y="240" width="120" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="escalate" value="Escalate to Senior Tech" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="180" y="260" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="assign" value="Assign to Technician" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="520" y="260" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="work" value="Work on Issue" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="350" y="380" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="resolved" value="Issue Resolved?" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="350" y="480" width="120" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="document" value="Document Solution" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="350" y="620" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="close" value="Close Ticket" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;arcSize=50;" vertex="1" parent="1">
      <mxGeometry x="350" y="720" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;endArrow=classic;" edge="1" parent="1" source="start" target="review">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="review" target="priority">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e3" value="Yes" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="priority" target="escalate">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e4" value="No" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="priority" target="assign">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e5" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="escalate" target="work">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e6" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="assign" target="work">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e7" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="work" target="resolved">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e8" value="Yes" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="resolved" target="document">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="e9" value="No" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;entryX=1;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" source="resolved" target="work">
      <mxGeometry relative="1" as="geometry">
        <Array as="points">
          <mxPoint x="550" y="530"/>
          <mxPoint x="550" y="410"/>
        </Array>
      </mxGeometry>
    </mxCell>
    <mxCell id="e10" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;" edge="1" parent="1" source="document" target="close">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>'''

        diagrams_data = [
            {
                'title': 'Main Office Network Diagram',
                'diagram_type': 'network',
                'description': 'Network topology for Acme Corporation main office',
                'diagram_xml': network_diagram_xml
            },
            {
                'title': 'Server Rack Layout',
                'diagram_type': 'rack',
                'description': 'Physical layout of server rack equipment',
                'diagram_xml': rack_diagram_xml
            },
            {
                'title': 'Ticket Resolution Flowchart',
                'diagram_type': 'flowchart',
                'description': 'Process flow for resolving support tickets',
                'diagram_xml': flowchart_diagram_xml
            }
        ]

        diagrams = []
        for data in diagrams_data:
            diagram = Diagram.objects.create(
                organization=organization,
                title=data['title'],
                diagram_type=data.get('diagram_type', 'network'),
                diagram_xml=data['diagram_xml'],
                description=data.get('description', ''),
                created_by=user,
            )
            diagrams.append(diagram)
            self.stdout.write(f'  Created diagram: {diagram.title}')

        return diagrams

    def _create_assets(self, organization, user):
        """Create demo assets."""
        assets_data = [
            {'name': 'WS-001', 'asset_type': 'desktop', 'manufacturer': 'Dell', 'model': 'Latitude 5420', 'serial_number': 'DL123456', 'hostname': 'ACME-WS-001', 'ip_address': '10.0.20.10'},
            {'name': 'WS-002', 'asset_type': 'desktop', 'manufacturer': 'Dell', 'model': 'Latitude 5420', 'serial_number': 'DL123457', 'hostname': 'ACME-WS-002', 'ip_address': '10.0.20.11'},
            {'name': 'WS-003', 'asset_type': 'laptop', 'manufacturer': 'HP', 'model': 'EliteBook 850', 'serial_number': 'HP789012', 'hostname': 'ACME-WS-003', 'ip_address': '10.0.20.12'},
            {'name': 'SRV-001-DC', 'asset_type': 'server', 'manufacturer': 'Dell', 'model': 'PowerEdge R740', 'serial_number': 'SVR123456', 'hostname': 'ACME-DC-01', 'ip_address': '10.0.30.10'},
            {'name': 'SRV-002-FILE', 'asset_type': 'server', 'manufacturer': 'Dell', 'model': 'PowerEdge R740', 'serial_number': 'SVR123457', 'hostname': 'ACME-FILE-01', 'ip_address': '10.0.30.11'},
            {'name': 'SW-CORE-01', 'asset_type': 'switch', 'manufacturer': 'Cisco', 'model': 'Catalyst 3850-48P', 'serial_number': 'CS234567', 'hostname': 'ACME-SW-CORE-01', 'ip_address': '10.0.10.2'},
            {'name': 'SW-CORE-02', 'asset_type': 'switch', 'manufacturer': 'Cisco', 'model': 'Catalyst 3850-48P', 'serial_number': 'CS234568', 'hostname': 'ACME-SW-CORE-02', 'ip_address': '10.0.10.3'},
            {'name': 'FW-01', 'asset_type': 'firewall', 'manufacturer': 'pfSense', 'model': 'SG-5100', 'serial_number': 'PF456789', 'hostname': 'ACME-FW-01', 'ip_address': '10.0.10.1'},
            {'name': 'AP-01', 'asset_type': 'access_point', 'manufacturer': 'Ubiquiti', 'model': 'UniFi AP Pro', 'serial_number': 'UB987654', 'hostname': 'ACME-AP-01', 'ip_address': '10.0.10.20'},
            {'name': 'AP-02', 'asset_type': 'access_point', 'manufacturer': 'Ubiquiti', 'model': 'UniFi AP Pro', 'serial_number': 'UB987655', 'hostname': 'ACME-AP-02', 'ip_address': '10.0.10.21'},
        ]

        assets = []
        for data in assets_data:
            asset = Asset.objects.create(
                organization=organization,
                name=data['name'],
                asset_type=data['asset_type'],
                serial_number=data['serial_number'],
                manufacturer=data['manufacturer'],
                model=data['model'],
                hostname=data['hostname'],
                ip_address=data['ip_address'],
            )
            assets.append(asset)
            self.stdout.write(f'  Created asset: {asset.name}')

        return assets

    def _create_passwords(self, organization, user):
        """Create demo passwords."""
        passwords_data = [
            {'title': 'Domain Admin Account', 'username': 'administrator', 'password': 'DemoPass123!', 'password_type': 'login', 'url': 'https://acme.local', 'notes': 'Primary domain admin'},
            {'title': 'WiFi Password', 'username': '', 'password': 'AcmeWiFi2024!', 'password_type': 'wifi', 'notes': 'Main office WiFi'},
            {'title': 'Firewall Admin', 'username': 'admin', 'password': 'FWAdmin123!', 'password_type': 'login', 'url': 'https://10.0.10.1', 'notes': 'pfSense admin'},
            {'title': 'File Server SMB', 'username': 'svc_backup', 'password': 'BackupSvc456!', 'password_type': 'service', 'notes': 'Backup service account'},
            {'title': 'Email Admin', 'username': 'admin@acme.com', 'password': 'EmailAdmin789!', 'password_type': 'login', 'url': 'https://mail.acme.com', 'notes': 'Exchange admin'},
        ]

        passwords = []
        for data in passwords_data:
            password = Password.objects.create(
                organization=organization,
                title=data['title'],
                username=data['username'],
                password_type=data['password_type'],
                url=data.get('url', ''),
                notes=data.get('notes', ''),
            )
            password.set_password(data['password'])
            passwords.append(password)
            self.stdout.write(f'  Created password: {password.title}')

        return passwords

    def _create_processes(self, organization, user, documents, passwords):
        """Create demo workflows with stages."""
        from processes.models import ProcessStage

        # Find specific documents and passwords to link
        onboarding_doc = next((d for d in documents if 'Onboarding' in d.title), None)
        security_doc = next((d for d in documents if 'Security' in d.title or 'Password' in d.title), None)
        backup_doc = next((d for d in documents if 'Backup' in d.title), None)
        runbook_doc = next((d for d in documents if 'Runbook' in d.title), None)

        domain_admin_pw = next((p for p in passwords if 'Domain Admin' in p.title), None)
        firewall_pw = next((p for p in passwords if 'Firewall' in p.title), None)

        processes_data = [
            {
                'title': 'New Employee Onboarding',
                'description': 'Complete IT onboarding workflow for new employees',
                'category': 'onboarding',
                'stages': [
                    {
                        'order': 1,
                        'title': 'Create Active Directory Account',
                        'description': '1. Open Active Directory Users and Computers\n2. Navigate to appropriate OU\n3. Create new user with naming convention: firstname.lastname\n4. Set temporary password\n5. Enable account and require password change at next login',
                        'linked_password': domain_admin_pw,
                    },
                    {
                        'order': 2,
                        'title': 'Provision Email Account',
                        'description': '1. Log into Exchange Admin Center\n2. Create new mailbox for user\n3. Assign appropriate license\n4. Add to relevant distribution groups\n5. Configure mobile device policy',
                    },
                    {
                        'order': 3,
                        'title': 'Assign Security Groups',
                        'description': '1. Review department access requirements\n2. Add user to department security groups\n3. Add to file share groups\n4. Grant application access as needed\n5. Document all group memberships',
                        'linked_document': security_doc,
                    },
                    {
                        'order': 4,
                        'title': 'Provision and Configure Workstation',
                        'description': '1. Assign laptop from inventory\n2. Install standard software package\n3. Join to domain\n4. Configure encryption (BitLocker)\n5. Install and configure VPN client\n6. Test all required applications',
                    },
                    {
                        'order': 5,
                        'title': 'First Day Setup and Training',
                        'description': '1. Provide credentials securely\n2. Help user log in for first time\n3. Guide password setup\n4. Review security policies\n5. Configure MFA/2FA\n6. Demonstrate key applications',
                        'linked_document': onboarding_doc,
                    },
                ]
            },
            {
                'title': 'Server Maintenance Runbook',
                'description': 'Monthly maintenance workflow for production servers',
                'category': 'maintenance',
                'stages': [
                    {
                        'order': 1,
                        'title': 'Pre-Maintenance Checks',
                        'description': '1. Verify change control approval received\n2. Confirm maintenance window scheduled\n3. Check backup completion status\n4. Review server health dashboard\n5. Notify stakeholders of upcoming maintenance',
                        'linked_document': backup_doc,
                    },
                    {
                        'order': 2,
                        'title': 'Create Backup and Snapshot',
                        'description': '1. Take VM snapshot (if applicable)\n2. Run full backup job manually\n3. Verify backup completed successfully\n4. Document backup location and timestamp\n5. Confirm restore point is valid',
                        'linked_document': backup_doc,
                    },
                    {
                        'order': 3,
                        'title': 'Apply Security Patches',
                        'description': '1. Review available patches\n2. Download patches to staging area\n3. Apply Windows/Linux updates\n4. Apply application-specific patches\n5. Document all patches applied',
                    },
                    {
                        'order': 4,
                        'title': 'System Maintenance Tasks',
                        'description': '1. Clear temporary files and logs\n2. Update antivirus definitions\n3. Check disk space usage\n4. Review event logs for errors\n5. Optimize databases if needed',
                        'linked_document': runbook_doc,
                    },
                    {
                        'order': 5,
                        'title': 'Reboot and Verify Services',
                        'description': '1. Gracefully restart the server\n2. Monitor boot process\n3. Verify all services started\n4. Test critical applications\n5. Check network connectivity\n6. Validate with smoke tests',
                    },
                    {
                        'order': 6,
                        'title': 'Post-Maintenance Documentation',
                        'description': '1. Document all changes made\n2. Update maintenance log\n3. Remove old snapshots\n4. Notify stakeholders of completion\n5. Close change control ticket',
                    },
                ]
            },
            {
                'title': 'Security Incident Response',
                'description': 'Workflow for responding to security incidents',
                'category': 'incident',
                'stages': [
                    {
                        'order': 1,
                        'title': 'Initial Detection and Reporting',
                        'description': '1. Document initial alert or report\n2. Record time of detection\n3. Identify affected systems/users\n4. Assess initial severity\n5. Notify security team lead',
                    },
                    {
                        'order': 2,
                        'title': 'Containment',
                        'description': '1. Isolate affected systems from network\n2. Disable compromised user accounts\n3. Block malicious IP addresses at firewall\n4. Prevent lateral movement\n5. Preserve evidence for investigation',
                        'linked_password': firewall_pw,
                    },
                    {
                        'order': 3,
                        'title': 'Investigation and Analysis',
                        'description': '1. Collect logs from affected systems\n2. Analyze attack vectors and entry points\n3. Identify scope of compromise\n4. Document attacker tactics and IOCs\n5. Determine root cause',
                    },
                    {
                        'order': 4,
                        'title': 'Eradication',
                        'description': '1. Remove malware/unauthorized access\n2. Patch vulnerabilities exploited\n3. Reset compromised credentials\n4. Update firewall and IDS rules\n5. Verify threats eliminated',
                        'linked_document': security_doc,
                    },
                    {
                        'order': 5,
                        'title': 'Recovery and Monitoring',
                        'description': '1. Restore systems from clean backups\n2. Bring systems back online gradually\n3. Implement enhanced monitoring\n4. Verify normal operations\n5. Watch for signs of re-infection',
                    },
                    {
                        'order': 6,
                        'title': 'Post-Incident Review',
                        'description': '1. Document full incident timeline\n2. Conduct lessons learned meeting\n3. Update security policies/procedures\n4. Implement preventive measures\n5. File final incident report',
                    },
                ]
            },
            {
                'title': 'Firewall Configuration Change',
                'description': 'Workflow for safely implementing firewall rule changes',
                'category': 'change',
                'stages': [
                    {
                        'order': 1,
                        'title': 'Request and Approval',
                        'description': '1. Submit change request with justification\n2. Document required rule changes\n3. Identify affected services/systems\n4. Obtain manager approval\n5. Schedule implementation window',
                    },
                    {
                        'order': 2,
                        'title': 'Backup Current Configuration',
                        'description': '1. Log into firewall admin console\n2. Export current configuration\n3. Save backup with timestamp\n4. Store in secure location\n5. Verify backup file integrity',
                        'linked_password': firewall_pw,
                    },
                    {
                        'order': 3,
                        'title': 'Implement Changes',
                        'description': '1. Document each rule being added/modified\n2. Apply changes in firewall console\n3. Follow principle of least privilege\n4. Add detailed comments to rules\n5. Review before committing',
                    },
                    {
                        'order': 4,
                        'title': 'Testing and Validation',
                        'description': '1. Test affected services immediately\n2. Verify traffic flows as expected\n3. Check for unintended blocks\n4. Monitor firewall logs\n5. Confirm with stakeholders',
                    },
                    {
                        'order': 5,
                        'title': 'Documentation and Closure',
                        'description': '1. Update network documentation\n2. Document business justification\n3. Update change log\n4. Notify relevant teams\n5. Close change request',
                    },
                ]
            },
            {
                'title': 'Employee Offboarding',
                'description': 'IT offboarding workflow when employee leaves',
                'category': 'offboarding',
                'stages': [
                    {
                        'order': 1,
                        'title': 'Disable Active Directory Account',
                        'description': '1. Disable AD account immediately\n2. Reset password to random value\n3. Remove from all security groups\n4. Document account status\n5. Set account expiration date',
                        'linked_password': domain_admin_pw,
                    },
                    {
                        'order': 2,
                        'title': 'Revoke System Access',
                        'description': '1. Disable email account\n2. Remove VPN access\n3. Disable remote desktop access\n4. Revoke application licenses\n5. Remove from cloud services (O365, AWS, etc.)',
                    },
                    {
                        'order': 3,
                        'title': 'Collect Company Equipment',
                        'description': '1. Retrieve laptop/desktop\n2. Collect mobile devices\n3. Recover security badges/keys\n4. Get chargers and accessories\n5. Document all items returned',
                    },
                    {
                        'order': 4,
                        'title': 'Data Backup and Transfer',
                        'description': '1. Backup user home directory\n2. Backup email/calendar to PST\n3. Transfer files to manager\n4. Archive important documents\n5. Document data retention',
                    },
                    {
                        'order': 5,
                        'title': 'Final Cleanup',
                        'description': '1. Wipe workstation\n2. Remove from asset inventory\n3. Cancel software licenses\n4. Update documentation\n5. Close offboarding ticket',
                    },
                ]
            },
        ]

        processes = []
        for data in processes_data:
            # Create the process
            process = Process.objects.create(
                organization=organization,
                title=data['title'],
                slug=slugify(data['title']),
                description=data['description'],
                category=data.get('category', 'other'),
                is_published=True,
                created_by=user,
            )

            # Create stages for this process
            for stage_data in data['stages']:
                ProcessStage.objects.create(
                    process=process,
                    order=stage_data['order'],
                    title=stage_data['title'],
                    description=stage_data['description'],
                    linked_document=stage_data.get('linked_document'),
                    linked_password=stage_data.get('linked_password'),
                )

            processes.append(process)
            self.stdout.write(f'  Created workflow: {process.title} ({len(data["stages"])} stages)')

        return processes
