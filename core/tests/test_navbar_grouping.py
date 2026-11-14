"""The primary sidebar: which sections and entries, for whom.

Nine work sections (Dashboard, My Work, Service Desk, Clients, Assets &
Network, Business, Knowledge & Vault, Security & Monitoring, Reports) and
Administration pinned at the foot, built from core.navigation.PRIMARY /
ADMIN. Each entry lands on its section's first tab, the current entry's tabs
are nested under it (core/navigation.py, tested in test_navbar_sections.py),
and Administration is one link to the settings center, whose cards are the
ten settings categories. The before → after map is docs/navigation-map.md.

The risk in a regrouping is a destination quietly disappearing or a staff
destination leaking to customer users, so these tests assert on the rendered
sidebar, group by group, for a superuser, a technician and a customer user,
with modules switched on and off — and that nothing is drawn which the server
would answer with 403 (RoleSidebarTests walks every drawn link per role).
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
             'scheduling_enabled', 'monitoring_enabled', 'vehicles_enabled', 'pulse_enabled')

GROUP_ORDER = ['dashboard', 'my_work', 'service_desk', 'clients', 'assets', 'business',
               'knowledge', 'security', 'reports']

# Entry landing pages per section, for a superuser with every module on and
# no customer selected. Dashboard ends with the default pin (Tickets).
OVERVIEW = ['core:dashboard', 'core:favorite_list']
# Default pins for a staff user (core.shortcut_strip): My Work and Tickets.
OVERVIEW_STAFF = OVERVIEW + ['psa:my_work', 'psa:ticket_list']
MY_WORK = ['psa:my_work', 'scheduling:my_tasks', 'psa:my_timesheet', 'psa:timesheet_approval_queue',
           'resourcing:shift_schedule', 'resourcing:my_leave', 'resourcing:my_resourcing',
           'resourcing:my_billable_target']
OPERATIONS = ['psa:ticket_list', 'psa:dispatch_board', 'scheduling:task_list',
              'resourcing:shift_schedule', 'psa:project_list', 'psa:service_catalog',
              'processes:process_list']
# Client Workspace opens the selected client (these tests select one).
CLIENTS = ['accounts:organization_list', 'CURRENT_ORG', 'core:customer_ops_current']
ASSETS = ['assets:asset_list', 'integrations:rmm_devices', 'assets:device_workspace_home',
          'hardware:device_list', ('hardware:diagram', 'connectivity'), 'monitoring:rack_list',
          'monitoring:subnet_list', 'inventory:inventory_dashboard', 'vehicles:vehicle_list']
BUSINESS = ['crm:home', 'psa:contract_list', 'psa:quote_list', 'psa:invoice_list', 'psa:aging_report',
            'psa:requisition_list', 'psa:vendor_list', 'pulse:check_list']
KNOWLEDGE = ['docs:document_list', 'psa:kb_browse', 'docs:diagram_list', 'docs:document_drafts_list',
             'readiness:overview', 'vault:password_list', 'vault:personal_vault_list',
             'core:secure_note_inbox']
TOOLS_SU = ['security_alerts:alert_list', 'security_alerts:incident_list', 'integrations:rmm_alerts',
            'ticket_routing:alerts', 'monitoring:website_monitor_list']
# A technician with no role: Security Alerts needs security_alerts_view
# (@require_perm on the page), so it is not drawn.
TOOLS = ['integrations:rmm_alerts', 'monitoring:website_monitor_list']
REPORTS = ['reports:home']
# Administration: one link, the settings center.
SETTINGS_SU = ['core:settings_home']
ACCOUNT = ['accounts:profile', 'resourcing:my_resourcing', 'core:help_index',
           'core:beta_test_signup', 'core:install_app']

# Destinations only MSP staff (or superusers) may see.
STAFF_ONLY = ['security_alerts:alert_list', 'crm:home', 'reports:home',
              'assets:vendor_list', 'core:settings_general', 'core:security_dashboard',
              'integrations:integration_list', 'core:mobile_apps_admin',
              'core:snyk_scans', 'accounts:access_management',
              'core:beta_test_admin', 'integrations:rmm_devices', 'integrations:rmm_alerts',
              'assets:device_workspace_home', 'inventory:inventory_dashboard',
              'contracts:dashboard', 'pulse:check_list', 'security_alerts:incident_list',
              'psa:dispatch_heatmap', 'psa:workflow_template_list', 'vault:reveal_request_list']


def urls(names):
    return [reverse(n[0], args=n[1:]) if isinstance(n, tuple) else reverse(n) for n in names]


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
    hrefs = [h for h in re.findall(r'<a class="dropdown-item[^"]*" href="([^"]+)"', body)
             if h != '#']   # '#' opens a modal (Help Us Grow)
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
        for key, expected in (('dashboard', OVERVIEW_STAFF), ('my_work', MY_WORK),
                              ('service_desk', OPERATIONS), ('clients', CLIENTS), ('assets', ASSETS),
                              ('business', BUSINESS), ('knowledge', KNOWLEDGE), ('security', TOOLS_SU),
                              ('reports', REPORTS), ('settings', SETTINGS_SU)):
            expected = [('accounts:organization_detail', self.org.id) if n == 'CURRENT_ORG' else n
                        for n in expected]
            with self.subTest(group=key):
                self.assertEqual(self.nav[key], urls(expected))

    def test_administration_is_one_link_to_the_settings_center(self):
        """No settings pages in the sidebar: Administration opens the settings
        center, whose cards are the categories (test_nav_overhaul.py)."""
        body = self.html.split('data-group="settings"', 1)[1].split('</ul>', 1)[0]
        self.assertNotIn('app-nav__sub', body)
        self.assertEqual(self.nav['settings'], [reverse('core:settings_home')])
        self.assertEqual(len(navigation.ADMIN.entries), len(navigation.SETTINGS_CATEGORIES))

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
        self.assertIn('data-filter="Tickets psa helpdesk queue ai inbox Service Desk"', self.html)
        # Configure pages are found by the filter too (filter-only list).
        self.assertRegex(self.html, r'<li data-filter="Canned Replies [^"]*Tickets Service Desk" hidden>')

    def test_g_shortcuts(self):
        """Each group and the shortcut entries keep a `g <key>` target."""
        for key in ('h', 'w', 't', 'c', 'd', 'b', 'k', 'a', 'r', 's'):
            with self.subTest(key=key):
                self.assertIn(f'data-shortcut-key="{key}"', self.html)

    def test_every_old_menu_landing_page_is_still_one_click_away(self):
        """Each pre-sidebar navbar entry is an entry (or nested tab) here, or a
        settings category page one click from Administration."""
        old = ['core:dashboard', 'psa:my_work', 'psa:ticket_list', 'psa:dispatch_board',
               'psa:project_list', 'psa:service_catalog', 'psa:contract_list',
               'psa:requisition_list', 'processes:process_list', 'inventory:inventory_dashboard',
               'scheduling:task_list', 'monitoring:website_monitor_list', 'vehicles:vehicle_list',
               'security_alerts:alert_list', 'crm:home', 'reports:home', 'assets:asset_list',
               'hardware:device_list', 'monitoring:rack_list',
               'docs:document_list', 'docs:diagram_list', 'docs:document_drafts_list',
               'readiness:overview', 'vault:password_list', 'vault:personal_vault_list',
               'core:secure_note_inbox', 'core:settings_general',
               'accounts:organization_list']
        aside = aside_of(self.html)
        for name in old:
            if name == 'core:settings_general':
                continue  # a settings page: one click from the settings center
            self.assertIn(f'href="{reverse(name)}"', aside, name)
        # In the settings workspace (one click from the settings center).
        for name in ('assets:vendor_list', 'core:security_dashboard', 'core:mobile_apps_admin',
                     'core:settings_general', 'integrations:integration_list'):
            self.assertEqual(navigation.VIEW_INDEX[name].menu, 'settings', name)

    def test_sign_out_is_still_a_post_form(self):
        body = self.html.split('aria-labelledby="userDropdown"', 1)[1].split('</ul>', 1)[0]
        self.assertIn(f'<form method="post" action="{reverse("logout")}"', body)
        self.assertIn('csrfmiddlewaretoken', body)

    def test_client_switcher_and_its_integration_points(self):
        self.assertIn('id="orgDropdown"', self.html)
        self.assertIn('Global View', self.html)
        self.assertIn('data-nav="all-clients"', self.html)

    def test_sidebar_follows_the_navbar_in_the_document(self):
        """Skip link → bar → sidebar → main."""
        self.assertLess(self.html.index('class="navbar'), self.html.index('id="appNav"'))
        self.assertLess(self.html.index('id="appNav"'), self.html.index('id="main-content"'))
        self.assertLess(self.html.index('id="utilityNav"'), self.html.index('id="appNav"'))

    def test_no_shortcut_strip_under_the_bar(self):
        """Pins live in Dashboard now; the old strip is not drawn."""
        self.assertNotIn('id="shortcutStrip"', self.html)
        self.assertIn('app-nav__entry--pin', self.html)
        self.assertIn('Edit pinned pages', self.html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TechnicianSidebarTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.tech = self.make_technician()
        self.html = self.page(self.tech)
        self.nav = sidebar(self.html)

    def ctx(self):
        from django.test import RequestFactory
        from django.urls import resolve
        request = RequestFactory().get(reverse('core:dashboard'))
        request.resolver_match = resolve(request.path)
        request.user = self.tech
        request.is_staff_user = True
        return navigation.request_context(request)

    def test_groups(self):
        self.assertEqual(list(self.nav), GROUP_ORDER + ['settings'])
        self.assertEqual(self.nav['security'], urls(TOOLS))
        # Reports Home needs a reports role flag; Software Compliance admits
        # MSP staff by the legacy rule (require_msp_wide_perm, legacy='staff').
        self.assertEqual(self.nav['reports'], urls(['reports:software_compliance_report']))

    def test_administration_holds_only_what_a_technician_may_open(self):
        # A category is listed only when some page in it passes its check.
        center = self.client.get(reverse('core:settings_home')).content.decode()
        self.assertEqual(re.findall(r'class="settings-card" data-settings-group="([^"]+)"', center),
                         ['settings_general', 'settings_integrations', 'settings_automation'])
        for name in ('assets:vendor_list', 'office:org_policy', 'psa:workflow_template_list'):
            self.assertIn(f'href="{reverse(name)}"', center, name)
        self.assertEqual(self.nav['settings'], [reverse('core:settings_home')])
        aside = aside_of(self.html)
        for name in ('core:settings_general', 'core:security_dashboard', 'core:snyk_scans',
                     'core:mobile_apps_admin', 'accounts:access_management'):
            self.assertNotIn(f'href="{reverse(name)}"', aside, name)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerSidebarTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_customer())
        self.nav = sidebar(self.html)

    def test_no_staff_destinations(self):
        self.assertNotIn('reports', self.nav)
        self.assertNotIn('settings', self.nav)
        for name in STAFF_ONLY:
            self.assertNotIn(f'href="{reverse(name)}"', self.html, name)
        self.assertNotIn(f'href="{reverse("assets:custom_field_list")}"', self.html)
        # Website monitoring was in the customer's menu before and stays.
        self.assertIn(reverse('monitoring:website_monitor_list'), self.nav['security'])

    def test_customer_keeps_what_they_saw_before(self):
        # Dispatch is MSP-staff-only: the server refuses it to customers.
        self.assertIn(reverse('psa:ticket_list'), self.nav['service_desk'])
        self.assertNotIn(reverse('psa:dispatch_board'), self.nav['service_desk'])
        for name in ('assets:asset_list', 'hardware:device_list', 'monitoring:rack_list'):
            self.assertIn(reverse(name), self.nav['assets'], name)
        for name in ('docs:document_list', 'vault:password_list'):
            self.assertIn(reverse(name), self.nav['knowledge'], name)
        self.assertIn(reverse('psa:contract_list'), self.nav['business'])

    def test_customer_owner_reaches_their_settings_from_the_account_menu(self):
        hrefs, _ = menu(self.html, 'userDropdown')
        self.assertIn(reverse('core:settings_home'), hrefs)
        center = self.client.get(reverse('core:settings_home')).content.decode()
        self.assertIn(f'href="{reverse("accounts:member_list")}"', center)

    def test_nothing_drawn_that_the_server_would_refuse(self):
        """Every sidebar link a customer sees answers something other than 403."""
        for href in sorted(set(re.findall(r'href="(/[^"#?]*)"', aside_of(self.html)))):
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
        aside = aside_of(self.page(user))
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
        # Service Desk keeps only Workflows' Support Workflows? No: it needs PSA too.
        self.assertNotIn('service_desk', nav)
        # Contract documents are not behind a module flag; the rest of Business is.
        self.assertEqual(nav['business'], urls(['contracts:dashboard']))
        self.assertEqual(nav['reports'], urls(REPORTS))   # Reports is ungated
        self.assertNotIn(reverse('psa:my_work'), nav['my_work'])
        self.assertIn(reverse('integrations:rmm_alerts'), nav['security'])

    def test_psa_off_drops_tickets_billing_procurement_and_security(self):
        self.flags(psa_enabled=False)
        nav = sidebar(self.page(self.make_superuser()))
        self.assertNotIn(reverse('psa:ticket_list'), nav.get('service_desk', []))
        self.assertNotIn(reverse('psa:contract_list'), nav.get('business', []))
        self.assertNotIn(reverse('psa:requisition_list'), nav.get('business', []))
        self.assertNotIn(reverse('security_alerts:alert_list'), nav['security'])

    def test_crm_off(self):
        self.flags(crm_enabled=False)
        html = self.page(self.make_superuser())
        self.assertNotIn(reverse('crm:home'), sidebar(html)['business'])
        self.assertNotIn(reverse('crm:pipeline'), aside_of(html))

    def test_inventory_and_vehicles_follow_their_flags(self):
        self.flags(vehicles_enabled=False, inventory_enabled=False)
        nav = sidebar(self.page(self.make_technician()))
        self.assertNotIn(reverse('inventory:inventory_dashboard'), nav['assets'])
        self.assertNotIn(reverse('vehicles:vehicle_list'), nav['assets'])

    def test_one_knowledge_base_entry_whichever_module_serves_it(self):
        self.flags(psa_enabled=False, global_kb_enabled=True)
        nav = sidebar(self.page(self.make_superuser()))
        self.assertIn(reverse('docs:global_kb_list'), nav['knowledge'])
        self.assertNotIn(reverse('psa:kb_browse'), nav['knowledge'])
        self.flags(psa_enabled=True)
        nav = sidebar(self.page(self.make_superuser_again()))
        self.assertIn(reverse('psa:kb_browse'), nav['knowledge'])
        self.assertNotIn(reverse('docs:global_kb_list'), nav['knowledge'])

    def make_superuser_again(self):
        return get_user_model().objects.create_user('nav_su2', 'n2@x.com', 'pw', is_staff=True,
                                                    is_superuser=True)


class RegistryTests(TestCase):

    def test_every_section_with_a_sidebar_home_is_reachable(self):
        """Every SECTION is an entry of some group, except the account-menu
        ones and My Work, whose pages are entries of their own."""
        placed = {e.section for g in navigation.ALL_GROUPS for e in g.entries if e.section}
        account = {s.key for s in navigation.SECTIONS if s.menu == 'account'}
        entry_urls = {e.url_name for g in navigation.ALL_GROUPS for e in g.entries if e.url_name}
        flat = {s.key for s in navigation.SECTIONS
                if all(t.url_name in entry_urls for t in s.tabs if not t.link_only)}
        missing = {s.key for s in navigation.SECTIONS} - placed - account - flat
        self.assertEqual(missing, set())

    def test_ten_settings_categories(self):
        self.assertEqual(list(navigation.SETTINGS_CATEGORIES),
                         ['settings_general', 'settings_access', 'settings_security',
                          'settings_integrations', 'settings_ai', 'settings_automation',
                          'settings_email', 'settings_features', 'settings_system',
                          'settings_maintenance'])
        self.assertEqual([e.section for e in navigation.ADMIN.entries],
                         list(navigation.SETTINGS_CATEGORIES))

    def test_group_for(self):
        for name, group in (('psa:ticket_detail', 'service_desk'),
                            ('psa:recurring_list', 'service_desk'),
                            ('monitoring:rack_detail', 'assets'),
                            ('monitoring:website_monitor_detail', 'security'),
                            ('integrations:rmm_device_detail', 'assets'),
                            ('integrations:rmm_detail', 'settings'),
                            ('core:settings_smtp', 'settings'),
                            ('assets:custom_field_list', 'settings'),
                            ('psa:contract_list', 'business'),
                            ('reports:home', 'reports'),
                            ('resourcing:my_leave', 'my_work'),
                            ('core:settings_home', 'settings'),
                            ('accounts:profile', '')):
            with self.subTest(name=name):
                self.assertEqual(navigation.group_for(name), group)

    def test_group_count_and_order(self):
        self.assertEqual([g.key for g in navigation.PRIMARY], GROUP_ORDER)
        self.assertEqual(navigation.SETTINGS.key, 'settings')
        self.assertEqual(str(navigation.SETTINGS.label), 'Administration')


ADDED_PAGES = ['resourcing:shift_schedule', 'resourcing:shift_templates', 'field_ops:dispatch_sharing',
               'field_ops:dispatch_geo_settings', 'psa:billing_review', 'assets:serial_search',
               'psa:workflow_rule_map', 'support_workflows:admin', 'ticket_routing:alerts',
               'docs:kb_analytics', 'security_alerts:digest_subscriptions']
# Pages a technician without any role flag may still open.
TECH_ADDED = ['resourcing:shift_schedule', 'field_ops:dispatch_sharing', 'assets:serial_search',
              'docs:kb_analytics']
# Superuser- or role-only pages a plain technician must not be offered.
TECH_HIDDEN = ['field_ops:dispatch_geo_settings']


def aside_of(html):
    return html.split('id="appNav"', 1)[1].split('</aside>', 1)[0]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AddedPagesInSidebarTests(NavbarTestBase):
    """Pages that were only linked from inside their apps have a sidebar
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
        aside = aside_of(self.page(self.make_technician()))
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
        for name, group in (('resourcing:shift_schedule', 'my_work'),
                            ('field_ops:dispatch_geo_settings', 'service_desk'),
                            ('psa:billing_review', 'business'),
                            ('assets:serial_search', 'assets'),
                            ('ticket_routing:alerts', 'security'),
                            ('ticket_routing:alert_maintenance', 'security'),
                            ('support_workflows:admin', 'service_desk'),
                            ('support_workflows:admin_new', 'service_desk'),
                            ('rmm_permissions:index', 'settings'),
                            ('rmm_permissions:approvals', 'settings'),
                            ('accounts:ldap_group_mappings', 'settings'),
                            ('integrations:rem0te_setup', 'settings'),
                            ('security_alerts:digest_subscriptions', 'security')):
            with self.subTest(page=name):
                self.assertEqual(navigation.group_for(name), group)
