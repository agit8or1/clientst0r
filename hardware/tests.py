"""Hardware catalog & visual inventory tests."""
import io
import json
import re
import tempfile
import textwrap
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from monitoring.models import Rack, VLAN, VLANGroup

from . import connectors as C
from . import services as S
from .catalog_import import Importer, finish_job, list_files, start_job
from .layout import get_layout, save_layout
from .local_models import ensure_local_models
from .models import (
    Cable, CableTermination, ComponentTemplate, DevicePort, HardwareDevice, HardwareModel, LabelTemplate,
    Manufacturer, PortMapping,
)

TEST_MIDDLEWARE = [m for m in settings.MIDDLEWARE if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


def make_model(name, components, manufacturer='TestCo', u=1, mappings=(), **kw):
    m, _ = Manufacturer.objects.get_or_create(name=manufacturer, defaults={'slug': manufacturer.lower()})
    hm = HardwareModel.objects.create(manufacturer=m, model=name, slug=name.lower().replace(' ', '-'),
                                      u_height=Decimal(u), **kw)
    for i, (cls, cname, t) in enumerate(components, 1):
        eff, conn = C.classify(cls, t)
        ComponentTemplate.objects.create(hardware_model=hm, component_class=eff, name=cname, type=t,
                                         connector=conn, sort_order=i, label=re.sub(r'\D', '', cname))
    from .models import PortMappingTemplate
    for f, r in mappings:
        PortMappingTemplate.objects.create(
            hardware_model=hm, front_port=hm.components.get(component_class=C.CLASS_FRONT_PORT, name=f),
            rear_port=hm.components.get(component_class=C.CLASS_REAR_PORT, name=r))
    return hm


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org A', slug='org-a')
        cls.other = Organization.objects.create(name='Org B', slug='org-b')
        cls.switch = make_model('SW8', [(C.CLASS_INTERFACE, f'p{i}', '1000base-t') for i in range(1, 9)]
                                + [(C.CLASS_INTERFACE, 'sfp1', '10gbase-x-sfpp'), (C.CLASS_POWER_PORT, 'PSU', 'iec-60320-c14'),
                                   (C.CLASS_INTERFACE, 'vlan1', 'virtual'), (C.CLASS_INTERFACE, 'wlan0', 'ieee802.11ax')])
        cls.panel = make_model('PP4', [(C.CLASS_FRONT_PORT, f'Port {i}', '8p8c') for i in range(1, 5)]
                               + [(C.CLASS_REAR_PORT, f'Port {i}', '8p8c') for i in range(1, 5)],
                               mappings=[(f'Port {i}', f'Port {i}') for i in range(1, 5)])
        cls.fiber = make_model('LC2', [(C.CLASS_FRONT_PORT, 'F1', 'lc'), (C.CLASS_REAR_PORT, 'R1', 'lc')],
                               mappings=[('F1', 'R1')])
        cls.ws = make_model('WS', [(C.CLASS_INTERFACE, 'nic1', '1000base-t')], u=0)

    def dev(self, hm, name, org=None):
        return S.create_device(org or self.org, hm, name)

    def port(self, d, name, cls=None):
        qs = d.ports.filter(name=name)
        return (qs.filter(component_class=cls) if cls else qs).get()


class InstantiationTests(Fixture):
    def test_components_dispatch_to_the_right_tables(self):
        d = self.dev(self.switch, 'sw1')
        self.assertEqual(d.ports.filter(component_class=C.CLASS_INTERFACE).count(), 9)
        self.assertEqual(d.ports.filter(component_class=C.CLASS_POWER_PORT).count(), 1)
        self.assertEqual(d.logical_interfaces.count(), 1, 'virtual interfaces are not cable ports')
        self.assertEqual(d.radios.count(), 1, 'radios are not cable ports')
        self.assertFalse(d.ports.filter(name__in=['vlan1', 'wlan0']).exists())
        self.assertEqual(d.asset.organization, self.org)

    def test_passive_mappings_are_copied(self):
        d = self.dev(self.panel, 'pp1')
        self.assertEqual(PortMapping.objects.filter(device=d).count(), 4)

    def test_clone_does_not_copy_identity_or_cables(self):
        a = self.dev(self.switch, 'sw1')
        a.asset.serial_number, a.asset.asset_tag, a.asset.ip_address = 'SN1', 'TAG1', '10.0.0.1'
        a.asset.save()
        b = self.dev(self.ws, 'ws1')
        S.connect(self.org, [self.port(a, 'p1')], [self.port(b, 'nic1')], label='C1')
        v = VLAN.objects.create(organization=self.org, vlan_id=10, name='Staff')
        S.update_port(self.port(a, 'p2'), {'mode': 'access', 'untagged_vlan': v})
        c = S.clone_device(a, 'sw2')
        self.assertEqual((c.asset.serial_number, c.asset.asset_tag, c.asset.ip_address), ('', '', None))
        self.assertFalse(c.ports.filter(cable_termination__isnull=False).exists())
        self.assertEqual(self.port(c, 'p2').untagged_vlan, v)
        self.assertNotEqual(c.public_id, a.public_id)


class TemplateUpdateTests(Fixture):
    def test_port_ids_and_cables_survive_rename_and_additions(self):
        a = self.dev(self.switch, 'sw1')
        b = self.dev(self.ws, 'ws1')
        p1 = self.port(a, 'p1')
        p1.description = 'uplink'
        p1.save()
        cable = S.connect(self.org, [p1], [self.port(b, 'nic1')], label='C1')
        tpl = self.switch.components.get(name='p1')
        tpl.name, tpl.label = 'GigabitEthernet1/0/1', '1'
        tpl.save()
        ComponentTemplate.objects.create(hardware_model=self.switch, component_class=C.CLASS_INTERFACE, name='p9',
                                         type='1000base-t', connector='rj45', sort_order=99)
        self.switch.components.filter(name='p8').delete()
        self.switch.revision += 1
        self.switch.save()
        a.refresh_from_db()
        self.assertTrue(a.template_outdated)
        diff = S.template_diff(a)
        self.assertEqual([t.name for t in diff.add], ['p9'])
        self.assertEqual([p.name for p in diff.orphaned], ['p8'])
        # Preview did not change anything.
        self.assertTrue(DevicePort.objects.filter(pk=p1.pk, name='p1').exists())
        S.apply_template_update(a)
        p1_after = DevicePort.objects.get(pk=p1.pk)
        self.assertEqual(p1_after.name, 'GigabitEthernet1/0/1')
        self.assertEqual(p1_after.description, 'uplink', 'technician data untouched')
        self.assertEqual(p1_after.cable_termination.cable, cable, 'cable still attached to the same port id')
        self.assertTrue(a.ports.filter(name='p8').exists(), 'removed-upstream ports are kept, not deleted')
        self.assertTrue(a.ports.filter(name='p9').exists())
        a.refresh_from_db()
        self.assertFalse(a.template_outdated)


class CableRuleTests(Fixture):
    def setUp(self):
        self.sw = self.dev(self.switch, 'sw1')
        self.pp = self.dev(self.panel, 'pp1')
        self.wsd = self.dev(self.ws, 'ws1')

    def test_occupancy(self):
        S.connect(self.org, [self.port(self.sw, 'p1')], [self.port(self.pp, 'Port 1', 'front_port')])
        with self.assertRaisesRegex(ValidationError, 'already has cable'):
            S.connect(self.org, [self.port(self.sw, 'p1')], [self.port(self.pp, 'Port 2', 'front_port')])

    def test_cross_tenant_cable_refused(self):
        foreign = self.dev(self.ws, 'theirs', org=self.other)
        with self.assertRaisesRegex(ValidationError, 'different clients'):
            S.connect(self.org, [self.port(self.sw, 'p1')], [self.port(foreign, 'nic1')])

    def test_incompatible_connectors_refused(self):
        lc = self.dev(self.fiber, 'lc1')
        with self.assertRaisesRegex(ValidationError, 'cannot share a cable'):
            S.connect(self.org, [self.port(self.sw, 'p1')], [self.port(lc, 'F1', 'front_port')])
        with self.assertRaisesRegex(ValidationError, 'power'):
            S.connect(self.org, [self.port(self.sw, 'PSU')], [self.port(self.wsd, 'nic1')])
        with self.assertRaisesRegex(ValidationError, 'does not fit'):
            S.connect(self.org, [self.port(self.sw, 'p1')], [self.port(self.wsd, 'nic1')], cable_type='smf')
        # A cage takes fibre.
        S.connect(self.org, [self.port(self.sw, 'sfp1')], [self.port(lc, 'F1', 'front_port')], cable_type='mmf')

    def test_combo_ports_are_exclusive(self):
        DevicePort.objects.filter(device=self.sw, name__in=['p8', 'sfp1']).update(combo_group='g8')
        S.connect(self.org, [self.port(self.sw, 'p8')], [self.port(self.wsd, 'nic1')])
        other_ws = self.dev(self.fiber, 'lc2')
        with self.assertRaisesRegex(ValidationError, 'combo'):
            S.connect(self.org, [self.port(self.sw, 'sfp1')], [self.port(other_ws, 'F1', 'front_port')])

    def test_breakout_lane_cannot_be_cabled(self):
        parent = self.port(self.sw, 'sfp1')
        lane = DevicePort.objects.create(organization=self.org, device=self.sw, component_class=C.CLASS_INTERFACE,
                                         name='sfp1:1', connector='sfp', breakout_parent=parent)
        with self.assertRaisesRegex(ValidationError, 'breakout lane'):
            S.connect(self.org, [lane], [self.port(self.wsd, 'nic1')])

    def test_label_unique_per_client_only(self):
        S.connect(self.org, [self.port(self.sw, 'p1')], [self.port(self.wsd, 'nic1')], label='C-1')
        with self.assertRaisesRegex(ValidationError, 'already used'):
            S.connect(self.org, [self.port(self.sw, 'p2')], [self.port(self.pp, 'Port 1', 'front_port')], label='C-1')
        a, b = self.dev(self.switch, 'x', org=self.other), self.dev(self.ws, 'y', org=self.other)
        S.connect(self.other, [self.port(a, 'p1')], [self.port(b, 'nic1')], label='C-1')


class TraceTests(Fixture):
    def test_full_path_both_directions(self):
        sw, pp, jack, ws = (self.dev(self.switch, 'sw'), self.dev(self.panel, 'pp'), self.dev(self.panel, 'jack'),
                            self.dev(self.ws, 'ws'))
        f = lambda d, n: self.port(d, n, 'front_port')
        r = lambda d, n: self.port(d, n, 'rear_port')
        S.connect(self.org, [self.port(sw, 'p1')], [f(pp, 'Port 1')])
        S.connect(self.org, [r(pp, 'Port 1')], [r(jack, 'Port 2')])
        S.connect(self.org, [f(jack, 'Port 2')], [self.port(ws, 'nic1')])
        res = S.trace(self.port(sw, 'p1'))
        self.assertEqual(res.status, 'complete', res.problems)
        self.assertEqual([str(p) for p in res.ports][-1], 'ws / nic1')
        back = S.trace(self.port(ws, 'nic1'))
        self.assertEqual(back.ports[-1], self.port(sw, 'p1'))
        mid = S.trace(r(pp, 'Port 1'))
        self.assertEqual(mid.status, 'complete')
        self.assertEqual({mid.ports[0], mid.ports[-1]}, {self.port(sw, 'p1'), self.port(ws, 'nic1')})

    def test_incomplete_path_names_the_gap(self):
        sw, pp = self.dev(self.switch, 'sw'), self.dev(self.panel, 'pp')
        S.connect(self.org, [self.port(sw, 'p1')], [self.port(pp, 'Port 1', 'front_port')])
        res = S.trace(self.port(sw, 'p1'))
        self.assertEqual(res.status, 'incomplete')
        self.assertTrue(any('Port 1' in p and 'no cable' in p for p in res.problems))

    def test_cycle_terminates(self):
        """Two panels cabled rear-to-rear and front-to-front form a loop; tracing stops."""
        a, b = self.dev(self.panel, 'a'), self.dev(self.panel, 'b')
        f = lambda d, n: self.port(d, n, 'front_port')
        r = lambda d, n: self.port(d, n, 'rear_port')
        S.connect(self.org, [r(a, 'Port 1')], [r(b, 'Port 1')])
        S.connect(self.org, [f(b, 'Port 1')], [f(a, 'Port 1')])
        res = S.trace(f(a, 'Port 1'))
        self.assertEqual(res.status, 'loop')
        self.assertLess(len(res.steps), 20)


class VlanTests(Fixture):
    def test_vlan_numbers_are_scoped_per_client(self):
        VLAN.objects.create(organization=self.org, vlan_id=10, name='Staff')
        VLAN.objects.create(organization=self.other, vlan_id=10, name='Unrelated')   # allowed
        g1 = VLANGroup.objects.create(organization=self.org, name='Site 1')
        g2 = VLANGroup.objects.create(organization=self.org, name='Site 2')
        VLAN.objects.create(organization=self.org, vlan_id=20, name='a', vlan_group=g1)
        VLAN.objects.create(organization=self.org, vlan_id=20, name='b', vlan_group=g2)
        with self.assertRaises(ValidationError):
            VLAN(organization=self.org, vlan_id=10, name='dup').validate_constraints()

    def test_port_vlan_rules(self):
        sw = self.dev(self.switch, 'sw')
        mine = VLAN.objects.create(organization=self.org, vlan_id=10, name='Staff')
        theirs = VLAN.objects.create(organization=self.other, vlan_id=10, name='Theirs')
        voice = VLAN.objects.create(organization=self.org, vlan_id=20, name='Voice')
        p = self.port(sw, 'p1')
        with self.assertRaisesRegex(ValidationError, 'different client'):
            S.update_port(p, {'mode': 'access', 'untagged_vlan': theirs})
        with self.assertRaisesRegex(ValidationError, 'no tagged'):
            S.update_port(p, {'mode': 'access', 'untagged_vlan': mine}, tagged=[voice])
        with self.assertRaisesRegex(ValidationError, 'both native'):
            S.update_port(p, {'mode': 'trunk', 'untagged_vlan': mine}, tagged=[mine])
        S.update_port(p, {'mode': 'trunk', 'untagged_vlan': mine}, tagged=[voice])
        self.assertEqual(list(p.tagged_memberships.values_list('vlan__vlan_id', flat=True)), [20])
        with self.assertRaisesRegex(ValidationError, 'network interfaces'):
            S.update_port(self.port(sw, 'PSU'), {'untagged_vlan': mine})

    def test_site_scoped_group(self):
        from locations.models import Location
        site = Location.objects.create(organization=self.org, name='HQ', street_address='1 A St', city='X',
                                       postal_code='1')
        g = VLANGroup.objects.create(organization=self.org, name='HQ only', site=site)
        v = VLAN.objects.create(organization=self.org, vlan_id=30, name='hq', vlan_group=g)
        sw = self.dev(self.switch, 'sw')
        with self.assertRaisesRegex(ValidationError, 'scoped to another site'):
            S.update_port(self.port(sw, 'p1'), {'mode': 'access', 'untagged_vlan': v})
        sw.site = site
        sw.save()
        S.update_port(self.port(sw, 'p1'), {'mode': 'access', 'untagged_vlan': v})

    def test_vlan_diagram_device_nodes_carry_artwork(self):
        # v3.17.632: device nodes lacked 'thumb', so the page requested ".../undefined".
        from hardware.diagrams import vlan_data
        v = VLAN.objects.create(organization=self.org, vlan_id=10, name='Staff')
        sw = self.dev(self.switch, 'sw')
        S.update_port(self.port(sw, 'p1'), {'mode': 'access', 'untagged_vlan': v})
        devices = [n for n in vlan_data(self.org)['nodes'] if n['kind'] == 'device']
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices[0]['thumb'].startswith(f'/hardware/catalog/models/{self.switch.pk}/art/front.svg'))


