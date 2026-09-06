"""
Phase 32 (v3.17.556) — remote network discovery.

The upload endpoint is the only unauthenticated write surface in the product, so
most of these are about what it refuses: expired tokens, revoked tokens, spent
tokens, oversized payloads, and anything that would let a token reach outside the
one organization and location it was issued for.
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
    NetworkDiscoveryAssetResult, NetworkDiscoveryImport, NetworkDiscoveryToken,
    hash_token, normalise_mac, valid_ipv4,
)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

UPLOAD_URL = '/network-discovery/upload/'


def _post_json(client, url, payload, **extra):
    return client.post(url, data=json.dumps(payload),
                       content_type='application/json', **extra)


class HelperTests(TestCase):
    def test_mac_normalisation_across_formats(self):
        """Windows reports MACs three different ways depending on where they
        came from; deduplication matches on this field."""
        for raw in ('aa:bb:cc:dd:ee:ff', 'AA-BB-CC-DD-EE-FF', 'aabb.ccdd.eeff',
                    'AABBCCDDEEFF'):
            self.assertEqual(normalise_mac(raw), 'AA-BB-CC-DD-EE-FF', raw)

    def test_rubbish_is_not_a_mac(self):
        for raw in ('', None, 'hello', '00-11-22'):
            self.assertEqual(normalise_mac(raw), '')

    def test_ipv4_validation(self):
        self.assertTrue(valid_ipv4('192.168.1.1'))
        self.assertFalse(valid_ipv4('999.1.1.1'))
        self.assertFalse(valid_ipv4('::1'))
        self.assertFalse(valid_ipv4('not an ip'))

    def test_hashing_is_stable_and_not_reversible_in_the_row(self):
        self.assertEqual(hash_token('abc'), hash_token('abc'))
        self.assertNotEqual(hash_token('abc'), hash_token('abd'))
        self.assertEqual(len(hash_token('abc')), 64)


class TokenLifecycleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='DiscoCo', slug='disco-co')
        self.location = Location.objects.create(
            organization=self.org, name='Head office')

    def _issue(self, **kw):
        return NetworkDiscoveryToken.issue(
            organization=self.org, location=self.location, **kw)

    def test_the_plaintext_is_never_stored(self):
        """The whole point: a token you can read back out of the database is a
        standing credential."""
        token, raw = self._issue()
        self.assertNotIn(raw, json.dumps({
            f.name: str(getattr(token, f.name))
            for f in token._meta.fields
        }))
        self.assertEqual(token.token_hash, hash_token(raw))

    def test_a_fresh_token_is_usable(self):
        token, raw = self._issue()
        self.assertTrue(token.is_usable)
        self.assertEqual(NetworkDiscoveryToken.find_usable(raw), token)

    def test_an_expired_token_is_not_usable(self):
        token, raw = self._issue(ttl_minutes=1)
        token.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        token.save(update_fields=['expires_at'])
        self.assertFalse(token.is_usable)
        self.assertIsNone(NetworkDiscoveryToken.find_usable(raw))

    def test_a_revoked_token_is_not_usable(self):
        token, raw = self._issue()
        token.revoke()
        self.assertIsNone(NetworkDiscoveryToken.find_usable(raw))

    def test_revoking_twice_keeps_the_first_timestamp(self):
        token, _ = self._issue()
        token.revoke()
        first = token.revoked_at
        token.revoke()
        self.assertEqual(token.revoked_at, first)

    def test_a_spent_token_is_not_usable(self):
        token, raw = self._issue(max_uses=1)
        token.record_use(source_ip='10.0.0.5')
        self.assertIsNone(NetworkDiscoveryToken.find_usable(raw))

    def test_a_limited_use_token_survives_until_spent(self):
        token, raw = self._issue(max_uses=2)
        token.record_use(source_ip='10.0.0.5')
        self.assertIsNotNone(NetworkDiscoveryToken.find_usable(raw))
        token.record_use(source_ip='10.0.0.5')
        self.assertIsNone(NetworkDiscoveryToken.find_usable(raw))

    def test_an_unknown_token_finds_nothing(self):
        self._issue()
        self.assertIsNone(NetworkDiscoveryToken.find_usable('not-a-real-token'))
        self.assertIsNone(NetworkDiscoveryToken.find_usable(''))

    def test_state_reports_revoked_over_expired(self):
        """A revoked token that also expired is described as revoked, because
        that is the fact somebody acted on."""
        token, _ = self._issue()
        token.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        token.revoke()
        self.assertEqual(token.state, 'revoked')

    def test_recording_a_use_captures_the_source(self):
        token, _ = self._issue()
        token.record_use(source_ip='203.0.113.9', user_agent='PowerShell/7.4')
        self.assertEqual(token.source_ip_last_used, '203.0.113.9')
        self.assertIn('PowerShell', token.user_agent_last_used)
        self.assertIsNotNone(token.used_at)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UploadEndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='UpCo', slug='up-co')
        self.other_org = Organization.objects.create(name='OtherUp', slug='other-up')
        self.location = Location.objects.create(
            organization=self.org, name='Head office')
        self.other_location = Location.objects.create(
            organization=self.other_org, name='Their office')
        self.token, self.raw = NetworkDiscoveryToken.issue(
            organization=self.org, location=self.location)
        self.client = Client()

    def _upload(self, devices=None, **payload):
        body = {'token': self.raw, 'devices': devices if devices is not None else []}
        body.update(payload)
        return _post_json(self.client, UPLOAD_URL, body)

    def test_a_valid_upload_is_accepted(self):
        resp = self._upload([{'ip': '192.168.1.10', 'mac': 'AA-BB-CC-DD-EE-01'}])
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_no_session_is_needed(self):
        """The caller is a PowerShell script with no cookie."""
        anonymous = Client()
        resp = _post_json(anonymous, UPLOAD_URL, {
            'token': self.raw, 'devices': [{'ip': '192.168.1.10'}]})
        self.assertEqual(resp.status_code, 200)

    def test_an_expired_token_is_rejected(self):
        self.token.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.token.save(update_fields=['expires_at'])
        self.assertEqual(self._upload([{'ip': '192.168.1.10'}]).status_code, 403)

    def test_a_revoked_token_is_rejected(self):
        self.token.revoke()
        self.assertEqual(self._upload([{'ip': '192.168.1.10'}]).status_code, 403)

    def test_a_token_cannot_be_used_twice(self):
        self._upload([{'ip': '192.168.1.10'}])
        self.assertEqual(self._upload([{'ip': '192.168.1.11'}]).status_code, 403)

    def test_every_rejection_looks_the_same(self):
        """An anonymous caller must not learn whether a token exists but is
        expired, or never existed at all."""
        unknown = _post_json(self.client, UPLOAD_URL,
                             {'token': 'nope', 'devices': []})
        self.token.revoke()
        revoked = self._upload([])
        self.assertEqual(unknown.status_code, revoked.status_code)
        self.assertEqual(unknown.json(), revoked.json())

    def test_a_missing_token_is_rejected(self):
        resp = _post_json(self.client, UPLOAD_URL, {'devices': []})
        self.assertEqual(resp.status_code, 403)

    def test_get_is_not_allowed(self):
        """Write-only. There is nothing to read here."""
        self.assertEqual(self.client.get(UPLOAD_URL).status_code, 405)

    def test_invalid_json_is_rejected(self):
        resp = self.client.post(UPLOAD_URL, data='{not json',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_devices_must_be_a_list(self):
        resp = _post_json(self.client, UPLOAD_URL,
                          {'token': self.raw, 'devices': 'lots'})
        self.assertEqual(resp.status_code, 400)

    def test_too_many_devices_is_rejected(self):
        from network_discovery.models import MAX_DEVICES_PER_UPLOAD
        devices = [{'ip': '10.0.0.1'}] * (MAX_DEVICES_PER_UPLOAD + 1)
        self.assertEqual(self._upload(devices).status_code, 413)

    def test_the_import_is_scoped_to_the_tokens_org_and_location(self):
        """A token cannot reach outside where it was issued — the payload has
        no say in where its results land."""
        self._upload([{'ip': '192.168.1.10'}])
        row = NetworkDiscoveryImport.objects.get()
        self.assertEqual(row.organization, self.org)
        self.assertEqual(row.location, self.location)

    def test_a_payload_cannot_redirect_itself_to_another_org(self):
        resp = _post_json(self.client, UPLOAD_URL, {
            'token': self.raw,
            'organization_id': self.other_org.pk,
            'location_id': self.other_location.pk,
            'devices': [{'ip': '192.168.1.10'}],
        })
        self.assertEqual(resp.status_code, 200)
        row = NetworkDiscoveryImport.objects.get()
        self.assertEqual(row.organization, self.org)
        self.assertEqual(row.location, self.location)
        self.assertEqual(
            Asset.objects.filter(organization=self.other_org).count(), 0)

    def test_the_source_ip_is_recorded(self):
        self._upload([{'ip': '192.168.1.10'}])
        self.assertIsNotNone(NetworkDiscoveryImport.objects.get().source_ip)

    def test_rate_limiting_kicks_in(self):
        from network_discovery.views import UPLOAD_RATE_LIMIT
        for _ in range(UPLOAD_RATE_LIMIT):
            NetworkDiscoveryImport.objects.create(
                organization=self.org, location=self.location,
                source_ip='127.0.0.1')
        self.assertEqual(self._upload([{'ip': '192.168.1.10'}]).status_code, 429)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetImportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='ImpCo', slug='imp-co')
        self.location = Location.objects.create(
            organization=self.org, name='Head office')
        self.client = Client()

    def _upload(self, devices, **payload):
        _token, raw = NetworkDiscoveryToken.issue(
            organization=self.org, location=self.location)
        body = {'token': raw, 'devices': devices}
        body.update(payload)
        return _post_json(self.client, UPLOAD_URL, body)

    def test_a_new_device_creates_an_asset(self):
        self._upload([{'ip': '192.168.1.10', 'mac': 'AA-BB-CC-DD-EE-01',
                       'hostname': 'sw-01'}])
        asset = Asset.objects.get()
        self.assertEqual(asset.organization, self.org)
        self.assertEqual(asset.name, 'sw-01')
        self.assertEqual(asset.mac_address, 'AA-BB-CC-DD-EE-01')

    def test_the_name_falls_back_hostname_then_ip_then_mac(self):
        self._upload([
            {'ip': '192.168.1.11', 'mac': 'AA-BB-CC-DD-EE-02'},
            {'mac': 'AA-BB-CC-DD-EE-03'},
        ])
        names = set(Asset.objects.values_list('name', flat=True))
        self.assertIn('192.168.1.11', names)
        self.assertIn('AA-BB-CC-DD-EE-03', names)

    def test_a_duplicate_mac_updates_rather_than_creating(self):
        existing = Asset.objects.create(
            organization=self.org, name='Core switch',
            mac_address='AA-BB-CC-DD-EE-01')
        self._upload([{'ip': '192.168.1.10', 'mac': 'aa:bb:cc:dd:ee:01'}])
        self.assertEqual(Asset.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.ip_address, '192.168.1.10')

    def test_a_manually_entered_name_is_never_overwritten(self):
        """A sweep knows a device answered at an address. It does not know
        better than the technician who named it."""
        existing = Asset.objects.create(
            organization=self.org, name='Core switch — do not touch',
            mac_address='AA-BB-CC-DD-EE-01')
        self._upload([{'ip': '192.168.1.10', 'mac': 'AA-BB-CC-DD-EE-01',
                       'hostname': 'sw-01'}])
        existing.refresh_from_db()
        self.assertEqual(existing.name, 'Core switch — do not touch')

    def test_a_populated_field_is_left_alone(self):
        existing = Asset.objects.create(
            organization=self.org, name='Core switch',
            mac_address='AA-BB-CC-DD-EE-01', hostname='real-name')
        self._upload([{'mac': 'AA-BB-CC-DD-EE-01', 'hostname': 'discovered-name'}])
        existing.refresh_from_db()
        self.assertEqual(existing.hostname, 'real-name')

    def test_a_duplicate_ip_updates_the_existing_asset(self):
        existing = Asset.objects.create(
            organization=self.org, name='Printer', ip_address='192.168.1.50')
        self._upload([{'ip': '192.168.1.50', 'mac': 'AA-BB-CC-DD-EE-09'}])
        self.assertEqual(Asset.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.mac_address, 'AA-BB-CC-DD-EE-09')

    def test_an_ip_belonging_to_another_org_is_not_matched(self):
        """192.168.1.10 exists at every client an MSP looks after."""
        other_org = Organization.objects.create(name='Neighbour', slug='neigh')
        Asset.objects.create(
            organization=other_org, name='Theirs', ip_address='192.168.1.10')
        self._upload([{'ip': '192.168.1.10'}])
        self.assertEqual(Asset.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(Asset.objects.filter(organization=other_org).count(), 1)

    def test_the_same_device_listed_twice_is_collapsed(self):
        """A sweep can list a device once from ping and once from ARP."""
        self._upload([
            {'ip': '192.168.1.10', 'mac': 'AA-BB-CC-DD-EE-01'},
            {'ip': '192.168.1.10', 'mac': 'AA-BB-CC-DD-EE-01'},
        ])
        self.assertEqual(Asset.objects.count(), 1)

    def test_a_device_with_neither_ip_nor_mac_is_an_error_not_an_asset(self):
        resp = self._upload([{'hostname': 'ghost'}])
        self.assertEqual(Asset.objects.count(), 0)
        self.assertEqual(resp.json()['errors'], 1)

    def test_an_invalid_ip_is_rejected_per_device(self):
        resp = self._upload([{'ip': '999.999.999.999'}])
        self.assertEqual(resp.json()['errors'], 1)
        self.assertEqual(Asset.objects.count(), 0)

    def test_one_bad_device_does_not_lose_the_others(self):
        resp = self._upload([
            {'ip': '192.168.1.10'},
            {'nonsense': True},
            {'ip': '192.168.1.11'},
        ])
        body = resp.json()
        self.assertEqual(body['created'], 2)
        self.assertEqual(body['errors'], 1)

    def test_a_dry_run_writes_nothing(self):
        resp = self._upload([{'ip': '192.168.1.10'}], dry_run=True)
        self.assertTrue(resp.json()['dry_run'])
        self.assertEqual(Asset.objects.count(), 0)
        self.assertEqual(
            NetworkDiscoveryAssetResult.objects.filter(status='preview').count(), 1)

    def test_results_are_recorded_per_device(self):
        """"Why was that switch skipped" needs an answer three weeks later."""
        self._upload([{'ip': '192.168.1.10', 'mac': 'AA-BB-CC-DD-EE-01'}])
        result = NetworkDiscoveryAssetResult.objects.get()
        self.assertEqual(result.status, 'created')
        self.assertEqual(result.ip_address, '192.168.1.10')

    def test_discovered_assets_carry_the_discovery_note(self):
        self._upload([{'ip': '192.168.1.10'}])
        self.assertIn('Discovered by', Asset.objects.get().notes)

    def test_last_seen_is_stamped_in_custom_fields(self):
        self._upload([{'ip': '192.168.1.10'}])
        asset = Asset.objects.get()
        self.assertIn('network_discovery_last_seen', asset.custom_fields)

    def test_device_type_maps_to_an_asset_type(self):
        self._upload([{'ip': '192.168.1.10', 'device_type': 'printer'}])
        self.assertEqual(Asset.objects.get().asset_type, 'printer')

    def test_an_unknown_device_type_does_not_invent_one(self):
        """Guessing "server" from an open port would put a fiction in the
        asset register."""
        self._upload([{'ip': '192.168.1.10', 'device_type': 'mystery'}])
        self.assertEqual(Asset.objects.get().asset_type, 'other')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ManagementViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MgmtDisco', slug='mgmt-disco')
        self.other_org = Organization.objects.create(name='Elsewhere', slug='elsewhere-d')
        self.location = Location.objects.create(
            organization=self.org, name='Head office')
        self.foreign_location = Location.objects.create(
            organization=self.other_org, name='Not ours')
        self.admin = User.objects.create_superuser(
            'discoadmin', 'd@example.com', 'hunter2xyz')
        self.plain = User.objects.create_user('plain', 'p@example.com', 'pw')
        self.client = Client()

    def _home(self):
        return f'/network-discovery/orgs/{self.org.pk}/locations/{self.location.pk}/'

    def test_anonymous_is_redirected(self):
        resp = Client().get(self._home())
        self.assertIn(resp.status_code, (302, 403))

    def test_an_admin_sees_the_page(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._home())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'authorised to scan')

    def test_generating_issues_a_token_and_shows_it_once(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self._home() + 'generate/', {'ttl_minutes': '15'},
                                follow=True)
        self.assertEqual(NetworkDiscoveryToken.objects.count(), 1)
        self.assertContains(resp, 'shown once')

    def test_the_token_is_not_shown_again_on_reload(self):
        self.client.force_login(self.admin)
        self.client.post(self._home() + 'generate/', {'ttl_minutes': '15'})
        self.client.get(self._home())          # consumes it from the session
        second = self.client.get(self._home())
        self.assertNotContains(second, 'shown once')

    def test_a_user_without_the_permission_cannot_generate(self):
        self.client.force_login(self.plain)
        self.client.post(self._home() + 'generate/', {'ttl_minutes': '15'})
        self.assertEqual(NetworkDiscoveryToken.objects.count(), 0)

    def test_ttl_is_capped_at_a_day(self):
        """A token that lives for a week is a standing credential."""
        self.client.force_login(self.admin)
        self.client.post(self._home() + 'generate/', {'ttl_minutes': '100000'})
        token = NetworkDiscoveryToken.objects.get()
        self.assertLessEqual(
            (token.expires_at - timezone.now()).total_seconds(), 1440 * 60 + 5)

    def test_revoking_through_the_view(self):
        self.client.force_login(self.admin)
        token, _ = NetworkDiscoveryToken.issue(
            organization=self.org, location=self.location)
        self.client.post(self._home() + f'revoke/{token.pk}/')
        token.refresh_from_db()
        self.assertTrue(token.is_revoked)

    def test_a_location_from_another_org_404s(self):
        """The org+location pairing is the whole scope of this feature."""
        self.client.force_login(self.admin)
        resp = self.client.get(
            f'/network-discovery/orgs/{self.org.pk}/'
            f'locations/{self.foreign_location.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_a_token_from_another_location_cannot_be_revoked_here(self):
        self.client.force_login(self.admin)
        other_location = Location.objects.create(
            organization=self.org, name='Branch')
        token, _ = NetworkDiscoveryToken.issue(
            organization=self.org, location=other_location)
        resp = self.client.post(self._home() + f'revoke/{token.pk}/')
        self.assertEqual(resp.status_code, 404)
        token.refresh_from_db()
        self.assertFalse(token.is_revoked)

    def test_the_script_download_contains_the_token_and_the_warning(self):
        self.client.force_login(self.admin)
        self.client.post(self._home() + 'generate/', {'ttl_minutes': '15'})
        token = NetworkDiscoveryToken.objects.get()
        resp = self.client.get(self._home() + f'download/{token.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('AUTHORISED TO SCAN', body.upper())
        self.assertIn('/network-discovery/upload/', body)

    def test_the_script_cannot_be_rebuilt_once_the_session_is_gone(self):
        """The server holds a hash. There is nothing to rebuild it from."""
        self.client.force_login(self.admin)
        self.client.post(self._home() + 'generate/', {'ttl_minutes': '15'})
        token = NetworkDiscoveryToken.objects.get()
        self.client.get(self._home())   # consumes the session copy
        resp = self.client.get(self._home() + f'download/{token.pk}/', follow=True)
        self.assertContains(resp, 'no longer available')

    def test_import_detail_lists_devices(self):
        self.client.force_login(self.admin)
        token, raw = NetworkDiscoveryToken.issue(
            organization=self.org, location=self.location)
        _post_json(Client(), UPLOAD_URL,
                   {'token': raw, 'devices': [{'ip': '192.168.1.10'}]})
        row = NetworkDiscoveryImport.objects.get()
        resp = self.client.get(self._home() + f'imports/{row.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '192.168.1.10')
