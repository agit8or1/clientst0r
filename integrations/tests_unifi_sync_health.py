"""UniFi asset sync (scheduled + manual share one implementation) and the
standard integration sync health.

No controller is contacted: the provider is replaced with a mock whose
sync() returns canned controller data.
"""
import copy
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from assets.models import Asset
from audit.models import AuditLog
from core.models import Organization
from integrations import health
from integrations.models import (
    IntegrationSyncHealth, NetworkAssetLink, PSAConnection, UnifiConnection,
)
from integrations.network_assets import (
    apply_unifi_corrections, build_unifi_placement_report, classify_unifi_device,
    import_unifi_assets, resolve_unifi_sites,
)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

API_KEY = 'UNIFI-API-KEY-7f3a9c'
PASSWORD = 'hunter2-controller-pw'

# One controller, two customer sites, each with a gateway, a switch and an AP.
# Device dicts use the shapes the different controller APIs return.
CONTROLLER = {
    'sites': [
        {'id': 'site-hq', 'name': 'HQ', 'devices': [
            {'name': 'HQ-GW', 'model': 'UDM Pro', 'macAddress': 'AA:BB:CC:00:00:01',
             'ipAddress': '10.1.0.1', 'features': ['gateway', 'switching']},
            {'name': 'HQ-SW', 'type': 'usw', 'model': 'US24P250', 'mac': 'aa:bb:cc:00:00:02',
             'serial': 'SW-HQ-1', 'ip': '10.1.0.2'},
            {'name': 'HQ-AP', 'model': 'U6 Pro', 'macAddress': 'aa-bb-cc-00-00-03',
             'features': ['accessPoint']},
        ]},
        {'id': 'site-branch', 'name': 'Branch', 'devices': [
            {'name': 'BR-GW', 'type': 'ugw', 'model': 'USG-3P', 'mac': 'aa:bb:cc:00:00:11'},
            {'name': 'BR-SW', 'productType': 'NETWORK_SWITCH', 'model': 'USW-Lite-8-PoE',
             'mac': 'aabbcc000012', 'serialNumber': 'SW-BR-1'},
            {'name': 'BR-AP', 'productType': 'accessPoint', 'model': 'U7-Pro',
             'mac': 'aa:bb:cc:00:00:13'},
        ]},
    ],
}

EXPECTED = {
    'aa:bb:cc:00:00:01': ('a', 'router'),
    'aa:bb:cc:00:00:02': ('a', 'switch'),
    'aa:bb:cc:00:00:03': ('a', 'wireless_ap'),
    'aa:bb:cc:00:00:11': ('b', 'router'),
    'aa:bb:cc:00:00:12': ('b', 'switch'),
    'aa:bb:cc:00:00:13': ('b', 'wireless_ap'),
}


def fake_provider(data):
    provider = mock.Mock()
    provider.sync.side_effect = lambda: copy.deepcopy(data)
    return provider


class _Base(TestCase):

    def setUp(self):
        self.msp = Organization.objects.create(name='MSP', slug='msp')
        self.cust_a = Organization.objects.create(name='Customer A', slug='cust-a')
        self.cust_b = Organization.objects.create(name='Customer B', slug='cust-b')
        self.conn = UnifiConnection(
            organization=self.msp, name='Shared controller', host='https://10.0.0.1',
            auto_sync_assets=True,
            site_org_map={'site-hq': self.cust_a.pk, 'site-branch': self.cust_b.pk})
        self.conn.set_credentials({'api_key': API_KEY, 'username': 'admin', 'password': PASSWORD})
        self.conn.save()
        self.org_by_letter = {'a': self.cust_a, 'b': self.cust_b}

    def staff_admin(self, username='staffadmin'):
        user = User.objects.create_user(username, password='pw-123456')
        Membership.objects.create(user=user, organization=self.msp, role=Role.ADMIN, is_active=True)
        from psa.tests._base import _make_msp_tech
        _make_msp_tech(user)
        return user

    def customer_admin(self, username='custadmin'):
        user = User.objects.create_user(username, password='pw-123456')
        Membership.objects.create(user=user, organization=self.msp, role=Role.ADMIN, is_active=True)
        return user

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['current_organization_id'] = self.msp.pk
        session.save()

    def assert_correct_assets(self):
        unifi_assets = Asset.objects.filter(manufacturer='Ubiquiti')
        self.assertEqual(unifi_assets.count(), 6, list(unifi_assets.values('name', 'organization__name')))
        for mac, (letter, atype) in EXPECTED.items():
            matches = list(Asset.objects.filter(mac_address__iexact=mac))
            self.assertEqual(len(matches), 1, f'duplicate or missing asset for {mac}')
            self.assertEqual(matches[0].organization, self.org_by_letter[letter], mac)
            self.assertEqual(matches[0].asset_type, atype, mac)
        self.assertFalse(Asset.objects.filter(organization=self.msp).exists())
        self.assertEqual(NetworkAssetLink.objects.filter(connection_id=self.conn.pk).count(), 6)


