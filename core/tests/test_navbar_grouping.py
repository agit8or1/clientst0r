"""The top nav fits, and regrouping it lost nothing.

Ten top-level menus plus the search box, org pill and user menu overflowed the
bar at any realistic width. Security, CRM and Reports became sections of one
"More" menu, grouped with headers the way the Admin menu already was.

The risk in that kind of change is a destination quietly disappearing, so
these tests assert on the rendered page rather than on the template source.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Organization, SystemSetting


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# Every destination that used to hang off the Security, CRM or Reports menus.
REGROUPED_URLS = [
    'security_alerts:alert_list', 'security_alerts:connection_list',
    'security_alerts:rule_list', 'core:security_dashboard', 'core:snyk_scans',
    'crm:home', 'crm:pipeline', 'crm:lead_list', 'crm:opportunity_list',
    'crm:campaign_list', 'crm:commission_list', 'crm:commission_rule_list',
    'reports:home', 'reports:dashboard_list', 'reports:wallboard_list',
    'reports:template_list', 'reports:generated_list',
    'reports:analytics_overview',
]

TOP_LEVEL_KEPT = ['Dashboard', 'Operations']


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NavbarGroupingTests(TestCase):

    def setUp(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.crm_enabled = True
        row.workflows_enabled = True
        row.save()
        self.org = Organization.objects.create(name='Nav Co', slug='nav-co')
        self.user = get_user_model().objects.create_user(
            'nav_su', 'n@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _page(self):
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_every_regrouped_destination_is_still_in_the_navbar(self):
        html = self._page()
        missing = [name for name in REGROUPED_URLS
                   if f'href="{reverse(name)}"' not in html]
        self.assertEqual(missing, [])

    def test_the_three_menus_are_no_longer_top_level(self):
        html = self._page()
        for gone in ('securityDropdown', 'crmDropdown', 'reportsDropdown'):
            self.assertNotIn(gone, html)

    def test_they_are_sections_of_the_more_menu(self):
        html = self._page()
        self.assertIn('moreNavDropdown', html)
        more = html.split('moreNavDropdown', 1)[1].split('</ul>', 1)[0]
        for section in ('Security', 'CRM', 'Reports'):
            self.assertIn(section, more)

    def test_the_menus_that_earn_their_place_stay_top_level(self):
        html = self._page()
        for label in TOP_LEVEL_KEPT:
            self.assertIn(label, html)
        # Operations keeps its own menu: nineteen children is too many to nest.
        self.assertIn('opsDropdown', html)

    def test_the_bar_carries_fewer_top_level_menus_than_before(self):
        html = self._page()
        bar = html.split('navbar-nav mx-auto', 1)[1].split('</ul>', 1)[0]
        toggles = bar.count('nav-link dropdown-toggle')
        self.assertLessEqual(toggles, 7,
                             'the left nav is drifting back towards overflow')

    def test_crm_section_disappears_when_crm_is_off(self):
        row = SystemSetting.get_settings()
        row.crm_enabled = False
        row.save()
        html = self._page()
        self.assertNotIn(reverse('crm:pipeline'), html)
        # Reports is ungated, so the menu itself must survive.
        self.assertIn(reverse('reports:home'), html)

    def test_security_section_disappears_when_psa_is_off(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        html = self._page()
        self.assertNotIn(reverse('security_alerts:alert_list'), html)
        self.assertIn(reverse('reports:home'), html)

    def test_a_non_superuser_does_not_see_the_superuser_only_entries(self):
        plain = get_user_model().objects.create_user('nav_plain', 'p@x.com', 'pw')
        self.client.force_login(plain)
        r = self.client.get(reverse('core:dashboard'))
        html = r.content.decode()
        self.assertNotIn(reverse('core:snyk_scans'), html)
