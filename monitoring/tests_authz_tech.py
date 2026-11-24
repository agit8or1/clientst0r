"""Roles & permissions program (authz-tech): monitoring writes check the
monitoring_* flag in the record's customer (require_write passed any create
flag), the rack JSON endpoints check them at all, a rack cannot be moved to
another customer through the hidden organization field, and the unscoped
Global View lookups are for MSP staff only."""
import json

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from monitoring.models import Rack, RackDevice, Subnet

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MonitoringFlagTests(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='Mon A', slug='authz-mon-a')
        self.b = Organization.objects.create(name='Mon B', slug='authz-mon-b')
        self.rack = Rack.objects.create(organization=self.a, name='R1', units=42)
        self.device = RackDevice.objects.create(rack=self.rack, name='sw1', start_unit=1, units=1)
        self.subnet = Subnet.objects.create(organization=self.a, name='LAN', network='10.0.0.0/24')
        self.c = Client()

    def _member(self, role, template=None, org=None):
        u = User.objects.create_user(f'authz-mon-{User.objects.count()}', password='pw')
        Membership.objects.create(user=u, organization=self.a, role=role, role_template=template)
        self.c.force_login(u)
        s = self.c.session
        s['2fa_prompted'] = True
        if org is not False:
            s['current_organization_id'] = (org or self.a).id
        s.save()
        return u

    def test_editor_cannot_delete_rack_or_subnet(self):
        # Built-in Editor: monitoring_delete is off (it passed require_write).
        self._member(Role.EDITOR)
        self.assertEqual(self.c.post(f'/monitoring/racks/{self.rack.pk}/delete/').status_code, 403)
        self.assertEqual(self.c.post(f'/monitoring/ipam/subnets/{self.subnet.pk}/delete/').status_code, 403)
        self.assertTrue(Rack.objects.filter(pk=self.rack.pk).exists())
        self.assertTrue(Subnet.objects.filter(pk=self.subnet.pk).exists())

    def test_files_only_role_cannot_create_rack(self):
        role = RoleTemplate.objects.create(name='authz mon files', files_upload=True, files_view=True,
                                           monitoring_view=True, monitoring_create=False)
        self._member(Role.EDITOR, role)
        resp = self.c.post('/monitoring/racks/create/', {'name': 'Sneaky', 'units': 42,
                                                        'organization': self.a.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Rack.objects.filter(name='Sneaky').exists())

    def test_readonly_cannot_delete_rack_device_through_json_api(self):
        self._member(Role.READONLY)
        resp = self.c.delete(f'/monitoring/api/rack-devices/{self.device.pk}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(RackDevice.objects.filter(pk=self.device.pk).exists())

    def test_editor_can_still_move_a_device(self):
        self._member(Role.EDITOR)
        resp = self.c.patch(f'/monitoring/api/rack-devices/{self.device.pk}/',
                            json.dumps({'name': 'sw1-renamed'}), content_type='application/json')
        self.assertNotEqual(resp.status_code, 403)

    def test_rack_cannot_be_moved_to_another_customer(self):
        from monitoring.forms import RackForm
        form = RackForm({'name': 'R1', 'units': 42, 'organization': self.b.pk, 'rack_type': 'full_rack'},
                        instance=self.rack, organization=self.a)
        self.assertFalse(form.is_valid())
        self.assertIn('organization', form.errors)

    def test_customer_without_selected_org_gets_no_global_lookup(self):
        self._member(Role.OWNER, org=False)
        Membership.objects.filter(organization=self.a).update(is_active=False)
        # 404 from the view guard (or a refusal earlier in the middleware).
        for url in (f'/monitoring/racks/{self.rack.pk}/', f'/monitoring/api/racks/{self.rack.pk}/devices/'):
            with self.subTest(url):
                self.assertIn(self.c.get(url).status_code, (302, 403, 404))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PatchPanelTests(TestCase):
    """Patch panels: creating one works again (it passed a removed field), and
    only a role that may edit can rewrite a panel's ports."""

    setUp = MonitoringFlagTests.setUp
    _member = MonitoringFlagTests._member

    def _panel(self):
        from monitoring.models import RackResource
        return RackResource.objects.create(rack=self.rack, name='PP-01', resource_type='patch_panel',
                                           port_count=48, port_configuration={'ports': []})

    def test_create_and_quick_create(self):
        from monitoring.models import RackResource
        self._member(Role.OWNER)
        r = self.c.post('/monitoring/patch-panels/create/', {'rack': self.rack.pk, 'name': 'PP-A',
                                                            'port_count': 24, 'rack_position': 40})
        self.assertEqual(r.status_code, 302, r.content[:300])
        r = self.c.post('/monitoring/patch-panels/quick-create/', {'rack': self.rack.pk, 'count': 2,
                                                                  'port_count': 48, 'start_position': 30,
                                                                  'name_prefix': 'PPQ'})
        self.assertEqual(r.status_code, 302, r.content[:300])
        self.assertEqual(RackResource.objects.filter(resource_type='patch_panel').count(), 3)
        self.assertEqual(RackResource.objects.get(name='PPQ-01').rack_units, 2)

    def test_readonly_can_read_but_not_rewrite_ports(self):
        panel = self._panel()
        self._member(Role.READONLY)
        url = f'/monitoring/api/patch-panels/{panel.pk}/ports/'
        self.assertEqual(self.c.get(url).status_code, 200)
        r = self.c.post(url, json.dumps({'ports': [{'port_number': 1, 'label': 'x'}]}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 403)
        panel.refresh_from_db()
        self.assertEqual(panel.port_configuration, {'ports': []})

    def test_editor_can_rewrite_ports(self):
        panel = self._panel()
        self._member(Role.EDITOR)
        r = self.c.post(f'/monitoring/api/patch-panels/{panel.pk}/ports/',
                        json.dumps({'ports': [{'port_number': 1, 'label': 'Desk 1'}]}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        panel.refresh_from_db()
        self.assertEqual(panel.port_configuration['ports'][0]['label'], 'Desk 1')
