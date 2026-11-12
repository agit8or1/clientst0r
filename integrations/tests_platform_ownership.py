"""Integrations belong to the platform owner.

A connection with no organization is platform-owned; one with an
organization is that customer's own. These tests pin down:

* the authorization matrix (integrations.ownership) for every create /
  detail / edit / delete / sync / test view of each connection type;
* that data a platform connection has not mapped to a customer is never
  shown to a customer, and mapped data only to its own customer;
* the "Make platform-owned" action (view and management command);
* that customer-owned connections keep their per-organization behaviour.
"""
import importlib
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate, UserType
from audit.models import AuditLog
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE

from .models import (AccountingConnection, AccountingCustomerLink, ExternalObjectMap, GrandstreamConnection,
                     M365Connection, OmadaConnection, PSACompany, PSAConnection, PSAContact, PSATicket,
                     RMMConnection, RMMDevice, UnifiConnection)
from . import ownership


def _psa(org, name='PSA'):
    c = PSAConnection(organization=org, provider_type='syncro', name=name, base_url='https://psa.example.test')
    c.set_credentials({'api_key': 'k'})
    c.save()
    return c


def _rmm(org, name='RMM', **kw):
    c = RMMConnection(organization=org, provider_type='tactical_rmm', name=name,
                      base_url='https://rmm.example.test', **kw)
    c.set_credentials({'api_key': 'k'})
    c.save()
    return c


def _unifi(org, name='UniFi'):
    return UnifiConnection.objects.create(organization=org, name=name, host='https://unifi.example.test')


def _m365(org, name='M365'):
    return M365Connection.objects.create(organization=org, name=name, tenant_id='tenant-' + name)


def _omada(org, name='Omada', **kw):
    return OmadaConnection.objects.create(organization=org, name=name, host='https://omada.example.test', **kw)


def _grandstream(org, name='GWN', **kw):
    return GrandstreamConnection.objects.create(organization=org, name=name, **kw)


# type key, factory, detail, edit, delete, sync, test (url names; None = no such view)
TYPES = [
    ('psa', _psa, 'integration_detail', 'integration_edit', 'integration_delete', 'integration_sync',
     'integration_test'),
    ('rmm', _rmm, 'rmm_detail', 'rmm_edit', 'rmm_delete', 'rmm_trigger_sync', None),
    ('unifi', _unifi, 'unifi_detail', 'unifi_edit', 'unifi_delete', 'unifi_sync', 'unifi_test'),
    ('m365', _m365, 'm365_detail', 'm365_edit', 'm365_delete', 'm365_sync', 'm365_test'),
    ('omada', _omada, 'omada_detail', 'omada_edit', 'omada_delete', 'omada_sync', 'omada_test'),
    ('grandstream', _grandstream, 'grandstream_detail', 'grandstream_edit', 'grandstream_delete',
     'grandstream_sync', 'grandstream_test'),
]
CREATE = {'psa': 'integration_create', 'rmm': 'rmm_create', 'unifi': 'unifi_create', 'm365': 'm365_create',
          'omada': 'omada_create', 'grandstream': 'grandstream_create'}


