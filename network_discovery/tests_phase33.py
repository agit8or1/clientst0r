"""
Phase 33 (v3.17.557–558) — persistent site collectors, topology, port map.

The collector key is a standing credential, which Phase 32's deliberately is
not. Most of these tests are about the boundary that makes that acceptable: it
reads only its own scan settings and writes only discovery results.
"""
from __future__ import annotations

import json

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from assets.models import Asset
from core.models import Organization
from locations.models import Location
from network_discovery.models import (
    DiscoverySite, NetworkDiscoveryImport, NetworkLink, SwitchPortEntry,
)
from network_discovery.topology import (
    ingest_links, ingest_switch_ports, topology_graph,
)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

CONFIG_URL = '/network-discovery/collector/config/'
RESULTS_URL = '/network-discovery/collector/results/'


class _SiteCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='SiteCo', slug='site-co')
        self.other_org = Organization.objects.create(name='Rival', slug='rival-nd')
        self.location = Location.objects.create(
            organization=self.org, name='HQ')
        self.site, self.key = DiscoverySite.register(
            organization=self.org, location=self.location, name='HQ collector')
        self.client = Client()


class DiscoverySiteTests(_SiteCase):
    def test_the_key_is_stored_hashed(self):
        self.assertNotIn(self.key, self.site.key_hash)
        self.assertEqual(len(self.site.key_hash), 64)

    def test_a_live_site_is_found_by_its_key(self):
        self.assertEqual(DiscoverySite.find_usable(self.key), self.site)

    def test_rotation_kills_the_old_key_immediately(self):
        new_key = self.site.rotate_key()
        self.assertIsNone(DiscoverySite.find_usable(self.key))
        self.assertEqual(DiscoverySite.find_usable(new_key), self.site)

    def test_revocation_kills_the_key(self):
        self.site.revoke()
        self.assertIsNone(DiscoverySite.find_usable(self.key))
        self.assertEqual(self.site.state, 'revoked')

    def test_disabling_stops_it_without_revoking(self):
        self.site.is_enabled = False
        self.site.save(update_fields=['is_enabled'])
        self.assertIsNone(DiscoverySite.find_usable(self.key))
        self.assertEqual(self.site.state, 'disabled')

    def test_an_unknown_key_finds_nothing(self):
        self.assertIsNone(DiscoverySite.find_usable('nope'))
        self.assertIsNone(DiscoverySite.find_usable(''))

    def test_scan_config_carries_no_credentials_or_assets(self):
        """The one read this credential can perform, and it is narrow."""
        Asset.objects.create(organization=self.org, name='Secret server')
        config = self.site.scan_config()
        blob = json.dumps(config)
        self.assertNotIn('Secret server', blob)
        self.assertNotIn('key', config)
        self.assertNotIn('snmp_credential', config)
        self.assertEqual(
            set(config), {'site_id', 'name', 'subnets', 'scan_interval_minutes',
                          'snmp_enabled', 'classify_enabled', 'scan_now'})

    def test_a_fresh_collector_is_not_overdue(self):
        self.assertFalse(self.site.is_overdue)

    def test_overdue_needs_three_missed_intervals(self):
        """A collector a few minutes late because a scan ran long is not a
        problem, and an alert that fires on that gets ignored."""
        self.site.scan_interval_minutes = 60
        self.site.last_seen_at = timezone.now() - timezone.timedelta(hours=2)
        self.site.save()
        self.assertFalse(self.site.is_overdue)
        self.site.last_seen_at = timezone.now() - timezone.timedelta(hours=4)
        self.site.save()
        self.assertTrue(self.site.is_overdue)

    def test_a_revoked_collector_is_never_overdue(self):
        self.site.last_seen_at = timezone.now() - timezone.timedelta(days=30)
        self.site.save()
        self.site.revoke()
        self.assertFalse(self.site.is_overdue)

    def test_requesting_a_scan_sets_the_flag(self):
        self.assertFalse(self.site.scan_pending)
        self.site.request_scan()
        self.assertTrue(self.site.scan_pending)
        self.assertTrue(self.site.scan_config()['scan_now'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CollectorEndpointTests(_SiteCase):
    def _config(self, key=None):
        return self.client.get(
            CONFIG_URL, HTTP_X_DISCOVERY_KEY=key if key is not None else self.key)

    def _results(self, payload, key=None):
        body = dict(payload)
        return self.client.post(
            RESULTS_URL, data=json.dumps(body),
            content_type='application/json',
            HTTP_X_DISCOVERY_KEY=key if key is not None else self.key)

    def test_config_needs_a_valid_key(self):
        self.assertEqual(self._config('nope').status_code, 403)
        self.assertEqual(self._config('').status_code, 403)

    def test_config_returns_the_scan_settings(self):
        resp = self._config()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['config']['site_id'], self.site.pk)

    def test_fetching_config_records_a_check_in(self):
        self._config()
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.last_seen_at)

    def test_a_pending_scan_is_delivered_once(self):
        """Leaving it set would make the collector scan on every fetch
        forever."""
        self.site.request_scan()
        self.assertTrue(self._config().json()['config']['scan_now'])
        self.assertFalse(self._config().json()['config']['scan_now'])

    def test_results_need_a_valid_key(self):
        self.assertEqual(
            self._results({'devices': []}, key='nope').status_code, 403)

    def test_a_revoked_key_is_rejected_on_both_endpoints(self):
        self.site.revoke()
        self.assertEqual(self._config().status_code, 403)
        self.assertEqual(self._results({'devices': []}).status_code, 403)

    def test_results_import_devices_through_the_phase_32_path(self):
        resp = self._results({'devices': [{'ip': '10.0.0.5',
                                           'mac': 'AA-BB-CC-00-00-01'}]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Asset.objects.count(), 1)
        self.assertEqual(NetworkDiscoveryImport.objects.count(), 1)

    def test_results_are_scoped_to_the_sites_org_and_location(self):
        self._results({'devices': [{'ip': '10.0.0.5'}]})
        row = NetworkDiscoveryImport.objects.get()
        self.assertEqual(row.organization, self.org)
        self.assertEqual(row.location, self.location)

    def test_a_payload_cannot_name_another_org(self):
        other_location = Location.objects.create(
            organization=self.other_org, name='Theirs')
        self._results({
            'organization_id': self.other_org.pk,
            'location_id': other_location.pk,
            'devices': [{'ip': '10.0.0.5'}],
        })
        self.assertEqual(
            Asset.objects.filter(organization=self.other_org).count(), 0)

    def test_a_scan_updates_last_scan_at(self):
        self._results({'devices': []})
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.last_scan_at)

    def test_a_dry_run_writes_no_topology(self):
        """A preview that quietly rewired the map would not be a preview."""
        switch = Asset.objects.create(
            organization=self.org, name='sw-1', mac_address='AA-BB-CC-00-00-09')
        self._results({
            'dry_run': True,
            'devices': [],
            'neighbours': [{'local_mac': 'AA-BB-CC-00-00-09',
                            'local_port': 'Gi0/1', 'remote_name': 'ap-1'}],
        })
        self.assertEqual(NetworkLink.objects.count(), 0)
        self.assertTrue(switch.pk)

    def test_oversized_payloads_are_rejected(self):
        from network_discovery.models import MAX_DEVICES_PER_UPLOAD
        resp = self._results(
            {'devices': [{'ip': '10.0.0.1'}] * (MAX_DEVICES_PER_UPLOAD + 1)})
        self.assertEqual(resp.status_code, 413)

    def test_invalid_json_is_rejected(self):
        resp = self.client.post(RESULTS_URL, data='{oops',
                                content_type='application/json',
                                HTTP_X_DISCOVERY_KEY=self.key)
        self.assertEqual(resp.status_code, 400)


