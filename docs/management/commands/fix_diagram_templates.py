"""
Fix diagram templates with self-reference errors
"""
from django.core.management.base import BaseCommand
from docs.models import Diagram


class Command(BaseCommand):
    help = 'Fix diagram templates with self-reference errors'

    def handle(self, *args, **options):
        # Simple working diagrams without self-references or complex formatting
        templates = {
            'network-diagram-template': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Router" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="240" y="120" width="120" height="60" as="geometry"/></mxCell><mxCell id="3" value="Switch" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="240" y="240" width="120" height="60" as="geometry"/></mxCell><mxCell id="4" value="Server" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="240" y="360" width="120" height="60" as="geometry"/></mxCell><mxCell id="5" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="6" style="endArrow=classic;html=1;" edge="1" parent="1" source="3" target="4"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel>',

            'rack-layout-template': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="42U Rack" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;verticalAlign=top;" vertex="1" parent="1"><mxGeometry x="200" y="40" width="200" height="600" as="geometry"/></mxCell><mxCell id="3" value="Switch (1U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="210" y="50" width="180" height="30" as="geometry"/></mxCell><mxCell id="4" value="Server 1 (2U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="210" y="90" width="180" height="60" as="geometry"/></mxCell><mxCell id="5" value="Server 2 (2U)" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="210" y="160" width="180" height="60" as="geometry"/></mxCell></root></mxGraphModel>',

            'process-flowchart-template': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Start" style="ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="240" y="40" width="120" height="60" as="geometry"/></mxCell><mxCell id="3" value="Process Step" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="240" y="140" width="120" height="60" as="geometry"/></mxCell><mxCell id="4" value="End" style="ellipse;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1"><mxGeometry x="240" y="240" width="120" height="60" as="geometry"/></mxCell><mxCell id="5" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="6" style="endArrow=classic;html=1;" edge="1" parent="1" source="3" target="4"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel>',

            'cloud-architecture-template': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Load Balancer" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="240" y="80" width="160" height="60" as="geometry"/></mxCell><mxCell id="3" value="App Server 1" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="140" y="200" width="120" height="60" as="geometry"/></mxCell><mxCell id="4" value="App Server 2" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="280" y="200" width="120" height="60" as="geometry"/></mxCell><mxCell id="5" value="Database" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1"><mxGeometry x="220" y="320" width="100" height="80" as="geometry"/></mxCell><mxCell id="6" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="7" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="4"><mxGeometry relative="1" as="geometry"/></mxCell><mxCell id="8" style="endArrow=classic;html=1;" edge="1" parent="1" source="3" target="5"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel>',

            'office-floor-plan-template': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Office 1" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="90" y="90" width="120" height="100" as="geometry"/></mxCell><mxCell id="3" value="Office 2" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1"><mxGeometry x="220" y="90" width="120" height="100" as="geometry"/></mxCell><mxCell id="4" value="Conference Room" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="350" y="90" width="180" height="100" as="geometry"/></mxCell><mxCell id="5" value="Open Workspace" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" vertex="1" parent="1"><mxGeometry x="90" y="200" width="280" height="120" as="geometry"/></mxCell></root></mxGraphModel>',
        }

        updated = 0
        for slug, xml in templates.items():
            diagram = Diagram.objects.filter(slug=slug).first()
            if diagram:
                diagram.diagram_xml = xml
                diagram.save()
                self.stdout.write(self.style.SUCCESS(f'✓ Fixed: {diagram.title}'))
                updated += 1
            else:
                self.stdout.write(self.style.WARNING(f'⚠ Not found: {slug}'))

        self.stdout.write(self.style.SUCCESS(f'\nFixed {updated} diagram templates'))
