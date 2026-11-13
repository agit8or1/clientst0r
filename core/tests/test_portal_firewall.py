"""
Separate GeoIP country policy for the customer portal surface.

These run the real FirewallMiddleware (only the HTTPS redirect is off);
the country database is faked.
"""
from unittest import mock

from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import TestCase, override_settings

from core import geoip_db
from core.models import FirewallCountryRule, FirewallLog, FirewallSettings

US, RU, IE = '8.8.8.8', '5.255.255.70', '185.60.216.35'
COUNTRIES = {US: 'US', RU: 'RU', IE: 'IE'}


class FakeReader:
    def get(self, ip):
        code = COUNTRIES.get(ip)
        return {'country': {'iso_code': code, 'names': {'en': code}}} if code else None


STAFF_PATHS = ('/', '/account/login/', '/core/dashboard/', '/admin/', '/not-a-real-page/')
PORTAL_PATHS = ('/portal/login/', '/portal/', '/portal/password-reset/',
                '/core/secret/sometoken/', '/psa/csat/sometoken/', '/status/p/sometoken/',
                '/security/digest/unsubscribe/sometoken/', '/portal/quote/sometoken/sign/')


@override_settings(SECURE_SSL_REDIRECT=False, TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class PortalGeoipPolicyTests(TestCase):

    def setUp(self):
        cache.clear()
        s = FirewallSettings.get_settings()
        s.geoip_firewall_enabled = True
        s.geoip_firewall_mode = 'allowlist'
        s.bypass_for_staff = False
        s.save()
        # The production rule: US only for staff.
        FirewallCountryRule.objects.create(country_code='US', country_name='United States')
        patcher = mock.patch.object(geoip_db, '_get_reader', return_value=FakeReader())
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, path, ip):
        return self.client.get(path, HTTP_X_FORWARDED_FOR=ip)

    def set_portal(self, mode, *codes):
        s = FirewallSettings.get_settings()
        s.portal_geoip_mode = mode
        s.save()
        for code in codes:
            FirewallCountryRule.objects.create(country_code=code, country_name=code,
                                               surface=FirewallCountryRule.SURFACE_PORTAL)

    def test_default_inherits_staff_policy_everywhere(self):
        self.assertEqual(FirewallSettings.get_settings().portal_geoip_mode, 'inherit')
        for path in STAFF_PATHS + PORTAL_PATHS:
            self.assertEqual(self.get(path, RU).status_code, 403, path)
            self.assertNotEqual(self.get(path, US).status_code, 403, path)

    def test_portal_rules_unused_while_inheriting(self):
        # A portal-only rule changes nothing until the portal has its own policy.
        FirewallCountryRule.objects.create(country_code='RU', country_name='Russia',
                                           surface=FirewallCountryRule.SURFACE_PORTAL)
        self.assertEqual(self.get('/portal/login/', RU).status_code, 403)

    def test_country_allowed_for_portal_but_blocked_for_staff(self):
        self.set_portal('allowlist', 'US', 'IE')
        for path in PORTAL_PATHS:
            self.assertNotEqual(self.get(path, IE).status_code, 403, path)
        for path in STAFF_PATHS:
            self.assertEqual(self.get(path, IE).status_code, 403, path)
        # Russia is on neither list.
        self.assertEqual(self.get('/portal/login/', RU).status_code, 403)

    def test_country_allowed_for_staff_but_blocked_for_portal(self):
        self.set_portal('blocklist', 'US')
        self.assertEqual(self.get('/portal/login/', US).status_code, 403)
        self.assertNotEqual(self.get('/account/login/', US).status_code, 403)

    def test_portal_off_opens_portal_only(self):
        self.set_portal('off')
        self.assertNotEqual(self.get('/portal/login/', RU).status_code, 403)
        self.assertEqual(self.get('/account/login/', RU).status_code, 403)

    def test_portal_policy_applies_with_staff_geoip_switched_off(self):
        s = FirewallSettings.get_settings()
        s.geoip_firewall_enabled = False
        s.save()
        self.set_portal('blocklist', 'RU')
        self.assertEqual(self.get('/portal/login/', RU).status_code, 403)
        self.assertNotEqual(self.get('/account/login/', RU).status_code, 403)

    def test_shared_media_follows_portal_policy_for_anonymous(self):
        self.set_portal('off')
        # Not a 403 from the firewall; serve_media then decides (404 here).
        self.assertNotEqual(self.get('/media/branding/nothing.png', RU).status_code, 403)
        # Staff are judged by the staff policy on shared paths.
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_superuser('su', 'su@x.com', 'pw'))
        self.assertEqual(self.get('/media/branding/nothing.png', RU).status_code, 403)

    def test_log_records_surface(self):
        self.set_portal('blocklist', 'RU')
        self.get('/portal/login/', RU)
        self.get('/account/login/', RU)
        surfaces = sorted(FirewallLog.objects.values_list('surface', flat=True))
        self.assertEqual(surfaces, ['portal', 'staff'])

    def test_unknown_path_counts_as_staff(self):
        self.set_portal('off')
        self.assertEqual(self.get('/portalish/', RU).status_code, 403)

    def test_client_cannot_pick_the_surface(self):
        self.set_portal('off')
        r = self.client.get('/core/dashboard/?surface=portal', HTTP_X_FORWARDED_FOR=RU,
                            HTTP_REFERER='https://x/portal/login/')
        self.assertEqual(r.status_code, 403)


