"""
RMM customer, site, device, asset and ticket association.

Every test drives the real adapters (vendor HTTP replaced by canned
payloads shaped like each vendor's documented API) through RMMSync, the
reconciliation command and the ticket views, so what is checked is what a
sync does on a live connection.
"""
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset
from core.models import Organization
from integrations.models import RMMAlert, RMMConnection, RMMDevice
from integrations.providers.rmm import (
    AteraProvider, ConnectWiseAutomateProvider, DattoRMMProvider, NinjaOneProvider, Rem0teProvider,
    TacticalRMMProvider,
)
from integrations.providers.rmm.console import validated_console_url
from integrations import rmm_association as ra
from integrations.sync import RMMSync, SyncAlreadyRunning, acquire_sync_lock, release_sync_lock
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed

PROVIDERS = {
    'ninjaone': (NinjaOneProvider, 'https://app.ninjarmm.com'),
    'datto_rmm': (DattoRMMProvider, 'https://pinotage-api.centrastage.net'),
    'atera': (AteraProvider, 'https://app.atera.com/api'),
    'connectwise_automate': (ConnectWiseAutomateProvider, 'https://automate.example.com'),
    'tactical_rmm': (TacticalRMMProvider, 'https://api.trmm.example.com'),
    'rem0te': (Rem0teProvider, 'https://remote.example.com'),
}


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.ok = status < 400
        self.text = ''
        self.content = b'[]'
        self.url = 'https://vendor.test/'
        self.headers = {'Content-Type': 'application/json'}

    def json(self):
        return self._data


