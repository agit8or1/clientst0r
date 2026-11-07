"""
Create the isolated "Client XYZ" demonstration for the hardware inventory.

    python manage.py seed_hardware_demo            # create (skips if present)
    python manage.py seed_hardware_demo --reset    # delete Client XYZ's hardware data and rebuild

Everything is invented: the organization, names, serials (DEMO-…), addresses
(RFC 1918), and the street address. Only catalog models are real, and they
come from the catalog: the Dell PowerConnect 3448P (manufacturer-documented),
the community library's Netgate 4100, Dell PowerEdge R640, Ubiquiti U6 Pro and
Generic 48-port patch panel, and local generic templates for the wall plates and
the workstation.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

DEMO_NAME = 'Client XYZ'
DEMO_DESCRIPTION = ('DEMO CLIENT — invented data for the hardware inventory demonstration '
                    '(seed_hardware_demo). Safe to delete.')


class Command(BaseCommand):
    help = 'Create the isolated "Client XYZ" hardware-inventory demonstration.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help="Delete Client XYZ's hardware records first")

    def handle(self, *args, **o):
        from core.models import Organization
        from hardware.labels import ensure_default_templates
        from hardware.local_models import ensure_local_models

        ensure_local_models(stdout=self.stdout)
        ensure_default_templates()
        org = Organization.objects.filter(name=DEMO_NAME).first()
        if org and not org.description.startswith('DEMO CLIENT'):
            raise CommandError(f'An organization named {DEMO_NAME} exists and is not the demo; refusing to touch it.')
        if org and org.hardware_devices.exists():
            if not o['reset']:
                self.stdout.write(self.style.WARNING(f'{DEMO_NAME} already has hardware. Use --reset to rebuild.'))
                return
            self._reset(org)
        with transaction.atomic():
            self._build(org)

    def _reset(self, org):
        from assets.models import Asset
        from hardware.models import Cable, CableTermination, DiagramLayout, HardwareChange, WirelessSSID
        from monitoring.models import Rack, VLAN, VLANGroup
        with transaction.atomic():
            CableTermination.objects.filter(organization=org).delete()
            Cable.objects.filter(organization=org).delete()
            WirelessSSID.objects.filter(organization=org).delete()
            Asset.objects.filter(organization=org, hardware__isnull=False).delete()
            Rack.objects.filter(organization=org).delete()
            VLAN.objects.filter(organization=org).delete()
            VLANGroup.objects.filter(organization=org).delete()
            DiagramLayout.objects.filter(organization=org).delete()
            HardwareChange.objects.filter(organization=org).delete()
        self.stdout.write('  reset existing demo hardware')

    def _build(self, org):
        from core.models import Organization
        from hardware import services as S
        from hardware.models import DevicePort, HardwareModel, LogicalInterface, WirelessSSID
        from locations.models import Location
        from monitoring.models import Rack, VLAN

        if org is None:
            org = Organization.objects.create(name=DEMO_NAME, slug=slugify(DEMO_NAME), description=DEMO_DESCRIPTION,
                                              organization_type='other')
        site = Location.objects.filter(organization=org, name='XYZ Headquarters').first() or Location.objects.create(
            organization=org, name='XYZ Headquarters', street_address='100 Example Way', city='Springfield',
            state='IL', postal_code='62701', country='United States')
        rack = Rack.objects.create(organization=org, name='XYZ-RACK-01', rack_type='full_rack', units=42, site=site,
                                   building='HQ', floor='1', room='IDF-1', notes='Demo rack')
        vlans = {}
        for vid, name, color in ((10, 'Staff', '#1c7ed6'), (20, 'Voice', '#f08c00'), (30, 'Guest', '#2f9e44'),
                                 (99, 'Management', '#7048e8')):
            vlans[vid] = VLAN.objects.create(organization=org, vlan_id=vid, name=name, color=color,
                                             description=f'Demo VLAN {vid}')

        def model(slug):
            return HardwareModel.objects.get(slug=slug)

        def port(dev, name, cls=None):
            qs = DevicePort.objects.filter(device=dev, name=name)
            if cls:
                qs = qs.filter(component_class=cls)
            return qs.get()

        sw = S.create_device(org, model('local-dell-powerconnect-3448p'), 'XYZ-SW-01', site=site, room='IDF-1',
                             hostname='xyz-sw-01.xyz.example', serial_number='DEMO-SW01-3448P', asset_tag='XYZ-0001',
                             ip_address='10.99.0.2', firmware_version='2.0.1.x (demo)', status='active')
        S.place_in_rack(sw, rack, 38)
        pp = S.create_device(org, model('generic-48-port-copper-patch-panel'), 'PP-01', site=site, room='IDF-1',
                             asset_tag='XYZ-0002', status='active')
        S.place_in_rack(pp, rack, 40)
        fw = S.create_device(org, model('netgate-4100-security-gateway'), 'XYZ-FW-01', site=site, room='IDF-1',
                             hostname='xyz-fw-01.xyz.example', serial_number='DEMO-FW01', asset_tag='XYZ-0003',
                             ip_address='10.99.0.1', platform='pfSense Plus', status='active')
        S.place_in_rack(fw, rack, 36)
        srv = S.create_device(org, model('dell-poweredge-r640'), 'XYZ-SRV-01', site=site, room='IDF-1',
                              hostname='xyz-srv-01.xyz.example', serial_number='DEMO-SVCTAG1', asset_tag='XYZ-0004',
                              ip_address='10.99.0.10', platform='Proxmox VE', status='active')
        S.place_in_rack(srv, rack, 30)
        nic = HardwareModel.objects.get(slug='local-generic-2-port-10gbe-sfp-nic', kind='module')
        S.install_module(srv, srv.module_bays.get(name='PCIe-Gen3 1'), nic, serial_number='DEMO-NIC-01')
        ap = S.create_device(org, model('ubiquiti-u6-pro'), 'XYZ-AP-01', site=site, room='Corridor',
                             location_detail='Ceiling, outside Office 104', serial_number='DEMO-AP01',
                             asset_tag='XYZ-0005', ip_address='10.99.0.21', status='active')
        ws = S.create_device(org, model('local-generic-workstation-1-rj45-nic'), 'XYZ-WS-104', site=site,
                             room='Office 104', hostname='xyz-ws-104.xyz.example', serial_number='DEMO-WS104',
                             asset_tag='XYZ-0006', ip_address='10.10.0.104', platform='Windows 11', status='active')
        plate = model('local-generic-wall-plate-2-jacks')
        jacks = {}
        for name, room in (('Office 104', 'Office 104'), ('Office 105', 'Office 105'), ('Ceiling AP-1', 'Corridor')):
            jacks[name] = S.create_device(org, plate, name, site=site, room=room, status='active')
        for d in jacks.values():
            for p in d.ports.all():
                p.tech_label = f'Jack {p.label}'
                p.save(update_fields=['tech_label'])

        # Switch port 12: workstation in Office 104 — access VLAN 10, voice 20, PoE on.
        u = S.update_port
        u(port(sw, '1/e12'), {'description': 'Office 104 — workstation', 'mode': 'access',
                              'untagged_vlan': vlans[10], 'voice_vlan': vlans[20], 'admin_state': 'enabled',
                              'configured_speed': 'auto', 'poe_setting': 'auto'})
        # AP uplink: trunk, native 99 (management), tagged 10 + 30 for the SSIDs, PoE on.
        u(port(sw, '1/e24'), {'description': 'XYZ-AP-01 uplink (corridor ceiling)', 'mode': 'trunk',
                              'untagged_vlan': vlans[99], 'admin_state': 'enabled', 'poe_setting': 'auto',
                              'poe_notes': 'Powers XYZ-AP-01'}, tagged=[vlans[10], vlans[30]])
        u(port(sw, '1/g3'), {'description': 'XYZ-FW-01 igc1 (LAN trunk)', 'mode': 'trunk',
                             'untagged_vlan': vlans[99], 'admin_state': 'enabled'},
          tagged=[vlans[10], vlans[20], vlans[30]])
        u(port(sw, '1/g4'), {'description': 'XYZ-SRV-01 Gig-E 1', 'mode': 'access', 'untagged_vlan': vlans[10],
                             'admin_state': 'enabled'})
        for n in range(13, 23):
            u(port(sw, f'1/e{n}'), {'mode': 'access', 'untagged_vlan': vlans[10], 'voice_vlan': vlans[20],
                                    'poe_setting': 'auto', 'description': 'Office drop (unpatched)'})
        u(port(sw, '1/e48'), {'mode': 'access', 'untagged_vlan': vlans[30], 'description': 'Guest kiosk',
                              'poe_setting': 'disabled'})
        u(port(ap, 'Port 1'), {'description': 'Uplink to XYZ-SW-01 1/e24 via PP-01 24', 'mode': 'trunk',
                               'untagged_vlan': vlans[99]}, tagged=[vlans[10], vlans[30]])
        u(port(fw, 'igc1'), {'description': 'LAN trunk to XYZ-SW-01 G3', 'mode': 'trunk', 'untagged_vlan': vlans[99]},
          tagged=[vlans[10], vlans[20], vlans[30]])
        u(port(ws, 'NIC1'), {'description': 'Onboard Ethernet', 'mode': 'access', 'untagged_vlan': vlans[10]})
        LogicalInterface.objects.create(organization=org, device=sw, name='vlan 99', kind='svi', vlan=vlans[99],
                                        ip_addresses='10.99.0.2/24', description='Switch management')

        radios = list(ap.radios.all())
        for ssid, vid, sec in (('XYZ-Staff', 10, 'WPA2-Enterprise'), ('XYZ-Guest', 30, 'WPA2-Personal')):
            s = WirelessSSID.objects.create(organization=org, ssid=ssid, vlan=vlans[vid], security=sec)
            s.radios.set(radios)

        def cable(a, b, **kw):
            return S.connect(org, [a], [b], **kw)
        front = lambda d, n: port(d, n, 'front_port')
        rear = lambda d, n: port(d, n, 'rear_port')
        # The requested path: SW port 12 → PP-01 12 → rear 12 → Office 104 Jack A → workstation.
        cable(port(sw, '1/e12'), front(pp, 'Port 12'), label='C-0012', cable_type='cat6', color='#1c7ed6',
              color_name='blue', length=Decimal('1.0'), length_unit='m')
        cable(rear(pp, 'Port 12'), rear(jacks['Office 104'], 'Jack A'), label='L-104A', cable_type='cat6',
              color='#868e96', color_name='grey (in wall)', length=Decimal('34.5'), length_unit='m',
              description='Permanent link IDF-1 → Office 104')
        cable(front(jacks['Office 104'], 'Jack A'), port(ws, 'NIC1'), label='W-104A', cable_type='cat6',
              color='#adb5bd', color_name='grey', length=Decimal('3.0'), length_unit='m')
        # AP: SW 1/e24 → PP-01 24 → Ceiling AP-1 Jack A → AP.
        cable(port(sw, '1/e24'), front(pp, 'Port 24'), label='C-0024', cable_type='cat6', color='#f08c00',
              color_name='orange', length=Decimal('1.0'), length_unit='m')
        cable(rear(pp, 'Port 24'), rear(jacks['Ceiling AP-1'], 'Jack A'), label='L-AP1', cable_type='cat6a',
              color='#868e96', color_name='grey (plenum)', length=Decimal('22.0'), length_unit='m')
        cable(front(jacks['Ceiling AP-1'], 'Jack A'), port(ap, 'Port 1'), label='W-AP1', cable_type='cat6',
              color='#ffffff', color_name='white', length=Decimal('1.0'), length_unit='m')
        # Office 105 Jack A is wired to PP-01 13 but nothing is patched at either end yet (shows as incomplete).
        cable(rear(pp, 'Port 13'), rear(jacks['Office 105'], 'Jack A'), label='L-105A', cable_type='cat6',
              length=Decimal('36.0'), length_unit='m')
        cable(port(sw, '1/g3'), port(fw, 'igc1'), label='C-FW1', cable_type='cat6', color='#e03131', color_name='red',
              length=Decimal('0.5'), length_unit='m')
        cable(port(sw, '1/g4'), port(srv, 'Gig-E 1'), label='C-SRV1', cable_type='cat6', color='#1c7ed6',
              color_name='blue', length=Decimal('2.0'), length_unit='m')

        self.stdout.write(self.style.SUCCESS(
            f'{DEMO_NAME} ready: {org.hardware_devices.count()} devices, {org.hardware_cables.count()} cables, '
            f'4 VLANs, rack {rack.name}. Switch: /hardware/devices/{sw.pk}/'))