NO_2FA_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                     if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


@override_settings(MIDDLEWARE=NO_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FirewallAdminTests(TestCase):

    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.create_superuser('fwadmin', 'a@x.com', 'pw')
        self.client.force_login(self.admin)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def test_settings_page_saves_portal_mode(self):
        r = self.client.post('/core/settings/firewall/', {
            'geoip_firewall_mode': 'allowlist', 'ip_firewall_mode': 'blocklist',
            'portal_geoip_mode': 'off', 'log_blocked_requests': 'on',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(FirewallSettings.get_settings().portal_geoip_mode, 'off')
        self.client.post('/core/settings/firewall/', {'portal_geoip_mode': 'bogus'})
        self.assertEqual(FirewallSettings.get_settings().portal_geoip_mode, 'off')

    def test_country_map_edits_one_list_only(self):
        FirewallCountryRule.objects.create(country_code='US', country_name='United States')
        r = self.client.post('/core/settings/firewall/country-rules/?surface=portal',
                             {'map_codes': 'IE,GB', 'surface': 'portal'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('surface=portal', r['Location'])
        staff = set(FirewallCountryRule.objects.filter(surface='staff').values_list('country_code', flat=True))
        portal = set(FirewallCountryRule.objects.filter(surface='portal').values_list('country_code', flat=True))
        self.assertEqual(staff, {'US'})
        self.assertEqual(portal, {'IE', 'GB'})
        page = self.client.get('/core/settings/firewall/country-rules/?surface=portal')
        self.assertContains(page, 'Customer portal')
        self.assertEqual(len(page.context['rules']), 2)

    def test_same_country_on_both_lists(self):
        FirewallCountryRule.objects.create(country_code='US', country_name='United States')
        FirewallCountryRule.objects.create(country_code='US', country_name='United States',
                                           surface='portal')
        self.assertEqual(FirewallCountryRule.objects.filter(country_code='US').count(), 2)


class ContractSigningSurfaceTests(TestCase):
    """/sign/ (contract signing) is customer-facing: portal surface, and
    signing links use the portal host while staff links keep the site URL."""

    def test_signing_pages_are_portal_surface(self):
        from core.portal_surface import PORTAL, STAFF, classify_path
        self.assertEqual(classify_path('/sign/t/abc123/'), PORTAL)
        self.assertEqual(classify_path('/contracts/'), STAFF)

    def test_signing_links_use_portal_host_and_staff_links_do_not(self):
        from contracts import mail
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.site_url = 'https://staff.example.com'
        s.save()
        with mock.patch('core.portal_surface.portal_origin', return_value='https://portal.example.com'):
            self.assertEqual(mail.base_url(), 'https://portal.example.com')
            self.assertEqual(mail.staff_base_url(), 'https://staff.example.com')
        with mock.patch('core.portal_surface.portal_origin', return_value=''):
            self.assertEqual(mail.base_url(), 'https://staff.example.com')
