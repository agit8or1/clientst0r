"""
Management command to seed diagram templates
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Organization
from docs.models import Diagram


class Command(BaseCommand):
    help = 'Seed diagram templates for organizations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-slug',
            type=str,
            help='Organization slug to create templates for (if not provided, creates global templates)'
        )

    def handle(self, *args, **options):
        org_slug = options.get('org_slug')

        if org_slug:
            try:
                organization = Organization.objects.get(slug=org_slug)
                self.stdout.write(f"Creating diagram templates for organization: {organization.name}")
                is_global = False
            except Organization.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Organization with slug '{org_slug}' not found"))
                return
        else:
            # Create global templates (no organization required)
            organization = None
            self.stdout.write("Creating global diagram templates (no organization required)")
            is_global = True

        # Get superuser for created_by field
        superuser = User.objects.filter(is_superuser=True).first()
        if not superuser:
            superuser = User.objects.first()

        # Diagram Templates with simple mxGraph XML (simplified to avoid issues)
        diagram_templates = [
            {
                'title': 'Network Diagram Template',
                'slug': 'network-diagram-template',
                'description': 'Basic network topology template - start here and customize',
                'diagram_type': 'network',
                'diagram_xml': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Router" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="240" y="120" width="120" height="60" as="geometry"/></mxCell><mxCell id="3" value="Switch" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="240" y="240" width="120" height="60" as="geometry"/></mxCell><mxCell id="4" value="Server" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="240" y="360" width="120" height="60" as="geometry"/></mxCell><mxCell id="5" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="6" style="endArrow=classic;html=1;" edge="1" parent="1" source="3" target="4"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel>',
            },
            {
                'title': 'Server Rack Layout Template',
                'slug': 'rack-layout-template',
                'description': '42U server rack layout with sample equipment',
                'diagram_type': 'rack',
                'diagram_xml': '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="rack" value="42U Rack" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;verticalAlign=top;" vertex="1" parent="1">
      <mxGeometry x="200" y="40" width="200" height="720" as="geometry"/>
    </mxCell>
    <mxCell id="pdu1" value="PDU" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;" vertex="1" parent="1">
      <mxGeometry x="210" y="50" width="180" height="20" as="geometry"/>
    </mxCell>
    <mxCell id="switch1" value="Switch (1U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="210" y="80" width="180" height="30" as="geometry"/>
    </mxCell>
    <mxCell id="firewall" value="Firewall (1U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="210" y="120" width="180" height="30" as="geometry"/>
    </mxCell>
    <mxCell id="server1" value="Server 1 (2U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="210" y="160" width="180" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="server2" value="Server 2 (2U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="210" y="230" width="180" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="storage" value="Storage (4U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="210" y="300" width="180" height="120" as="geometry"/>
    </mxCell>
    <mxCell id="label" value="Add equipment by copying and pasting these blocks.&#xa;Edit text to match your rack layout.&#xa;&#xa;Standard Heights:&#xa;1U = 30px&#xa;2U = 60px&#xa;4U = 120px" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;rounded=0;fontSize=11;" vertex="1" parent="1">
      <mxGeometry x="440" y="40" width="280" height="120" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>''',
            },
            {
                'title': 'Process Flowchart Template',
                'slug': 'process-flowchart-template',
                'description': 'Basic flowchart template with start, process, decision, and end',
                'diagram_type': 'flowchart',
                'diagram_xml': '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="start" value="Start" style="ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="240" y="40" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="process1" value="Process Step" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="240" y="140" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="decision" value="Decision?" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="230" y="240" width="140" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="processYes" value="Yes Path" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="100" y="380" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="processNo" value="No Path" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="380" y="380" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="end" value="End" style="ellipse;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="240" y="500" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="start" target="process1">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="process1" target="decision">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge3" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="decision" target="processYes">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge4" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="decision" target="processNo">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge5" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="processYes" target="end">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge6" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="processNo" target="end">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="labelYes" value="Yes" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;" vertex="1" parent="1">
      <mxGeometry x="170" y="310" width="40" height="20" as="geometry"/>
    </mxCell>
    <mxCell id="labelNo" value="No" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;" vertex="1" parent="1">
      <mxGeometry x="390" y="310" width="40" height="20" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>''',
            },
            {
                'title': 'Cloud Architecture Template',
                'slug': 'cloud-architecture-template',
                'description': 'Basic cloud system architecture with load balancer, app servers, and database',
                'diagram_type': 'architecture',
                'diagram_xml': '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="1"/>
    <mxCell id="internet" value="Internet" style="ellipse;shape=cloud;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="240" y="40" width="160" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="lb" value="Load Balancer" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="240" y="180" width="160" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="app1" value="App Server 1" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="120" y="300" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="app2" value="App Server 2" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="260" y="300" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="app3" value="App Server 3" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="400" y="300" width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="db" value="Database&#xa;(Master)" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="270" y="440" width="100" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="dbreplica" value="Database&#xa;(Replica)" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="410" y="440" width="100" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="cache" value="Cache&#xa;(Redis)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;" vertex="1" parent="1">
      <mxGeometry x="120" y="440" width="100" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="internet" target="lb">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="lb" target="app1">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge3" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="lb" target="app2">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge4" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="lb" target="app3">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge5" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="app2" target="db">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge6" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;dashed=1;" edge="1" parent="1" source="db" target="dbreplica">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
    <mxCell id="edge7" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;" edge="1" parent="1" source="app1" target="cache">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>''',
            },
            {
                'title': 'Office Floor Plan Template',
                'slug': 'office-floor-plan-template',
                'description': 'Basic office floor plan layout with rooms and areas',
                'diagram_type': 'floorplan',
                'diagram_xml': '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="building" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#666666;strokeWidth=3;" vertex="1" parent="1">
      <mxGeometry x="80" y="80" width="560" height="400" as="geometry"/>
    </mxCell>
    <mxCell id="office1" value="Office 1" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="90" y="90" width="120" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="office2" value="Office 2" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
      <mxGeometry x="220" y="90" width="120" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="conference" value="Conference Room" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="350" y="90" width="280" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="openspace" value="Open Workspace" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1">
      <mxGeometry x="90" y="200" width="380" height="150" as="geometry"/>
    </mxCell>
    <mxCell id="kitchen" value="Kitchen/Break Room" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">
      <mxGeometry x="480" y="200" width="150" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="storage" value="Storage" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;" vertex="1" parent="1">
      <mxGeometry x="480" y="290" width="150" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="serverroom" value="Server Room" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;" vertex="1" parent="1">
      <mxGeometry x="90" y="360" width="100" height="110" as="geometry"/>
    </mxCell>
    <mxCell id="restroom" value="Restroom" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="200" y="360" width="80" height="110" as="geometry"/>
    </mxCell>
    <mxCell id="reception" value="Reception/Lobby" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
      <mxGeometry x="290" y="360" width="340" height="110" as="geometry"/>
    </mxCell>
    <mxCell id="entrance" value="Entrance" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;dashed=1;" vertex="1" parent="1">
      <mxGeometry x="420" y="470" width="80" height="10" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>''',
            },
        ]

        created_count = 0
        skipped_count = 0

        for template_data in diagram_templates:
            slug = template_data['slug']

            # Check if template already exists
            if Diagram.objects.filter(organization=organization, slug=slug).exists():
                self.stdout.write(self.style.WARNING(f"Template '{template_data['title']}' already exists, skipping"))
                skipped_count += 1
                continue

            # Create template
            Diagram.objects.create(
                organization=organization,
                title=template_data['title'],
                slug=slug,
                description=template_data['description'],
                diagram_type=template_data['diagram_type'],
                diagram_xml=template_data['diagram_xml'],
                is_template=True,
                is_published=True,
                is_global=is_global,
                created_by=superuser,
                last_modified_by=superuser,
            )

            self.stdout.write(self.style.SUCCESS(f"✓ Created diagram template: {template_data['title']}"))
            created_count += 1

        self.stdout.write(self.style.SUCCESS(f"\n{'='*60}"))
        self.stdout.write(self.style.SUCCESS(f"Diagram templates created: {created_count}"))
        self.stdout.write(self.style.WARNING(f"Diagram templates skipped (already exist): {skipped_count}"))
        self.stdout.write(self.style.SUCCESS(f"{'='*60}"))
        self.stdout.write(self.style.SUCCESS(f"\nThese templates can be used as starting points when creating new diagrams."))
        self.stdout.write(self.style.SUCCESS(f"Users can open them in the Draw.io editor and customize as needed."))
