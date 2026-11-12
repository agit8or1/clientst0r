"""The primary sidebar: which groups and entries, for whom.

Seven technician groups (My Work, Tickets, Clients, Devices, Alerts, Tools,
Reports) and Settings at the foot, built from core.navigation.PRIMARY /
SETTINGS. Each entry lands on its section's first tab, and a section's tabs
are nested under it (core/navigation.py, tested in test_navbar_sections.py).
The before → after map is docs/navigation-map.md.

The risk in a regrouping is a destination quietly disappearing or a staff
destination leaking to customer users, so these tests assert on the rendered
sidebar, group by group, for a superuser, a technician and a customer user,
with modules switched on and off — and that nothing is drawn which the server
would answer with 403.
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

GROUP_ORDER = ['my_work', 'tickets', 'clients', 'devices', 'alerts', 'tools', 'reports']

# Entry landing pages per group, for a superuser with every module on.
MY_WORK = ['psa:my_work', 'core:dashboard', 'core:favorite_list', 'vault:personal_vault_list',
           'core:secure_note_inbox']
TICKETS = ['psa:ticket_list', 'psa:dispatch_board', 'psa:project_list', 'psa:service_catalog']
CLIENTS = ['accounts:organization_list', 'core:customer_ops_current', 'docs:document_list',
           'docs:diagram_list', 'docs:document_drafts_list', 'readiness:overview',
           'vault:password_list', 'vault:access_rule_list', 'psa:contract_list', 'crm:home']
DEVICES = ['assets:asset_list', 'integrations:rmm_devices', 'assets:device_workspace_home', 'hardware:device_list',
           'monitoring:rack_list']
ALERTS = ['integrations:rmm_alerts', 'security_alerts:alert_list', 'monitoring:website_monitor_list']
TOOLS = ['processes:process_list', 'scheduling:task_list', 'inventory:inventory_dashboard',
         'psa:requisition_list', 'vehicles:vehicle_list']
REPORTS = ['reports:home']
SETTINGS = ['core:settings_general', 'core:security_dashboard', 'accounts:access_management',
            'integrations:integration_list', 'assets:vendor_list', 'core:mobile_apps_admin']

# What a superuser sees on top of that: the pages added on the dev branch,
# each behind its page's own check (docs/navigation-map.md).
TICKETS_SU = ['psa:ticket_list', 'psa:dispatch_board', 'resourcing:shift_schedule',
              'psa:project_list', 'psa:service_catalog']
ALERTS_SU = ALERTS + ['ticket_routing:alerts']
TOOLS_SU = ['processes:process_list', 'support_workflows:admin', 'scheduling:task_list',
            'inventory:inventory_dashboard', 'psa:requisition_list', 'vehicles:vehicle_list']
SETTINGS_SU = ['core:settings_general', 'core:security_dashboard', 'accounts:access_management',
               'accounts:ldap_group_mappings', 'rmm_permissions:index',
               'integrations:integration_list', 'assets:vendor_list', 'core:mobile_apps_admin']
ACCOUNT = ['accounts:profile', 'resourcing:my_resourcing', 'core:help_index',
           'core:install_app']

# Destinations only MSP staff (or superusers) may see.
STAFF_ONLY = ['security_alerts:alert_list', 'crm:home', 'reports:home',
              'assets:vendor_list', 'core:settings_general', 'core:security_dashboard',
              'integrations:integration_list', 'core:mobile_apps_admin',
              'core:snyk_scans', 'accounts:access_management', 'core:webhook_list',
              'core:beta_test_admin', 'integrations:rmm_devices', 'integrations:rmm_alerts',
              'assets:device_workspace_home', 'inventory:inventory_dashboard']


def urls(names):
    return [reverse(n) for n in names]


def sidebar(html):
    """{group key: [entry hrefs]} of the rendered sidebar, in order."""
    if 'id="appNav"' not in html:
        return {}
    aside = html.split('id="appNav"', 1)[1].split('</aside>', 1)[0]
    out = {}
    parts = re.split(r'<li class="app-nav__group[^"]*" data-group="(\w+)"', aside)
    for key, body in zip(parts[1::2], parts[2::2]):
        out[key] = re.findall(r'<a class="app-nav__link[^"]*" href="([^"]+)"', body)
    return out


def menu(html, dropdown_id):
    """(hrefs, has_sign_out) of the dropdown labelled `dropdown_id`, or None."""
    m = re.search(r'<ul class="dropdown-menu[^"]*" aria-labelledby="%s">(.*?)</ul>'
                  % re.escape(dropdown_id), html, re.S)
    if m is None:
        return None
    body = m.group(1)
    hrefs = re.findall(r'<a class="dropdown-item[^"]*" href="([^"]+)"', body)
    return hrefs, 'Sign Out' in body


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

    def make_customer(self, role='owner', username='nav_cust'):
        from accounts.models import Membership
        u = get_user_model().objects.create_user(username, f'{username}@x.com', 'pw')
        Membership.objects.create(user=u, organization=self.org, role=role)
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
class SuperuserSidebarTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_superuser())
        self.nav = sidebar(self.html)

    def test_group_order(self):
        self.assertEqual(list(self.nav), GROUP_ORDER + ['settings'])

    def test_each_group_holds_exactly_its_entries(self):
        for key, expected in (('my_work', MY_WORK), ('tickets', TICKETS_SU), ('clients', CLIENTS),
                              ('devices', DEVICES), ('alerts', ALERTS_SU), ('tools', TOOLS_SU),
                              ('reports', REPORTS), ('settings', SETTINGS_SU)):
            with self.subTest(group=key):
                self.assertEqual(self.nav[key], urls(expected))

    def test_old_dropdowns_are_gone_but_the_account_menu_stays(self):
        for old in ('psaDropdown', 'opsDropdown', 'modulesDropdown', 'assetsDropdown',
                    'docsDropdown', 'vaultDropdown', 'adminDropdown', 'moreNavDropdown'):
            self.assertNotIn(f'id="{old}"', self.html)
        hrefs, sign_out = menu(self.html, 'userDropdown')
        self.assertEqual(hrefs, urls(ACCOUNT))
        self.assertTrue(sign_out)

    def test_sidebar_is_searchable_collapsible_and_labelled(self):
        self.assertIn('id="appNavFilter"', self.html)
        self.assertIn('id="appNavCollapse"', self.html)
        self.assertIn('id="appNavOpen"', self.html)          # phone drawer button
        self.assertIn('aria-label="Primary"', self.html)
        self.assertIn('id="shortcutHelp"', self.html)        # ? overlay
        self.assertIn('js/app_nav.js', self.html)
        # Every entry carries filter text, nested tabs included.
        self.assertIn('data-filter="Canned Replies Tickets Tickets"', self.html)

    def test_every_old_menu_landing_page_is_still_one_click_away(self):
        """Each pre-sidebar navbar entry is an entry (or nested tab) here."""
        old = ['core:dashboard', 'psa:my_work', 'psa:ticket_list', 'psa:dispatch_board',
               'psa:project_list', 'psa:service_catalog', 'psa:contract_list',
               'psa:requisition_list', 'processes:process_list', 'inventory:inventory_dashboard',
               'scheduling:task_list', 'monitoring:website_monitor_list', 'vehicles:vehicle_list',
               'security_alerts:alert_list', 'crm:home', 'reports:home', 'assets:asset_list',
               'hardware:device_list', 'monitoring:rack_list', 'assets:vendor_list',
               'docs:document_list', 'docs:diagram_list', 'docs:document_drafts_list',
               'readiness:overview', 'vault:password_list', 'vault:personal_vault_list',
               'core:secure_note_inbox', 'vault:access_rule_list', 'core:settings_general',
               'core:security_dashboard', 'accounts:organization_list',
               'integrations:integration_list', 'core:mobile_apps_admin']
        aside = self.html.split('id="appNav"', 1)[1].split('</aside>', 1)[0]
        for name in old:
            self.assertIn(f'href="{reverse(name)}"', aside, name)

    def test_sign_out_is_still_a_post_form(self):
        body = self.html.split('aria-labelledby="userDropdown"', 1)[1].split('</ul>', 1)[0]
        self.assertIn(f'<form method="post" action="{reverse("logout")}"', body)
        self.assertIn('csrfmiddlewaretoken', body)

    def test_client_switcher_and_its_integration_points(self):
        self.assertIn('id="orgDropdown"', self.html)
        self.assertIn('Global View', self.html)
        self.assertIn('data-nav="all-clients"', self.html)

    def test_sidebar_follows_the_navbar_in_the_document(self):
        """Skip link → bar → sidebar → main; the star stays the first
        favorites link (test_navbar_utility_buttons relies on it)."""
        self.assertLess(self.html.index('class="navbar'), self.html.index('id="appNav"'))
        self.assertLess(self.html.index('id="appNav"'), self.html.index('id="main-content"'))
        self.assertLess(self.html.index('nav-util'), self.html.index('id="appNav"'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TechnicianSidebarTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_technician())
        self.nav = sidebar(self.html)

    def test_groups(self):
        self.assertEqual(list(self.nav), GROUP_ORDER + ['settings'])
        self.assertEqual(self.nav['devices'], urls(DEVICES))
        self.assertEqual(self.nav['alerts'], urls(ALERTS))
        self.assertEqual(self.nav['reports'], urls(REPORTS))

    def test_settings_holds_only_what_a_technician_may_open(self):
        self.assertEqual(self.nav['settings'], urls(['assets:vendor_list']))
        for name in ('core:settings_general', 'core:security_dashboard', 'core:snyk_scans',
                     'core:mobile_apps_admin', 'accounts:access_management'):
            self.assertNotIn(f'href="{reverse(name)}"', self.html, name)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerSidebarTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_customer())
        self.nav = sidebar(self.html)

    def test_no_staff_destinations(self):
        # RMM and security alerts are staff-only; website monitoring was in
        # the customer's Operations menu before and stays.
        self.assertEqual(self.nav['alerts'], urls(['monitoring:website_monitor_list']))
        self.assertNotIn('reports', self.nav)
        self.assertNotIn('settings', self.nav)
        for name in STAFF_ONLY:
            self.assertNotIn(f'href="{reverse(name)}"', self.html, name)
        self.assertNotIn(f'href="{reverse("assets:custom_field_list")}"', self.html)

    def test_customer_keeps_what_they_saw_before(self):
        # Dispatch is MSP-staff-only: the server refuses it to customers.
        self.assertEqual(self.nav['tickets'],
                         urls([n for n in TICKETS if n != 'psa:dispatch_board']))
        self.assertEqual(self.nav['devices'], urls(['assets:asset_list', 'hardware:device_list',
                                                    'monitoring:rack_list']))
        for name in ('docs:document_list', 'vault:password_list', 'psa:contract_list'):
            self.assertIn(reverse(name), self.nav['clients'])

    def test_nothing_drawn_that_the_server_would_refuse(self):
        """Every sidebar link a customer sees answers something other than 403."""
        aside = self.html.split('id="appNav"', 1)[1].split('</aside>', 1)[0]
        for href in sorted(set(re.findall(r'href="(/[^"#?]*)"', aside))):
            with self.subTest(href=href):
                self.assertNotEqual(self.client.get(href).status_code, 403, href)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleFlagProbeTests(NavbarTestBase):
    """A customer role without vault_view / docs_view gets no link the
    SectionPermissionMiddleware would answer 403."""

    def test_role_without_vault_and_docs(self):
        from accounts.models import Membership, RoleTemplate
        user = get_user_model().objects.create_user('nav_novault', 'nv@x.com', 'pw')
        rt = RoleTemplate.objects.create(name='No vault or docs', organization=self.org,
                                         vault_view=False, docs_view=False, assets_view=True)
        Membership.objects.create(user=user, organization=self.org, role='readonly', role_template=rt)
        html = self.page(user)
        aside = html.split('id="appNav"', 1)[1].split('</aside>', 1)[0]
        self.assertNotIn(f'href="{reverse("vault:password_list")}"', aside)
        self.assertNotIn(f'href="{reverse("docs:document_list")}"', aside)
        self.assertIn(f'href="{reverse("assets:asset_list")}"', aside)
        # The personal vault is exempt from the vault gate and stays.
        self.assertIn(f'href="{reverse("vault:personal_vault_list")}"', aside)
        self.assertEqual(self.client.get(reverse('vault:password_list')).status_code, 403)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ModuleToggleTests(NavbarTestBase):

    def test_everything_off(self):
        self.flags(**{f: False for f in ALL_FLAGS})
        nav = sidebar(self.page(self.make_superuser()))
        self.assertNotIn('tickets', nav)
        # With PSA off the global knowledge base is the only tool left.
        self.assertEqual(nav['tools'], urls(['docs:global_kb_list']))
        self.assertEqual(nav['alerts'], urls(['integrations:rmm_alerts']))
        self.assertEqual(nav['reports'], urls(REPORTS))   # Reports is ungated
        self.assertNotIn(reverse('psa:my_work'), nav['my_work'])

    def test_psa_off_drops_tickets_billing_procurement_and_security(self):
        self.flags(psa_enabled=False)
        html = self.page(self.make_superuser())
        nav = sidebar(html)
        self.assertNotIn('tickets', nav)
        self.assertNotIn(reverse('psa:contract_list'), nav['clients'])
        self.assertNotIn(reverse('psa:requisition_list'), nav['tools'])
        self.assertNotIn(reverse('security_alerts:alert_list'), nav['alerts'])

    def test_crm_off(self):
        self.flags(crm_enabled=False)
        html = self.page(self.make_superuser())
        self.assertNotIn(reverse('crm:home'), sidebar(html)['clients'])
        self.assertNotIn(reverse('crm:pipeline'), html)

    def test_tools_follow_their_flags(self):
        self.flags(workflows_enabled=False, vehicles_enabled=False)
        nav = sidebar(self.page(self.make_technician()))
        self.assertEqual(nav['tools'], urls(['scheduling:task_list', 'inventory:inventory_dashboard',
                                             'psa:requisition_list']))

    def test_global_kb_moves_into_tools_when_psa_is_off(self):
        self.flags(psa_enabled=False, global_kb_enabled=True)
        nav = sidebar(self.page(self.make_superuser()))
        self.assertIn(reverse('docs:global_kb_list'), nav['tools'])


class RegistryTests(TestCase):

    def test_every_section_with_a_sidebar_home_is_reachable(self):
        """Every SECTION is an entry of some group, except the account-menu ones."""
        placed = {e.section for g in navigation.ALL_GROUPS for e in g.entries if e.section}
        account = {s.key for s in navigation.SECTIONS if s.menu == 'account'}
        missing = {s.key for s in navigation.SECTIONS} - placed - account
        self.assertEqual(missing, set())

    def test_group_for(self):
        self.assertEqual(navigation.group_for('psa:ticket_detail'), 'tickets')
        self.assertEqual(navigation.group_for('psa:recurring_list'), 'tickets')
        self.assertEqual(navigation.group_for('monitoring:rack_detail'), 'devices')
        self.assertEqual(navigation.group_for('monitoring:website_monitor_detail'), 'alerts')
        self.assertEqual(navigation.group_for('integrations:rmm_device_detail'), 'devices')
        self.assertEqual(navigation.group_for('integrations:rmm_detail'), 'settings')
        self.assertEqual(navigation.group_for('core:settings_smtp'), 'settings')
        self.assertEqual(navigation.group_for('assets:custom_field_list'), 'settings')
        self.assertEqual(navigation.group_for('accounts:profile'), '')

    def test_group_count_and_order(self):
        self.assertEqual([g.key for g in navigation.PRIMARY], GROUP_ORDER)
        self.assertEqual(navigation.SETTINGS.key, 'settings')


ADDED_PAGES = ['resourcing:shift_schedule', 'resourcing:shift_templates', 'field_ops:dispatch_sharing',
               'field_ops:dispatch_geo_settings', 'psa:billing_review', 'assets:serial_search',
               'psa:workflow_rule_map', 'support_workflows:admin', 'ticket_routing:alerts',
               'rmm_permissions:index', 'docs:kb_analytics', 'security_alerts:digest_subscriptions',
               'accounts:ldap_group_mappings', 'integrations:rem0te_setup']
# Pages a technician without any role flag may still open.
TECH_ADDED = ['resourcing:shift_schedule', 'field_ops:dispatch_sharing', 'assets:serial_search',
              'docs:kb_analytics']
# Superuser- or role-only pages a plain technician must not be offered.
TECH_HIDDEN = ['field_ops:dispatch_geo_settings', 'accounts:ldap_group_mappings',
               'integrations:rem0te_setup']


def aside_of(html):
    return html.split('id="appNav"', 1)[1].split('</aside>', 1)[0]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AddedPagesInSidebarTests(NavbarTestBase):
    """Pages that were only linked from inside their apps now have a sidebar
    link, behind the same check the page applies."""

    def test_superuser_reaches_every_added_page(self):
        aside = aside_of(self.page(self.make_superuser()))
        for name in ADDED_PAGES:
            with self.subTest(page=name):
                self.assertIn(f'href="{reverse(name)}"', aside)

    def test_every_added_link_opens_for_the_superuser(self):
        self.page(self.make_superuser())
        for name in ADDED_PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_technician_gets_only_what_their_checks_allow(self):
        html = self.page(self.make_technician())
        aside = aside_of(html)
        for name in TECH_ADDED:
            with self.subTest(page=name):
                self.assertIn(f'href="{reverse(name)}"', aside)
        for name in TECH_HIDDEN:
            with self.subTest(page=name):
                self.assertNotIn(f'href="{reverse(name)}"', aside)
        offered = set(re.findall(r'href="(/[^"#?]*)"', aside))
        for name in ADDED_PAGES:
            href = reverse(name)
            if href in offered:
                with self.subTest(href=href):
                    self.assertNotIn(self.client.get(href).status_code, (403, 404), href)

    def test_customer_gets_none_of_the_staff_pages(self):
        aside = aside_of(self.page(self.make_customer()))
        for name in ADDED_PAGES:
            if name == 'assets:serial_search':
                continue  # scoped to the customer's own assets, like All Assets
            with self.subTest(page=name):
                self.assertNotIn(f'href="{reverse(name)}"', aside)

    def test_active_group_of_the_added_pages(self):
        for name, group in (('resourcing:shift_schedule', 'tickets'),
                            ('field_ops:dispatch_geo_settings', 'tickets'),
                            ('psa:billing_review', 'clients'),
                            ('assets:serial_search', 'devices'),
                            ('ticket_routing:alerts', 'alerts'),
                            ('ticket_routing:alert_maintenance', 'alerts'),
                            ('support_workflows:admin', 'tools'),
                            ('support_workflows:admin_new', 'tools'),
                            ('rmm_permissions:index', 'settings'),
                            ('rmm_permissions:approvals', 'settings'),
                            ('accounts:ldap_group_mappings', 'settings'),
                            ('integrations:rem0te_setup', 'settings'),
                            ('security_alerts:digest_subscriptions', 'alerts')):
            with self.subTest(page=name):
                self.assertEqual(navigation.group_for(name), group)
