"""The condensed global menu: what each dropdown holds, for whom.

Every dropdown carries three to seven entries, one per section; the pages that
used to sit beside them in the menu are tabs on the section's landing page
(core/navigation.py, tested in test_navbar_sections.py). The before → after map
is docs/navigation-map.md.

The risk in a regrouping is a destination quietly disappearing or a staff
destination leaking to customer users, so these tests assert on the rendered
navbar, menu by menu, for a superuser, a technician and a customer user, with
modules switched on and off.
"""
import re

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core import navigation
from core.models import Organization, SystemSetting


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

ALL_FLAGS = ('psa_enabled', 'crm_enabled', 'workflows_enabled', 'inventory_enabled',
             'scheduling_enabled', 'monitoring_enabled', 'vehicles_enabled')

PSA = ['psa:my_work', 'psa:ticket_list', 'psa:dispatch_board', 'psa:project_list',
       'psa:service_catalog', 'psa:contract_list', 'psa:requisition_list']
OPS = ['processes:process_list', 'inventory:inventory_dashboard', 'scheduling:task_list',
       'monitoring:website_monitor_list', 'vehicles:vehicle_list']
MODULES = ['security_alerts:alert_list', 'crm:home', 'reports:home']
ASSETS = ['assets:asset_list', 'hardware:device_list', 'monitoring:rack_list',
          'assets:vendor_list']
DOCS = ['docs:document_list', 'docs:diagram_list', 'docs:document_drafts_list',
        'readiness:overview']
VAULT = ['vault:password_list', 'vault:personal_vault_list', 'core:secure_note_inbox',
         'vault:access_rule_list']
ADMIN = ['core:settings_general', 'core:security_dashboard', 'accounts:organization_list',
         'integrations:integration_list', 'core:mobile_apps_admin']
ACCOUNT = ['accounts:profile', 'resourcing:my_resourcing', 'core:help_index',
           'core:install_app']

# Destinations only MSP staff (or superusers) may see in the navbar.
STAFF_ONLY = ['security_alerts:alert_list', 'crm:home', 'reports:home',
              'assets:vendor_list', 'core:settings_general', 'core:security_dashboard',
              'integrations:integration_list', 'core:mobile_apps_admin',
              'core:snyk_scans', 'accounts:access_management', 'core:webhook_list',
              'core:beta_test_admin']


def urls(names):
    return [reverse(n) for n in names]


def menu(html, dropdown_id):
    """(hrefs, has_sign_out) of the dropdown labelled `dropdown_id`, or None."""
    m = re.search(r'<ul class="dropdown-menu[^"]*" aria-labelledby="%s">(.*?)</ul>'
                  % re.escape(dropdown_id), html, re.S)
    if m is None:
        return None
    body = m.group(1)
    hrefs = re.findall(r'<a class="dropdown-item[^"]*" href="([^"]+)"', body)
    return hrefs, 'Sign Out' in body


def top_level(html):
    bar = html.split('id="primaryNav"', 1)[1].split('</ul>\n                <ul class="navbar-nav">', 1)[0]
    return re.findall(r'id="(\w+Dropdown)"', bar)