class TopologyIngestTests(_SiteCase):
    def setUp(self):
        super().setUp()
        self.switch = Asset.objects.create(
            organization=self.org, name='core-sw', asset_type='switch',
            mac_address='AA-BB-CC-00-00-01')
        self.ap = Asset.objects.create(
            organization=self.org, name='ap-01', asset_type='wireless_ap',
            mac_address='AA-BB-CC-00-00-02')

    def _neighbour(self, **kw):
        base = {'local_mac': 'AA-BB-CC-00-00-01', 'local_port': 'Gi0/1',
                'remote_name': 'ap-01', 'remote_port': 'eth0'}
        base.update(kw)
        return base

    def test_a_neighbour_becomes_a_link(self):
        counts = ingest_links(self.site, [self._neighbour()])
        self.assertEqual(counts['created'], 1)
        link = NetworkLink.objects.get()
        self.assertEqual(link.local_asset, self.switch)

    def test_the_far_end_resolves_to_an_asset_when_known(self):
        ingest_links(self.site, [self._neighbour(
            remote_mac='AA-BB-CC-00-00-02')])
        self.assertEqual(NetworkLink.objects.get().remote_asset, self.ap)

    def test_an_unmanaged_neighbour_is_kept_unresolved(self):
        """"There is something on port 12 we do not manage" is exactly what a
        topology map should show."""
        ingest_links(self.site, [self._neighbour(remote_name='mystery-box')])
        link = NetworkLink.objects.get()
        self.assertIsNone(link.remote_asset)
        self.assertEqual(link.remote_label, 'mystery-box')

    def test_reporting_the_same_link_again_updates_rather_than_duplicates(self):
        """A year of nightly scans must not bury the one link that changed."""
        ingest_links(self.site, [self._neighbour()])
        counts = ingest_links(self.site, [self._neighbour()])
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(NetworkLink.objects.count(), 1)

    def test_a_neighbour_resolved_later_is_filled_in(self):
        ingest_links(self.site, [self._neighbour(remote_name='not-yet-known')])
        Asset.objects.create(
            organization=self.org, name='not-yet-known',
            mac_address='AA-BB-CC-00-00-77')
        ingest_links(self.site, [self._neighbour(remote_name='not-yet-known')])
        self.assertIsNotNone(NetworkLink.objects.get().remote_asset)

    def test_a_link_whose_local_device_is_unknown_is_skipped(self):
        """Without knowing which switch reported it, the edge has no anchor."""
        counts = ingest_links(self.site, [self._neighbour(
            local_mac='FF-FF-FF-FF-FF-FF', local_name='', local_ip='')])
        self.assertEqual(counts['skipped'], 1)
        self.assertEqual(NetworkLink.objects.count(), 0)

    def test_rubbish_entries_are_skipped_not_fatal(self):
        counts = ingest_links(self.site, ['not a dict', None, self._neighbour()])
        self.assertEqual(counts['created'], 1)
        self.assertEqual(counts['skipped'], 2)

    # --- switch ports ---

    def _port(self, **kw):
        base = {'switch_mac': 'AA-BB-CC-00-00-01', 'port': 'Gi0/5',
                'vlan': 10, 'mac': 'AA-BB-CC-00-00-02'}
        base.update(kw)
        return base

    def test_a_bridge_entry_becomes_a_port_row(self):
        counts = ingest_switch_ports(self.site, [self._port()])
        self.assertEqual(counts['created'], 1)
        entry = SwitchPortEntry.objects.get()
        self.assertEqual(entry.switch_asset, self.switch)
        self.assertEqual(entry.device_asset, self.ap)

    def test_one_port_can_hold_many_macs(self):
        """An uplink carries everything behind it — a fact, not a conflict."""
        ingest_switch_ports(self.site, [
            self._port(mac='AA-BB-CC-00-00-02'),
            self._port(mac='AA-BB-CC-00-00-03'),
        ])
        self.assertEqual(SwitchPortEntry.objects.count(), 2)

    def test_repeat_reports_update_rather_than_duplicate(self):
        ingest_switch_ports(self.site, [self._port()])
        counts = ingest_switch_ports(self.site, [self._port()])
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(SwitchPortEntry.objects.count(), 1)

    def test_an_entry_without_a_mac_or_port_is_skipped(self):
        counts = ingest_switch_ports(self.site, [
            self._port(mac=''), self._port(port='')])
        self.assertEqual(counts['skipped'], 2)

    def test_an_unknown_switch_is_skipped(self):
        counts = ingest_switch_ports(self.site, [
            self._port(switch_mac='FF-FF-FF-FF-FF-FF', switch_name='')])
        self.assertEqual(counts['skipped'], 1)

    def test_an_out_of_range_vlan_is_dropped_not_stored(self):
        ingest_switch_ports(self.site, [self._port(vlan=99999)])
        self.assertIsNone(SwitchPortEntry.objects.get().vlan_id)

    def test_an_unknown_device_leaves_the_link_empty_rather_than_guessing(self):
        """A port entry naming the wrong device sends somebody to the wrong
        socket."""
        ingest_switch_ports(self.site, [self._port(mac='11-22-33-44-55-66')])
        self.assertIsNone(SwitchPortEntry.objects.get().device_asset)