class ModuleTests(Fixture):
    def test_install_and_remove_module(self):
        chassis = make_model('SRV', [(C.CLASS_INTERFACE, 'eth0', '1000base-t'), (C.CLASS_MODULE_BAY, 'Slot 1', '')])
        ComponentTemplate.objects.filter(hardware_model=chassis, name='Slot 1').update(bay_position='1')
        nic = make_model('NIC2', [(C.CLASS_INTERFACE, 'nic{module}-p1', '10gbase-x-sfpp'),
                                  (C.CLASS_INTERFACE, 'nic{module}-p2', '10gbase-x-sfpp')], u=0,
                         kind=HardwareModel.KIND_MODULE)
        srv = self.dev(chassis, 'srv')
        bay = srv.module_bays.get()
        mod = S.install_module(srv, bay, nic)
        self.assertEqual(sorted(srv.ports.filter(module=mod).values_list('name', flat=True)), ['nic1-p1', 'nic1-p2'])
        other_srv = self.dev(chassis, 'srv2')
        self.assertEqual(other_srv.ports.count(), 1, 'same chassis, different configuration')
        with self.assertRaisesRegex(ValidationError, 'already holds'):
            S.install_module(srv, bay, nic)
        ws = self.dev(self.fiber, 'lc')
        S.connect(self.org, [srv.ports.get(name='nic1-p1')], [self.port(ws, 'F1', 'front_port')])
        with self.assertRaisesRegex(ValidationError, 'Disconnect'):
            S.remove_module(mod)