class ClassificationTests(TestCase):

    def test_device_types_from_each_api_shape(self):
        for device in CONTROLLER['sites'][0]['devices'] + CONTROLLER['sites'][1]['devices']:
            mac = device.get('mac') or device.get('macAddress')
            from integrations.network_assets import normalize_mac
            self.assertEqual(classify_unifi_device(device), EXPECTED[normalize_mac(mac)][1], device['name'])

    def test_unknown_device_is_other(self):
        self.assertEqual(classify_unifi_device({'model': 'Mystery Box'}), 'other')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SharedControllerSyncTests(_Base):
    """One controller serving two customers: scheduled + manual paths agree."""

    def run_scheduled(self):
        with mock.patch('integrations.network_assets.get_unifi_provider',
                        return_value=fake_provider(CONTROLLER)):
            call_command('sync_network_assets', '--force', stdout=mock.MagicMock(), stderr=mock.MagicMock())

    def run_manual(self):
        user = User.objects.filter(username='su').first() or User.objects.create_superuser('su', 's@x.com', 'pw')
        self.login(user)
        resp = self.client.post(reverse('integrations:unifi_import_assets', args=[self.conn.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_scheduled_sync_twice_places_and_types_every_device(self):
        self.run_scheduled()
        self.assert_correct_assets()
        self.run_scheduled()
        self.assert_correct_assets()
        row = IntegrationSyncHealth.objects.get(object_id=self.conn.pk, kind='unifi')
        self.assertEqual(row.status, 'success')
        self.assertEqual((row.created_count, row.failed_count), (0, 0))
        self.assertIsNotNone(row.last_success_at)

    def test_manual_import_twice_matches_scheduled(self):
        self.conn.cached_data = copy.deepcopy(CONTROLLER)
        self.conn.save()
        self.run_manual()
        self.assert_correct_assets()
        self.run_manual()
        self.assert_correct_assets()

    def test_scheduled_then_manual_then_scheduled_no_duplicates(self):
        self.run_scheduled()
        self.conn.refresh_from_db()
        self.run_manual()
        self.run_scheduled()
        self.assert_correct_assets()
        row = IntegrationSyncHealth.objects.get(object_id=self.conn.pk, kind='unifi')
        self.assertEqual(row.created_count, 0)
        self.assertEqual(row.status, 'success')

    def test_existing_asset_in_customer_is_adopted_not_duplicated(self):
        Asset.objects.create(organization=self.cust_a, name='hand made', asset_type='router',
                             mac_address='AA:BB:CC:00:00:01')
        self.run_scheduled()
        self.assert_correct_assets()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UnmappedAndAmbiguousSiteTests(_Base):

    def setUp(self):
        super().setUp()
        self.data = {'sites': [
            {'id': 'site-hq', 'name': 'HQ', 'devices': [
                {'name': 'HQ-AP', 'model': 'U6 Pro', 'mac': 'aa:bb:cc:00:01:01'}]},
            {'id': 'site-new', 'name': 'Warehouse', 'devices': [
                {'name': 'WH-AP', 'model': 'U6 Pro', 'mac': 'aa:bb:cc:00:01:02'}]},
            {'id': 'site-two', 'name': 'Shared Office', 'devices': [
                {'name': 'SO-AP', 'model': 'U6 Pro', 'mac': 'aa:bb:cc:00:01:03'}]},
            {'id': 'dup-1', 'name': 'Default', 'devices': [
                {'name': 'D1-AP', 'model': 'U6 Pro', 'mac': 'aa:bb:cc:00:01:04'}]},
            {'id': 'dup-2', 'name': 'Default', 'devices': [
                {'name': 'D2-AP', 'model': 'U6 Pro', 'mac': 'aa:bb:cc:00:01:05'}]},
        ]}
        self.conn.site_org_map = {
            'site-hq': self.cust_a.pk,
            'site-two': [self.cust_a.pk, self.cust_b.pk],   # >1 customers
            'Default': self.cust_b.pk,                       # by name, but two sites share it
        }
        self.conn.save()

    def test_resolution_statuses(self):
        res = {r.site_name + r.site_id: r.status for r in resolve_unifi_sites(self.conn, self.data['sites'])}
        self.assertEqual(res['HQsite-hq'], 'mapped')
        self.assertEqual(res['Warehousesite-new'], 'unmapped')
        self.assertEqual(res['Shared Officesite-two'], 'ambiguous')
        self.assertEqual(res['Defaultdup-1'], 'ambiguous')
        self.assertEqual(res['Defaultdup-2'], 'ambiguous')

    def test_id_and_name_keys_disagreeing_is_ambiguous(self):
        self.conn.site_org_map = {'site-hq': self.cust_a.pk, 'HQ': self.cust_b.pk}
        [r] = resolve_unifi_sites(self.conn, self.data['sites'][:1])
        self.assertEqual(r.status, 'ambiguous')

    def test_deleted_customer_is_invalid(self):
        self.conn.site_org_map = {'site-hq': 999999}
        [r] = resolve_unifi_sites(self.conn, self.data['sites'][:1])
        self.assertEqual(r.status, 'invalid')

    def test_skipped_sites_import_nothing_and_are_reported(self):
        with mock.patch('integrations.network_assets.get_unifi_provider',
                        return_value=fake_provider(self.data)):
            call_command('sync_network_assets', '--force', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(list(Asset.objects.values_list('mac_address', flat=True)), ['aa:bb:cc:00:01:01'])
        self.assertEqual(Asset.objects.get().organization, self.cust_a)

        row = IntegrationSyncHealth.objects.get(object_id=self.conn.pk, kind='unifi')
        self.assertEqual(row.status, 'partial')
        self.assertEqual(row.created_count, 1)
        self.assertEqual(row.skipped_count, 4)
        sites = {i['site'] for i in row.issues}
        self.assertEqual(sites, {'Warehouse', 'Shared Office', 'Default'})
        self.assertTrue(all('Map site' in i['action'] for i in row.issues))
        self.assertIn('Map site', row.corrective_action)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'partial')

        from integrations.status import connection_status
        self.assertEqual(connection_status(self.conn, row)['state'], 'partial')

    def test_manual_import_result_message_and_settings_page_show_what_to_fix(self):
        self.conn.cached_data = self.data
        self.conn.save()
        self.login(User.objects.create_superuser('su', 's@x.com', 'pw'))
        resp = self.client.post(reverse('integrations:unifi_import_assets', args=[self.conn.pk]), follow=True)
        body = resp.content.decode()
        self.assertIn('needs correcting', body)
        self.assertIn('Warehouse', body)
        self.assertEqual(Asset.objects.count(), 1)

        resp = self.client.get(reverse('integrations:unifi_detail', args=[self.conn.pk]))
        body = resp.content.decode()
        self.assertIn('Site → customer mapping', body)
        self.assertIn('Unmapped', body)
        self.assertIn('Ambiguous', body)
        self.assertIn('skipped by asset sync', body)

    def test_single_site_without_any_mapping_uses_connection_org(self):
        self.conn.site_org_map = {}
        self.conn.save()
        result = import_unifi_assets(self.conn, {'sites': self.data['sites'][:1]})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(Asset.objects.get().organization, self.msp)

    def test_multi_site_without_mapping_imports_nothing(self):
        self.conn.site_org_map = {}
        self.conn.save()
        result = import_unifi_assets(self.conn, self.data)
        self.assertEqual(result['skipped_sites'], 5)
        self.assertFalse(Asset.objects.exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PlacementReportTests(_Base):
    """Pre-seeded damage from earlier syncs is reported, not changed."""

    def setUp(self):
        super().setUp()
        self.conn.cached_data = copy.deepcopy(CONTROLLER)
        self.conn.save()
        # What the old scheduled sync did: everything under the connection's
        # org, every device typed as an AP.
        self.misplaced = Asset.objects.create(organization=self.msp, name='HQ-AP', asset_type='wireless_ap',
                                              mac_address='aa:bb:cc:00:00:03', manufacturer='Ubiquiti')
        self.misclassified = Asset.objects.create(organization=self.cust_a, name='HQ-SW',
                                                  asset_type='wireless_ap', mac_address='aa:bb:cc:00:00:02')
        self.dup_keep = Asset.objects.create(organization=self.cust_b, name='BR-GW', asset_type='router',
                                             mac_address='aa:bb:cc:00:00:11')
        self.dup_extra = Asset.objects.create(organization=self.cust_b, name='BR-GW copy',
                                              asset_type='router', mac_address='AA:BB:CC:00:00:11')

    def snapshot(self):
        return sorted(Asset.objects.values_list('pk', 'organization_id', 'asset_type', 'name'))

    def findings(self):
        return {f['id']: f for f in build_unifi_placement_report(self.conn)['findings']}

    def test_report_detects_each_problem_without_changing_anything(self):
        before = self.snapshot()
        audit_before = AuditLog.objects.count()
        found = self.findings()
        self.assertIn(f'move:{self.misplaced.pk}:{self.cust_a.pk}', found)
        self.assertIn(f'retype:{self.misclassified.pk}:switch', found)
        self.assertIn(f'remove_duplicate:{self.dup_extra.pk}:{self.dup_keep.pk}', found)
        self.assertEqual(len(found), 3, found.keys())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(AuditLog.objects.count(), audit_before)

    def test_report_page_is_read_only_and_staff_admin_only(self):
        before = self.snapshot()
        self.login(self.staff_admin())
        resp = self.client.get(reverse('integrations:unifi_placement_report', args=[self.conn.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'misplaced')
        self.assertContains(resp, 'misclassified')
        self.assertContains(resp, 'duplicate')
        self.assertEqual(self.snapshot(), before)

        self.client.logout()
        self.login(self.customer_admin())
        resp = self.client.get(reverse('integrations:unifi_placement_report', args=[self.conn.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_correction_requires_staff_admin_and_confirmation(self):
        before = self.snapshot()
        ids = list(self.findings())
        url = reverse('integrations:unifi_placement_correct', args=[self.conn.pk])

        self.login(self.customer_admin())
        self.assertEqual(self.client.post(url, {'finding': ids, 'confirm': 'yes'}).status_code, 403)
        self.assertEqual(self.snapshot(), before)

        self.client.logout()
        self.login(self.staff_admin())
        self.client.post(url, {'finding': ids})   # no confirm tick
        self.assertEqual(self.snapshot(), before)

        self.client.post(url, {'finding': ids, 'confirm': 'yes'})
        self.misplaced.refresh_from_db()
        self.misclassified.refresh_from_db()
        self.assertEqual(self.misplaced.organization, self.cust_a)
        self.assertEqual(self.misclassified.asset_type, 'switch')
        self.assertFalse(Asset.objects.filter(pk=self.dup_extra.pk).exists())
        self.assertEqual(self.findings(), {})

        logs = AuditLog.objects.filter(object_type='asset', extra_data__source='unifi')
        by_fix = {}
        for log in logs:
            by_fix.setdefault(log.extra_data['correction'], []).append(log)
        self.assertEqual(by_fix['retype'][0].extra_data['before']['asset_type'], 'wireless_ap')
        self.assertEqual({l.extra_data['before']['organization'] for l in by_fix['move']}, {self.msp.pk})
        self.assertEqual(len(by_fix['move']), 2)  # old and new customer's audit trail
        dup = by_fix['remove_duplicate'][0]
        self.assertEqual(dup.extra_data['before']['name'], 'BR-GW copy')
        self.assertEqual(dup.action, 'delete')
        self.assertTrue(all(l.user is not None for l in logs))

    def test_only_selected_findings_are_applied(self):
        fid = f'retype:{self.misclassified.pk}:switch'
        apply_unifi_corrections(self.conn, [fid, 'move:999:1'], user=None)
        self.misplaced.refresh_from_db()
        self.assertEqual(self.misplaced.organization, self.msp)
        self.assertTrue(Asset.objects.filter(pk=self.dup_extra.pk).exists())

    def test_sync_does_not_silently_fix_existing_assets(self):
        with mock.patch('integrations.network_assets.get_unifi_provider',
                        return_value=fake_provider(CONTROLLER)):
            call_command('sync_network_assets', '--force', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.misplaced.refresh_from_db()
        self.misclassified.refresh_from_db()
        self.assertEqual(self.misplaced.organization, self.msp)
        self.assertEqual(self.misclassified.asset_type, 'wireless_ap')
        self.assertTrue(Asset.objects.filter(pk=self.dup_extra.pk).exists())


class RedactionTests(TestCase):

    def test_patterns(self):
        cases = [
            'GET https://admin:s3cretPW@10.0.0.1:8443/api failed',
            'headers={"Authorization": "Bearer abcdefghijklmnop"}',
            'Authorization: Basic YWRtaW46aHVudGVy',
            'url=https://api.example.com/v1?api_key=TOPSECRET123&page=2',
            "{'password': 'pw-in-dict', 'user': 'bob'}",
            'X-API-KEY: TOPSECRET123',
            'client_secret=TOPSECRET123',
            'token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlLXZhbHVl rejected',
        ]
        for text in cases:
            out = health.redact(text)
            for secret in ('s3cretPW', 'abcdefghijklmnop', 'YWRtaW46aHVudGVy', 'TOPSECRET123',
                           'pw-in-dict', 'eyJhbGciOiJIUzI1NiJ9'):
                self.assertNotIn(secret, out, (text, out))

    def test_keeps_diagnostic_detail(self):
        out = health.redact('HTTPSConnectionPool(host=10.0.0.1, port=8443): Max retries exceeded (401 Unauthorized)')
        self.assertIn('10.0.0.1', out)
        self.assertIn('401', out)

    def test_literal_credential_values(self):
        org = Organization.objects.create(name='R', slug='r')
        conn = UnifiConnection(organization=org, name='c', host='https://10.0.0.1')
        conn.set_credentials({'api_key': API_KEY})
        conn.save()
        self.assertEqual(health.redact_for(conn, f'bad key {API_KEY} here'), 'bad key *** here')

    def test_corrective_actions(self):
        self.assertIn('re-enter', health.suggest_action('401 Client Error: Unauthorized'))
        self.assertIn('Unreachable', health.suggest_action('Max retries exceeded with url: /api'))
        self.assertIn('Verify SSL', health.suggest_action('SSL: CERTIFICATE_VERIFY_FAILED'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class HealthDiagnosticsAreRedactedTests(_Base):

    def failing_provider(self):
        provider = mock.Mock()
        provider.sync.side_effect = ConnectionError(
            f'HTTPSConnectionPool(host=10.0.0.1, port=443): Max retries exceeded with url: '
            f'https://admin:{PASSWORD}@10.0.0.1/proxy?apikey={API_KEY} (Connection refused)')
        return provider

    def test_failed_sync_stores_and_shows_no_credentials(self):
        with mock.patch('integrations.network_assets.get_unifi_provider',
                        return_value=self.failing_provider()):
            call_command('sync_network_assets', '--force', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.conn.refresh_from_db()
        row = IntegrationSyncHealth.objects.get(object_id=self.conn.pk, kind='unifi')
        self.assertEqual(row.status, 'error')
        self.assertIsNone(row.last_success_at)
        for stored in (row.error, row.corrective_action, self.conn.last_error):
            self.assertNotIn(PASSWORD, stored)
            self.assertNotIn(API_KEY, stored)
        self.assertIn('Unreachable', row.corrective_action)
        self.assertIn('Connection refused', row.error)

        self.login(User.objects.create_superuser('su', 's@x.com', 'pw'))
        for url in (reverse('integrations:unifi_detail', args=[self.conn.pk]),
                    reverse('integrations:integration_list')):
            body = self.client.get(url).content.decode()
            self.assertNotIn(PASSWORD, body, url)
            self.assertNotIn(API_KEY, body, url)
        self.assertIn('Unreachable', self.client.get(
            reverse('integrations:unifi_detail', args=[self.conn.pk])).content.decode())

    def test_manual_sync_message_is_redacted(self):
        self.login(User.objects.create_superuser('su', 's@x.com', 'pw'))
        with mock.patch('integrations.network_assets.get_unifi_provider',
                        return_value=self.failing_provider()):
            resp = self.client.get(reverse('integrations:unifi_sync', args=[self.conn.pk]), follow=True)
        body = resp.content.decode()
        self.assertIn('Sync failed', body)
        self.assertNotIn(PASSWORD, body)
        self.assertNotIn(API_KEY, body)

    def test_legacy_stored_error_is_redacted_on_pages(self):
        # Written by a version before redaction existed.
        self.conn.last_sync_status = 'error'
        self.conn.last_error = f'login failed for https://admin:{PASSWORD}@10.0.0.1 key={API_KEY}'
        self.conn.save()
        self.login(User.objects.create_superuser('su', 's@x.com', 'pw'))
        for url in (reverse('integrations:unifi_detail', args=[self.conn.pk]),
                    reverse('integrations:integration_list')):
            body = self.client.get(url).content.decode()
            self.assertNotIn(PASSWORD, body, url)
            self.assertNotIn(API_KEY, body, url)


class PsaRmmHealthTests(TestCase):

    def test_partial_psa_sync_records_counts_and_status(self):
        from integrations.sync import PSASync
        org = Organization.objects.create(name='P', slug='p')
        conn = PSAConnection(organization=org, provider_type='connectwise_manage', name='cw',
                             base_url='https://psa.example.com', sync_companies=True,
                             sync_contacts=False, sync_tickets=False)
        conn.set_credentials({'company_id': 'x', 'public_key': 'p', 'private_key': 'q'})
        conn.save()
        s = PSASync(conn)
        records = [{'external_id': f'c{i}', 'name': f'Co{i}'} for i in range(3)]
        with mock.patch.object(type(s.provider), 'test_connection', return_value=True), \
                mock.patch.object(type(s.provider), 'list_companies', return_value=records), \
                mock.patch.object(PSASync, '_upsert_company', side_effect=ValueError('boom')):
            s.sync_all()
        row = health.get_health_row(conn)
        self.assertEqual(row.status, 'partial')
        self.assertEqual(row.failed_count, 3)
        self.assertEqual(row.kind, 'psa')
        conn.refresh_from_db()
        self.assertEqual(conn.last_sync_status, 'partial')  # legacy field unchanged in meaning

    def test_failed_psa_sync_redacts_last_error(self):
        from integrations.sync import PSASync
        org = Organization.objects.create(name='P2', slug='p2')
        conn = PSAConnection(organization=org, provider_type='connectwise_manage', name='cw2',
                             base_url='https://psa.example.com', sync_companies=True)
        conn.set_credentials({'company_id': 'x', 'public_key': 'pubkey-123', 'private_key': 'privkey-456'})
        conn.save()
        s = PSASync(conn)
        with mock.patch.object(type(s.provider), 'test_connection',
                               side_effect=RuntimeError('401 Unauthorized using privkey-456')):
            with self.assertRaises(RuntimeError):
                s.sync_all()
        conn.refresh_from_db()
        self.assertNotIn('privkey-456', conn.last_error)
        row = health.get_health_row(conn)
        self.assertEqual(row.status, 'error')
        self.assertIn('re-enter', row.corrective_action)

    def test_connection_without_health_row_falls_back_to_legacy_fields(self):
        org = Organization.objects.create(name='P3', slug='p3')
        conn = UnifiConnection.objects.create(organization=org, name='old', host='https://10.0.0.2',
                                              last_sync_status='ok')
        h = health.health_for(conn)
        self.assertEqual(h['status'], 'success')
        self.assertFalse(h['has_counts'])