class TopologyGraphTests(_SiteCase):
    def setUp(self):
        super().setUp()
        self.switch = Asset.objects.create(
            organization=self.org, name='core-sw', mac_address='AA-BB-CC-00-00-01')
        self.ap = Asset.objects.create(
            organization=self.org, name='ap-01', mac_address='AA-BB-CC-00-00-02')

    def test_an_empty_network_has_no_nodes(self):
        graph = topology_graph(self.org, self.location)
        self.assertEqual(graph['nodes'], [])
        self.assertEqual(graph['edges'], [])

    def test_a_link_produces_two_nodes_and_an_edge(self):
        ingest_links(self.site, [{
            'local_mac': 'AA-BB-CC-00-00-01', 'local_port': 'Gi0/1',
            'remote_mac': 'AA-BB-CC-00-00-02', 'remote_name': 'ap-01'}])
        graph = topology_graph(self.org, self.location)
        self.assertEqual(len(graph['nodes']), 2)
        self.assertEqual(len(graph['edges']), 1)

    def test_an_unresolved_neighbour_is_flagged_not_dropped(self):
        ingest_links(self.site, [{
            'local_mac': 'AA-BB-CC-00-00-01', 'remote_name': 'mystery'}])
        graph = topology_graph(self.org, self.location)
        unresolved = [n for n in graph['nodes'] if not n['resolved']]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]['label'], 'mystery')

    def test_a_stale_link_is_flagged_not_removed(self):
        """A cable that stopped being reported is information; silently
        removing it makes a map that only ever agrees with itself."""
        ingest_links(self.site, [{
            'local_mac': 'AA-BB-CC-00-00-01', 'remote_name': 'ap-01'}])
        link = NetworkLink.objects.get()
        link.last_seen_at = timezone.now() - timezone.timedelta(days=60)
        link.save(update_fields=['last_seen_at'])
        graph = topology_graph(self.org, self.location)
        self.assertTrue(graph['edges'][0]['is_stale'])

    def test_edges_carry_labels_as_well_as_keys(self):
        ingest_links(self.site, [{
            'local_mac': 'AA-BB-CC-00-00-01', 'remote_name': 'ap-01'}])
        edge = topology_graph(self.org, self.location)['edges'][0]
        self.assertEqual(edge['source_label'], 'core-sw')
        self.assertEqual(edge['target_label'], 'ap-01')

    def test_another_organizations_links_do_not_appear(self):
        other_location = Location.objects.create(
            organization=self.other_org, name='Theirs')
        other_site, _ = DiscoverySite.register(
            organization=self.other_org, location=other_location, name='Theirs')
        Asset.objects.create(
            organization=self.other_org, name='their-sw',
            mac_address='DD-EE-FF-00-00-01')
        ingest_links(other_site, [{
            'local_mac': 'DD-EE-FF-00-00-01', 'remote_name': 'their-ap'}])
        graph = topology_graph(self.org, self.location)
        self.assertEqual(graph['nodes'], [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SiteManagementViewTests(_SiteCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            'siteadmin', 's@example.com', 'hunter2xyz')
        self.plain = User.objects.create_user('plainsite', 'p@example.com', 'pw')
        self.client = Client()

    def _base(self):
        return (f'/network-discovery/orgs/{self.org.pk}/'
                f'locations/{self.location.pk}/collectors/')

    def test_anonymous_is_redirected(self):
        self.assertIn(Client().get(self._base()).status_code, (302, 403))

    def test_registering_shows_the_key_once(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self._base() + 'register/',
                                {'name': 'Branch collector'}, follow=True)
        self.assertContains(resp, 'shown once')
        self.assertTrue(DiscoverySite.objects.filter(
            name='Branch collector').exists())

    def test_a_user_without_permission_cannot_register(self):
        self.client.force_login(self.plain)
        self.client.post(self._base() + 'register/', {'name': 'Sneaky'})
        self.assertFalse(DiscoverySite.objects.filter(name='Sneaky').exists())

    def test_duplicate_names_are_refused(self):
        self.client.force_login(self.admin)
        self.client.post(self._base() + 'register/', {'name': 'HQ collector'})
        self.assertEqual(DiscoverySite.objects.filter(
            name='HQ collector').count(), 1)

    def test_rotating_through_the_view(self):
        self.client.force_login(self.admin)
        self.client.post(self._base() + f'{self.site.pk}/rotate/')
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.key_rotated_at)
        self.assertIsNone(DiscoverySite.find_usable(self.key))

    def test_revoking_through_the_view(self):
        self.client.force_login(self.admin)
        self.client.post(self._base() + f'{self.site.pk}/revoke/')
        self.site.refresh_from_db()
        self.assertEqual(self.site.state, 'revoked')

    def test_requesting_a_scan_through_the_view(self):
        self.client.force_login(self.admin)
        self.client.post(self._base() + f'{self.site.pk}/scan-now/')
        self.site.refresh_from_db()
        self.assertTrue(self.site.scan_pending)

    def test_a_revoked_collector_cannot_be_asked_to_scan(self):
        self.client.force_login(self.admin)
        self.site.revoke()
        self.client.post(self._base() + f'{self.site.pk}/scan-now/')
        self.site.refresh_from_db()
        self.assertFalse(self.site.scan_pending)

    def test_topology_page_renders(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            f'/network-discovery/orgs/{self.org.pk}/'
            f'locations/{self.location.pk}/topology/')
        self.assertEqual(resp.status_code, 200)

    def test_port_map_search_by_mac_finds_the_entry(self):
        self.client.force_login(self.admin)
        Asset.objects.create(organization=self.org, name='core-sw',
                             mac_address='AA-BB-CC-00-00-01')
        ingest_switch_ports(self.site, [{
            'switch_mac': 'AA-BB-CC-00-00-01', 'port': 'Gi0/5',
            'mac': 'AA-BB-CC-00-00-42'}])
        resp = self.client.get(
            f'/network-discovery/orgs/{self.org.pk}/'
            f'locations/{self.location.pk}/port-map/?q=aa:bb:cc:00:00:42')
        self.assertContains(resp, 'Gi0/5')
