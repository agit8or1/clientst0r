"""
Create a demo office floor plan diagram with network infrastructure.
"""
from django.core.management.base import BaseCommand
from docs.models import Diagram
from core.models import Organization
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create professional demo office floor plan with network infrastructure'

    def add_arguments(self, parser):
        parser.add_argument(
            '--organization-id',
            type=int,
            help='Organization ID (default: first org)'
        )

    def handle(self, *args, **options):
        # Get organization
        if options['organization_id']:
            org = Organization.objects.get(id=options['organization_id'])
        else:
            org = Organization.objects.first()

        if not org:
            self.stdout.write(self.style.ERROR("No organization found"))
            return

        # Get admin user
        user = User.objects.filter(is_staff=True).first()
        if not user:
            user = User.objects.first()

        self.stdout.write(f"Creating demo floor plan for organization: {org.name}")

        # Create the diagram with professional floor plan XML
        diagram_xml = '''<mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>

    <!-- Office Building Outline -->
    <mxCell id="building" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;strokeWidth=3;opacity=30;" vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="1080" height="720" as="geometry"/>
    </mxCell>

    <!-- Reception Area -->
    <mxCell id="reception-area" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="60" y="60" width="320" height="200" as="geometry"/>
    </mxCell>
    <mxCell id="reception-label" value="&lt;b&gt;RECEPTION&lt;/b&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;" vertex="1" parent="1">
      <mxGeometry x="140" y="150" width="160" height="30" as="geometry"/>
    </mxCell>

    <!-- Access Control at Reception -->
    <mxCell id="ac-reception" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="340" y="140" width="20" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ac-reception-icon" value="🔐" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;" vertex="1" parent="1">
      <mxGeometry x="335" y="145" width="30" height="30" as="geometry"/>
    </mxCell>
    <mxCell id="ac-reception-label" value="Access Control" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="310" y="185" width="80" height="20" as="geometry"/>
    </mxCell>

    <!-- Reception AP -->
    <mxCell id="ap-reception" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="195" y="85" width="50" height="50" as="geometry"/>
    </mxCell>
    <mxCell id="ap-reception-icon" value="📡" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="200" y="90" width="40" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ap-reception-label" value="AP-01 (2.4/5GHz)" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="175" y="140" width="90" height="20" as="geometry"/>
    </mxCell>

    <!-- Open Office Area -->
    <mxCell id="open-office" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="400" y="60" width="380" height="320" as="geometry"/>
    </mxCell>
    <mxCell id="open-office-label" value="&lt;b&gt;OPEN OFFICE&lt;/b&gt;&lt;br&gt;Hot Desks" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=14;" vertex="1" parent="1">
      <mxGeometry x="520" y="200" width="140" height="40" as="geometry"/>
    </mxCell>

    <!-- Open Office APs -->
    <mxCell id="ap-office1" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="480" y="100" width="50" height="50" as="geometry"/>
    </mxCell>
    <mxCell id="ap-office1-icon" value="📡" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="485" y="105" width="40" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ap-office1-label" value="AP-02" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="475" y="155" width="60" height="20" as="geometry"/>
    </mxCell>

    <mxCell id="ap-office2" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="680" y="100" width="50" height="50" as="geometry"/>
    </mxCell>
    <mxCell id="ap-office2-icon" value="📡" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="685" y="105" width="40" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ap-office2-label" value="AP-03" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="675" y="155" width="60" height="20" as="geometry"/>
    </mxCell>

    <!-- Desk representations -->
    <mxCell id="desk1" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="420" y="260" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk2" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="500" y="260" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk3" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="580" y="260" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk4" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="660" y="260" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk5" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="420" y="320" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk6" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="500" y="320" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk7" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="580" y="320" width="60" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="desk8" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;" vertex="1" parent="1">
      <mxGeometry x="660" y="320" width="60" height="40" as="geometry"/>
    </mxCell>

    <!-- Conference Room 1 -->
    <mxCell id="conf1" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="60" y="280" width="200" height="160" as="geometry"/>
    </mxCell>
    <mxCell id="conf1-label" value="&lt;b&gt;CONFERENCE 1&lt;/b&gt;&lt;br&gt;Cap: 8" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=12;" vertex="1" parent="1">
      <mxGeometry x="100" y="345" width="120" height="30" as="geometry"/>
    </mxCell>

    <!-- Access Control Conf 1 -->
    <mxCell id="ac-conf1" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="240" y="340" width="20" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ac-conf1-icon" value="🔐" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;" vertex="1" parent="1">
      <mxGeometry x="235" y="345" width="30" height="30" as="geometry"/>
    </mxCell>

    <!-- Conference Room 2 -->
    <mxCell id="conf2" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="60" y="460" width="200" height="160" as="geometry"/>
    </mxCell>
    <mxCell id="conf2-label" value="&lt;b&gt;CONFERENCE 2&lt;/b&gt;&lt;br&gt;Cap: 12" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=12;" vertex="1" parent="1">
      <mxGeometry x="100" y="525" width="120" height="30" as="geometry"/>
    </mxCell>

    <!-- Access Control Conf 2 -->
    <mxCell id="ac-conf2" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="240" y="520" width="20" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ac-conf2-icon" value="🔐" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;" vertex="1" parent="1">
      <mxGeometry x="235" y="525" width="30" height="30" as="geometry"/>
    </mxCell>

    <!-- Conference Room AP -->
    <mxCell id="ap-conf" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="135" y="640" width="50" height="50" as="geometry"/>
    </mxCell>
    <mxCell id="ap-conf-icon" value="📡" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="140" y="645" width="40" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ap-conf-label" value="AP-04" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="130" y="695" width="60" height="20" as="geometry"/>
    </mxCell>

    <!-- Server Room -->
    <mxCell id="server-room" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=3;" vertex="1" parent="1">
      <mxGeometry x="800" y="60" width="300" height="320" as="geometry"/>
    </mxCell>
    <mxCell id="server-room-label" value="&lt;b&gt;SERVER ROOM&lt;/b&gt;&lt;br&gt;🚨 Restricted Access" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=16;fontColor=#CC0000;" vertex="1" parent="1">
      <mxGeometry x="860" y="85" width="180" height="50" as="geometry"/>
    </mxCell>

    <!-- Biometric Access Control Server Room -->
    <mxCell id="ac-server" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#CC0000;strokeColor=#660000;strokeWidth=3;" vertex="1" parent="1">
      <mxGeometry x="1080" y="190" width="20" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="ac-server-icon" value="👁️" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="1073" y="200" width="34" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ac-server-label" value="Biometric" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;fontColor=#CC0000;" vertex="1" parent="1">
      <mxGeometry x="1045" y="255" width="90" height="20" as="geometry"/>
    </mxCell>

    <!-- Server Racks -->
    <mxCell id="rack1" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#333333;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="830" y="160" width="80" height="200" as="geometry"/>
    </mxCell>
    <mxCell id="rack1-label" value="&lt;font color=&quot;#ffffff&quot;&gt;&lt;b&gt;RACK 1&lt;/b&gt;&lt;br&gt;Core&lt;br&gt;Switching&lt;/font&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="835" y="240" width="70" height="40" as="geometry"/>
    </mxCell>

    <mxCell id="rack2" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#333333;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="930" y="160" width="80" height="200" as="geometry"/>
    </mxCell>
    <mxCell id="rack2-label" value="&lt;font color=&quot;#ffffff&quot;&gt;&lt;b&gt;RACK 2&lt;/b&gt;&lt;br&gt;Servers&lt;br&gt;Storage&lt;/font&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="935" y="240" width="70" height="40" as="geometry"/>
    </mxCell>

    <mxCell id="rack3" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#333333;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="1030" y="160" width="80" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="rack3-label" value="&lt;font color=&quot;#ffffff&quot;&gt;&lt;b&gt;PATCH&lt;/b&gt;&lt;br&gt;PANEL&lt;/font&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="1040" y="190" width="60" height="40" as="geometry"/>
    </mxCell>

    <!-- UPS -->
    <mxCell id="ups" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffff00;strokeColor=#CC6600;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="1030" y="280" width="80" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="ups-label" value="&lt;b&gt;UPS&lt;/b&gt;&lt;br&gt;⚡ 10kVA" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="1040" y="295" width="60" height="30" as="geometry"/>
    </mxCell>

    <!-- Break Room -->
    <mxCell id="break-room" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="280" y="460" width="220" height="160" as="geometry"/>
    </mxCell>
    <mxCell id="break-room-label" value="&lt;b&gt;BREAK ROOM&lt;/b&gt;&lt;br&gt;☕ 🍕" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=14;" vertex="1" parent="1">
      <mxGeometry x="330" y="525" width="120" height="30" as="geometry"/>
    </mxCell>

    <!-- IT Closet -->
    <mxCell id="it-closet" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="520" y="460" width="140" height="100" as="geometry"/>
    </mxCell>
    <mxCell id="it-closet-label" value="&lt;b&gt;IT CLOSET&lt;/b&gt;&lt;br&gt;🖥️ Workstations" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=11;" vertex="1" parent="1">
      <mxGeometry x="540" y="495" width="100" height="30" as="geometry"/>
    </mxCell>

    <!-- Access Control IT Closet -->
    <mxCell id="ac-it" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="640" y="490" width="20" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ac-it-icon" value="🔐" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;" vertex="1" parent="1">
      <mxGeometry x="635" y="495" width="30" height="30" as="geometry"/>
    </mxCell>

    <!-- Manager Offices -->
    <mxCell id="office1" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="680" y="460" width="200" height="120" as="geometry"/>
    </mxCell>
    <mxCell id="office1-label" value="&lt;b&gt;MANAGER OFFICE 1&lt;/b&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=11;" vertex="1" parent="1">
      <mxGeometry x="710" y="505" width="140" height="30" as="geometry"/>
    </mxCell>

    <mxCell id="office2" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="900" y="460" width="200" height="120" as="geometry"/>
    </mxCell>
    <mxCell id="office2-label" value="&lt;b&gt;MANAGER OFFICE 2&lt;/b&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=11;" vertex="1" parent="1">
      <mxGeometry x="930" y="505" width="140" height="30" as="geometry"/>
    </mxCell>

    <!-- Storage Room -->
    <mxCell id="storage" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="520" y="580" width="140" height="180" as="geometry"/>
    </mxCell>
    <mxCell id="storage-label" value="&lt;b&gt;STORAGE&lt;/b&gt;&lt;br&gt;📦" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=12;" vertex="1" parent="1">
      <mxGeometry x="550" y="655" width="80" height="30" as="geometry"/>
    </mxCell>

    <!-- Restrooms -->
    <mxCell id="restroom1" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="680" y="600" width="100" height="80" as="geometry"/>
    </mxCell>
    <mxCell id="restroom1-label" value="&lt;b&gt;🚹&lt;/b&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="705" y="625" width="50" height="30" as="geometry"/>
    </mxCell>

    <mxCell id="restroom2" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="680" y="700" width="100" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="restroom2-label" value="&lt;b&gt;🚺&lt;/b&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="705" y="715" width="50" height="30" as="geometry"/>
    </mxCell>

    <!-- Executive Area -->
    <mxCell id="exec-area" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=3;" vertex="1" parent="1">
      <mxGeometry x="800" y="600" width="300" height="160" as="geometry"/>
    </mxCell>
    <mxCell id="exec-label" value="&lt;b&gt;EXECUTIVE SUITE&lt;/b&gt;&lt;br&gt;CEO Office" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=14;" vertex="1" parent="1">
      <mxGeometry x="875" y="665" width="150" height="30" as="geometry"/>
    </mxCell>

    <!-- Access Control Executive -->
    <mxCell id="ac-exec" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="1080" y="660" width="20" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ac-exec-icon" value="🔐" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;" vertex="1" parent="1">
      <mxGeometry x="1075" y="665" width="30" height="30" as="geometry"/>
    </mxCell>

    <!-- Executive AP -->
    <mxCell id="ap-exec" value="" style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="925" y="710" width="50" height="50" as="geometry"/>
    </mxCell>
    <mxCell id="ap-exec-icon" value="📡" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=24;" vertex="1" parent="1">
      <mxGeometry x="930" y="715" width="40" height="40" as="geometry"/>
    </mxCell>
    <mxCell id="ap-exec-label" value="AP-05" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=9;" vertex="1" parent="1">
      <mxGeometry x="920" y="735" width="60" height="20" as="geometry"/>
    </mxCell>

    <!-- Network Backbone Lines -->
    <mxCell id="line1" value="" style="endArrow=classic;html=1;strokeWidth=2;strokeColor=#0066CC;dashed=1;" edge="1" parent="1" source="ap-reception" target="rack1">
      <mxGeometry width="50" height="50" relative="1" as="geometry">
        <mxPoint x="570" y="430" as="sourcePoint"/>
        <mxPoint x="620" y="380" as="targetPoint"/>
      </mxGeometry>
    </mxCell>
    <mxCell id="line2" value="" style="endArrow=classic;html=1;strokeWidth=2;strokeColor=#0066CC;dashed=1;" edge="1" parent="1" source="ap-office1" target="rack1">
      <mxGeometry width="50" height="50" relative="1" as="geometry">
        <mxPoint x="570" y="430" as="sourcePoint"/>
        <mxPoint x="620" y="380" as="targetPoint"/>
      </mxGeometry>
    </mxCell>
    <mxCell id="line3" value="" style="endArrow=classic;html=1;strokeWidth=2;strokeColor=#0066CC;dashed=1;" edge="1" parent="1" source="ap-office2" target="rack1">
      <mxGeometry width="50" height="50" relative="1" as="geometry">
        <mxPoint x="570" y="430" as="sourcePoint"/>
        <mxPoint x="620" y="380" as="targetPoint"/>
      </mxGeometry>
    </mxCell>

    <!-- Legend -->
    <mxCell id="legend-box" value="" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2;" vertex="1" parent="1">
      <mxGeometry x="280" y="640" width="220" height="120" as="geometry"/>
    </mxCell>
    <mxCell id="legend-title" value="&lt;b&gt;LEGEND&lt;/b&gt;" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=12;fontStyle=1" vertex="1" parent="1">
      <mxGeometry x="340" y="645" width="100" height="20" as="geometry"/>
    </mxCell>
    <mxCell id="legend1" value="📡 Wireless Access Point" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="290" y="670" width="200" height="15" as="geometry"/>
    </mxCell>
    <mxCell id="legend2" value="🔐 Access Control Reader" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="290" y="690" width="200" height="15" as="geometry"/>
    </mxCell>
    <mxCell id="legend3" value="⚡ UPS Power Backup" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="290" y="710" width="200" height="15" as="geometry"/>
    </mxCell>
    <mxCell id="legend4" value="🚨 Restricted Area" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;" vertex="1" parent="1">
      <mxGeometry x="290" y="730" width="200" height="15" as="geometry"/>
    </mxCell>
  </root>
</mxGraphModel>'''

        # Check if diagram already exists
        existing = Diagram.objects.filter(
            organization=org,
            slug='demo-office-floor-plan'
        ).first()

        if existing:
            self.stdout.write(self.style.WARNING(f"Diagram already exists (ID: {existing.id}), updating..."))
            existing.diagram_xml = diagram_xml
            existing.last_modified_by = user
            existing.save()
            diagram = existing
        else:
            # Create new diagram
            diagram = Diagram.objects.create(
                organization=org,
                title='Demo Office Floor Plan - 2nd Floor',
                slug='demo-office-floor-plan',
                diagram_type='floorplan',
                diagram_xml=diagram_xml,
                description='Professional office floor plan with network infrastructure, access control points, server room, and various office areas. Includes 5 wireless APs, 7 access control readers, server room with 3 racks and UPS.',
                created_by=user,
                last_modified_by=user,
                version_number=1
            )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Created diagram: {diagram.title} (ID: {diagram.id})"))
        self.stdout.write("\nDiagram includes:")
        self.stdout.write("  📡 5 Wireless Access Points (AP-01 through AP-05)")
        self.stdout.write("  🔐 7 Access Control Readers (Reception, Conf Rooms, Server Room, IT Closet, Executive)")
        self.stdout.write("  🖥️  Server Room with 3 racks (Core, Servers, Patch Panel)")
        self.stdout.write("  ⚡ 10kVA UPS Power Backup")
        self.stdout.write("  🏢 Multiple office areas (Open Office, Conf Rooms, Manager Offices, Executive Suite)")
        self.stdout.write("  📦 Support rooms (IT Closet, Storage, Break Room, Restrooms)")
        self.stdout.write("\nTo view: Go to Documents → Diagrams")
        self.stdout.write(f"Direct link: /docs/diagrams/{diagram.slug}/")
