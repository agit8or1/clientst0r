"""
Baseline test coverage for the locations/ app.

Tracks physical locations + WAN connections + floor plans for
multi-location clients. Bug = wrong tenant access (shared-location
ACL leak), broken HQ uniqueness (multiple primaries claimed), or
silent address-rendering breakage.

Coverage areas:
  * `Location` model — `is_primary` uniqueness per org (only one HQ
    per organization), `is_shared` enforces `is_primary=False`,
    `__str__` discriminates shared / HQ / regular.
  * `Location.full_address` formatting + `has_coordinates` flag.
  * `Location.can_organization_access` ACL — owner-only by default,
    associated_organizations only for shared.
  * `WAN.is_down`, `bandwidth_display` formatting.
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from core.models import Organization
from locations.models import WAN, Location


def _addr_kwargs(**overrides):
    """Common address fields so tests don't repeat them."""
    out = dict(
        street_address='123 Main St',
        city='Austin',
        state='TX',
        postal_code='78701',
        country='United States',
    )
    out.update(overrides)
    return out


class LocationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='LocCo', slug='loc-co')

    def test_str_for_owned_location(self):
        loc = Location.objects.create(
            organization=self.org, name='Main', **_addr_kwargs(),
        )
        s = str(loc)
        self.assertIn('Main', s)
        self.assertIn('LocCo', s)

    def test_str_marks_hq_when_primary(self):
        loc = Location.objects.create(
            organization=self.org, name='HQ', is_primary=True, **_addr_kwargs(),
        )
        self.assertIn('(HQ)', str(loc))

    def test_str_marks_shared(self):
        # Shared locations have no `organization` (per the model contract)
        # — leave it null and put the access list on associated_organizations.
        loc = Location.objects.create(
            organization=None, is_shared=True, name='Colo', **_addr_kwargs(),
        )
        loc.associated_organizations.add(self.org)
        self.assertIn('(Shared)', str(loc))

    def test_full_address_includes_required_fields(self):
        loc = Location.objects.create(
            organization=self.org, name='X',
            **_addr_kwargs(street_address_2='Suite 100'),
        )
        addr = loc.full_address
        self.assertIn('123 Main St', addr)
        self.assertIn('Suite 100', addr)
        self.assertIn('Austin', addr)
        self.assertIn('TX', addr)
        self.assertIn('78701', addr)

    def test_full_address_omits_country_when_united_states(self):
        loc = Location.objects.create(
            organization=self.org, name='X', **_addr_kwargs(),
        )
        # United States is the default and shouldn't be appended.
        self.assertNotIn('United States', loc.full_address)

    def test_full_address_includes_country_when_non_us(self):
        loc = Location.objects.create(
            organization=self.org, name='X',
            **_addr_kwargs(country='Canada'),
        )
        self.assertIn('Canada', loc.full_address)

    def test_has_coordinates_true_only_with_lat_and_lng(self):
        loc1 = Location.objects.create(
            organization=self.org, name='no-coords', **_addr_kwargs(),
        )
        loc2 = Location.objects.create(
            organization=self.org, name='with-coords',
            latitude=Decimal('30.2672'), longitude=Decimal('-97.7431'),
            **_addr_kwargs(city='AustinB'),
        )
        self.assertFalse(loc1.has_coordinates)
        self.assertTrue(loc2.has_coordinates)

    def test_setting_is_primary_demotes_other_primaries(self):
        # Only ONE primary location per organization. Saving a new primary
        # must demote the existing one. This is the load-bearing HQ
        # uniqueness invariant.
        first = Location.objects.create(
            organization=self.org, name='Old HQ', is_primary=True, **_addr_kwargs(),
        )
        new = Location.objects.create(
            organization=self.org, name='New HQ', is_primary=True,
            **_addr_kwargs(city='AustinB'),
        )
        first.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(new.is_primary)

    def test_shared_location_cannot_be_primary(self):
        # Save() forces is_primary=False for shared locations.
        loc = Location.objects.create(
            organization=None, is_shared=True, is_primary=True,
            name='Colo', **_addr_kwargs(),
        )
        self.assertFalse(loc.is_primary)


