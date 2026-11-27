"""Administration -> Security pages say what the code does (docs/SECURITY_SETTINGS.md):
the dashboard's automated-scan interval, the firewall page's GeoIP source and
staff-bypass rule, the Snyk settings that automatic scans ignore, and the 2FA
safeguard's single sign-on condition.
"""
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from core.models import ScheduledTask
from core.security_features import FEATURES
from core.settings_views import _every_minutes

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class EveryMinutesTests(SimpleTestCase):
    def test_labels(self):
        self.assertEqual(_every_minutes(1440), 'every day')
        self.assertEqual(_every_minutes(2880), 'every 2 days')
        self.assertEqual(_every_minutes(360), 'every 6 hours')
        self.assertEqual(_every_minutes(60), 'every hour')
        self.assertEqual(_every_minutes(90), 'every 90 minutes')
        self.assertEqual(_every_minutes(1), 'every minute')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecurityAdminPagesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('sec-admin', 'sec-admin@example.com', 'x-Long-passw0rd!')
        self.client.force_login(self.admin)

    def test_dashboard_states_the_scan_interval_plainly(self):
        ScheduledTask.get_or_create_defaults()
        with mock.patch('core.system_warnings.collect_system_warnings', return_value=[]):
            r = self.client.get('/core/security/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Runs every day.')
        self.assertNotContains(r, 'every 1440day')

    def test_firewall_page_names_the_local_geoip_database_and_staff_flag(self):
        r = self.client.get('/core/settings/firewall/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'IP to Country Lite')
        self.assertNotContains(r, '45 requests/minute')
        self.assertContains(r, 'is_staff')

    def test_snyk_page_says_frequency_is_not_used(self):
        r = self.client.get('/core/settings/snyk/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Saved, but not used yet')

    def test_pages_stay_superuser_only(self):
        tech = User.objects.create_user('sec-tech', 'sec-tech@example.com', 'x-Long-passw0rd!')
        self.client.force_login(tech)
        for path in ('/core/security/', '/core/settings/security/', '/core/settings/firewall/',
                     '/core/settings/snyk/', '/core/security/features/', '/core/security/vault-visibility/'):
            self.assertIn(self.client.get(path).status_code, (302, 403), path)


class TwoFactorCatalogTests(SimpleTestCase):
    def test_sso_condition_matches_the_middleware(self):
        entry = next(f for f in FEATURES if f['key'] == 'two_factor')
        self.assertIn('AZURE_SSO_TRUSTED_AS_2FA', entry['prerequisites'])
        self.assertIn('oidc_sso_2fa_accepted', entry['prerequisites'])
