"""
GeoIP firewall: local country lookups and no login-page exemption (v3.17.598).

The firewall used to call ip-api.com on every request (plain HTTP, 45/min, no
cache); in allowlist mode a failed lookup blocked the visitor. Sign-in and 2FA
pages also skipped the country check entirely.
"""
from unittest import mock

from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from core import geoip_db
from core.models import FirewallCountryRule, FirewallIPRule, FirewallSettings

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

COUNTRIES = {'8.8.8.8': 'US', '5.255.255.70': 'RU', '185.60.216.35': 'IE'}


class FakeReader:
    def get(self, ip):
        code = COUNTRIES.get(ip)
        return {'country': {'iso_code': code, 'names': {'en': code}}} if code else None


class LookupTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def test_local_database_is_used_when_present(self):
        with mock.patch.object(geoip_db, '_get_reader', return_value=FakeReader()), \
             mock.patch('requests.get') as remote:
            self.assertEqual(geoip_db.lookup('8.8.8.8'), ('US', 'US'))
            self.assertEqual(geoip_db.lookup('192.168.1.1'), ('', ''))
        remote.assert_not_called()

    def test_remote_fallback_is_cached(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {'status': 'success', 'countryCode': 'de', 'country': 'Germany'}
        with mock.patch.object(geoip_db, '_get_reader', return_value=None), \
             mock.patch('requests.get', return_value=response) as remote:
            self.assertEqual(geoip_db.lookup('9.9.9.9'), ('DE', 'Germany'))
            self.assertEqual(geoip_db.lookup('9.9.9.9'), ('DE', 'Germany'))
        self.assertEqual(remote.call_count, 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class UsOnlyFirewallTests(TestCase):
    """Requests arrive from the trusted proxy (127.0.0.1) with the real client
    in X-Forwarded-For, as they do behind the reverse proxy in production."""

    def setUp(self):
        cache.clear()
        s = FirewallSettings.get_settings()
        s.geoip_firewall_enabled = True
        s.geoip_firewall_mode = 'allowlist'
        s.bypass_for_staff = False
        s.save()
        FirewallCountryRule.objects.create(country_code='US', country_name='United States', is_active=True)
        patcher = mock.patch.object(geoip_db, '_get_reader', return_value=FakeReader())
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, path, client_ip):
        return self.client.get(path, HTTP_X_FORWARDED_FOR=client_ip)

    def test_us_visitor_is_allowed(self):
        self.assertNotEqual(self.get('/accounts/login/', '8.8.8.8').status_code, 403)

    def test_foreign_visitor_is_blocked_everywhere_including_login(self):
        for path in ('/', '/accounts/login/', '/two_factor/', '/api/mobile/v1/version/'):
            self.assertEqual(self.get(path, '5.255.255.70').status_code, 403, path)

    def test_unknown_country_is_blocked_in_allowlist_mode(self):
        self.assertEqual(self.get('/accounts/login/', '44.0.0.1').status_code, 403)

    def test_lan_is_never_blocked(self):
        self.assertNotEqual(self.get('/accounts/login/', '192.168.22.50').status_code, 403)

    def test_ip_allowlist_still_exempts_login(self):
        """The login exemption remains for the IP-list firewall, so an admin
        whose address changed can still sign in and fix it."""
        s = FirewallSettings.get_settings()
        s.geoip_firewall_enabled = False
        s.ip_firewall_enabled = True
        s.ip_firewall_mode = 'allowlist'
        s.save()
        FirewallIPRule.objects.all().delete()
        self.assertNotEqual(self.get('/accounts/login/', '8.8.8.8').status_code, 403)
        self.assertEqual(self.get('/', '8.8.8.8').status_code, 403)