class LocationAccessControlTests(TestCase):
    """`can_organization_access` is the load-bearing ACL for locations.
    Bug here = wrong tenant gets to see a location."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='ACL-A', slug='acl-a')
        cls.org_b = Organization.objects.create(name='ACL-B', slug='acl-b')

    def test_owner_can_access_owned_location(self):
        loc = Location.objects.create(
            organization=self.org_a, name='A-only', **_addr_kwargs(),
        )
        self.assertTrue(loc.can_organization_access(self.org_a))

    def test_other_org_cannot_access_owned_location(self):
        loc = Location.objects.create(
            organization=self.org_a, name='A-only', **_addr_kwargs(),
        )
        self.assertFalse(loc.can_organization_access(self.org_b))

    def test_associated_org_can_access_shared_location(self):
        shared = Location.objects.create(
            organization=None, is_shared=True, name='Colo', **_addr_kwargs(),
        )
        shared.associated_organizations.add(self.org_a)
        self.assertTrue(shared.can_organization_access(self.org_a))
        self.assertFalse(shared.can_organization_access(self.org_b))

    def test_get_all_organizations_returns_associated_for_shared(self):
        shared = Location.objects.create(
            organization=None, is_shared=True, name='Colo', **_addr_kwargs(),
        )
        shared.associated_organizations.add(self.org_a, self.org_b)
        all_orgs = list(shared.get_all_organizations())
        self.assertIn(self.org_a, all_orgs)
        self.assertIn(self.org_b, all_orgs)

    def test_get_all_organizations_returns_owner_for_non_shared(self):
        loc = Location.objects.create(
            organization=self.org_a, name='A-only', **_addr_kwargs(),
        )
        self.assertEqual(list(loc.get_all_organizations()), [self.org_a])


class WANModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='WANCo-loc', slug='wan-loc')
        cls.location = Location.objects.create(
            organization=cls.org, name='HQ', **_addr_kwargs(),
        )

    def _wan(self, **overrides):
        defaults = dict(
            organization=self.org, location=self.location,
            name='Primary Fiber', wan_type='fiber',
            isp_name='Acme Net', status='active',
        )
        defaults.update(overrides)
        return WAN.objects.create(**defaults)

    def test_str_includes_location_and_name(self):
        w = self._wan()
        self.assertIn('HQ', str(w))
        self.assertIn('Primary Fiber', str(w))

    def test_is_down_true_when_status_down(self):
        self.assertTrue(self._wan(status='down').is_down)

    def test_is_down_false_when_status_active(self):
        self.assertFalse(self._wan().is_down)

    def test_bandwidth_display_unknown_when_no_speeds(self):
        w = self._wan()
        self.assertEqual(w.bandwidth_display, 'Unknown')

    def test_bandwidth_display_full_when_both_speeds_set(self):
        w = self._wan(bandwidth_download_mbps=1000, bandwidth_upload_mbps=500)
        self.assertIn('1000', w.bandwidth_display)
        self.assertIn('500', w.bandwidth_display)

    def test_bandwidth_display_download_only(self):
        w = self._wan(bandwidth_download_mbps=200)
        self.assertEqual(w.bandwidth_display, '200 Mbps')


# --- import_property_from_url: SSRF + authorization -----------------------

import json  # noqa: E402
from unittest import mock  # noqa: E402

from django.conf import settings as django_settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402

from accounts.models import Membership, Role  # noqa: E402
from core.safe_http import FetchError, UnsafeURLError  # noqa: E402
import locations.services.property_url_importer  # noqa: E402,F401  (patch target must be importable)

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ImportPropertyFromURLTests(TestCase):
    """The endpoint fetches a user-supplied URL server-side.

    The importer is mocked: these tests cover what reaches it (nothing,
    for a disallowed URL or an unauthorized user) and what the user sees
    when it fails (a generic message, never the internal detail). The fetch
    guard itself is covered in core/tests/test_safe_http.py.
    """

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.org = Organization.objects.create(name='ImportCo', slug='import-co')
        cls.other_org = Organization.objects.create(name='OtherCo', slug='other-co')
        cls.location = Location.objects.create(organization=cls.org, name='Main', **_addr_kwargs())
        cls.other_location = Location.objects.create(organization=cls.other_org, name='Theirs', **_addr_kwargs())

        cls.editor = User.objects.create_user('loc_editor', 'e@example.com', 'pw-not-secret')
        Membership.objects.create(user=cls.editor, organization=cls.org, role=Role.EDITOR, is_active=True)
        cls.reader = User.objects.create_user('loc_reader', 'r@example.com', 'pw-not-secret')
        Membership.objects.create(user=cls.reader, organization=cls.org, role=Role.READONLY, is_active=True)

    def _login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()

    def _post(self, url_value, location=None, raw=None):
        location = location or self.location
        body = raw if raw is not None else json.dumps({'url': url_value})
        return self.client.post(
            reverse('locations:import_property_from_url', args=[location.id]),
            data=body, content_type='application/json',
        )

    def _importer(self, **kwargs):
        importer = mock.Mock(**kwargs)
        return mock.patch('locations.services.property_url_importer.get_property_url_importer',
                          return_value=importer), importer

    # -- authorization -----------------------------------------------------
    def test_unauthenticated_user_cannot_use_endpoint(self):
        patcher, importer = self._importer()
        with patcher:
            resp = self._post('https://example.com/parcel')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])
        importer.import_from_url.assert_not_called()

    def test_readonly_member_cannot_import(self):
        self._login(self.reader)
        patcher, importer = self._importer()
        with patcher:
            resp = self._post('https://example.com/parcel')
        self.assertEqual(resp.status_code, 403)
        importer.import_from_url.assert_not_called()

    def test_cannot_import_into_another_orgs_location(self):
        self._login(self.editor)
        patcher, importer = self._importer()
        with patcher:
            resp = self._post('https://example.com/parcel', location=self.other_location)
        self.assertEqual(resp.status_code, 404)
        importer.import_from_url.assert_not_called()
        self.other_location.refresh_from_db()
        self.assertFalse(self.other_location.external_data)

    def test_get_not_allowed(self):
        self._login(self.editor)
        resp = self.client.get(reverse('locations:import_property_from_url', args=[self.location.id]))
        self.assertEqual(resp.status_code, 405)

    # -- input -------------------------------------------------------------
    def test_missing_url(self):
        self._login(self.editor)
        for raw in (json.dumps({}), json.dumps({'url': ''}), json.dumps({'url': '   '}),
                    json.dumps({'url': None}), json.dumps({'url': ['x']}), json.dumps(['x'])):
            with self.subTest(raw=raw):
                resp = self._post(None, raw=raw)
                self.assertEqual(resp.status_code, 400)

    def test_invalid_json(self):
        self._login(self.editor)
        resp = self._post(None, raw='{not json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])

    def test_disallowed_urls_rejected_before_fetch(self):
        self._login(self.editor)
        patcher, importer = self._importer()
        with patcher:
            for url in ('file:///etc/passwd', 'ftp://example.com/', 'gopher://example.com/',
                        'dict://example.com:11211/', 'http://localhost/', 'http://127.0.0.1/',
                        'http://0.0.0.0/', 'http://169.254.169.254/latest/meta-data/',
                        'http://10.0.0.1/', 'http://172.16.0.1/', 'http://192.168.1.1/',
                        'http://[::1]/', 'http://[fe80::1]/', 'http://[fd00::1]/',
                        'http://[::ffff:10.0.0.1]/', 'http://2130706433/',
                        'http://example.com:6379/', 'http://user:pw@example.com/', 'not a url'):
                with self.subTest(url=url):
                    resp = self._post(url)
                    self.assertEqual(resp.status_code, 400)
                    data = resp.json()
                    self.assertFalse(data['success'])
                    self.assertEqual(data['error'], 'That URL is not allowed. Use a public http:// or https:// address.')
        importer.import_from_url.assert_not_called()

    # -- outcomes ----------------------------------------------------------
    def test_valid_public_url_updates_location(self):
        self._login(self.editor)
        patcher, importer = self._importer()
        importer.import_from_url.return_value = {
            'building_sqft': '5,000', 'year_built': 1995, 'floors_count': 'two',
            'property_type': 'Commercial Office', 'property_id': '1442930000',
        }
        with patcher:
            resp = self._post('https://example.com/parcel?id=1')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        importer.import_from_url.assert_called_once_with('https://example.com/parcel?id=1')
        self.location.refresh_from_db()
        self.assertEqual(self.location.building_sqft, 5000)
        self.assertEqual(self.location.year_built, 1995)
        self.assertEqual(self.location.property_id, '1442930000')
        self.assertIn('url_import', self.location.external_data)

    def test_redirect_or_dns_block_returns_generic_400(self):
        # The guard can also refuse later, e.g. on a redirect to an internal host.
        self._login(self.editor)
        patcher, importer = self._importer()
        importer.import_from_url.side_effect = UnsafeURLError('redirect to http://10.1.2.3:8080/admin')
        with patcher:
            resp = self._post('https://example.com/parcel')
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn('10.1.2.3', resp.content.decode())

    def test_fetch_failure_is_generic(self):
        self._login(self.editor)
        patcher, importer = self._importer()
        importer.import_from_url.side_effect = FetchError('Upstream returned HTTP 500: secret-body')
        with patcher:
            resp = self._post('https://example.com/parcel')
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn('secret-body', resp.content.decode())
        self.assertNotIn('500', resp.json()['error'])

    def test_unexpected_error_is_generic(self):
        self._login(self.editor)
        patcher, importer = self._importer()
        importer.import_from_url.side_effect = RuntimeError('db password=hunter2 at 10.0.0.3')
        with patcher:
            resp = self._post('https://example.com/parcel')
        self.assertEqual(resp.status_code, 500)
        body = resp.content.decode()
        self.assertNotIn('hunter2', body)
        self.assertNotIn('10.0.0.3', body)

    def test_end_to_end_internal_address_never_connected(self):
        """No importer mock: a name resolving to loopback is refused at fetch time."""
        self._login(self.editor)
        loopback = [(2, 1, 6, '', ('127.0.0.1', 80))]
        with mock.patch('django.conf.settings.ANTHROPIC_API_KEY', 'test-key', create=True), \
                mock.patch.dict('sys.modules', {'anthropic': mock.Mock()}), \
                mock.patch('socket.getaddrinfo', return_value=loopback), \
                mock.patch('core.safe_http.urllib3_connection.create_connection') as connect:
            resp = self._post('http://sneaky.example/parcel')
        self.assertEqual(resp.status_code, 400)
        connect.assert_not_called()