class NavbarTestBase(TestCase):

    def setUp(self):
        self.flags(**{f: True for f in ALL_FLAGS})
        self.org = Organization.objects.create(name='Nav Co', slug='nav-co')

    def flags(self, **values):
        row = SystemSetting.get_settings()
        for k, v in values.items():
            setattr(row, k, v)
        row.save()

    def make_superuser(self):
        return get_user_model().objects.create_user(
            'nav_su', 'n@x.com', 'pw', is_staff=True, is_superuser=True)

    def make_technician(self):
        """MSP staff by profile only: not a superuser, not Django is_staff."""
        from psa.tests._base import _make_msp_tech
        return _make_msp_tech(get_user_model().objects.create_user('nav_tech', 't@x.com', 'pw'))

    def make_customer(self):
        from accounts.models import Membership
        u = get_user_model().objects.create_user('nav_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=u, organization=self.org, role='owner')
        return u

    def page(self, user, name='core:dashboard'):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        r = self.client.get(reverse(name), follow=True)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SuperuserMenuTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_superuser())

    def test_top_level_order(self):
        self.assertEqual(top_level(self.html), [
            'psaDropdown', 'opsDropdown', 'modulesDropdown', 'assetsDropdown',
            'docsDropdown', 'vaultDropdown', 'adminDropdown'])

    def test_dashboard_stays_a_direct_link(self):
        bar = self.html.split('id="primaryNav"', 1)[1]
        self.assertIn(f'href="{reverse("core:dashboard")}"', bar[:600])

    def test_each_dropdown_holds_exactly_its_sections(self):
        for dropdown, expected in (
                ('psaDropdown', PSA), ('opsDropdown', OPS), ('modulesDropdown', MODULES),
                ('assetsDropdown', ASSETS), ('docsDropdown', DOCS),
                ('vaultDropdown', VAULT), ('adminDropdown', ADMIN),
                ('userDropdown', ACCOUNT)):
            with self.subTest(dropdown=dropdown):
                hrefs, _ = menu(self.html, dropdown)
                self.assertEqual(hrefs, urls(expected))

    def test_counts_stay_within_budget(self):
        budget = {'psaDropdown': 7, 'opsDropdown': 5, 'modulesDropdown': 3,
                  'assetsDropdown': 4, 'docsDropdown': 4, 'vaultDropdown': 4,
                  'adminDropdown': 5}
        for dropdown, limit in budget.items():
            hrefs, _ = menu(self.html, dropdown)
            self.assertLessEqual(len(hrefs), limit, dropdown)
            self.assertGreaterEqual(len(hrefs), 3, dropdown)
        hrefs, sign_out = menu(self.html, 'userDropdown')
        self.assertEqual(len(hrefs) + int(sign_out), 5)

    def test_no_nested_flyouts_or_section_headers(self):
        for dropdown in ('psaDropdown', 'opsDropdown', 'modulesDropdown', 'assetsDropdown',
                         'docsDropdown', 'vaultDropdown', 'adminDropdown', 'userDropdown'):
            body = self.html.split(f'aria-labelledby="{dropdown}"', 1)[1].split('</ul>', 1)[0]
            self.assertNotIn('dropdown-header', body, dropdown)
            self.assertNotIn('dropdown-submenu', body, dropdown)

    def test_the_old_more_menu_is_gone(self):
        self.assertNotIn('moreNavDropdown', self.html)

    def test_new_ticket_left_the_menu_but_is_on_the_ticket_list(self):
        hrefs, _ = menu(self.html, 'psaDropdown')
        self.assertNotIn(reverse('psa:ticket_create'), hrefs)
        tickets = self.page(self.make_technician(), 'psa:ticket_list')
        self.assertIn(reverse('psa:ticket_create'), tickets)

    def test_sign_out_is_still_a_post_form(self):
        body = self.html.split('aria-labelledby="userDropdown"', 1)[1].split('</ul>', 1)[0]
        self.assertIn(f'<form method="post" action="{reverse("logout")}"', body)
        self.assertIn('csrfmiddlewaretoken', body)
        self.assertIn('type="submit"', body)

    def test_visible_utility_controls_survive(self):
        cluster = self.html.split('</ul>\n                <ul class="navbar-nav">', 1)[1]
        self.assertIn(reverse('core:beta_test_signup'), cluster)
        self.assertIn(reverse('core:install_app'), cluster)
        self.assertIn('data-bs-target="#supportProjectModal"', cluster)
        # Both Help modals are still on every page.
        self.assertIn('id="reportBugModal"', self.html)
        self.assertIn('id="supportProjectModal"', self.html)

    def test_client_switcher_and_its_integration_points(self):
        self.assertIn('id="orgDropdown"', self.html)
        self.assertIn('Global View', self.html)
        # The PSA menu's old "Clients" entry lives at the foot of the switcher.
        self.assertIn('data-nav="all-clients"', self.html)

    def test_navbar_entries_match_the_section_registry(self):
        """Each navbar entry is its section's landing page (first tab)."""
        landing = {reverse(s.tabs[0].url_name, args=s.tabs[0].args) for s in navigation.SECTIONS}
        for dropdown in ('psaDropdown', 'opsDropdown', 'modulesDropdown', 'assetsDropdown',
                         'docsDropdown', 'vaultDropdown', 'adminDropdown', 'userDropdown'):
            hrefs, _ = menu(self.html, dropdown)
            for href in hrefs:
                self.assertIn(href, landing, f'{dropdown}: {href} has no section')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TechnicianMenuTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_technician())

    def test_no_admin_menu(self):
        self.assertNotIn('adminDropdown', self.html)
        for name in ('core:settings_general', 'core:security_dashboard', 'core:snyk_scans',
                     'core:mobile_apps_admin', 'accounts:access_management'):
            self.assertNotIn(f'href="{reverse(name)}"', self.html, name)

    def test_menus(self):
        self.assertEqual(top_level(self.html), [
            'psaDropdown', 'opsDropdown', 'modulesDropdown', 'assetsDropdown',
            'docsDropdown', 'vaultDropdown'])
        self.assertEqual(menu(self.html, 'psaDropdown')[0], urls(PSA))
        self.assertEqual(menu(self.html, 'modulesDropdown')[0], urls(MODULES))
        self.assertEqual(menu(self.html, 'assetsDropdown')[0], urls(ASSETS))
        self.assertEqual(menu(self.html, 'userDropdown')[0], urls(ACCOUNT))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerMenuTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_customer())

    def test_no_staff_destinations(self):
        self.assertNotIn('modulesDropdown', self.html)
        self.assertNotIn('adminDropdown', self.html)
        for name in STAFF_ONLY:
            self.assertNotIn(f'href="{reverse(name)}"', self.html, name)
        self.assertNotIn(f'href="{reverse("assets:custom_field_list")}"', self.html)

    def test_menus_match_what_customers_saw_before(self):
        # PSA, Assets (minus Setup), Docs, Vault and Account were never
        # staff-gated in the navbar; the condensed menu keeps that.
        self.assertEqual(menu(self.html, 'psaDropdown')[0], urls(PSA))
        self.assertEqual(menu(self.html, 'assetsDropdown')[0], urls(ASSETS[:3]))
        self.assertEqual(menu(self.html, 'docsDropdown')[0], urls(DOCS))
        self.assertEqual(menu(self.html, 'vaultDropdown')[0], urls(VAULT))
        self.assertEqual(menu(self.html, 'userDropdown')[0], urls(ACCOUNT))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ModuleToggleTests(NavbarTestBase):

    def test_everything_off(self):
        self.flags(**{f: False for f in ALL_FLAGS})
        html = self.page(self.make_superuser())
        self.assertEqual(top_level(html), [
            'modulesDropdown', 'assetsDropdown', 'docsDropdown', 'vaultDropdown',
            'adminDropdown'])
        # Reports is ungated, so Modules survives with one entry.
        self.assertEqual(menu(html, 'modulesDropdown')[0], urls(['reports:home']))

    def test_psa_off_drops_psa_and_security(self):
        self.flags(psa_enabled=False)
        html = self.page(self.make_superuser())
        self.assertNotIn('psaDropdown', html)
        self.assertEqual(menu(html, 'modulesDropdown')[0], urls(['crm:home', 'reports:home']))

    def test_crm_off(self):
        self.flags(crm_enabled=False)
        html = self.page(self.make_superuser())
        self.assertEqual(menu(html, 'modulesDropdown')[0],
                         urls(['security_alerts:alert_list', 'reports:home']))
        self.assertNotIn(reverse('crm:pipeline'), html)

    def test_operations_follow_their_flags(self):
        self.flags(workflows_enabled=False, vehicles_enabled=False)
        html = self.page(self.make_technician())
        self.assertEqual(menu(html, 'opsDropdown')[0], urls(OPS[1:4]))

    def test_operations_menu_disappears_when_all_off(self):
        self.flags(workflows_enabled=False, inventory_enabled=False,
                   scheduling_enabled=False, monitoring_enabled=False,
                   vehicles_enabled=False)
        self.assertNotIn('opsDropdown', self.page(self.make_technician()))
