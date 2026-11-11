"""
Who may open and act on the RMM pages under /integrations/rmm/.

RMM data (devices, software, alerts, console links, connections, sync) is
MSP technician tooling: customer users never see it (see
docs/CLIENT_DATA_PROTECTION.md, "RMM data stay with technicians"). Among
technicians, reading follows the selected customer; changing a connection,
importing, mapping and deleting devices needs an administrator; a sync needs
write access. A device outside the selected customer answers 404, so its
existence isn't confirmed.

Users exercised: a customer Owner, a customer with no membership at all
(no organization in the session), an MSP technician with a read-only
membership ("without access"), an MSP technician who is Owner at every
customer ("with access") and a superuser.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, override_settings

from accounts.models import Membership, Role
from audit.models import AuditLog
from integrations.models import RMMAlert, RMMConnection, RMMDevice, RMMSoftware
from integrations.tests_rmm_association import _Base
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RMMScopeTests(_Base):

    def setUp(self):
        super().setUp()
        self.conn = self.connection('ninjaone')                      # owned by the MSP, multi-customer
        self.conn_a = self.connection('rem0te', scope=RMMConnection.CUSTOMER_SCOPE_SINGLE, owner=self.a)
        self.dev_a = self._device(self.conn, '101', self.a, 'ACME-PC')
        self.dev_b = self._device(self.conn, '201', self.b, 'BOLT-SECRET-PC')
        RMMAlert.objects.create(organization=self.a, connection=self.conn, device=self.dev_a,
                                external_id='al-a', alert_type='disk', message='ACME disk full',
                                severity='warning', status='active', triggered_at=self.dev_a.last_seen)
        RMMSoftware.objects.create(organization=self.a, connection=self.conn, device=self.dev_a, name='AcmeOnlyApp',
                                   vendor='Acme', version='1.0')

        self.customer = User.objects.create_user('scope_cust', 'c@a.test', 'pw')
        Membership.objects.create(user=self.customer, organization=self.a, role=Role.OWNER, is_active=True)
        self.nobody = User.objects.create_user('scope_nobody', 'n@x.test', 'pw')

        self.tech_ro = _make_msp_tech(User.objects.create_user('scope_tech_ro', 'r@msp.test', 'pw'))
        Membership.objects.create(user=self.tech_ro, organization=self.a, role=Role.READONLY, is_active=True)
        self.tech = _make_msp_tech(User.objects.create_user('scope_tech', 't@msp.test', 'pw'))
        for org in (self.msp, self.a, self.b):
            Membership.objects.create(user=self.tech, organization=org, role=Role.OWNER, is_active=True)
        self.root = User.objects.create_superuser('scope_root', 's@msp.test', 'pw')

    def _device(self, conn, ext, org, name):
        from django.utils import timezone
        return RMMDevice.objects.create(
            organization=org, connection=conn, external_id=ext, device_name=name,
            ownership_status=RMMDevice.OWNERSHIP_RESOLVED, last_seen=timezone.now(),
            latitude=1.0, longitude=2.0)

    def login(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        if org is not None:
            s['current_organization_id'] = org.id
        else:
            s['global_view_mode'] = True
        s['2fa_prompted'] = True
        s.save()
        return c

    # -- S1: device delete ---------------------------------------------------

    def test_user_without_organization_cannot_reach_or_delete_any_device(self):
        c = self.login(self.nobody)
        url = f'/integrations/rmm/devices/{self.dev_b.pk}/delete/'
        self.assertIn(c.get(url).status_code, (403, 404))
        self.assertNotContains(c.get(url), 'BOLT-SECRET-PC', status_code=c.get(url).status_code)
        c.post(url)
        self.assertTrue(RMMDevice.objects.filter(pk=self.dev_b.pk).exists())

    def test_customer_owner_cannot_delete_devices(self):
        c = self.login(self.customer, self.a)
        for dev in (self.dev_a, self.dev_b):
            r = c.post(f'/integrations/rmm/devices/{dev.pk}/delete/')
            self.assertIn(r.status_code, (403, 404))
            self.assertTrue(RMMDevice.objects.filter(pk=dev.pk).exists())

    def test_read_only_technician_cannot_delete(self):
        c = self.login(self.tech_ro, self.a)
        self.assertEqual(c.get(f'/integrations/rmm/devices/{self.dev_a.pk}/delete/').status_code, 403)
        self.assertEqual(c.post(f'/integrations/rmm/devices/{self.dev_a.pk}/delete/').status_code, 403)
        self.assertTrue(RMMDevice.objects.filter(pk=self.dev_a.pk).exists())

    def test_admin_technician_device_outside_selected_customer_is_404(self):
        c = self.login(self.tech, self.a)
        self.assertEqual(c.get(f'/integrations/rmm/devices/{self.dev_b.pk}/delete/').status_code, 404)
        self.assertEqual(c.post(f'/integrations/rmm/devices/{self.dev_b.pk}/delete/').status_code, 404)
        self.assertTrue(RMMDevice.objects.filter(pk=self.dev_b.pk).exists())

    def test_global_view_without_customer_finds_nothing_to_delete(self):
        c = self.login(self.root)
        self.assertEqual(c.post(f'/integrations/rmm/devices/{self.dev_b.pk}/delete/').status_code, 404)
        self.assertTrue(RMMDevice.objects.filter(pk=self.dev_b.pk).exists())

    def test_admin_technician_deletes_in_scope_device_and_it_is_audited(self):
        c = self.login(self.tech, self.a)
        self.assertContains(c.get(f'/integrations/rmm/devices/{self.dev_a.pk}/delete/'), 'ACME-PC')
        r = c.post(f'/integrations/rmm/devices/{self.dev_a.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(RMMDevice.objects.filter(pk=self.dev_a.pk).exists())
        log = AuditLog.objects.get(object_type='rmm_device', object_id=self.dev_a.pk,
                                   object_repr__contains='ACME-PC')
        self.assertEqual((log.action, log.user, log.organization), ('delete', self.tech, self.a))
        self.assertEqual(log.extra_data['connection_id'], self.conn.pk)

    def test_connection_owner_can_delete_an_unresolved_device(self):
        stray = RMMDevice.objects.create(connection=self.conn, external_id='999', device_name='STRAY',
                                         ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED)
        c = self.login(self.tech, self.msp)
        self.assertEqual(c.post(f'/integrations/rmm/devices/{stray.pk}/delete/').status_code, 302)
        self.assertFalse(RMMDevice.objects.filter(pk=stray.pk).exists())
        # ...but a customer selected elsewhere doesn't reach it.
        stray2 = RMMDevice.objects.create(connection=self.conn, external_id='998', device_name='STRAY2',
                                          ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED)
        c = self.login(self.tech, self.b)
        self.assertEqual(c.post(f'/integrations/rmm/devices/{stray2.pk}/delete/').status_code, 404)

    # -- S3: customers and the RMM pages -------------------------------------

    def _pages(self):
        d, ca = self.dev_a.pk, self.conn_a.pk
        return [
            ('get', '/integrations/rmm/devices/'),
            ('get', f'/integrations/rmm/devices/{d}/'),
            ('get', f'/integrations/rmm/devices/{d}/open/'),
            ('get', f'/integrations/rmm/devices/{d}/delete/'),
            ('post', f'/integrations/rmm/devices/{d}/decide/'),
            ('get', '/integrations/rmm/alerts/'),
            ('get', '/integrations/rmm/software/'),
            ('get', '/integrations/rmm/device-map-data/'),
            ('get', '/integrations/rmm/global-device-map-data/'),
            ('get', '/integrations/rmm/create/'),
            ('get', f'/integrations/rmm/{ca}/'),
            ('get', f'/integrations/rmm/{ca}/edit/'),
            ('get', f'/integrations/rmm/{ca}/delete/'),
            ('post', f'/integrations/rmm/{ca}/sync/'),
            ('post', f'/integrations/rmm/{ca}/pairing/check/'),
            ('get', f'/integrations/rmm/{ca}/import-clients/'),
            ('get', f'/integrations/rmm/{ca}/map-organizations/'),
            ('get', f'/integrations/rmm/{ca}/review/'),
        ]

    def test_customer_owner_is_refused_every_rmm_page(self):
        c = self.login(self.customer, self.a)
        with mock.patch('integrations.sync.RMMSync.sync_all') as sync:
            for method, url in self._pages():
                r = getattr(c, method)(url)
                self.assertEqual(r.status_code, 403, f'{method.upper()} {url} -> {r.status_code}')
                for secret in ('ACME-PC', 'ACME disk full', 'AcmeOnlyApp', 'BOLT-SECRET-PC'):
                    self.assertNotIn(secret, r.content.decode(), url)
            sync.assert_not_called()
        self.assertTrue(RMMConnection.objects.filter(pk=self.conn_a.pk).exists())
        self.assertTrue(RMMDevice.objects.filter(pk=self.dev_a.pk).exists())

    def test_customer_cannot_change_or_delete_their_own_connection(self):
        c = self.login(self.customer, self.a)
        self.assertEqual(c.post(f'/integrations/rmm/{self.conn_a.pk}/delete/').status_code, 403)
        self.assertTrue(RMMConnection.objects.filter(pk=self.conn_a.pk).exists())
        r = c.post(f'/integrations/rmm/{self.conn_a.pk}/edit/', {'name': 'hijacked'})
        self.assertEqual(r.status_code, 403)
        self.conn_a.refresh_from_db()
        self.assertNotEqual(self.conn_a.name, 'hijacked')

    def test_customer_without_membership_is_refused_too(self):
        c = self.login(self.nobody)
        for method, url in self._pages():
            r = getattr(c, method)(url)
            self.assertIn(r.status_code, (403, 404), f'{method.upper()} {url} -> {r.status_code}')

    def test_read_only_technician_reads_but_does_not_change(self):
        c = self.login(self.tech_ro, self.a)
        self.assertContains(c.get('/integrations/rmm/devices/'), 'ACME-PC')
        self.assertNotContains(c.get('/integrations/rmm/devices/'), 'BOLT-SECRET-PC')
        self.assertContains(c.get(f'/integrations/rmm/devices/{self.dev_a.pk}/'), 'ACME-PC')
        self.assertEqual(c.get(f'/integrations/rmm/devices/{self.dev_b.pk}/').status_code, 404)
        self.assertContains(c.get('/integrations/rmm/alerts/'), 'ACME disk full')
        self.assertContains(c.get('/integrations/rmm/software/'), 'AcmeOnlyApp')
        self.assertEqual(c.get('/integrations/rmm/device-map-data/').json()['features'][0]['properties']['name'],
                         'ACME-PC')
        with mock.patch('integrations.sync.RMMSync.sync_all') as sync:
            self.assertEqual(c.post(f'/integrations/rmm/{self.conn_a.pk}/sync/').status_code, 403)
            sync.assert_not_called()
        for url in (f'/integrations/rmm/{self.conn_a.pk}/edit/', f'/integrations/rmm/{self.conn_a.pk}/delete/',
                    f'/integrations/rmm/{self.conn_a.pk}/import-clients/',
                    f'/integrations/rmm/{self.conn_a.pk}/map-organizations/'):
            self.assertEqual(c.get(url).status_code, 403, url)
        self.assertEqual(c.post(f'/integrations/rmm/devices/{self.dev_a.pk}/decide/',
                                {'action': 'leave_unlinked'}).status_code, 403)

    def test_admin_technician_and_superuser_use_the_pages(self):
        for user in (self.tech, self.root):
            c = self.login(user, self.a)
            for url in ('/integrations/rmm/devices/', f'/integrations/rmm/devices/{self.dev_a.pk}/',
                        '/integrations/rmm/alerts/', '/integrations/rmm/software/',
                        '/integrations/rmm/device-map-data/', '/integrations/rmm/global-device-map-data/',
                        f'/integrations/rmm/{self.conn_a.pk}/', f'/integrations/rmm/{self.conn_a.pk}/edit/',
                        f'/integrations/rmm/{self.conn_a.pk}/delete/', f'/integrations/rmm/{self.conn_a.pk}/review/',
                        f'/integrations/rmm/{self.conn_a.pk}/map-organizations/',
                        f'/integrations/rmm/devices/{self.dev_a.pk}/delete/'):
                self.assertEqual(c.get(url).status_code, 200, f'{user.username} {url}')
            with mock.patch('integrations.sync.RMMSync.sync_all', return_value={
                    'devices': {'created': 0, 'updated': 0}, 'alerts': {'created': 0},
                    'software': {'created': 0}}) as sync:
                self.assertEqual(c.post(f'/integrations/rmm/{self.conn_a.pk}/sync/').status_code, 302)
                sync.assert_called_once()
            # Still bounded by the selected customer.
            self.assertEqual(c.get(f'/integrations/rmm/devices/{self.dev_b.pk}/').status_code, 404)
            self.assertEqual(c.get(f'/integrations/rmm/{self.conn.pk}/').status_code, 404)