class ArtworkAlignmentTests(Fixture):
    def test_every_hit_target_matches_its_element_and_a_component(self):
        ensure_local_models()
        for hm in [HardwareModel.objects.get(slug='local-dell-powerconnect-3448p'), self.switch, self.panel]:
            layout = get_layout(hm)
            keys = {str(k) for k in hm.components.values_list('key', flat=True)}
            from .renderer import render_face
            for face_name, face in layout.faces.items():
                svg = render_face(hm, face_name, face)
                for e in face['elements']:
                    self.assertIn(e['key'], keys)
                    m = re.search(r'data-key="%s"[^>]*>.*?<rect class="hw-hit" x="([\d.]+)" y="([\d.]+)" '
                                  r'width="([\d.]+)" height="([\d.]+)"' % e['key'], svg, re.S)
                    self.assertIsNotNone(m, e['name'])
                    for got, want in zip(map(float, m.groups()), (e['x'], e['y'], e['w'], e['h'])):
                        self.assertAlmostEqual(got, float(want), places=2)
                    self.assertLessEqual(e['x'] + e['w'], face['width'] + 0.01)
                    self.assertLessEqual(e['y'] + e['h'], face['height'] + 0.01)

    def test_dell_3448p_layout_and_provenance(self):
        ensure_local_models()
        hm = HardwareModel.objects.get(slug='local-dell-powerconnect-3448p')
        self.assertEqual(hm.spec_provenance, 'manufacturer')
        ifaces = hm.components.filter(component_class=C.CLASS_INTERFACE)
        self.assertEqual(ifaces.filter(type='100base-tx').count(), 48, '48 Fast Ethernet ports, not gigabit')
        self.assertEqual(ifaces.filter(combo_group__gt='').count(), 0, 'the guide documents no combo ports')
        self.assertEqual(sorted(ifaces.filter(name__startswith='1/g').values_list('type', flat=True)),
                         ['1000base-t', '1000base-t', '1000base-x-sfp', '1000base-x-sfp'])
        lay = get_layout(hm)
        self.assertEqual(lay.faces['front']['accuracy'], 'verified')
        self.assertEqual(lay.faces['rear']['accuracy'], 'approximate')
        self.assertEqual(lay.accuracy, 'approximate')
        el = {e['name']: e for e in lay.faces['front']['elements']}
        self.assertLess(el['1/e1']['y'], el['1/e2']['y'], 'odd numbers on the top row')
        self.assertEqual(el['1/e1']['x'], el['1/e2']['x'])
        self.assertGreater(el['1/g1']['x'], el['1/e48']['x'], 'uplinks right of the access ports')

    def test_layout_versions_keep_port_keys(self):
        lay = get_layout(self.switch)
        faces = json.loads(json.dumps(lay.faces))
        faces['front']['elements'][0]['x'] += 1
        new = save_layout(self.switch, faces, accuracy='approximate', bump_model=True)
        self.assertEqual(new.version, lay.version + 1)
        self.assertEqual({e['key'] for e in new.faces['front']['elements']},
                         {e['key'] for e in lay.faces['front']['elements']})


