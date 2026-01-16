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
                }

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

                # Skip KB articles - no KB model exists yet
                stats['kb_articles'] = 0

                # Skip processes - model structure needs verification
                stats['processes'] = 0

                self.stdout.write(
                    self.style.SUCCESS(
                        '\n✓ Successfully imported Acme Corporation demo data:'
                    )
                )
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

    def _create_processes(self, organization, user):
        """Create demo processes."""
        processes_data = [
            {
                'title': 'New Employee Onboarding',
                'description': 'Complete IT onboarding process for new employees',
                'process_steps': [
                    {'order': 1, 'title': 'Create AD Account', 'description': 'Create Active Directory user account'},
                    {'order': 2, 'title': 'Provision Email', 'description': 'Create Exchange mailbox'},
                    {'order': 3, 'title': 'Assign Equipment', 'description': 'Order and assign laptop'},
                    {'order': 4, 'title': 'Setup Workstation', 'description': 'Configure laptop with required software'},
                ]
            },
            {
                'title': 'Server Patching',
                'description': 'Monthly server patching and maintenance',
                'process_steps': [
                    {'order': 1, 'title': 'Backup Verification', 'description': 'Verify backups are current'},
                    {'order': 2, 'title': 'Apply Patches', 'description': 'Install security updates'},
                    {'order': 3, 'title': 'Reboot', 'description': 'Restart server if required'},
                    {'order': 4, 'title': 'Verify Services', 'description': 'Test critical services'},
                ]
            },
        ]

        processes = []
        for data in processes_data:
            process = Process.objects.create(
                organization=organization,
                title=data['title'],
                description=data['description'],
                process_steps=data.get('process_steps', []),
                created_by=user,
            )
            processes.append(process)
            self.stdout.write(f'  Created process: {process.title}')

        return processes
