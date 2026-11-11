"""
Device Workspace data: per-provider field maps (integrations/rmm_fields.py),
opt-in service lists (integrations/rmm_snapshots.py) and the single-device
refresh (integrations/rmm_refresh.py). No real RMM is called: every
provider request is answered by the fixtures below, shaped like each
provider's documented response.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core.models import Organization

from . import rmm_fields, rmm_refresh, rmm_snapshots
from .models import RMMConnection, RMMDevice, RMMDeviceSnapshot
from .providers.rmm import RMM_PROVIDER_REGISTRY
from .rmm_association import set_device_organization
from .sync import RMMSync

BOOT = datetime(2026, 11, 9, 7, 30, tzinfo=dt_timezone.utc)

# --- fixture payloads, as each provider documents them --------------------------

# Tactical RMM GET /agents/ row (AgentTableSerializer).
TRMM_TABLE_ROW = {
    'agent_id': 'aKvTqWzZ1rYxwLmN0pQs', 'hostname': 'FRONTDESK-01', 'site_name': 'Main Office',
    'client_name': 'Alpha Dental', 'monitoring_type': 'workstation', 'description': '', 'needs_reboot': True,
    'status': 'online', 'last_seen': '2026-11-11T08:00:00Z', 'boot_time': BOOT.timestamp(),
    'logged_username': 'ALPHA\\pat', 'italic': False, 'plat': 'windows', 'goarch': 'amd64',
    'has_patches_pending': True, 'version': '2.8.0', 'operating_system': 'Windows 11 Pro, 64 bit (build 22631)',
    'public_ip': '203.0.113.7', 'cpu_model': ['Intel(R) Core(TM) i5-12500, 6C/12T'], 'graphics': 'Intel UHD 770',
    'local_ips': '10.0.0.21, 192.168.56.1', 'make_model': 'Dell Inc. OptiPlex 7000',
    'physical_disks': ['SAMSUNG MZVL2256 238GB NVMe'], 'serial_number': 'ABC1234', 'custom_fields': [],
    'total_ram': 16, 'MACAddress': '00:11:22:33:44:55',
    'disks': [{'device': 'C:', 'fstype': 'NTFS', 'total': '237.5 GB', 'used': '168.2 GB', 'free': '69.3 GB',
               'percent': 71}],
}
# Tactical RMM GET /agents/{agent_id}/ (AgentSerializer): logged_in_username
# is "None" when nobody is signed in; services as the agent last sent them.
TRMM_DETAIL = dict(
    {k: v for k, v in TRMM_TABLE_ROW.items() if k not in ('logged_username', 'italic', 'client_name')},
    client='Alpha Dental', logged_in_username='None', last_logged_in_user='ALPHA\\pat',
    patches_last_installed='2026-11-05T03:12:00Z',
    services=[{'name': 'Spooler', 'display_name': 'Print Spooler', 'status': 'running', 'start_type': 'Automatic',
               'pid': 2212, 'binpath': 'C:\\Windows\\System32\\spoolsv.exe', 'username': 'LocalSystem',
               'description': 'Loads files to memory for later printing', 'autodelay': False},
              {'name': 'wuauserv', 'display_name': 'Windows Update', 'status': 'stopped', 'start_type': 'Manual',
               'pid': 0, 'binpath': '', 'username': 'LocalSystem', 'description': '', 'autodelay': False}],
    wmi_detail={'network_config': [[{'Description': 'Intel(R) Ethernet Connection I219-V', 'IPEnabled': True,
                                     'MACAddress': '00:11:22:33:44:55',
                                     'IPAddress': ['10.0.0.21', 'fe80::1c2d:3e4f:5a6b:7c8d']}],
                                   [{'Description': 'WAN Miniport (IP)', 'IPEnabled': False, 'MACAddress': None}]]},
)

# NinjaOne GET /v2/devices-detailed item.
NINJA_DEVICE = {
    'id': 1042, 'uid': '5c9b7e1a-1111-2222-3333-444455556666', 'organizationId': 7, 'locationId': 12,
    'nodeClass': 'WINDOWS_WORKSTATION', 'offline': False, 'displayName': 'Front desk PC',
    'systemName': 'FRONTDESK-01', 'dnsName': 'frontdesk-01.alpha.local', 'lastContact': 1762848000.0,
    'lastUpdate': 1762847700.0, 'ipAddresses': ['10.0.0.21', 'fe80::1c2d:3e4f:5a6b:7c8d'],
    'macAddresses': ['00:11:22:33:44:55'], 'publicIP': '203.0.113.7', 'lastLoggedInUser': 'ALPHA\\pat',
    'references': {'organization': {'id': 7, 'name': 'Alpha Dental'}, 'location': {'id': 12, 'name': 'Main'}},
    'os': {'manufacturer': 'Microsoft Corporation', 'name': 'Windows 11 Professional Edition',
           'architecture': '64-bit', 'lastBootTime': BOOT.timestamp(), 'buildNumber': '22631', 'releaseId': '23H2',
           'needsReboot': False},
    'system': {'name': 'FRONTDESK-01', 'manufacturer': 'Dell Inc.', 'model': 'OptiPlex 7000',
               'serialNumber': 'ABC1234', 'biosSerialNumber': 'ABC1234'},
    'volumes': [{'name': 'C:', 'label': 'OS', 'deviceType': 'Local Disk', 'fileSystem': 'NTFS',
                 'capacity': 255013216256, 'freeSpace': 74415534080}],
}

# Datto RMM GET /v2/account/devices item (Device schema, API v2).
DATTO_DEVICE = {
    'id': 3301, 'uid': 'f2d1c0b9-aaaa-bbbb-cccc-0123456789ab', 'siteId': 9, 'siteUid': 'site-9',
    'siteName': 'Alpha Dental', 'deviceType': {'category': 'Desktop', 'type': 'Desktop'},
    'hostname': 'FRONTDESK-01', 'intIpAddress': '10.0.0.21', 'operatingSystem': 'Microsoft Windows 11 Pro 22631',
    'lastLoggedInUser': 'ALPHA\\pat', 'domain': 'ALPHA', 'cagVersion': '4.4.2216.2216', 'displayVersion': '4.4.2216',
    'extIpAddress': '203.0.113.7', 'description': '', 'a64Bit': True, 'rebootRequired': True, 'online': True,
    'suspended': False, 'deleted': False, 'lastSeen': 1762848000000, 'lastReboot': int(BOOT.timestamp() * 1000),
    'lastAuditDate': 1762840000000, 'creationDate': 1700000000000, 'snmpEnabled': False, 'deviceClass': 'device',
    'portalUrl': 'https://pinotage.centrastage.net/csm/search?dev=3301', 'warrantyDate': None,
    'antivirus': {'antivirusProduct': 'Microsoft Defender', 'antivirusStatus': 'RunningAndUpToDate'},
    'patchManagement': {'patchStatus': 'ApprovedPending', 'patchesApprovedPending': 3, 'patchesNotApproved': 1,
                        'patchesInstalled': 212},
    'softwareStatus': 'Compliant', 'webRemoteUrl': 'https://pinotage.centrastage.net/csm/remote/3301',
}

# Atera GET /v3/agents item.
ATERA_AGENT = {
    'AgentID': 123456, 'DeviceGuid': '6f0c2a1e-1111-2222-3333-444455556666', 'FolderID': 3, 'CustomerID': 42,
    'CustomerName': 'Alpha Dental', 'AgentName': 'FRONTDESK-01', 'SystemName': 'FRONTDESK-01',
    'MachineName': 'FRONTDESK-01', 'DomainName': 'ALPHA', 'CurrentLoggedUsers': 'ALPHA\\pat',
    'LastPatchManagementReceived': '2026-11-10T22:15:00', 'AgentVersion': '1.8.7.2', 'Online': True,
    'ReportFromIP': '203.0.113.7', 'AppViewUrl': 'https://app.atera.com/new/agent/123456',
    'Vendor': 'Dell Inc.', 'VendorBrandModel': 'OptiPlex 7000', 'VendorSerialNumber': 'ABC1234',
    'MacAddresses': ['00-11-22-33-44-55'], 'IpAddresses': ['10.0.0.21'],
    'HardwareDisks': [{'Drive': 'C:', 'Free': 70966, 'Used': 172234, 'Total': 243200}],
    'LastRebootTime': '2026-11-09T07:30:00Z', 'OSType': 'Work Station', 'OS': 'Microsoft Windows 11 Pro',
    'OSVersion': '10.0.22631', 'LastLoginUser': 'ALPHA\\pat', 'Modified': '2026-11-11T08:00:00Z',
    'LastSeen': '2026-11-11T08:00:00Z',
}

# ConnectWise Automate GET /cwa/api/v1/Computers item.
AUTOMATE_COMPUTER = {
    'Id': 4711, 'ComputerName': 'FRONTDESK-01', 'Client': {'Id': 1, 'Name': 'Alpha Dental'},
    'Location': {'Id': 10, 'Name': 'Main Office'}, 'LocalIPAddress': '10.0.0.21', 'GatewayIPAddress': '10.0.0.1',
    'MacAddress': '00:11:22:33:44:55', 'Status': 'Online', 'Type': 0,
    'OperatingSystemName': 'Microsoft Windows 11 Pro x64', 'RemoteAgentVersion': '2023.10.0.123',
    'RemoteAgentLastContact': '2026-11-11T08:00:00', 'SystemUptime': 2 * 86400 + 3 * 3600, 'IsRebootNeeded': False,
    'WindowsUpdateDate': '2026-11-04T02:00:00', 'SerialNumber': 'ABC1234', 'BIOSManufacturer': 'Dell Inc.',
    'LoggedInUsers': [{'LoggedInUserName': 'ALPHA\\pat', 'ConsoleNumber': 1}], 'LastUserName': 'ALPHA\\pat',
}

# Rem0te GET /api/v1/pub/v1/computers item.
REM0TE_COMPUTER = {
    'id': 'cmtaiwkdb0017za3stnccaho1', 'name': 'FRONTDESK-01', 'hostname': 'FRONTDESK-01', 'status': 'ONLINE',
    'platform': 'Windows', 'osVersion': 'Microsoft Windows NT 10.0.26100.0', 'ipAddress': '10.0.0.21',
    'macAddress': '00:11:22:33:44:55', 'serialNumber': 'ABC1234', 'isOnline': True,
    'lastSeenAt': '2026-11-11T08:00:00.000Z', 'customerId': 'biz-alpha',
    'customer': {'id': 'biz-alpha', 'name': 'Alpha Dental'}, 'site': {'id': 's1', 'name': 'Main office'},
}


class Resp:
    """A requests.Response stand-in."""

    def __init__(self, data, status=200, url='https://rmm.example.test/'):
        import json
        self._data = data
        self.status_code = status
        self.url = url
        self.text = json.dumps(data)
        self.content = self.text.encode()

    def json(self):
        return self._data


def make_conn(org, provider_type, name=None, **kw):
    kw.setdefault('customer_scope', RMMConnection.CUSTOMER_SCOPE_SINGLE)
    conn = RMMConnection.objects.create(organization=org, provider_type=provider_type,
                                        name=name or f'{provider_type} {org.slug}',
                                        base_url='https://rmm.example.test', **kw)
    conn.set_credentials({'api_key': 'k', 'api_secret': 's', 'access_token': 't', 'username': 'u',
                          'password': 'p'})
    conn.save()
    return conn


def device_from(conn, payload, org=None, now=None):
    """Store a payload the way the sync does (provider normalize → raw_data)."""
    norm = RMM_PROVIDER_REGISTRY[conn.provider_type](conn).normalize_device(dict(payload))
    return RMMDevice.objects.create(organization=org or conn.organization, connection=conn,
                                    external_id=norm['external_id'], device_name=norm['device_name'],
                                    raw_data=norm['raw_data'], is_online=True,
                                    data_refreshed_at=now or timezone.now())


class FieldMapTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Alpha Dental', slug='alpha')

    def facts(self, provider_type, payload, **kw):
        return rmm_fields.facts(device_from(make_conn(self.org, provider_type), payload, **kw))

    def test_tactical_table_row(self):
        f = self.facts('tactical_rmm', TRMM_TABLE_ROW)
        self.assertEqual(f['agent_version'], '2.8.0')
        self.assertEqual(f['last_boot'], BOOT)
        self.assertEqual(f['logged_in'], 'ALPHA\\pat')
        self.assertIs(f['reboot'], True)
        self.assertEqual(f['ips'], ['10.0.0.21', '192.168.56.1'])  # comma-separated text in the API
        self.assertEqual(f['public_ip'], '203.0.113.7')
        self.assertEqual(f['disks'][0], {'name': 'C:', 'total': '237.5 GB', 'free': '69.3 GB', 'percent': 71,
                                         'fstype': 'NTFS'})
        self.assertIn(('Patches pending', 'Yes'), f['patch_fields'])
        self.assertEqual(f['nics'], [])  # no wmi_detail in the table row

    def test_tactical_detail_none_sentinel_and_adapters(self):
        f = self.facts('tactical_rmm', TRMM_DETAIL)
        # logged_in_username "None" is nobody; last_logged_in_user is the fallback.
        self.assertEqual(f['logged_in'], 'ALPHA\\pat')
        self.assertEqual(f['last_patched'], datetime(2026, 11, 5, 3, 12, tzinfo=dt_timezone.utc))
        self.assertEqual(f['nics'], [{'name': 'Intel(R) Ethernet Connection I219-V', 'mac': '00:11:22:33:44:55',
                                      'ips': '10.0.0.21, fe80::1c2d:3e4f:5a6b:7c8d'}])
        conn = RMMDevice.objects.get(external_id=TRMM_DETAIL['agent_id']).connection
        nobody = rmm_fields.facts(device_from(conn, dict(TRMM_TABLE_ROW, logged_username='-', agent_id='x2')))
        self.assertIsNone(nobody['logged_in'])

    def test_tactical_numeric_disk_sizes(self):
        f = self.facts('tactical_rmm', dict(TRMM_TABLE_ROW, disks=[
            {'device': 'C:', 'fstype': 'NTFS', 'total': 255013216256, 'free': 74415534080, 'percent': 70.8}]))
        self.assertEqual((f['disks'][0]['total'], f['disks'][0]['free']), ('237.5 GB', '69.3 GB'))

    def test_ninjaone(self):
        f = self.facts('ninjaone', NINJA_DEVICE)
        self.assertIsNone(f['agent_version'])
        self.assertIn('agent version', f['unsupported']['agent_version'])
        self.assertEqual(f['last_boot'], BOOT)
        self.assertIs(f['reboot'], False)
        self.assertEqual(f['logged_in'], 'ALPHA\\pat')
        self.assertEqual(f['public_ip'], '203.0.113.7')
        self.assertEqual(f['ips'], ['10.0.0.21', 'fe80::1c2d:3e4f:5a6b:7c8d'])
        self.assertEqual(f['disks'][0]['name'], 'C:')
        self.assertEqual(f['disks'][0]['total'], '237.5 GB')
        self.assertEqual(f['disks'][0]['percent'], 70.8)
        self.assertIn('nics', f['unsupported'])

    def test_datto(self):
        f = self.facts('datto_rmm', DATTO_DEVICE)
        self.assertEqual(f['agent_version'], '4.4.2216')
        self.assertEqual(f['last_boot'], BOOT)  # epoch milliseconds
        self.assertEqual(f['logged_in'], 'ALPHA\\pat')
        self.assertIs(f['reboot'], True)
        self.assertEqual(f['ips'], ['10.0.0.21'])
        self.assertEqual(f['public_ip'], '203.0.113.7')
        self.assertIn(('Patch status', 'ApprovedPending'), f['patch_fields'])
        self.assertIn(('Approved, pending', '3'), f['patch_fields'])
        self.assertEqual(f['disks'], [])
        self.assertIn('audit', f['unsupported']['disks'])

    def test_atera(self):
        f = self.facts('atera', ATERA_AGENT)
        self.assertEqual(f['agent_version'], '1.8.7.2')
        self.assertEqual(f['last_boot'], BOOT)
        self.assertEqual(f['logged_in'], 'ALPHA\\pat')
        self.assertIsNone(f['reboot'])
        self.assertIn('restart-pending', f['unsupported']['reboot'])
        self.assertEqual(f['disks'][0]['total'], '237.5 GB')  # HardwareDisks are in MB
        self.assertEqual(f['public_ip'], '203.0.113.7')
        self.assertEqual(f['patch_fields'], [('Patch report received', '2026-11-10T22:15:00')])

    def test_connectwise_automate(self):
        now = timezone.now()
        f = self.facts('connectwise_automate', AUTOMATE_COMPUTER, now=now)
        self.assertEqual(f['agent_version'], '2023.10.0.123')
        self.assertEqual(f['last_boot'], now - timedelta(days=2, hours=3))  # SystemUptime as of the read
        self.assertEqual(f['logged_in'], 'ALPHA\\pat')
        self.assertIs(f['reboot'], False)
        self.assertEqual(f['last_patched'], datetime(2026, 11, 4, 2, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(f['ips'], ['10.0.0.21'])
        self.assertIsNone(f['public_ip'])
        dev = RMMDevice.objects.get(connection__provider_type='connectwise_automate')
        self.assertEqual(dev.raw_data['MacAddress'], '00:11:22:33:44:55')

    def test_rem0te(self):
        f = self.facts('rem0te', REM0TE_COMPUTER)
        for fact in ('agent_version', 'logged_in', 'last_boot', 'disks'):
            self.assertIn(fact, f['unsupported'])
        self.assertIsNone(f['agent_version'])
        self.assertEqual(f['ips'], ['10.0.0.21'])

    def test_one_provider_never_reads_another_providers_keys(self):
        # A Datto device whose payload happens to carry Tactical RMM's names.
        f = self.facts('datto_rmm', dict(DATTO_DEVICE, displayVersion=None, cagVersion=None, version='2.8.0',
                                         logged_username='intruder', lastLoggedInUser=None))
        self.assertIsNone(f['agent_version'])
        self.assertIsNone(f['logged_in'])

    def test_every_provider_has_a_map_and_list_gaps(self):
        for ptype in RMM_PROVIDER_REGISTRY:
            self.assertIn(ptype, rmm_fields.EXTRACTORS)
            for kind in ('processes', 'events'):
                self.assertTrue(rmm_fields.list_gap(ptype, kind))


class TrmmRoutes:
    """Answers Tactical RMM requests from the fixtures; records them."""

    def __init__(self, agents, details):
        self.agents, self.details, self.calls = agents, details, []

    def __call__(self, method, endpoint, **kw):
        self.calls.append((method, endpoint))
        if endpoint == '/agents/' and (kw.get('params') or {}).get('limit') == 1:
            return Resp([])
        if endpoint == '/agents/':
            return Resp(self.agents)
        if endpoint == '/clients/':
            return Resp([{'id': 5, 'name': 'Alpha Dental', 'sites': [{'id': 8, 'name': 'Main Office'}]}])
        if endpoint.startswith('/agents/') and endpoint.count('/') == 3:
            return Resp(self.details[endpoint.split('/')[2]])
        if endpoint == '/alerts/':
            return Resp([])
        raise AssertionError(f'unexpected request {method} {endpoint}')


class ServiceCollectionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Alpha Dental', slug='alpha')
        self.conn = make_conn(self.org, 'tactical_rmm', sync_alerts=False, sync_software=False,
                              map_to_assets=False)
        # The table row has disks, RAM and a MAC, so the sync reads no detail
        # for it; the second agent is missing its MAC, so the sync merges the
        # detail record (which carries services).
        bare = dict(TRMM_TABLE_ROW, agent_id='agent-2', hostname='RECEPTION-02', MACAddress=None)
        self.routes = TrmmRoutes([TRMM_TABLE_ROW, bare], {
            TRMM_TABLE_ROW['agent_id']: TRMM_DETAIL,
            'agent-2': dict(TRMM_DETAIL, agent_id='agent-2', hostname='RECEPTION-02')})

    def sync(self):
        with mock.patch.object(RMM_PROVIDER_REGISTRY['tactical_rmm'], '_make_request', side_effect=self.routes):
            return RMMSync(self.conn).sync_all()

    def test_off_by_default_and_never_kept_in_raw_data(self):
        self.sync()
        self.assertFalse(RMMDeviceSnapshot.objects.exists())
        for d in RMMDevice.objects.all():
            self.assertNotIn('services', d.raw_data)

    def test_opt_in_keeps_latest_list_with_whitelisted_fields(self):
        self.conn.sync_services = True
        self.conn.save()
        stats = self.sync()
        self.assertEqual(stats['services'], {'collected': 2, 'errors': 0})
        d1 = RMMDevice.objects.get(external_id=TRMM_TABLE_ROW['agent_id'])
        snap = rmm_snapshots.latest(d1)
        self.assertEqual(snap.organization, self.org)
        self.assertEqual([s['display_name'] for s in snap.items], ['Print Spooler', 'Windows Update'])
        self.assertEqual(set(snap.items[0]), {'name', 'display_name', 'status', 'start_type'})
        self.assertNotIn('services', d1.raw_data)
        # One detail read per agent: agent-2's came with the device list.
        details = [c for c in self.routes.calls if c[1].startswith('/agents/') and c[1].count('/') == 3]
        self.assertEqual(sorted(details), sorted([('GET', '/agents/agent-2/'),
                                                  ('GET', f"/agents/{TRMM_TABLE_ROW['agent_id']}/")]))
        # A second sync replaces the list rather than adding to it.
        self.routes.details[TRMM_TABLE_ROW['agent_id']] = dict(TRMM_DETAIL, services=TRMM_DETAIL['services'][:1])
        self.sync()
        self.assertEqual(RMMDeviceSnapshot.objects.filter(device=d1).count(), 1)
        self.assertEqual(rmm_snapshots.latest(d1).item_count, 1)

    def test_unowned_devices_are_not_collected(self):
        self.conn.sync_services = True
        self.conn.customer_scope = RMMConnection.CUSTOMER_SCOPE_MULTI  # nothing mapped: all unresolved
        self.conn.save()
        self.sync()
        self.assertFalse(RMMDeviceSnapshot.objects.exists())

    def test_switching_off_deletes_kept_lists(self):
        self.conn.sync_services = True
        self.conn.save()
        self.sync()
        self.assertTrue(RMMDeviceSnapshot.objects.exists())
        self.conn.sync_services = False
        self.conn.save()
        self.sync()
        self.assertFalse(RMMDeviceSnapshot.objects.exists())

    def test_provider_without_services_never_collects(self):
        conn = make_conn(self.org, 'ninjaone', sync_services=True)
        self.assertFalse(rmm_snapshots.collecting(conn))
        self.assertFalse(rmm_snapshots.collecting(self.conn))  # Tactical RMM, but not opted in


class RetentionAndIsolationTests(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='Alpha Dental', slug='alpha')
        self.b = Organization.objects.create(name='Beta Law', slug='beta')
        self.conn = make_conn(self.a, 'tactical_rmm', sync_services=True)
        self.dev = device_from(self.conn, TRMM_TABLE_ROW)
        self.rows = rmm_snapshots.normalize_services(TRMM_DETAIL['services'])

    def test_older_than_retention_is_hidden_then_purged(self):
        old = timezone.now() - timedelta(days=rmm_snapshots.RETENTION_DAYS + 1)
        rmm_snapshots.store(self.dev, 'services', self.rows, now=old)
        self.assertIsNone(rmm_snapshots.latest(self.dev))
        self.assertEqual(rmm_snapshots.purge(), 1)
        self.assertFalse(RMMDeviceSnapshot.objects.exists())
        rmm_snapshots.store(self.dev, 'services', self.rows)
        self.assertEqual(rmm_snapshots.purge(), 0)
        self.assertIsNotNone(rmm_snapshots.latest(self.dev))

    def test_list_is_capped(self):
        many = [{'name': f's{i}', 'display_name': f'S{i}', 'status': 'running', 'start_type': 'Manual'}
                for i in range(rmm_snapshots.MAX_ITEMS + 5)]
        snap = rmm_snapshots.store(self.dev, 'services', many)
        self.assertEqual(len(snap.items), rmm_snapshots.MAX_ITEMS)
        self.assertTrue(snap.truncated)
        self.assertEqual(snap.item_count, rmm_snapshots.MAX_ITEMS + 5)

    def test_customer_change_drops_the_list(self):
        rmm_snapshots.store(self.dev, 'services', self.rows)
        RMMDevice.objects.filter(pk=self.dev.pk).update(organization=self.b)
        self.dev.refresh_from_db()
        # Collected under Alpha: never shown under Beta, even before cleanup.
        self.assertIsNone(rmm_snapshots.latest(self.dev))
        set_device_organization(self.dev, self.b)
        self.assertFalse(RMMDeviceSnapshot.objects.exists())

    def test_unowned_device_shows_nothing(self):
        rmm_snapshots.store(self.dev, 'services', self.rows)
        self.dev.organization = None
        self.assertIsNone(rmm_snapshots.latest(self.dev))

    def test_scoped_manager_filters_by_customer(self):
        rmm_snapshots.store(self.dev, 'services', self.rows)
        self.assertEqual(RMMDeviceSnapshot.objects.filter(organization=self.b).count(), 0)
        self.assertEqual(RMMDeviceSnapshot.objects.filter(organization=self.a).count(), 1)


class RefreshTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Alpha Dental', slug='alpha')
        self.conn = make_conn(self.org, 'tactical_rmm', sync_services=True)
        self.dev = device_from(self.conn, TRMM_TABLE_ROW, now=timezone.now() - timedelta(hours=5))
        RMMDevice.objects.filter(pk=self.dev.pk).update(raw_data=dict(self.dev.raw_data, id=77))
        self.dev.refresh_from_db()
        self.routes = TrmmRoutes([], {TRMM_TABLE_ROW['agent_id']: dict(TRMM_DETAIL, version='2.9.1')})

    def refresh(self, now=None):
        with mock.patch.object(RMM_PROVIDER_REGISTRY['tactical_rmm'], '_make_request', side_effect=self.routes):
            return rmm_refresh.refresh_device(self.dev, now=now)

    def test_refresh_stores_detail_and_services(self):
        r = self.refresh()
        self.assertTrue(r.ok, r.message)
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.raw_data['version'], '2.9.1')
        self.assertEqual(self.dev.raw_data['id'], 77)  # kept: the detail route leaves it out
        self.assertNotIn('services', self.dev.raw_data)
        self.assertGreater(self.dev.data_refreshed_at, timezone.now() - timedelta(minutes=1))
        self.assertEqual(rmm_snapshots.latest(self.dev).item_count, 2)
        self.assertEqual(self.routes.calls, [('GET', '/clients/'), ('GET', f"/agents/{TRMM_TABLE_ROW['agent_id']}/")])

    def test_rate_limited_per_device(self):
        self.assertTrue(self.refresh().ok)
        calls = len(self.routes.calls)
        again = self.refresh()
        self.assertEqual(again.outcome, rmm_refresh.RATE_LIMITED)
        self.assertGreater(again.retry_after, 0)
        self.assertEqual(len(self.routes.calls), calls)  # the provider wasn't asked again
        # Another device of the same connection has its own slot.
        other = device_from(self.conn, dict(TRMM_TABLE_ROW, agent_id='agent-2'))
        self.routes.details['agent-2'] = dict(TRMM_DETAIL, agent_id='agent-2')
        with mock.patch.object(RMM_PROVIDER_REGISTRY['tactical_rmm'], '_make_request', side_effect=self.routes):
            self.assertTrue(rmm_refresh.refresh_device(other).ok)
        later = timezone.now() + rmm_refresh.REFRESH_INTERVAL + timedelta(seconds=1)
        self.assertTrue(self.refresh(now=later).ok)

    def test_failed_answer_still_uses_the_slot(self):
        def boom(method, endpoint, **kw):
            raise RuntimeError('connection reset')
        with mock.patch.object(RMM_PROVIDER_REGISTRY['tactical_rmm'], '_make_request', side_effect=boom):
            r = rmm_refresh.refresh_device(self.dev)
        self.assertEqual(r.outcome, rmm_refresh.FAILED)
        self.assertEqual(self.refresh().outcome, rmm_refresh.RATE_LIMITED)

    def test_different_customer_is_refused(self):
        self.conn.customer_scope = RMMConnection.CUSTOMER_SCOPE_MULTI
        self.conn.save()
        RMMDevice.objects.filter(pk=self.dev.pk).update(customer_key='id:5')
        self.dev.refresh_from_db()
        self.routes.details[TRMM_TABLE_ROW['agent_id']] = dict(TRMM_DETAIL, client='Beta Law', version='9')
        r = self.refresh()
        self.assertEqual(r.outcome, rmm_refresh.REFUSED)
        self.dev.refresh_from_db()
        self.assertNotEqual(self.dev.raw_data.get('version'), '9')
        self.assertEqual(self.dev.organization, self.org)
        # The same customer by ID goes through.
        self.routes.details[TRMM_TABLE_ROW['agent_id']] = dict(TRMM_DETAIL, version='9')
        self.assertTrue(self.refresh(now=timezone.now() + timedelta(minutes=6)).ok)

    def test_rem0te_refresh_checks_the_pinned_business(self):
        from .providers.rmm.rem0te import BUSINESS_PIN
        conn = make_conn(self.org, 'rem0te')
        conn.field_mappings = {BUSINESS_PIN: 'biz-alpha'}
        conn.save()
        dev = device_from(conn, REM0TE_COMPUTER)
        answer = {'data': dict(REM0TE_COMPUTER, customerId='biz-other', customer={'id': 'biz-other'})}
        with mock.patch.object(RMM_PROVIDER_REGISTRY['rem0te'], '_make_request', return_value=Resp(answer)):
            self.assertEqual(rmm_refresh.refresh_device(dev).outcome, rmm_refresh.REFUSED)

    def test_unavailable_when_switched_off_or_under_review(self):
        self.conn.sync_enabled = False
        self.conn.save()
        self.assertEqual(self.refresh().outcome, rmm_refresh.UNAVAILABLE)
        self.assertEqual(self.routes.calls, [])
        self.conn.sync_enabled = True
        self.conn.save()
        RMMDevice.objects.filter(pk=self.dev.pk).update(ownership_status=RMMDevice.OWNERSHIP_MOVED)
        self.dev.refresh_from_db()
        self.assertEqual(self.refresh().outcome, rmm_refresh.UNAVAILABLE)

    def test_every_provider_has_a_single_device_read(self):
        for ptype in RMM_PROVIDER_REGISTRY:
            conn = make_conn(self.org, ptype, name=f'x {ptype}')
            dev = RMMDevice(connection=conn, organization=self.org, external_id='1')
            self.assertEqual(rmm_refresh.availability(dev), (True, ''), ptype)


class ProviderRouteTests(TestCase):
    """Routes fixed against the providers' API references."""

    def setUp(self):
        self.org = Organization.objects.create(name='Alpha Dental', slug='alpha')

    def test_datto_device_and_software_routes(self):
        conn = make_conn(self.org, 'datto_rmm')
        p = RMM_PROVIDER_REGISTRY['datto_rmm'](conn)
        seen = []

        def routes(method, endpoint, **kw):
            seen.append(endpoint)
            if endpoint.startswith('/api/v2/device/'):
                return Resp(DATTO_DEVICE)
            return Resp({'pageDetails': {'nextPageUrl': None},
                         'software': [{'name': '7-Zip 23.01 (x64)', 'version': '23.01'}]})
        with mock.patch.object(type(p), '_make_request', side_effect=routes):
            self.assertEqual(p.get_device(DATTO_DEVICE['uid'])['external_id'], DATTO_DEVICE['uid'])
            sw = p.list_software(DATTO_DEVICE['uid'])
        self.assertEqual(seen, [f"/api/v2/device/{DATTO_DEVICE['uid']}",
                                f"/api/v2/audit/device/{DATTO_DEVICE['uid']}/software"])
        self.assertEqual([s['name'] for s in sw], ['7-Zip 23.01 (x64)'])

    def test_software_sync_passes_only_the_device_id_to_other_providers(self):
        conn = make_conn(self.org, 'ninjaone', sync_software=True)
        dev = device_from(conn, NINJA_DEVICE)
        sync = RMMSync(conn)
        with mock.patch.object(sync.provider, 'list_software', return_value=[]) as ls:
            sync.sync_software()
        ls.assert_called_once_with(dev.external_id)