class _Vendor:
    """Canned vendor API: `routes` maps (method, path) to a payload or a
    callable; anything else is a 404 error."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint))
        key = (method, endpoint.split('?')[0])
        if key not in self.routes:
            raise RuntimeError(f'unexpected vendor call {key}')
        data = self.routes[key]
        if isinstance(data, Exception):
            raise data
        return _Resp(data(kwargs) if callable(data) else data)


class _Base(TestCase):
    def setUp(self):
        self.msp = Organization.objects.create(name='MSP', slug='rmma-msp')
        self.a = Organization.objects.create(name='Acme Ltd', slug='rmma-a')
        self.b = Organization.objects.create(name='Bolt Inc', slug='rmma-b')

    def connection(self, provider='ninjaone', scope=RMMConnection.CUSTOMER_SCOPE_MULTI, **kw):
        cls, base_url = PROVIDERS[provider]
        kw.setdefault('sync_software', False)
        self._n = getattr(self, '_n', 0) + 1
        kw.setdefault('base_url', base_url)
        return RMMConnection.objects.create(
            organization=kw.pop('owner', self.msp), provider_type=provider, name=f'{provider} test {self._n}',
            customer_scope=scope, **kw)

    def sync(self, connection, routes, alerts=True):
        cls = PROVIDERS[connection.provider_type][0]
        vendor = _Vendor(routes)
        with mock.patch.object(cls, '_make_request', side_effect=vendor), \
                mock.patch.object(cls, 'test_connection', return_value=True):
            connection.refresh_from_db()
            connection.sync_alerts = alerts
            syncer = RMMSync(connection)
            syncer.sync_all()
        return syncer, vendor

    def map(self, connection, client_id, org, name=''):
        ra.map_customer(connection, ra.customer_identity({'client_id': client_id, 'client_name': name}), org)

    def device(self, connection, external_id):
        return RMMDevice.objects.get(connection=connection, external_id=external_id)


# ---------------------------------------------------------------------------
# Payload builders, one per vendor
# ---------------------------------------------------------------------------

def ninja_device(did, org_id, loc_id, name='FRONTDESK', serial='', ip='192.168.1.10', offline=False):
    return {'id': did, 'nodeClass': 'WINDOWS_WORKSTATION', 'systemName': name, 'offline': offline,
            'lastContact': 1767920400.5, 'organizationId': org_id, 'locationId': loc_id,
            'system': {'manufacturer': 'Dell Inc.', 'model': 'OptiPlex 7090', 'serialNumber': serial},
            'os': {'name': 'Windows 11 Pro'}, 'ipAddresses': [ip]}


def ninja_routes(devices, alerts=(), orgs=((7, 'Acme Ltd'), (8, 'Bolt Inc')),
                 locations=((12, 'Main Office'), (13, 'Main Office'))):
    def paged(rows):
        return lambda kw: rows if 'after' not in (kw.get('params') or {}) else []
    return {
        ('GET', '/v2/organizations'): paged([{'id': i, 'name': n} for i, n in orgs]),
        ('GET', '/v2/locations'): paged([{'id': i, 'name': n} for i, n in locations]),
        ('GET', '/v2/devices-detailed'): paged(list(devices)),
        ('GET', '/v2/alerts'): list(alerts),
    }


def datto_routes(devices, alerts=()):
    return {
        ('GET', '/api/v2/account/devices'): {'devices': list(devices), 'pageDetails': {}},
        ('GET', '/api/v2/account/alerts/open'): {'alerts': list(alerts), 'pageDetails': {}},
    }


def datto_device(uid, site_uid, site_name, name='FRONTDESK', portal=''):
    return {'uid': uid, 'hostname': name, 'intIpAddress': '192.168.1.10', 'online': True,
            'lastSeen': 1767920400000, 'siteUid': site_uid, 'siteName': site_name,
            'deviceType': {'category': 'Desktop'}, 'portalUrl': portal}


def atera_agent(agent_id, guid, customer_id, customer, name='FRONTDESK', serial=''):
    return {'AgentID': agent_id, 'DeviceGuid': guid, 'MachineName': name, 'CustomerID': customer_id,
            'CustomerName': customer, 'Online': True, 'VendorSerialNumber': serial,
            'IpAddresses': ['192.168.1.10'], 'LastSeen': '2026-11-08T09:00:00',
            'AppViewUrl': f'https://app.atera.com/new/device/{agent_id}'}


def atera_routes(agents, alerts=()):
    return {
        ('GET', '/v3/agents'): {'items': list(agents), 'totalPages': 1},
        ('GET', '/v3/alerts'): {'items': list(alerts), 'totalPages': 1},
    }


def automate_routes(computers, alerts=(), clients=(), locations=()):
    def paged(rows):
        return lambda kw: rows if (kw.get('params') or {}).get('page', 1) == 1 else []
    return {
        ('GET', '/cwa/api/v1/Computers'): paged(list(computers)),
        ('GET', '/cwa/api/v1/Alerts'): paged(list(alerts)),
        ('GET', '/cwa/api/v1/Clients'): paged(list(clients)),
        ('GET', '/cwa/api/v1/Locations'): paged(list(locations)),
    }


def tactical_agent(agent_id, client, site, name='FRONTDESK', serial=''):
    return {'agent_id': agent_id, 'hostname': name, 'client_name': client, 'site_name': site,
            'monitoring_type': 'workstation', 'plat': 'windows', 'serial_number': serial,
            'local_ips': '192.168.1.10', 'online': True, 'total_ram': 16, 'disks': [{'x': 1}],
            'MACAddress': '00:11:22:33:44:55', 'last_seen': '2026-11-08T09:00:00Z'}


def tactical_routes(agents, clients=None, alerts=()):
    routes = {
        ('GET', '/agents/'): list(agents),
        ('PATCH', '/alerts/'): list(alerts),
    }
    routes[('GET', '/clients/')] = clients if clients is not None else RuntimeError('clients unavailable')
    return routes


# ---------------------------------------------------------------------------
# Adapters: customer and site identity
# ---------------------------------------------------------------------------

class NinjaOneAdapterTests(_Base):

    def test_organization_and_location_stay_distinct_and_alerts_follow_device(self):
        conn = self.connection('ninjaone')
        self.map(conn, '7', self.a)
        self.call = self.sync(conn, ninja_routes(
            [ninja_device(101, 7, 12)],
            alerts=[{'uid': 'al-1', 'deviceId': 101, 'sourceType': 'CONDITION', 'message': 'Disk full',
                     'severity': 'MAJOR', 'createTime': 1767920400}]))
        d = self.device(conn, '101')
        self.assertEqual((d.client_id, d.client_name, d.site_id, d.site_name),
                         ('7', 'Acme Ltd', '12', 'Main Office'))
        self.assertEqual(d.organization, self.a)
        self.assertTrue(d.is_exposed)
        self.assertEqual(d.last_seen.year, 2026)  # epoch seconds, not ms
        alert = RMMAlert.objects.get(connection=conn)
        self.assertEqual((alert.device, alert.organization), (d, self.a))

    def test_console_link_is_fetched_on_demand_and_validated(self):
        conn = self.connection('ninjaone')
        self.map(conn, '7', self.a)
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        d = self.device(conn, '101')
        self.assertEqual(ra.console_link(d), f'/integrations/rmm/devices/{d.pk}/open/')
        hosts = NinjaOneProvider.console_hosts(conn)
        self.assertEqual(validated_console_url('https://app.ninjarmm.com/#/deviceDashboard/101', hosts),
                         'https://app.ninjarmm.com/#/deviceDashboard/101')
        self.assertEqual(validated_console_url('https://evil.example.com/x', hosts), '')


class DattoAdapterTests(_Base):

    def test_site_is_the_customer_and_never_two_customers(self):
        conn = self.connection('datto_rmm', import_organizations=True)
        self.sync(conn, datto_routes([
            datto_device('d-1', 'site-9', 'Acme Ltd'),
            datto_device('d-2', 'site-9', 'Acme Ltd', name='OFFICE2'),
        ], alerts=[{'alertUid': 'a-1', 'priority': 'High', 'timestamp': 1767920400000,
                    'alertSourceInfo': {'deviceUid': 'd-1'}, 'diagnostics': 'CPU'}]))
        d1, d2 = self.device(conn, 'd-1'), self.device(conn, 'd-2')
        self.assertEqual((d1.client_id, d1.site_id), ('site-9', 'site-9'))
        # The existing "Acme Ltd" is adopted once; both devices land in it.
        self.assertEqual(d1.organization, self.a)
        self.assertEqual(d2.organization, self.a)
        self.assertEqual(Organization.objects.filter(name='Acme Ltd').count(), 1)
        self.assertEqual(RMMAlert.objects.get(connection=conn).device, d1)

    def test_portal_url_only_on_the_platform_host(self):
        conn = self.connection('datto_rmm')
        self.map(conn, 'site-9', self.a)
        self.sync(conn, datto_routes([
            datto_device('d-1', 'site-9', 'Acme', portal='https://pinotage.centrastage.net/csm/device/1'),
            datto_device('d-2', 'site-9', 'Acme', name='X', portal='https://phish.example.com/?token=abc'),
        ]))
        self.assertEqual(ra.console_link(self.device(conn, 'd-1')), 'https://pinotage.centrastage.net/csm/device/1')
        self.assertEqual(ra.console_link(self.device(conn, 'd-2')), '')


class AteraAdapterTests(_Base):

    def test_customer_ids_carried_and_end_user_id_is_not_a_device(self):
        conn = self.connection('atera')
        self.map(conn, '42', self.a)
        self.map(conn, '43', self.b)
        agents = [atera_agent(500, 'guid-a', 42, 'Acme Ltd'), atera_agent(501, 'guid-b', 43, 'Bolt Inc')]
        alerts = [
            # Old code read EndUserID as the device: 500 is a real AgentID.
            {'AlertID': 1, 'EndUserID': 500, 'Title': 'Ticket-ish', 'Severity': 'Warning'},
            # Verified: GUID belongs to agent 500 and the customers agree.
            {'AlertID': 2, 'DeviceGuid': 'GUID-A', 'CustomerID': 42, 'Title': 'Disk', 'Severity': 'Critical'},
            # GUID of a Bolt agent but claims Acme: not attached.
            {'AlertID': 3, 'DeviceGuid': 'guid-b', 'CustomerID': 42, 'Title': 'Odd', 'Severity': 'Warning'},
        ]
        self.sync(conn, atera_routes(agents, alerts))
        da = self.device(conn, '500')
        self.assertEqual((da.client_id, da.client_name, da.organization), ('42', 'Acme Ltd', self.a))
        stored = list(RMMAlert.objects.filter(connection=conn).values_list('external_id', 'device__external_id'))
        self.assertEqual(stored, [('2', '500')])
        self.assertEqual(RMMAlert.objects.get(external_id='2').organization, self.a)

    def test_alert_sync_alone_uses_one_agent_lookup(self):
        conn = self.connection('atera', sync_devices=False)
        self.map(conn, '42', self.a)
        RMMDevice.objects.create(connection=conn, organization=self.a, external_id='500', device_name='FRONTDESK',
                                 client_id='42', customer_key='id:42')
        _, vendor = self.sync(conn, atera_routes([atera_agent(500, 'guid-a', 42, 'Acme')],
                                                 [{'AlertID': 9, 'DeviceGuid': 'guid-a', 'CustomerID': 42}]))
        self.assertEqual([c for c in vendor.calls if c[1] == '/v3/agents'], [('GET', '/v3/agents')])
        self.assertTrue(RMMAlert.objects.filter(external_id='9', device__external_id='500').exists())


class AutomateAdapterTests(_Base):

    def test_client_and_location_ids_preserved_and_names_resolved(self):
        conn = self.connection('connectwise_automate')
        self.map(conn, '1', self.a, name='Old name')
        self.sync(conn, automate_routes(
            [{'Id': '12345', 'ComputerName': 'FRONTDESK', 'Status': 'Online', 'SerialNumber': 'SN-ACME-1',
              'ClientId': 1, 'LocationId': 10, 'RemoteAgentLastContact': '2026-11-08T09:00:00'}],
            alerts=[{'AlertId': 77, 'Computer': {'Id': 12345}, 'Message': 'Offline', 'Severity': 'Error'}],
            clients=[{'Id': 1, 'Name': 'Acme Ltd (renamed)'}],
            locations=[{'Id': 10, 'Name': 'Main Office'}]))
        d = self.device(conn, '12345')
        # Resolved by ID even though the name no longer matches the mapping.
        self.assertEqual((d.client_id, d.client_name, d.site_id, d.site_name),
                         ('1', 'Acme Ltd (renamed)', '10', 'Main Office'))
        self.assertEqual(d.organization, self.a)
        self.assertEqual(RMMAlert.objects.get(connection=conn).device, d)
        self.assertEqual(ra.console_link(d), '')  # no documented console URL


class TacticalAdapterTests(_Base):

    clients = [
        {'id': 1, 'name': 'Acme Ltd', 'sites': [{'id': 11, 'name': 'Main Office'}]},
        {'id': 2, 'name': 'Bolt Inc', 'sites': [{'id': 21, 'name': 'Main Office'}]},
    ]

    def test_real_ids_and_same_site_name_under_two_customers(self):
        conn = self.connection('tactical_rmm', console_base_url='https://rmm.trmm.example.com')
        self.map(conn, '1', self.a)
        self.map(conn, '2', self.b)
        self.sync(conn, tactical_routes(
            [tactical_agent('ag-a', 'Acme Ltd', 'Main Office'), tactical_agent('ag-b', 'Bolt Inc', 'Main Office')],
            clients=self.clients,
            alerts=[{'id': 5, 'agent_id': 'ag-b', 'message': 'Down', 'severity': 'error',
                     'alert_time': '2026-11-08T09:00:00Z'}]))
        da, db = self.device(conn, 'ag-a'), self.device(conn, 'ag-b')
        self.assertEqual((da.client_id, da.site_id, da.organization), ('1', '11', self.a))
        self.assertEqual((db.client_id, db.site_id, db.organization), ('2', '21', self.b))
        self.assertEqual(RMMAlert.objects.get(connection=conn).organization, self.b)
        self.assertEqual(ra.console_link(da), 'https://rmm.trmm.example.com/agents/ag-a')

    def test_name_only_needs_an_explicit_mapping_even_with_import_on(self):
        conn = self.connection('tactical_rmm', import_organizations=True)
        routes = tactical_routes([tactical_agent('ag-a', 'Acme Ltd', 'Main Office')])
        self.sync(conn, routes)
        d = self.device(conn, 'ag-a')
        self.assertEqual(d.ownership_status, RMMDevice.OWNERSHIP_UNRESOLVED)
        self.assertIsNone(d.organization)
        self.assertIn('by name only', d.ownership_note)
        self.assertEqual(Organization.objects.filter(name='Acme Ltd').count(), 1)

        staff = User.objects.create_superuser('rmma_admin', 'x@x.test', 'pw')
        ra.assign_customer(d, self.a, staff, map_all=True)
        self.sync(conn, routes)
        self.assertEqual(self.device(conn, 'ag-a').organization, self.a)

    def test_rename_does_not_create_or_move_silently(self):
        conn = self.connection('tactical_rmm', import_organizations=True)
        ra.map_customer(conn, ra.customer_identity({'client_name': 'Acme Ltd'}), self.a)
        self.sync(conn, tactical_routes([tactical_agent('ag-a', 'Acme Ltd', 'Main Office')]))
        self.assertEqual(self.device(conn, 'ag-a').organization, self.a)
        orgs_before = Organization.objects.count()

        self.sync(conn, tactical_routes([tactical_agent('ag-a', 'Acme Holdings', 'Main Office')]))
        d = self.device(conn, 'ag-a')
        self.assertEqual(d.ownership_status, RMMDevice.OWNERSHIP_MOVED)
        self.assertIsNone(d.organization)
        self.assertEqual(Organization.objects.count(), orgs_before)

    def test_legacy_slug_mapping_and_name_to_id_upgrade_carry_over(self):
        conn = self.connection('tactical_rmm')
        # Older versions mapped Tactical customers under a name slug.
        self.map(conn, 'acme-ltd', self.a)
        self.sync(conn, tactical_routes([tactical_agent('ag-a', 'Acme Ltd', 'Main Office')], clients=self.clients))
        self.assertEqual(self.device(conn, 'ag-a').organization, self.a)

        conn2 = self.connection('tactical_rmm')
        ra.map_customer(conn2, ra.customer_identity({'client_name': 'Acme Ltd'}), self.a)
        self.sync(conn2, tactical_routes([tactical_agent('ag-a', 'Acme Ltd', 'Main Office')]))
        self.sync(conn2, tactical_routes([tactical_agent('ag-a', 'Acme Ltd', 'Main Office')], clients=self.clients))
        d = self.device(conn2, 'ag-a')
        self.assertEqual((d.ownership_status, d.organization, d.customer_key),
                         (RMMDevice.OWNERSHIP_RESOLVED, self.a, 'id:1'))


# ---------------------------------------------------------------------------
# Tenant-safe association
# ---------------------------------------------------------------------------

class AssociationTests(_Base):

    def ninja(self, **kw):
        conn = self.connection('ninjaone', **kw)
        self.map(conn, '7', self.a)
        self.map(conn, '8', self.b)
        return conn

    def test_two_customers_with_frontdesk_on_the_same_ip(self):
        asset_a = Asset.objects.create(organization=self.a, name='FRONTDESK', hostname='FRONTDESK',
                                       ip_address='192.168.1.10')
        asset_b = Asset.objects.create(organization=self.b, name='FRONTDESK', hostname='FRONTDESK',
                                       ip_address='192.168.1.10')
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12), ninja_device(102, 8, 13)]))
        da, db = self.device(conn, '101'), self.device(conn, '102')
        self.assertEqual(da.linked_asset, asset_a)
        self.assertEqual(db.linked_asset, asset_b)
        self.assertEqual(list(ra.exposed_devices(asset_a)), [da])
        self.assertEqual(list(ra.exposed_devices(asset_b)), [db])

    def test_identical_external_ids_on_separate_connections(self):
        c1, c2 = self.ninja(), self.connection('datto_rmm')
        self.map(c2, 'site-b', self.b)
        self.sync(c1, ninja_routes([ninja_device(100, 7, 12)]))
        self.sync(c2, datto_routes([datto_device('100', 'site-b', 'Bolt')]))
        d1, d2 = self.device(c1, '100'), self.device(c2, '100')
        self.assertNotEqual(d1.pk, d2.pk)
        self.assertEqual((d1.organization, d2.organization), (self.a, self.b))
        self.assertEqual(d1.linked_asset.organization, self.a)
        self.assertEqual(d2.linked_asset.organization, self.b)

    def test_unresolved_customer_is_not_filed_under_the_owner(self):
        conn = self.connection('ninjaone')  # nothing mapped, import off
        self.sync(conn, ninja_routes([ninja_device(101, 99, 12)], orgs=((99, 'Stranger'),)))
        d = self.device(conn, '101')
        self.assertEqual(d.ownership_status, RMMDevice.OWNERSHIP_UNRESOLVED)
        self.assertIsNone(d.organization)
        self.assertIsNone(d.linked_asset)
        self.assertFalse(Asset.objects.filter(organization=self.msp).exists())

    def test_single_customer_connection_files_everything_under_owner(self):
        conn = self.connection('ninjaone', scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        self.sync(conn, ninja_routes([ninja_device(101, 99, 12)], orgs=((99, 'Whatever'),)))
        d = self.device(conn, '101')
        self.assertEqual((d.organization, d.ownership_status), (self.msp, RMMDevice.OWNERSHIP_RESOLVED))
        self.assertEqual(d.linked_asset.organization, self.msp)

    def test_blank_device_ids_are_rejected(self):
        conn = self.ninja()
        syncer, _ = self.sync(conn, ninja_routes([ninja_device(None, 7, 12)]))
        self.assertFalse(RMMDevice.objects.filter(connection=conn).exists())
        self.assertEqual(syncer.stats['devices']['errors'], 1)

    def test_duplicate_serials_go_to_review_with_candidates(self):
        x = Asset.objects.create(organization=self.a, name='PC-1', serial_number='SN12345678')
        y = Asset.objects.create(organization=self.a, name='PC-2', serial_number='SN12345678')
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, name='PC-3', serial='SN12345678')]))
        d = self.device(conn, '101')
        self.assertEqual(d.link_status, RMMDevice.LINK_REVIEW)
        self.assertIsNone(d.linked_asset)
        self.assertEqual(sorted(d.link_candidates), sorted([x.pk, y.pk]))
        self.assertEqual(Asset.objects.filter(organization=self.a).count(), 2)

    def test_placeholder_serial_is_ignored(self):
        other = Asset.objects.create(organization=self.a, name='OTHER', serial_number='To Be Filled By O.E.M.')
        mine = Asset.objects.create(organization=self.a, name='FRONTDESK', hostname='FRONTDESK')
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, serial='To Be Filled By O.E.M.')]))
        self.assertEqual(self.device(conn, '101').linked_asset, mine)
        other.refresh_from_db()
        self.assertFalse(other.rmm_devices.exists())

    def test_ambiguous_hostname_is_explained(self):
        Asset.objects.create(organization=self.a, name='FRONTDESK', hostname='FRONTDESK')
        Asset.objects.create(organization=self.a, name='FRONTDESK (old)', hostname='frontdesk.corp.local')
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        d = self.device(conn, '101')
        self.assertEqual(d.link_status, RMMDevice.LINK_REVIEW)
        self.assertIn('2 assets at this customer have the hostname FRONTDESK. Choose the correct one.', d.link_note)

    def test_hostname_rename_keeps_the_link(self):
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        asset = self.device(conn, '101').linked_asset
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, name='RECEPTION')]))
        d = self.device(conn, '101')
        self.assertEqual(d.linked_asset, asset)
        self.assertEqual(Asset.objects.filter(organization=self.a).count(), 1)

    def test_upstream_customer_move_stops_exposure_until_reviewed(self):
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)],
                                     alerts=[{'uid': 'x', 'deviceId': 101, 'message': 'm'}]))
        asset = self.device(conn, '101').linked_asset
        self.sync(conn, ninja_routes([ninja_device(101, 8, 13)]))
        d = self.device(conn, '101')
        self.assertEqual(d.ownership_status, RMMDevice.OWNERSHIP_MOVED)
        self.assertEqual(d.pending_organization, self.b)
        self.assertEqual(list(ra.exposed_devices(asset)), [])
        self.assertIsNone(RMMAlert.objects.get(device=d).organization)
        # Stays under review however many syncs run.
        self.sync(conn, ninja_routes([ninja_device(101, 8, 13)]))
        self.assertEqual(self.device(conn, '101').ownership_status, RMMDevice.OWNERSHIP_MOVED)

        staff = User.objects.create_superuser('rmma_mover', 'm@x.test', 'pw')
        ra.assign_customer(self.device(conn, '101'), self.b, staff)
        d = self.device(conn, '101')
        self.assertEqual((d.organization, d.ownership_status), (self.b, RMMDevice.OWNERSHIP_RESOLVED))
        self.assertNotEqual(d.linked_asset, asset)  # A's asset is never carried to B
        self.assertEqual(RMMAlert.objects.get(device=d).organization, self.b)

    def test_unlink_is_remembered_across_syncs(self):
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        staff = User.objects.create_superuser('rmma_unlink', 'u@x.test', 'pw')
        ra.leave_unlinked(self.device(conn, '101'), staff)
        assets_before = Asset.objects.count()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        d = self.device(conn, '101')
        self.assertIsNone(d.linked_asset)
        self.assertEqual(d.link_status, RMMDevice.LINK_UNLINKED)
        self.assertEqual(Asset.objects.count(), assets_before)

    def test_confirmed_link_survives_a_serial_change(self):
        asset = Asset.objects.create(organization=self.a, name='Reception PC', serial_number='SERIAL-OLD-1')
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        staff = User.objects.create_superuser('rmma_confirm', 'c@x.test', 'pw')
        ra.link_asset(self.device(conn, '101'), asset, staff)
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, serial='SERIAL-NEW-2')]))
        d = self.device(conn, '101')
        self.assertEqual((d.linked_asset, d.link_status), (asset, RMMDevice.LINK_CONFIRMED))

    def test_cannot_link_to_another_customers_asset(self):
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12)]))
        b_asset = Asset.objects.create(organization=self.b, name='B-PC')
        staff = User.objects.create_superuser('rmma_cross', 'x2@x.test', 'pw')
        with self.assertRaises(ValueError):
            ra.link_asset(self.device(conn, '101'), b_asset, staff)

    def test_repeated_syncs_and_a_concurrent_retry_create_one_asset(self):
        conn = self.ninja()
        routes = ninja_routes([ninja_device(101, 7, 12)])
        self.sync(conn, routes)
        self.sync(conn, routes)
        self.assertEqual(Asset.objects.filter(organization=self.a).count(), 1)
        # A second run while one holds the lock is refused, not run twice.
        self.assertTrue(acquire_sync_lock(conn))
        try:
            with self.assertRaises(SyncAlreadyRunning):
                self.sync(conn, routes)
        finally:
            release_sync_lock(conn)
        self.assertEqual(Asset.objects.filter(organization=self.a).count(), 1)

    def test_two_rmms_share_one_asset(self):
        asset = Asset.objects.create(organization=self.a, name='FRONTDESK', hostname='FRONTDESK')
        ninja = self.ninja()
        datto = self.connection('datto_rmm')
        self.map(datto, 'site-a', self.a)
        self.sync(ninja, ninja_routes([ninja_device(101, 7, 12)]))
        self.sync(datto, datto_routes([datto_device('d-1', 'site-a', 'Acme')]))
        self.assertEqual(asset.rmm_devices.count(), 2)
        self.assertEqual(len(ra.summaries_for_asset(asset)), 2)

    def test_technician_edits_are_kept(self):
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, serial='SN-ORIGINAL')]))
        asset = self.device(conn, '101').linked_asset
        asset.model = 'Tech-entered model'
        asset.save()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, serial='SN-ORIGINAL')]))
        asset.refresh_from_db()
        self.assertEqual(asset.model, 'Tech-entered model')

    def test_status_distinguishes_stale_from_offline(self):
        conn = self.ninja()
        self.sync(conn, ninja_routes([ninja_device(101, 7, 12, offline=True)]))
        d = self.device(conn, '101')
        self.assertEqual(ra.device_status(d)['state'], 'offline')
        from datetime import timedelta
        RMMDevice.objects.filter(pk=d.pk).update(data_refreshed_at=timezone.now() - timedelta(days=3))
        self.assertEqual(ra.device_status(self.device(conn, '101'))['state'], 'stale')
        RMMDevice.objects.filter(pk=d.pk).update(data_refreshed_at=None)
        self.assertEqual(ra.device_status(self.device(conn, '101'))['state'], 'unknown')


class ConsoleUrlTests(TestCase):

    def test_rules(self):
        hosts = {'app.atera.com'}
        ok = 'https://app.atera.com/new/device/1'
        self.assertEqual(validated_console_url(ok, hosts), ok)
        for bad in ('http://app.atera.com/x', 'https://user:pw@app.atera.com/x',
                    'https://app.atera.com/x?api_key=1', 'https://app.atera.com.evil.test/x',
                    'javascript:alert(1)', ''):
            with self.subTest(bad=bad):
                self.assertEqual(validated_console_url(bad, hosts), '')


# ---------------------------------------------------------------------------
# Upgrade: reconciliation
# ---------------------------------------------------------------------------

class ReconcileTests(_Base):

    def run_cmd(self, *args):
        out = StringIO()
        call_command('rmm_reconcile', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing_apply_fixes_and_rerun_is_a_no_op(self):
        conn = self.connection('ninjaone')
        self.map(conn, '7', self.a)
        b_asset = Asset.objects.create(organization=self.b, name='FRONTDESK', hostname='FRONTDESK')
        # As left by older versions: an unplaceable device under the owner,
        # and one of A's devices linked to B's asset by hostname.
        legacy = RMMDevice.objects.create(connection=conn, organization=self.msp, external_id='1',
                                          device_name='MYSTERY')
        crossed = RMMDevice.objects.create(connection=conn, organization=self.a, external_id='2',
                                           device_name='FRONTDESK', hostname='FRONTDESK', client_id='7',
                                           customer_key='id:7', linked_asset=b_asset, link_status='auto')
        RMMAlert.objects.create(connection=conn, organization=self.msp, device=crossed, external_id='al',
                                message='m', severity='warning', status='active',
                                triggered_at=timezone.now())

        # The cross-customer link is hidden before any reconciliation runs.
        self.assertEqual(list(ra.exposed_devices(b_asset)), [])

        out = self.run_cmd()
        self.assertIn('DRY RUN', out)
        self.assertIn('Links to another customer\'s asset (removed, or hidden until reviewed): 1', out)
        self.assertIn('Devices with no settled customer (hidden until reviewed): 1', out)
        legacy.refresh_from_db()
        crossed.refresh_from_db()
        self.assertEqual(legacy.organization, self.msp)
        self.assertEqual(crossed.linked_asset, b_asset)

        self.run_cmd('--apply')
        legacy.refresh_from_db()
        crossed.refresh_from_db()
        self.assertEqual((legacy.organization, legacy.ownership_status), (None, RMMDevice.OWNERSHIP_UNRESOLVED))
        # Cleared and sent to review, never re-pointed or recreated on its own.
        self.assertIsNone(crossed.linked_asset)
        self.assertEqual(crossed.link_status, RMMDevice.LINK_REVIEW)
        self.assertIn('belongs to another customer', crossed.link_note)
        self.assertEqual(RMMAlert.objects.get(external_id='al').organization, self.a)

        again = self.run_cmd('--apply')
        self.assertIn('Links to another customer\'s asset (removed, or hidden until reviewed): 0', again)
        self.assertIn('Assets created for unmatched devices: 0', again)
        self.assertIn('Customer changes', again.replace('Devices whose customer changed', 'Customer changes'))
        self.assertIn('Devices whose customer changed: 0', again)
        self.assertFalse(Asset.objects.filter(organization=self.a).exists())


# ---------------------------------------------------------------------------
# Tickets and visibility
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketAssetTests(_Base):

    def setUp(self):
        super().setUp()
        _setup_seed()
        _enable_psa_global()
        for org in (self.a, self.b):
            _enable_psa_for(org)
        self.tech = _make_msp_tech(User.objects.create_user('rmma_tech', 't@msp.test', 'pw'))
        for org in (self.msp, self.a, self.b):
            Membership.objects.create(user=self.tech, organization=org, role=Role.OWNER, is_active=True)
        self.customer = User.objects.create_user('rmma_cust', 'c@a.test', 'pw')
        Membership.objects.create(user=self.customer, organization=self.a, role=Role.EDITOR, is_active=True)

        self.conn = self.connection('ninjaone')
        self.map(self.conn, '7', self.a)
        self.asset_a = Asset.objects.create(organization=self.a, name='FRONTDESK', hostname='FRONTDESK')
        self.asset_b = Asset.objects.create(organization=self.b, name='B-SERVER')
        self.sync(self.conn, ninja_routes([ninja_device(101, 7, 12)],
                                          alerts=[{'uid': 'al-1', 'deviceId': 101, 'message': 'Disk full'}]))
        self.alert = RMMAlert.objects.get(connection=self.conn)

    def login(self, user, org):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = org.id
        s['2fa_prompted'] = True
        s.save()
        return c

    def form(self, **extra):
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType
        data = {'client': self.a.pk, 'subject': 'Printer jam', 'description': 'x',
                'queue': Queue.objects.first().pk, 'status': TicketStatus.objects.first().pk,
                'priority': TicketPriority.objects.first().pk, 'ticket_type': TicketType.objects.first().pk}
        data.update(extra)
        return data

    def test_create_with_own_asset_and_reject_another_customers(self):
        from psa.models import Ticket
        c = self.login(self.tech, self.a)
        c.post('/psa/new/', self.form(related_asset=self.asset_a.pk))
        self.assertEqual(Ticket.objects.get(subject='Printer jam').related_asset, self.asset_a)

        c.post('/psa/new/', self.form(subject='Sneaky', related_asset=self.asset_b.pk))
        self.assertFalse(Ticket.objects.filter(subject='Sneaky').exists())

    def test_asset_picker_lists_only_the_clients_assets(self):
        c = self.login(self.tech, self.a)
        names = [a['name'] for a in c.get(f'/psa/new/assets/?client={self.a.pk}').json()['assets']]
        self.assertEqual(names, ['FRONTDESK'])

    def test_alert_with_verified_device_preselects_asset(self):
        c = self.login(self.tech, self.a)
        r = c.get(f'/psa/new/?rmm_alert={self.alert.pk}')
        self.assertEqual(r.context['preselected_client_id'], self.a.pk)
        self.assertEqual(r.context['preselected_asset_id'], self.asset_a.pk)
        self.assertIn('FRONTDESK', r.context['prefill_subject'])

    def test_alert_of_unsettled_device_prefills_nothing(self):
        RMMDevice.objects.filter(pk=self.alert.device_id).update(
            ownership_status=RMMDevice.OWNERSHIP_MOVED, organization=None)
        r = self.login(self.tech, self.a).get(f'/psa/new/?rmm_alert={self.alert.pk}')
        self.assertIsNone(r.context['preselected_asset_id'])

    def _ticket(self, asset=None):
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        return Ticket.objects.create(
            organization=self.a, subject='Slow PC', description='x', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.get(slug='new'), client_can_view=True, related_asset=asset)

    def test_set_asset_rejects_another_customers_asset(self):
        t = self._ticket()
        c = self.login(self.tech, self.a)
        c.post(f'/psa/t/{t.ticket_number}/action/', {'action': 'set_asset', 'asset': self.asset_b.pk})
        t.refresh_from_db()
        self.assertIsNone(t.related_asset)
        c.post(f'/psa/t/{t.ticket_number}/action/', {'action': 'set_asset', 'asset': self.asset_a.pk})
        t.refresh_from_db()
        self.assertEqual(t.related_asset, self.asset_a)

    def test_rmm_summary_for_technicians_only(self):
        t = self._ticket(self.asset_a)
        staff_page = self.login(self.tech, self.a).get(f'/psa/t/{t.ticket_number}/').content.decode()
        self.assertIn('ticket-asset-card', staff_page)
        self.assertIn('NinjaOne', staff_page)
        self.assertIn('Open in', staff_page)

        r = self.login(self.customer, self.a).get(f'/psa/t/{t.ticket_number}/')
        page = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('ticket-asset-card', page)
        self.assertNotIn('rmm-summary', page)
        self.assertNotIn('/integrations/rmm/devices/', page)

    def test_customer_cannot_use_set_asset(self):
        t = self._ticket()
        self.login(self.customer, self.a).post(f'/psa/t/{t.ticket_number}/action/',
                                               {'action': 'set_asset', 'asset': self.asset_a.pk})
        t.refresh_from_db()
        self.assertIsNone(t.related_asset)

    def test_alerts_page_hides_unsettled_devices(self):
        c = self.login(self.tech, self.a)
        self.assertContains(c.get('/integrations/rmm/alerts/'), 'Disk full')
        RMMDevice.objects.filter(pk=self.alert.device_id).update(
            ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED, organization=None)
        self.assertNotContains(c.get('/integrations/rmm/alerts/'), 'Disk full')

    def test_review_queue_and_decisions(self):
        conn = self.connection('ninjaone')
        self.sync(conn, ninja_routes([ninja_device(201, 50, 1)], orgs=((50, 'Unknown Co'),)))
        d = self.device(conn, '201')
        c = self.login(self.tech, self.msp)
        self.assertContains(c.get(f'/integrations/rmm/{conn.pk}/review/'), 'Unknown Co')
        c.post(f'/integrations/rmm/devices/{d.pk}/decide/', {'action': 'map_customer', 'organization': self.b.pk})
        d.refresh_from_db()
        self.assertEqual((d.organization, d.ownership_status), (self.b, RMMDevice.OWNERSHIP_RESOLVED))
        self.assertEqual(ra.mapped_organization(conn, ra.reported_identity(d)), self.b)
        # A customer user can't decide anything.
        self.login(self.customer, self.a).post(f'/integrations/rmm/devices/{d.pk}/decide/',
                                               {'action': 'assign_customer', 'organization': self.a.pk})
        d.refresh_from_db()
        self.assertEqual(d.organization, self.b)


    def test_ticket_offers_connect_to_technicians_only(self):
        conn = self.connection('rem0te', scope=RMMConnection.CUSTOMER_SCOPE_SINGLE, owner=self.a)
        self.sync(conn, rem0te_routes('biz-a', [[rem0te_computer('c-1', 'biz-a')]]))
        self.assertEqual(self.device(conn, 'c-1').linked_asset, self.asset_a)
        t = self._ticket(self.asset_a)
        staff_page = self.login(self.tech, self.a).get(f'/psa/t/{t.ticket_number}/').content.decode()
        self.assertIn('Connect with Rem0te', staff_page)
        self.assertIn('https://remote.example.com/endpoints/c-1', staff_page)

        page = self.login(self.customer, self.a).get(f'/psa/t/{t.ticket_number}/').content.decode()
        self.assertNotIn('Rem0te', page)
        self.assertNotIn('remote.example.com', page)

    def test_client_import_is_not_offered(self):
        conn = self.connection('rem0te', scope=RMMConnection.CUSTOMER_SCOPE_SINGLE, owner=self.a)
        c = self.login(self.tech, self.a)
        self.assertNotContains(c.get(f'/integrations/rmm/{conn.pk}/'), 'Import Clients')
        r = c.get(f'/integrations/rmm/{conn.pk}/import-clients/')
        self.assertEqual(r.status_code, 302)


# ---------------------------------------------------------------------------
# Rem0te: one API key, one business, one organization
# ---------------------------------------------------------------------------

def rem0te_computer(cid, business, name='FRONTDESK', serial='', ip='192.168.1.10', status='ACTIVE',
                    online=True, site=None):
    return {'id': cid, 'name': name, 'hostname': name, 'status': status, 'platform': 'Windows',
            'osVersion': 'Microsoft Windows NT 10.0.26100.0', 'ipAddress': ip, 'macAddress': '00:11:22:33:44:55',
            'serialNumber': serial, 'isOnline': online, 'isManaged': True,
            'lastSeenAt': '2026-11-08T09:00:00.000Z', 'customerId': business,
            'customer': {'id': business, 'name': f'Business {business}'}, 'site': site,
            'rustdeskNode': {'rustdeskId': '145925926', 'lastSeenAt': '2026-11-08T09:00:00.000Z',
                             'hasPassword': True, 'permanentPassword': 'should-never-be-kept'}}


def rem0te_routes(business, pages, scopes=('computers:read',)):
    """`pages` is a list of computer lists, one per page."""
    def computers(kw):
        page = (kw.get('params') or {}).get('page', 1)
        rows = pages[page - 1] if page <= len(pages) else []
        return {'success': True, 'data': {'endpoints': rows, 'total': sum(map(len, pages)),
                                          'page': page, 'limit': 200, 'pages': len(pages)}}
    return {
        ('GET', '/whoami'): {'success': True, 'businessId': business, 'apiKeyId': 'k', 'scopes': list(scopes)},
        ('GET', '/computers'): computers,
    }


class Rem0teAdapterTests(_Base):

    def rem0te(self, owner, **kw):
        return self.connection('rem0te', scope=RMMConnection.CUSTOMER_SCOPE_SINGLE, owner=owner, **kw)

    def test_each_key_files_computers_under_its_own_customer_only(self):
        conn_a, conn_b = self.rem0te(self.a), self.rem0te(self.b)
        asset_a = Asset.objects.create(organization=self.a, name='FRONTDESK', hostname='FRONTDESK')
        asset_b = Asset.objects.create(organization=self.b, name='FRONTDESK', hostname='FRONTDESK')
        # Same hostname and IP at both customers.
        self.sync(conn_a, rem0te_routes('biz-a', [[rem0te_computer('c-a', 'biz-a')]]))
        self.sync(conn_b, rem0te_routes('biz-b', [[rem0te_computer('c-b', 'biz-b')]]))
        da, db = self.device(conn_a, 'c-a'), self.device(conn_b, 'c-b')
        self.assertEqual((da.organization, da.linked_asset), (self.a, asset_a))
        self.assertEqual((db.organization, db.linked_asset), (self.b, asset_b))
        self.assertEqual([d.pk for d in ra.exposed_devices(asset_a)], [da.pk])
        self.assertEqual([d.pk for d in ra.exposed_devices(asset_b)], [db.pk])
        self.assertEqual((da.client_id, da.os_type, da.serial_number, da.is_online),
                         ('biz-a', 'windows', '', True))

    def test_pages_archived_foreign_and_credentials(self):
        conn = self.rem0te(self.a, map_to_assets=False)
        self.sync(conn, rem0te_routes('biz-a', [
            [rem0te_computer('c-1', 'biz-a', serial='SN1'), rem0te_computer('c-2', 'biz-a', name='OLD',
                                                                             status='ARCHIVED')],
            [rem0te_computer('c-3', 'biz-a', name='LAPTOP'), rem0te_computer('c-x', 'biz-other', name='THEIRS')],
        ]))
        self.assertEqual(sorted(RMMDevice.objects.filter(connection=conn).values_list('external_id', flat=True)),
                         ['c-1', 'c-3'])
        d = self.device(conn, 'c-1')
        self.assertEqual(d.serial_number, 'SN1')
        self.assertNotIn('should-never-be-kept', str(d.raw_data))
        self.assertEqual(d.raw_data['rustdeskNode']['rustdeskId'], '145925926')

    def test_key_for_another_business_stops_the_sync(self):
        conn = self.rem0te(self.a)
        self.sync(conn, rem0te_routes('biz-a', [[rem0te_computer('c-1', 'biz-a')]]))
        conn.refresh_from_db()
        self.assertEqual(conn.field_mappings['rem0te_business_id'], 'biz-a')

        # Someone pastes Bolt's key into Acme's connection.
        with self.assertRaisesMessage(Exception, 'different business'):
            self.sync(conn, rem0te_routes('biz-b', [[rem0te_computer('c-b', 'biz-b', name='BOLT-PC')]]))
        conn.refresh_from_db()
        self.assertEqual(conn.last_sync_status, 'error')
        self.assertFalse(RMMDevice.objects.filter(external_id='c-b').exists())
        self.assertIn('different business', conn.last_error)
        self.assertEqual(conn.field_mappings['rem0te_business_id'], 'biz-a')

    def test_connect_link_opens_the_computer_page_without_credentials(self):
        conn = self.rem0te(self.a, base_url='https://remote.example.com/api/v1/pub/v1/')
        self.sync(conn, rem0te_routes('biz-a', [[rem0te_computer('c-1', 'biz-a')]]))
        d = self.device(conn, 'c-1')
        self.assertEqual(ra.console_link(d), 'https://remote.example.com/endpoints/c-1')
        self.assertEqual(ra.console_label(d), 'Connect with Rem0te')
        RMMConnection.objects.filter(pk=conn.pk).update(base_url='http://remote.example.com')
        d = self.device(conn, 'c-1')
        self.assertEqual(ra.console_link(d), '')  # https only

    def test_connection_test_names_a_missing_scope(self):
        conn = self.rem0te(self.a)
        for scopes, ok in ((('computers:read',), True), (('users:read',), False)):
            vendor = _Vendor(rem0te_routes('biz-a', [[]], scopes=scopes))
            with mock.patch.object(Rem0teProvider, '_make_request', side_effect=vendor):
                self.assertEqual(Rem0teProvider(conn).test_connection(), ok)
            self.assertEqual(vendor.calls[0], ('GET', '/whoami'))

    def test_form_forces_single_customer_and_no_import(self):
        from integrations.forms import RMMConnectionForm
        form = RMMConnectionForm(data={
            'provider_type': 'rem0te', 'name': 'Acme remote', 'base_url': 'https://remote.example.com',
            'customer_scope': RMMConnection.CUSTOMER_SCOPE_MULTI, 'import_organizations': 'on',
            'sync_enabled': 'on', 'sync_devices': 'on', 'map_to_assets': 'on', 'sync_interval_minutes': 60,
            'rem0te_api_key': 'rk_' + '0' * 48,
        }, organization=self.a)
        self.assertTrue(form.is_valid(), form.errors)
        conn = form.save()
        self.assertEqual((conn.customer_scope, conn.import_organizations, conn.organization),
                         (RMMConnection.CUSTOMER_SCOPE_SINGLE, False, self.a))
        self.assertEqual(conn.get_credentials(), {'api_key': 'rk_' + '0' * 48})