def _url(name, pk=None):
    return reverse(f'integrations:{name}', args=[pk] if pk is not None else [])


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Acme Own', slug='acme-own')
        cls.b = Organization.objects.create(name='Bolt Own', slug='bolt-own')
        cls.root = User.objects.create_superuser('own_root', 'r@x.test', 'pw')
        cls.org_admin = cls._customer('own_admin_a', cls.a, Role.ADMIN)
        cls.org_owner = cls._customer('own_owner_a', cls.a, Role.OWNER)
        cls.portal = cls._customer('own_portal_a', cls.a, Role.READONLY)
        cls.admin_b = cls._customer('own_admin_b', cls.b, Role.ADMIN)
        cls.tech_plain = cls._staff('own_tech_plain', None)
        cls.tech_view = cls._staff('own_tech_view', cls._role('Own view', integrations_view=True))
        cls.tech_sync = cls._staff('own_tech_sync', cls._role('Own sync', integrations_view=True,
                                                             integrations_sync=True))
        cls.tech_conf = cls._staff('own_tech_conf', cls._role('Own conf', integrations_view=True,
                                                             integrations_sync=True,
                                                             integrations_configure=True))

    @staticmethod
    def _role(name, **flags):
        return RoleTemplate.objects.create(name=name, **flags)

    @staticmethod
    def _customer(name, org, role):
        u = User.objects.create_user(name, f'{name}@x.test', 'pw')
        Membership.objects.create(user=u, organization=org, role=role, is_active=True)
        return u

    @staticmethod
    def _staff(name, role):
        u = User.objects.create_user(name, f'{name}@x.test', 'pw')
        u.profile.user_type = UserType.STAFF
        u.profile.global_role_template = role
        u.profile.save()
        return u

    def client_for(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is None:
            s['global_view_mode'] = True
            s.pop('current_organization_id', None)
        else:
            s['current_organization_id'] = org.pk
            s['global_view_mode'] = False
        s.save()
        return c


class AuthorizationHelperTests(_Base):

    def test_platform_rights(self):
        self.assertTrue(ownership.can_manage_platform(self.root))
        self.assertTrue(ownership.can_manage_platform(self.tech_conf))
        for u in (self.tech_sync, self.tech_view, self.tech_plain, self.org_admin, self.org_owner, self.portal):
            self.assertFalse(ownership.can_manage_platform(u), u.username)
        self.assertTrue(ownership.can_sync_platform(self.tech_sync))
        self.assertFalse(ownership.can_sync_platform(self.tech_view))
        self.assertTrue(ownership.can_view_platform(self.tech_view))
        for u in (self.tech_plain, self.org_admin, self.org_owner, self.portal):
            self.assertFalse(ownership.can_view_platform(u), u.username)

    def test_customer_with_granting_role_still_no_platform_rights(self):
        # A customer user's own role at its organization never reaches the platform.
        role = self._role('Cust all', integrations_view=True, integrations_sync=True, integrations_configure=True)
        u = self._customer('own_cust_role', self.a, Role.OWNER)
        u.profile.global_role_template = role
        u.profile.save()
        self.assertFalse(ownership.can_view_platform(u))

    def test_owner_choices_only_for_platform_managers(self):
        self.assertEqual(ownership.owner_choices(self.org_admin), [])
        keys = [k for k, _ in ownership.owner_choices(self.root)]
        self.assertEqual(keys[0], '')
        self.assertIn(str(self.a.pk), keys)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PlatformConnectionMatrixTests(_Base):
    """Every view of every type, against a platform-owned connection."""

    def setUp(self):
        self.conns = {key: factory(None, name=f'Platform {key}') for key, factory, *_ in TYPES}

    def _assert_unchanged(self, key):
        conn = self.conns[key]
        fresh = type(conn).objects.filter(pk=conn.pk).first()
        self.assertIsNotNone(fresh, f'{key} connection was deleted')
        self.assertEqual(fresh.name, conn.name)
        self.assertIsNone(fresh.organization_id)

    def _denied(self, client, key, detail=True):
        _, _, d, e, x, s, t = next(row for row in TYPES if row[0] == key)
        pk = self.conns[key].pk
        checks = [('get', e), ('post', e), ('get', x), ('post', x), ('post', s)]
        if detail:
            checks.insert(0, ('get', d))
        if t:
            checks.append(('post', t))
        with mock.patch('integrations.views.get_provider') as p1, \
                mock.patch('integrations.views.get_rmm_provider') as p2:
            for method, name in checks:
                r = getattr(client, method)(_url(name, pk), {'name': 'hijacked'})
                self.assertIn(r.status_code, (403, 404), f'{key} {method} {name}: {r.status_code}')
            p1.assert_not_called()
            p2.assert_not_called()
        self._assert_unchanged(key)

    def test_customer_org_admin_and_owner_cannot_reach_platform_connections(self):
        for user in (self.org_admin, self.org_owner):
            c = self.client_for(user, self.a)
            for key, *_ in TYPES:
                with self.subTest(user=user.username, type=key):
                    self._denied(c, key)

    def test_portal_user_cannot_reach_platform_connections(self):
        c = self.client_for(self.portal, self.a)
        for key, *_ in TYPES:
            with self.subTest(type=key):
                self._denied(c, key)

    def test_staff_inside_a_customer_cannot_reach_platform_connections(self):
        # Even a superuser: platform connections are managed from global view.
        c = self.client_for(self.root, self.a)
        for key, *_ in TYPES:
            with self.subTest(type=key):
                self._denied(c, key)

    def test_tech_without_global_role_denied_in_global_view(self):
        c = self.client_for(self.tech_plain)
        for key, *_ in TYPES:
            with self.subTest(type=key):
                self._denied(c, key)

    def test_tech_with_view_role_can_view_only(self):
        c = self.client_for(self.tech_view)
        for key, _, d, *_ in TYPES:
            with self.subTest(type=key):
                self.assertEqual(c.get(_url(d, self.conns[key].pk)).status_code, 200)
                self._denied(c, key, detail=False)

    def test_tech_with_sync_role_cannot_edit_or_delete(self):
        c = self.client_for(self.tech_sync)
        for key, _, d, e, x, *_ in TYPES:
            with self.subTest(type=key):
                pk = self.conns[key].pk
                self.assertEqual(c.get(_url(d, pk)).status_code, 200)
                for method, name in (('get', e), ('post', e), ('get', x), ('post', x)):
                    self.assertEqual(getattr(c, method)(_url(name, pk), {'name': 'x'}).status_code, 403)
                self._assert_unchanged(key)

    def test_platform_admins_manage_from_global_view(self):
        for user in (self.root, self.tech_conf):
            c = self.client_for(user)
            for key, _, d, e, x, *_ in TYPES:
                with self.subTest(user=user.username, type=key):
                    pk = self.conns[key].pk
                    self.assertEqual(c.get(_url(d, pk)).status_code, 200)
                    self.assertEqual(c.get(_url(e, pk)).status_code, 200)
                    self.assertEqual(c.get(_url(x, pk)).status_code, 200)

    def test_platform_admin_can_delete(self):
        c = self.client_for(self.tech_conf)
        for key, _, _, _, x, *_ in TYPES:
            with self.subTest(type=key):
                conn = self.conns[key]
                r = c.post(_url(x, conn.pk))
                self.assertEqual(r.status_code, 302)
                self.assertFalse(type(conn).objects.filter(pk=conn.pk).exists())

    def test_sync_role_passes_the_sync_gate(self):
        c = self.client_for(self.tech_sync)
        with mock.patch('integrations.views.get_provider') as gp:
            gp.return_value.test_connection.return_value = False
            r = c.post(_url('unifi_sync', self.conns['unifi'].pk))
        self.assertNotIn(r.status_code, (403, 404))

    def test_create_pages_in_global_view(self):
        c = self.client_for(self.root)
        for key, url_name in CREATE.items():
            with self.subTest(type=key):
                r = c.get(_url(url_name))
                self.assertEqual(r.status_code, 200)
                body = r.content.decode()
                self.assertNotIn('select an organization first', body.lower())
                self.assertIn('Platform (the MSP)', body)

    def test_create_pages_denied_without_platform_rights(self):
        for user in (self.tech_plain, self.tech_view, self.tech_sync):
            c = self.client_for(user)
            for key, url_name in CREATE.items():
                with self.subTest(user=user.username, type=key):
                    self.assertEqual(c.get(_url(url_name)).status_code, 403)

    def test_platform_admin_creates_platform_and_customer_connections(self):
        c = self.client_for(self.root)
        data = {'name': 'HQ controller', 'mode': 'self_hosted', 'host': 'https://unifi.example.test',
                'api_key': 'key', 'is_active': 'on', 'owner': ''}
        r = c.post(_url('unifi_create'), data)
        self.assertEqual(r.status_code, 302, r.content.decode()[:500])
        self.assertIsNone(UnifiConnection.objects.get(name='HQ controller').organization_id)
        data.update(name='Acme site', owner=str(self.a.pk))
        c.post(_url('unifi_create'), data)
        self.assertEqual(UnifiConnection.objects.get(name='Acme site').organization_id, self.a.pk)

    def test_org_admin_create_is_customer_owned_and_ignores_owner_field(self):
        c = self.client_for(self.org_admin, self.a)
        r = c.post(_url('unifi_create'), {'name': 'Mine', 'mode': 'self_hosted', 'host': 'https://unifi.example.test',
                                         'api_key': 'key', 'is_active': 'on', 'owner': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(UnifiConnection.objects.get(name='Mine').organization_id, self.a.pk)

    def test_edit_never_changes_owner(self):
        c = self.client_for(self.root)
        conn = self.conns['unifi']
        c.post(_url('unifi_edit', conn.pk), {'name': 'Renamed', 'mode': 'self_hosted',
                                             'host': 'https://unifi.example.test', 'is_active': 'on',
                                             'owner': str(self.a.pk)})
        conn.refresh_from_db()
        self.assertEqual(conn.name, 'Renamed')
        self.assertIsNone(conn.organization_id)

    def test_platform_rmm_cannot_be_rem0te_or_paired(self):
        from .forms import RMMConnectionForm
        form = RMMConnectionForm(data={'name': 'R', 'provider_type': 'rem0te', 'base_url': 'https://r.test',
                                       'owner': ''},
                                 organization=None, owner_choices=ownership.owner_choices(self.root))
        self.assertFalse(form.is_valid())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerOwnedConnectionTests(_Base):
    """Existing per-organization behaviour still works."""

    def setUp(self):
        self.conns = {key: factory(self.a, name=f'Acme {key}') for key, factory, *_ in TYPES}

    def test_owner_admin_manages_own_connections(self):
        c = self.client_for(self.org_admin, self.a)
        for key, _, d, e, x, *_ in TYPES:
            if key == 'rmm':
                continue  # RMM pages are MSP-staff only (rmm_staff_only), unchanged
            with self.subTest(type=key):
                pk = self.conns[key].pk
                self.assertEqual(c.get(_url(d, pk)).status_code, 200)
                self.assertEqual(c.get(_url(e, pk)).status_code, 200)
                self.assertEqual(c.get(_url(x, pk)).status_code, 200)

    def test_other_customers_admin_cannot_reach_them(self):
        c = self.client_for(self.admin_b, self.b)
        for key, _, d, e, x, s, t in TYPES:
            with self.subTest(type=key):
                pk = self.conns[key].pk
                for method, name in (('get', d), ('get', e), ('post', e), ('post', x), ('post', s)):
                    self.assertIn(getattr(c, method)(_url(name, pk), {'name': 'x'}).status_code, (403, 404))
                self.assertTrue(type(self.conns[key]).objects.filter(pk=pk, name=f'Acme {key}').exists())

    def test_portal_user_cannot_edit_own_customers_connection(self):
        c = self.client_for(self.portal, self.a)
        for key, _, d, e, x, *_ in TYPES:
            with self.subTest(type=key):
                pk = self.conns[key].pk
                self.assertIn(c.post(_url(e, pk), {'name': 'x'}).status_code, (302, 403, 404))
                self.assertIn(c.post(_url(x, pk)).status_code, (302, 403, 404))
                self.assertTrue(type(self.conns[key]).objects.filter(pk=pk, name=f'Acme {key}').exists())

    def test_platform_staff_see_customer_owned_in_global_view(self):
        c = self.client_for(self.tech_view)
        body = c.get(_url('integration_list')).content.decode()
        self.assertIn('Acme psa', body)
        self.assertIn('Acme Own', body)  # owner label

    def test_single_customer_rmm_still_files_into_owner(self):
        from .rmm_association import resolve_customer
        conn = self.conns['rmm']
        conn.customer_scope = RMMConnection.CUSTOMER_SCOPE_SINGLE
        conn.save()
        self.assertEqual(resolve_customer(conn, {'client_id': 'x', 'client_name': 'X'}).organization, self.a)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class IntegrationListTests(_Base):

    def setUp(self):
        self.platform_psa = _psa(None, 'Platform Desk')
        self.acme_m365 = _m365(self.a, 'Acme Tenant')
        self.bolt_m365 = _m365(self.b, 'Bolt Tenant')
        PSACompany.objects.create(connection=self.platform_psa, organization=self.a, external_id='1', name='Acme Co')

    def test_global_view_lists_platform_first_with_add_buttons(self):
        body = self.client_for(self.root).get(_url('integration_list')).content.decode()
        self.assertIn('Integrations belong to the platform', body)
        self.assertNotIn('choose one to see and add', body)
        self.assertIn('Platform Desk', body)
        self.assertLess(body.index('Platform Desk'), body.index('Acme Tenant'))
        self.assertIn(reverse('integrations:make_platform_owned', args=['m365', self.acme_m365.pk]), body)
        self.assertIn(_url('rmm_create'), body)

    def test_view_only_tech_gets_no_make_platform_or_add(self):
        body = self.client_for(self.tech_view).get(_url('integration_list')).content.decode()
        self.assertIn('Platform Desk', body)
        self.assertNotIn('make-platform', body)
        self.assertNotIn(_url('rmm_create'), body)

    def test_tech_without_global_role_sees_no_platform_connection(self):
        body = self.client_for(self.tech_plain).get(_url('integration_list')).content.decode()
        self.assertNotIn('Platform Desk', body)
        self.assertNotIn('Acme Tenant', body)

    def test_customer_sees_only_own_connections_and_a_credential_free_note(self):
        body = self.client_for(self.org_admin, self.a).get(_url('integration_list')).content.decode()
        self.assertIn('Acme Tenant', body)
        self.assertNotIn('Bolt Tenant', body)
        self.assertNotIn('Platform Desk', body)  # customer users see only the kind
        self.assertIn('platform-suppliers-note', body)
        self.assertNotIn(_url('integration_detail', self.platform_psa.pk), body)
        self.assertNotIn('make-platform', body)

    def test_staff_inside_customer_see_supplier_name(self):
        body = self.client_for(self.root, self.a).get(_url('integration_list')).content.decode()
        self.assertIn('PSA: Platform Desk', body)
        self.assertNotIn('Bolt Tenant', body)

    def test_customer_b_gets_no_note(self):
        body = self.client_for(self.admin_b, self.b).get(_url('integration_list')).content.decode()
        self.assertNotIn('platform-suppliers-note', body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UnmappedDataIsolationTests(_Base):
    """Data a platform connection has not mapped stays with platform staff."""

    def setUp(self):
        self.psa = _psa(None, 'Platform Desk')
        self.co_a = PSACompany.objects.create(connection=self.psa, organization=self.a, external_id='1',
                                              name='Zeta Mapped A')
        self.co_b = PSACompany.objects.create(connection=self.psa, organization=self.b, external_id='2',
                                              name='Zeta Mapped B')
        self.co_none = PSACompany.objects.create(connection=self.psa, organization=None, external_id='3',
                                                 name='Zeta Pending')
        self.contact_none = PSAContact.objects.create(connection=self.psa, organization=None, company=self.co_none,
                                                      external_id='c3', first_name='Zeta', last_name='Person',
                                                      email='z@x.test')
        self.ticket_b = PSATicket.objects.create(connection=self.psa, organization=self.b, company=self.co_b,
                                                 external_id='t2', ticket_number='T-2', subject='Zeta B ticket')

    def test_customer_users_get_no_synced_psa_pages(self):
        # Synced PSA rows (raw provider JSON included) are MSP-staff tooling
        # since authz-tech; before, a customer saw its own mapped rows.
        c = self.client_for(self.org_admin, self.a)
        for url in (_url('psa_companies'), _url('psa_contacts'), _url('psa_tickets'),
                    _url('psa_company_detail', self.co_none.pk),
                    _url('psa_company_detail', self.co_b.pk),
                    _url('psa_contact_detail', self.contact_none.pk),
                    _url('psa_ticket_detail', self.ticket_b.pk)):
            with self.subTest(url):
                self.assertEqual(c.get(url).status_code, 403)

    def test_company_detail_hides_other_customers_tickets(self):
        # Same external company, but a ticket filed under another customer.
        PSATicket.objects.create(connection=self.psa, organization=self.b, company=self.co_a,
                                 external_id='t9', ticket_number='T-9', subject='Leaky ticket')
        body = self.client_for(self.org_admin, self.a).get(_url('psa_company_detail', self.co_a.pk)).content.decode()
        self.assertNotIn('Leaky ticket', body)

    def test_search_never_returns_pending_rows_to_customers(self):
        c = self.client_for(self.org_owner, self.a)
        body = c.get('/core/search/', {'q': 'Zeta'}).content.decode()
        self.assertNotIn('Zeta Pending', body)
        self.assertNotIn('Zeta Mapped B', body)

    def test_search_shows_pending_rows_to_platform_staff_in_global_view(self):
        body = self.client_for(self.root).get('/core/search/', {'q': 'Zeta'}).content.decode()
        self.assertIn('Zeta Pending', body)
        body = self.client_for(self.tech_plain).get('/core/search/', {'q': 'Zeta'}).content.decode()
        self.assertNotIn('Zeta Pending', body)

    def test_mapping_page_platform_only_and_assigns_children(self):
        url = _url('psa_organization_mapping', self.psa.pk)
        self.assertIn(self.client_for(self.org_admin, self.a).get(url).status_code, (403, 404))
        c = self.client_for(self.root)
        self.assertEqual(c.get(url).status_code, 200)
        from .psa_assignment import assign_company
        assign_company(self.co_none, self.a, self.root)
        self.contact_none.refresh_from_db()
        self.assertEqual(self.contact_none.organization_id, self.a.pk)

    def test_customer_owned_psa_maps_only_within_owner(self):
        from .psa_assignment import mapping_targets
        own = _psa(self.a, 'Acme Desk')
        self.assertNotIn(self.b.pk, {o.pk for o in mapping_targets(own)})
        self.assertIn(self.b.pk, {o.pk for o in mapping_targets(self.psa)})

    def test_rmm_unmapped_customer_stays_unresolved(self):
        from .rmm_association import customer_identity, map_customer, resolve_customer
        conn = _rmm(None, 'Platform RMM', customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        self.assertFalse(conn.is_single_customer)  # a platform connection has no single customer
        unknown = resolve_customer(conn, {'client_id': '77', 'client_name': 'Nobody'})
        self.assertIsNone(unknown.organization)
        self.assertEqual(unknown.status, RMMDevice.OWNERSHIP_UNRESOLVED)
        map_customer(conn, customer_identity({'client_id': '42', 'client_name': 'Bolt'}), self.b)
        self.assertEqual(resolve_customer(conn, {'client_id': '42', 'client_name': 'Bolt'}).organization, self.b)

    def test_platform_controller_imports_only_mapped_sites(self):
        from assets.models import Asset
        from .network_assets import import_flat_devices
        conn = _omada(None, 'Platform Omada', site_org_map={'s1': self.a.pk})
        data = {'sites': [
            {'id': 's1', 'name': 'Acme HQ', 'devices': [{'mac': 'aa:bb:cc:00:00:01', 'name': 'AP-A'}]},
            {'id': 's2', 'name': 'Unknown', 'devices': [{'mac': 'aa:bb:cc:00:00:02', 'name': 'AP-X'}]},
        ]}
        result = import_flat_devices(conn, 'omada', data)
        self.assertEqual(result['skipped_sites'], 1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(Asset.objects.get(name='AP-A').organization_id, self.a.pk)
        self.assertFalse(Asset.objects.filter(name='AP-X').exists())

    def test_single_site_platform_controller_is_not_guessed(self):
        from .network_assets import resolve_unifi_sites, UNMAPPED
        conn = _unifi(None, 'Platform UniFi')
        res = resolve_unifi_sites(conn, [{'id': 'x', 'name': 'Only', 'devices': []}])
        self.assertEqual(res[0].status, UNMAPPED)

    def test_omada_site_mapping_view(self):
        conn = _omada(None, 'Platform Omada', cached_data={'sites': [{'id': 's1', 'name': 'HQ', 'devices': []}]})
        url = _url('omada_site_org', conn.pk)
        self.assertIn(self.client_for(self.org_admin, self.a).post(url, {'site__s1': self.a.pk}).status_code,
                      (403, 404))
        self.assertEqual(self.client_for(self.tech_sync).post(url, {'site__s1': self.a.pk}).status_code, 403)
        c = self.client_for(self.root)
        self.assertIn('Site → customer mapping', c.get(_url('omada_detail', conn.pk)).content.decode())
        c.post(url, {'site__s1': str(self.b.pk)})
        conn.refresh_from_db()
        self.assertEqual(conn.site_org_map, {'s1': self.b.pk})
        self.assertTrue(AuditLog.objects.filter(object_type='omada_connection', object_id=conn.pk).exists())

    def test_customer_owned_unifi_cannot_map_sites_to_another_customer(self):
        conn = _unifi(self.a, 'Acme UniFi')
        r = self.client_for(self.root, self.a).post(_url('unifi_site_org', conn.pk),
                                                   data='{"site_org_map": {"s": %d}}' % self.b.pk,
                                                   content_type='application/json')
        self.assertEqual(r.status_code, 400)
        conn.refresh_from_db()
        self.assertNotIn(self.b.pk, (conn.site_org_map or {}).values())

    def test_pending_review_panel_is_global_view_only(self):
        rmm = _rmm(None, 'Platform RMM')
        RMMDevice.objects.create(connection=rmm, organization=None, external_id='d1', device_name='Pending PC',
                                 ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED)
        self.assertEqual(self.client_for(self.root).get(_url('rmm_review', rmm.pk)).status_code, 200)
        self.assertEqual(self.client_for(self.root, self.a).get(_url('rmm_review', rmm.pk)).status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ApiIsolationTests(_Base):
    """Data a platform connection put under a customer reaches only that
    customer's API keys; unassigned data reaches none."""

    def test_assets_from_platform_controller(self):
        from api.models import APIKey, APIKeyScope
        from .network_assets import import_flat_devices
        conn = _omada(None, 'Platform Omada', site_org_map={'s1': self.a.pk, 's2': self.b.pk})
        import_flat_devices(conn, 'omada', {'sites': [
            {'id': 's1', 'name': 'A', 'devices': [{'mac': 'aa:bb:cc:00:01:01', 'name': 'AP-Acme'}]},
            {'id': 's2', 'name': 'B', 'devices': [{'mac': 'aa:bb:cc:00:01:02', 'name': 'AP-Bolt'}]},
            {'id': 's3', 'name': 'C', 'devices': [{'mac': 'aa:bb:cc:00:01:03', 'name': 'AP-None'}]},
        ]})
        _, key = APIKey.create_key(organization=self.a, user=self.org_owner, name='k', role=Role.OWNER,
                                   scope=APIKeyScope.SINGLE)
        r = Client().get('/api/assets/', HTTP_AUTHORIZATION=f'Bearer {key}')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        names = {row['name'] for row in (data['results'] if isinstance(data, dict) else data)}
        self.assertIn('AP-Acme', names)
        self.assertNotIn('AP-Bolt', names)
        self.assertNotIn('AP-None', names)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MakePlatformOwnedTests(_Base):

    def setUp(self):
        self.rmm = _rmm(self.a, 'Acme RMM', customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        self.dev = RMMDevice.objects.create(connection=self.rmm, organization=self.a, external_id='d1',
                                            device_name='PC1', client_id='c1', client_name='Acme',
                                            customer_key='id:c1',
                                            ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
        self.url = reverse('integrations:make_platform_owned', args=['rmm', self.rmm.pk])

    def test_requires_post_confirm_and_platform_admin(self):
        self.assertEqual(self.client_for(self.root).get(self.url).status_code, 405)
        for user, org in ((self.org_admin, self.a), (self.org_owner, self.a), (self.tech_sync, None),
                          (self.tech_plain, None), (self.root, self.a)):
            with self.subTest(user=user.username, org=org):
                r = self.client_for(user, org).post(self.url, {'confirm': 'yes'})
                self.assertIn(r.status_code, (403, 404))
                self.rmm.refresh_from_db()
                self.assertEqual(self.rmm.organization_id, self.a.pk)
        self.client_for(self.root).post(self.url, {})  # no confirmation
        self.rmm.refresh_from_db()
        self.assertEqual(self.rmm.organization_id, self.a.pk)

    def test_csrf_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.root)
        s = c.session
        s['global_view_mode'] = True
        s['2fa_prompted'] = True
        s.save()
        self.assertEqual(c.post(self.url, {'confirm': 'yes'}).status_code, 403)
        self.rmm.refresh_from_db()
        self.assertEqual(self.rmm.organization_id, self.a.pk)

    def test_moves_connection_keeps_data_and_audits(self):
        r = self.client_for(self.tech_conf).post(self.url, {'confirm': 'yes'})
        self.assertEqual(r.status_code, 302)
        self.rmm.refresh_from_db()
        self.dev.refresh_from_db()
        self.assertIsNone(self.rmm.organization_id)
        self.assertEqual(self.rmm.customer_scope, RMMConnection.CUSTOMER_SCOPE_MULTI)
        self.assertEqual(self.dev.organization_id, self.a.pk)
        self.assertTrue(AuditLog.objects.filter(object_id=self.rmm.pk, organization=self.a,
                                                user=self.tech_conf).exists())
        # The device's customer is now an explicit mapping: the next sync keeps it there.
        from .rmm_association import resolve_customer
        self.assertEqual(resolve_customer(self.rmm, {'client_id': 'c1', 'client_name': 'Acme'}, self.dev)
                         .organization, self.a)
        # And a customer nobody mapped is not filed under Acme.
        self.assertIsNone(resolve_customer(self.rmm, {'client_id': 'zz', 'client_name': 'New'}).organization)
        # Acme's admin no longer reaches it.
        self.assertIn(self.client_for(self.org_admin, self.a).get(_url('rmm_detail', self.rmm.pk)).status_code,
                      (403, 404))

    def test_refuses_twice_and_rem0te(self):
        self.client_for(self.root).post(self.url, {'confirm': 'yes'})
        with self.assertRaises(ownership.OwnershipError):
            ownership.make_platform_owned(RMMConnection.objects.get(pk=self.rmm.pk))
        rem = RMMConnection(organization=self.a, provider_type='rem0te', name='Rem', base_url='https://r.test')
        rem.set_credentials({'api_key': 'k'})
        rem.save()
        self.assertTrue(ownership.make_platform_refusal(rem))

    def test_unifi_keeps_single_default_site(self):
        conn = _unifi(self.a, 'Acme UniFi')
        conn.cached_data = {'sites': [{'id': 'site1', 'name': 'Default', 'devices': []}]}
        conn.save()
        ownership.make_platform_owned(conn, self.root)
        conn.refresh_from_db()
        self.assertEqual(conn.site_org_map, {'site1': self.a.pk})

    def test_accounting_links_keep_client(self):
        acct = AccountingConnection.objects.create(organization=self.a, provider_type='quickbooks_online',
                                                   name='Acme Books')
        AccountingCustomerLink.objects.create(connection=acct, organization=self.a, client_org=self.a,
                                              provider_customer_id='9')
        ownership.make_platform_owned(acct, self.root)
        link = AccountingCustomerLink.objects.get(connection=acct)
        self.assertIsNone(link.organization_id)
        self.assertEqual(link.client_org_id, self.a.pk)

    def test_management_command(self):
        psa = _psa(self.a, 'Demo Desk')
        out = StringIO()
        call_command('integrations_ownership', '--list', stdout=out)
        self.assertIn('Demo Desk', out.getvalue())
        self.assertIn('Acme Own', out.getvalue())
        call_command('integrations_ownership', '--make-platform', 'psa', str(psa.pk), stdout=StringIO())
        psa.refresh_from_db()
        self.assertIsNone(psa.organization_id)
        with self.assertRaises(CommandError):
            call_command('integrations_ownership', '--make-platform', 'psa', str(psa.pk), stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('integrations_ownership', '--make-platform', 'nope', '1', stdout=StringIO())


class MigrationTests(TestCase):

    def test_migration_only_relaxes_columns(self):
        """0040 changes schema only (nullable owner, new site maps): no row is
        rewritten, so every existing connection keeps its organization."""
        from django.db import migrations
        mod = importlib.import_module('integrations.migrations.0040_platform_owned_connections')
        for op in mod.Migration.operations:
            self.assertIsInstance(op, (migrations.AlterField, migrations.AddField), op)
            if isinstance(op, migrations.AlterField) and op.name == 'organization':
                self.assertTrue(op.field.null)

    def test_existing_connections_keep_owner(self):
        org = Organization.objects.create(name='Keep', slug='keep')
        conn = _psa(org, 'Old')
        self.assertEqual(PSAConnection.objects.get(pk=conn.pk).organization_id, org.pk)
        self.assertFalse(PSAConnection.objects.get(pk=conn.pk).is_platform_owned)


class OtherAppsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Flag A', slug='flag-a')
        cls.b = Organization.objects.create(name='Flag B', slug='flag-b')
        cls.root = User.objects.create_superuser('flag_root', 'f@x.test', 'pw')

    def test_platform_psa_does_not_block_native_psa_for_everyone(self):
        from psa.feature_flags import client_has_external_psa, clients_eligible_for_native_psa
        psa = _psa(None, 'Platform Desk')
        PSACompany.objects.create(connection=psa, organization=self.a, external_id='1', name='A')
        eligible = set(clients_eligible_for_native_psa(self.root).values_list('pk', flat=True))
        self.assertNotIn(self.a.pk, eligible)
        self.assertIn(self.b.pk, eligible)
        self.assertTrue(client_has_external_psa(self.a))
        self.assertFalse(client_has_external_psa(self.b))

    def test_accounting_invoice_scope(self):
        own = AccountingConnection.objects.create(organization=self.a, provider_type='xero', name='A books')
        platform = AccountingConnection.objects.create(organization=None, provider_type='xero', name='MSP books',
                                                       sync_enabled=True)
        qs_own = ownership.invoices_for_connection(own).query
        self.assertIn('organization_id', str(qs_own))
        self.assertEqual(ownership.accounting_connection_for(self.b), platform)
        self.assertIsNone(ownership.accounting_connection_for(self.b, platform_fallback=False))

    def test_rmm_decision_allows_platform_connection(self):
        rmm = _rmm(None, 'Platform RMM')
        dev = RMMDevice.objects.create(connection=rmm, organization=self.a, external_id='d', device_name='PC',
                                       ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
        from rmm_permissions.decision import can
        d = can(self.root, self.a, 'alert.read_live', device=dev)
        self.assertNotIn('RMM connection belongs to a different customer', d.reason or '')
        rmm_b = _rmm(self.b, 'Bolt RMM')
        dev_b = RMMDevice.objects.create(connection=rmm_b, organization=self.a, external_id='e', device_name='PC2',
                                         ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
        d = can(self.root, self.a, 'alert.read_live', device=dev_b)
        self.assertFalse(d.allowed)
