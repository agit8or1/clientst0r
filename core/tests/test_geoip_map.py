"""
GeoIP click-to-select world map (v3.17.522).

The map is an input method over the country lists that already existed — it
writes into the same fields the text inputs posted. These tests hold the two
things that matter: codes are validated server-side (they drive a firewall), and
the cosmetic backdrop can never alter which countries are blocked.
"""
from __future__ import annotations

import json

from django.conf import settings as dj_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.geoip_map import (
    COLOR_ALLOW, COLOR_BLOCK, build_lists, map_background_context,
    name_for, normalise_codes,
)
from core.iso3166 import COUNTRY_NAMES, country_name, is_valid_code
from core.models import FirewallCountryRule, SystemSetting

_TEST_MIDDLEWARE = [
    m for m in dj_settings.MIDDLEWARE
    if 'Enforce2FA' not in m and 'AxesMiddleware' not in m
]

# Production uses a hashed manifest for static files, which only exists after
# `collectstatic`. The update script runs that (step 4/5), but the test runner
# does not — so rendering a page that {% static %}s a brand-new asset would
# raise "Missing staticfiles manifest entry" for reasons unrelated to the code
# under test. Use the plain storage backend here.
_TEST_STORAGES = {
    **dj_settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class Iso3166TableTests(TestCase):
    def test_table_is_populated_and_plausible(self):
        self.assertGreater(len(COUNTRY_NAMES), 200)
        for code in ('US', 'GB', 'DE', 'CN', 'RU', 'BR'):
            self.assertIn(code, COUNTRY_NAMES)

    def test_codes_are_two_upper_case_letters(self):
        bad = [c for c in COUNTRY_NAMES if len(c) != 2 or not c.isalpha() or c != c.upper()]
        self.assertEqual(bad, [])

    def test_lookup_is_case_insensitive_with_fallback(self):
        self.assertEqual(country_name('gb'), 'United Kingdom')
        self.assertEqual(country_name('ZZ'), 'ZZ')
        self.assertEqual(country_name('ZZ', default='Unknown'), 'Unknown')
        self.assertEqual(country_name(''), '')

    def test_validity_check(self):
        self.assertTrue(is_valid_code('ru'))
        self.assertFalse(is_valid_code('XX'))
        self.assertFalse(is_valid_code(''))


class NormaliseCodesTests(TestCase):
    def test_accepts_string_or_list_and_upper_cases(self):
        self.assertEqual(normalise_codes('us, gb'), ['US', 'GB'])
        self.assertEqual(normalise_codes(['us', 'GB']), ['US', 'GB'])

    def test_drops_unknown_codes(self):
        """A typo must not become a rule that silently matches nothing."""
        self.assertEqual(normalise_codes('US, XX, ZZ, CA'), ['US', 'CA'])

    def test_deduplicates_preserving_order(self):
        self.assertEqual(normalise_codes('CA, us, CA, US'), ['CA', 'US'])

    def test_empty_inputs(self):
        self.assertEqual(normalise_codes(None), [])
        self.assertEqual(normalise_codes(''), [])
        self.assertEqual(normalise_codes([]), [])


class MapBackgroundContextTests(TestCase):
    def test_pattern_mode_uses_the_saved_pattern(self):
        s = SystemSetting.get_settings()
        s.geoip_map_background_mode = 'pattern'
        s.geoip_map_background_pattern = 'ocean'
        s.save()
        ctx = map_background_context(s)
        self.assertEqual(ctx['geoip_map_mode'], 'pattern')
        self.assertEqual(ctx['geoip_map_pattern'], 'ocean')
        self.assertEqual(ctx['geoip_map_image_url'], '')

    def test_random_mode_picks_a_known_pattern(self):
        s = SystemSetting.get_settings()
        s.geoip_map_background_mode = 'random'
        s.save()
        valid = {k for k, _ in SystemSetting.GEOIP_MAP_PATTERNS}
        for _ in range(20):
            self.assertIn(map_background_context(s)['geoip_map_pattern'], valid)

    def test_image_mode_without_an_image_falls_back_to_pattern(self):
        """A missing file must not render an empty box."""
        s = SystemSetting.get_settings()
        s.geoip_map_background_mode = 'image'
        s.geoip_map_background_image = None
        s.geoip_map_background_pattern = 'terrain'
        s.save()
        ctx = map_background_context(s)
        self.assertEqual(ctx['geoip_map_mode'], 'pattern')
        self.assertEqual(ctx['geoip_map_pattern'], 'terrain')

    def test_unknown_pattern_falls_back_to_a_valid_one(self):
        s = SystemSetting.get_settings()
        s.geoip_map_background_mode = 'pattern'
        s.geoip_map_background_pattern = 'not-a-pattern'
        s.save()
        valid = {k for k, _ in SystemSetting.GEOIP_MAP_PATTERNS}
        self.assertIn(map_background_context(s)['geoip_map_pattern'], valid)


class BuildListsTests(TestCase):
    def test_payload_shape_is_what_the_component_expects(self):
        payload = json.loads(build_lists(
            ('allowed', 'Allowed', COLOR_ALLOW, 'id_a', ['us']),
            ('blocked', 'Blocked', COLOR_BLOCK, 'id_b', ['cn', 'bogus']),
        ))
        self.assertEqual([p['key'] for p in payload], ['allowed', 'blocked'])
        self.assertEqual(payload[0]['codes'], ['US'])
        self.assertEqual(payload[1]['codes'], ['CN'])       # invalid dropped
        self.assertEqual(payload[0]['input_id'], 'id_a')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   STORAGES=_TEST_STORAGES)
class FirewallMapSaveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            'geo-admin', 'g@x.com', 'pw', is_staff=True, is_superuser=True)

    def _login(self):
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_map_save_creates_rules_with_server_side_names(self):
        c = self._login()
        c.post('/core/settings/firewall/country-rules/', {'map_codes': 'cn,ru'})
        rules = {r.country_code: r.country_name for r in FirewallCountryRule.objects.all()}
        self.assertEqual(set(rules), {'CN', 'RU'})
        # Name comes from our ISO table, never from the request.
        self.assertEqual(rules['RU'], name_for('RU'))

    def test_map_save_reconciles_removals(self):
        FirewallCountryRule.objects.create(country_code='KP', country_name='Korea')
        c = self._login()
        c.post('/core/settings/firewall/country-rules/', {'map_codes': 'CN'})
        self.assertEqual(
            list(FirewallCountryRule.objects.values_list('country_code', flat=True)), ['CN'])

    def test_invalid_codes_are_ignored(self):
        c = self._login()
        c.post('/core/settings/firewall/country-rules/', {'map_codes': 'CN,XX,,ZZ'})
        self.assertEqual(
            list(FirewallCountryRule.objects.values_list('country_code', flat=True)), ['CN'])

    def test_empty_selection_clears_all_rules(self):
        FirewallCountryRule.objects.create(country_code='CN', country_name='China')
        c = self._login()
        c.post('/core/settings/firewall/country-rules/', {'map_codes': ''})
        self.assertEqual(FirewallCountryRule.objects.count(), 0)

    def test_manual_add_form_still_works(self):
        """The map must not have broken the pre-existing add path."""
        c = self._login()
        c.post('/core/settings/firewall/country-rules/',
               {'country_code': 'br', 'country_name': 'Brazil'})
        self.assertTrue(FirewallCountryRule.objects.filter(country_code='BR').exists())

    def test_backdrop_endpoint_never_touches_rules(self):
        FirewallCountryRule.objects.create(country_code='CN', country_name='China')
        c = self._login()
        c.post('/core/settings/firewall/geoip-map-background/',
               {'geoip_map_background_mode': 'random'})
        self.assertEqual(FirewallCountryRule.objects.count(), 1)
        self.assertEqual(SystemSetting.get_settings().geoip_map_background_mode, 'random')

    def test_backdrop_rejects_a_bogus_mode(self):
        c = self._login()
        before = SystemSetting.get_settings().geoip_map_background_mode
        c.post('/core/settings/firewall/geoip-map-background/',
               {'geoip_map_background_mode': 'sneaky'})
        self.assertEqual(SystemSetting.get_settings().geoip_map_background_mode, before)

    def test_country_rules_page_renders_the_map(self):
        """Both pages must actually render — the POST tests alone missed a 500
        caused by reading the firewall mode off the wrong settings model."""
        c = self._login()
        r = c.get('/core/settings/firewall/country-rules/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode('utf-8', 'replace')
        self.assertIn('data-geoip-map', body)
        self.assertIn('data-lists', body)
        self.assertIn('geoip-map-bg-', body)
        self.assertIn('jsvectormap', body)

    def test_country_rules_page_shows_current_selection(self):
        FirewallCountryRule.objects.create(country_code='CN', country_name='China')
        c = self._login()
        body = c.get('/core/settings/firewall/country-rules/').content.decode('utf-8', 'replace')
        self.assertIn('CN', body)

    def test_map_save_requires_superuser(self):
        peer = User.objects.create_user('geo-peer', 'p@x.com', 'pw')
        c = Client()
        c.force_login(peer)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        r = c.post('/core/settings/firewall/country-rules/', {'map_codes': 'CN'})
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(FirewallCountryRule.objects.count(), 0)