class ImportTests(TestCase):
    def test_laptop_with_wifi_is_not_an_access_point(self):
        # v3.17.632: a Dell Latitude (one NIC + Wi-Fi radio) was inferred as an access point.
        from hardware.catalog_import import ParsedModel, infer_category
        radio = {'component_class': 'wireless', 'connector': '', 'mgmt_only': False}
        nic = {'component_class': 'interface', 'connector': 'rj45', 'mgmt_only': False}
        laptop = ParsedModel(kind='device', manufacturer='Dell', model='Latitude 5540', slug='dell-latitude-5540',
                             fields={}, components=[nic, radio])
        self.assertEqual(infer_category(laptop), 'workstation')
        ap = ParsedModel(kind='device', manufacturer='Acme', model='Air-1', slug='acme-air-1', fields={},
                         components=[nic, radio])
        self.assertEqual(infer_category(ap), 'access_point')

    def test_recategorize_redraws_the_automatic_layout(self):
        from hardware.catalog_import import recategorize
        from hardware.layout import get_layout
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'device-types' / 'Dell').mkdir(parents=True)
            (root / 'device-types' / 'Dell' / 'latitude-9.yaml').write_text(textwrap.dedent('''
                manufacturer: Dell
                model: Latitude 9
                slug: dell-latitude-9
                interfaces:
                  - name: eth0
                    type: 1000base-t
                  - name: wlan0
                    type: ieee802.11ax
            '''))
            self.run_job(root)
        hm = HardwareModel.objects.get(slug='dell-latitude-9')
        self.assertEqual(hm.category, 'workstation')
        HardwareModel.objects.filter(pk=hm.pk).update(category='access_point')   # as an older rule had it
        hm.refresh_from_db()
        get_layout(hm)
        self.assertIn('top', get_layout(hm).faces)
        self.assertEqual(recategorize(), {'access_point→workstation': 1})
        hm.refresh_from_db()
        self.assertNotIn('top', get_layout(hm).faces)

    def _lib(self, root, extra=''):
        (root / 'device-types' / 'Acme').mkdir(parents=True, exist_ok=True)
        (root / 'module-types' / 'Acme').mkdir(parents=True, exist_ok=True)
        (root / 'device-types' / 'Acme' / 'sw-24.yaml').write_text(textwrap.dedent('''
            manufacturer: Acme
            model: SW-24
            slug: acme-sw-24
            u_height: 1
            is_full_depth: true
            front_image: true
            interfaces:
              - name: ge-0/0/1
                type: 1000base-t
                poe_mode: pse
                poe_type: type2-ieee802.3at
              - name: ge-0/0/2
                type: 1000base-t
                bridge: br0
            console-ports:
              - name: con
                type: rj-45
            ''') + extra)
        (root / 'device-types' / 'Acme' / 'broken.yaml').write_text('manufacturer: Acme\nmodel: [unterminated\n')
        (root / 'module-types' / 'Acme' / 'psu.yaml').write_text('manufacturer: Acme\nmodel: PSU-1\nprofile: Power supply\n'
                                                                 'power-ports:\n  - name: in\n    type: iec-60320-c14\n')
        return root

    def run_job(self, root, preview=False):
        job = start_job('testrev', preview=preview)
        Importer(root, job).run(list_files(root), batch_size=1)
        return finish_job(job)

    def test_import_is_idempotent_and_reports_honestly(self):
        root = self._lib(Path(tempfile.mkdtemp()))
        prev = self.run_job(root, preview=True)
        self.assertEqual(prev.counts.get('would_create'), 2)
        self.assertEqual(HardwareModel.objects.count(), 0, 'preview writes nothing')
        j1 = self.run_job(root)
        self.assertEqual((j1.counts.get('created'), j1.counts.get('failed')), (2, 1))
        self.assertEqual(j1.status, 'completed_with_errors')
        hm = HardwareModel.objects.get(slug='acme-sw-24')
        self.assertIn('front_image', hm.unsupported_fields)
        self.assertIn('interfaces.bridge', hm.unsupported_fields)
        self.assertEqual(hm.upstream_data['interfaces'][1]['bridge'], 'br0', 'nothing silently discarded')
        self.assertEqual(hm.components.get(name='ge-0/0/1').poe_type, 'type2-ieee802.3at')
        self.assertEqual(HardwareModel.objects.get(model='PSU-1').category, 'psu')
        keys = set(hm.components.values_list('key', flat=True))
        j2 = self.run_job(root)
        self.assertEqual(j2.counts.get('unchanged'), 2)
        self.assertEqual(HardwareModel.objects.count(), 2, 'no duplicates on re-run')
        self.assertEqual(set(hm.components.values_list('key', flat=True)), keys)

    def test_resume_skips_recorded_files(self):
        root = self._lib(Path(tempfile.mkdtemp()))
        job = start_job('testrev')
        files = list_files(root)
        Importer(root, job).run(files, batch_size=1, limit=1)
        self.assertEqual(job.records.count(), 1)
        Importer(root, job).run(files, batch_size=1)
        self.assertEqual(job.records.count(), len(files))
        self.assertEqual(HardwareModel.objects.filter(slug='acme-sw-24').count(), 1)

    def test_upstream_change_updates_keeps_keys_and_respects_local_edits(self):
        root = self._lib(Path(tempfile.mkdtemp()))
        self.run_job(root)
        hm = HardwareModel.objects.get(slug='acme-sw-24')
        key1 = hm.components.get(name='ge-0/0/1').key
        p = root / 'device-types' / 'Acme' / 'sw-24.yaml'
        p.write_text(p.read_text().replace('console-ports:', 'power-ports:\n  - name: PSU1\n    type: iec-60320-c14\nconsole-ports:'))
        j = self.run_job(root)
        self.assertEqual(j.counts.get('updated'), 1)
        hm.refresh_from_db()
        self.assertEqual(hm.components.get(name='ge-0/0/1').key, key1)
        self.assertEqual(hm.revision, 2)
        hm.locally_modified = True
        hm.save()
        p.write_text(p.read_text().replace('model: SW-24', 'model: SW-24 Rev B'))
        j = self.run_job(root)
        self.assertEqual(j.counts.get('conflict'), 1)
        hm.refresh_from_db()
        self.assertEqual(hm.model, 'SW-24', 'local edits are not overwritten')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewIsolationAndPersistenceTests(Fixture):
    def setUp(self):
        User = get_user_model()
        self.editor = User.objects.create_user('hw_editor', password='x')
        Membership.objects.create(user=self.editor, organization=self.org, role=Role.EDITOR, is_active=True)
        self.reader = User.objects.create_user('hw_reader', password='x')
        Membership.objects.create(user=self.reader, organization=self.org, role=Role.READONLY, is_active=True)
        self.outsider = User.objects.create_user('hw_outsider', password='x')
        Membership.objects.create(user=self.outsider, organization=self.other, role=Role.EDITOR, is_active=True)
        self.sw = self.dev(self.switch, 'sw1')
        self.ws = self.dev(self.ws, 'ws1')
        self.vlan = VLAN.objects.create(organization=self.org, vlan_id=10, name='Staff')

    def login(self, user, org):
        self.client.force_login(user)
        s = self.client.session
        s['current_organization_id'] = org.pk
        s.save()

    def test_patch_panel_mapping_names_both_ends(self):
        # v3.17.633: an unpatched front port listed the panel's own rear port as "patched from".
        pp, jack = self.dev(self.panel, 'pp'), self.dev(self.panel, 'jack')
        f = lambda d, n: self.port(d, n, 'front_port')
        r = lambda d, n: self.port(d, n, 'rear_port')
        S.connect(self.org, [self.port(self.sw, 'p1')], [f(pp, 'Port 1')])
        S.connect(self.org, [r(pp, 'Port 1')], [r(jack, 'Port 2')])
        S.connect(self.org, [f(jack, 'Port 2')], [self.port(self.ws, 'nic1')])
        S.connect(self.org, [r(pp, 'Port 2')], [r(jack, 'Port 1')])   # permanent link, nothing patched
        self.login(self.reader, self.org)
        rows = {row['m'].front_port.name: row for row in
                self.client.get(reverse('hardware:patch_panel', args=[pp.pk])).context['rows']}
        self.assertEqual(rows['Port 1']['near'], self.port(self.sw, 'p1'))
        self.assertEqual(rows['Port 1']['far'], self.port(self.ws, 'nic1'))
        self.assertIsNone(rows['Port 2']['near'])
        self.assertEqual(rows['Port 2']['far'], f(jack, 'Port 1'))
        self.assertIsNone(rows['Port 3']['near'])
        self.assertIsNone(rows['Port 3']['far'])
        used = self.client.get(reverse('hardware:patch_panel', args=[pp.pk]) + '?used=1').context['rows']
        self.assertEqual([row['m'].front_port.name for row in used], ['Port 1', 'Port 2'])

    def test_other_client_cannot_reach_records(self):
        self.login(self.outsider, self.other)
        p = self.port(self.sw, 'p1')
        for url in (reverse('hardware:device_detail', args=[self.sw.pk]), reverse('hardware:api_port', args=[p.pk]),
                    reverse('hardware:api_trace', args=[p.pk]), reverse('hardware:device_art', args=[self.sw.pk, 'front'])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        r = self.client.post(reverse('hardware:api_port', args=[p.pk]), json.dumps({'description': 'x'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 404)
        r = self.client.post(reverse('hardware:api_connect'), json.dumps({'a': [p.pk], 'b': [self.port(self.ws, 'nic1').pk]}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Cable.objects.count(), 0)
        csv = self.client.get(reverse('hardware:export_csv', args=['devices'])).content.decode()
        self.assertNotIn('sw1', csv)
        search = self.client.get(reverse('hardware:search') + '?q=sw1').content.decode()
        self.assertNotIn(f'/hardware/devices/{self.sw.pk}/', search)

    def test_qr_destination_requires_access(self):
        self.login(self.outsider, self.other)
        self.assertEqual(self.client.get(reverse('hardware:qr', args=['d', self.sw.public_id])).status_code, 404)
        self.login(self.editor, self.org)
        r = self.client.get(reverse('hardware:qr', args=['d', self.sw.public_id]))
        self.assertRedirects(r, reverse('hardware:device_detail', args=[self.sw.pk]), fetch_redirect_response=False)

    def test_read_only_user_cannot_edit(self):
        self.login(self.reader, self.org)
        p = self.port(self.sw, 'p1')
        self.assertEqual(self.client.get(reverse('hardware:device_detail', args=[self.sw.pk])).status_code, 200)
        r = self.client.post(reverse('hardware:api_port', args=[p.pk]), json.dumps({'description': 'x'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_port_edit_persists_across_reload(self):
        self.login(self.editor, self.org)
        p = self.port(self.sw, 'p1')
        r = self.client.post(reverse('hardware:api_port', args=[p.pk]), json.dumps({
            'description': 'Office 104', 'mode': 'access', 'untagged_vlan': self.vlan.pk, 'tagged_vlans': []}),
            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        page = self.client.get(reverse('hardware:device_detail', args=[self.sw.pk])).content.decode()
        data = json.loads(re.search(r'<script id="hw-page-data" type="application/json">(.*?)</script>', page, re.S).group(1))
        mine = [x for x in data['ports'] if x['id'] == p.pk][0]
        self.assertEqual((mine['description'], mine['mode'], mine['untagged_vlan']['vid']), ('Office 104', 'access', 10))
        self.assertEqual(mine['oper_state'], 'unknown', 'documentation never fakes link state')

    def test_api_connect_and_trace(self):
        self.login(self.editor, self.org)
        a, b = self.port(self.sw, 'p1'), self.port(self.ws, 'nic1')
        r = self.client.post(reverse('hardware:api_connect'), json.dumps({'a': [a.pk], 'b': [b.pk], 'label': 'C1',
                                                                          'cable_type': 'cat6'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        t = self.client.get(reverse('hardware:api_trace', args=[a.pk])).json()
        self.assertEqual(t['status'], 'complete')
        self.assertEqual(self.client.post(reverse('hardware:api_connect'), json.dumps({'a': [a.pk], 'b': [b.pk]}),
                                          content_type='application/json').status_code, 400)


class LabelAndExportTests(Fixture):
    def test_pdf_page_and_label_dimensions_are_exact(self):
        import fitz
        from . import labels as L
        tpl = LabelTemplate.objects.create(name='t', kind='cable', width_mm=Decimal('38'), height_mm=Decimal('19'),
                                           page_size='label', show_border=True)
        pdf = L.render_pdf(tpl, [L.LabelItem(['C-1', 'SW / 12'])])
        page = fitz.open(stream=pdf, filetype='pdf')[0]
        self.assertAlmostEqual(page.rect.width, 38 * 72 / 25.4, places=1)
        self.assertAlmostEqual(page.rect.height, 19 * 72 / 25.4, places=1)
        sheet = LabelTemplate.objects.create(name='s', kind='port', width_mm=Decimal('25'), height_mm=Decimal('10'),
                                             page_size='letter', columns=7, rows=25, page_margin_left_mm=Decimal('12'),
                                             page_margin_top_mm=Decimal('12'), gap_x_mm=Decimal('2'), show_border=True)
        doc = fitz.open(stream=L.render_pdf(sheet, [L.LabelItem([f'P{i}']) for i in range(3)]), filetype='pdf')
        self.assertAlmostEqual(doc[0].rect.width, 215.9 * 72 / 25.4, places=1)
        rects = [d['rect'] for d in doc[0].get_drawings() if d.get('rect') is not None]
        sizes = {(round(r.width / 72 * 25.4, 1), round(r.height / 72 * 25.4, 1)) for r in rects}
        self.assertIn((25.0, 10.0), sizes)
        first = min(rects, key=lambda r: (r.y0, r.x0))
        self.assertAlmostEqual(first.x0 / 72 * 25.4, 12.0, places=1)
        self.assertAlmostEqual(first.y0 / 72 * 25.4, 12.0, places=1)
        cal = fitz.open(stream=L.calibration_pdf(sheet), filetype='pdf')
        self.assertEqual(cal.page_count, 1)

    def test_qr_contains_only_the_opaque_url(self):
        from . import labels as L
        sw = self.dev(self.switch, 'sw1')

        class Req:
            def build_absolute_uri(self, path):
                return 'https://example.test' + path
        items = L.build_items(self.org, 'device', Req(), devices=[sw.pk], include_qr=True)
        self.assertEqual(items[0].qr, f'https://example.test/hardware/q/d/{sw.public_id}/')
        self.assertEqual(L.build_items(self.other, 'device', Req(), devices=[sw.pk]), [], 'other client sees nothing')

    def test_exports_render(self):
        from .diagrams import graph_svg, rack_svg, connectivity_data, auto_positions
        from .export import svg_to_pdf, svg_to_png
        sw = self.dev(self.switch, 'sw1')
        rack = Rack.objects.create(organization=self.org, name='R1', units=12)
        S.place_in_rack(sw, rack, 5)
        svg = rack_svg(rack, 'front', for_export=True)
        self.assertTrue(svg_to_png(svg).startswith(b'\x89PNG'))
        self.assertTrue(svg_to_pdf(svg).startswith(b'%PDF'))
        data = connectivity_data(self.org)
        g = graph_svg(data, auto_positions(data['nodes'], {}, data['edges']), 'T', 'Org A')
        self.assertIn('generated', g)

    def test_rack_space_rules(self):
        rack = Rack.objects.create(organization=self.org, name='R1', units=4)
        a, b = self.dev(self.switch, 'a'), self.dev(self.switch, 'b')
        S.place_in_rack(a, rack, 2)
        with self.assertRaisesRegex(ValidationError, 'overlaps'):
            S.place_in_rack(b, rack, 2, face='rear')     # full depth occupies both faces
        with self.assertRaisesRegex(ValidationError, 'does not fit'):
            S.place_in_rack(b, rack, 5)
        foreign_rack = Rack.objects.create(organization=self.other, name='R2', units=4)
        with self.assertRaisesRegex(ValidationError, 'different client'):
            S.place_in_rack(b, foreign_rack, 1)
