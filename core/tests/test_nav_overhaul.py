"""The 2026-11 navigation overhaul (docs/navigation-map.md).

Ten sections (Administration pinned at the foot as one link to the settings
center), per-section Configure menus, link-only tabs, a tab strip that never
wraps (More menu), Section › Workspace › Page breadcrumbs with a
breadcrumb_tail hook, accessible rail flyouts, the settings center and
destinations_for(). Gates are the pages' own; these tests pin that nothing
new is offered to a user the page would refuse.
"""
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from core import navigation
from core.tests.test_navbar_grouping import STAFF_ONLY, TEST_MIDDLEWARE, NavbarTestBase, aside_of, sidebar

User = get_user_model()

SECTION_KEYS = ['dashboard', 'my_work', 'service_desk', 'clients', 'assets', 'business',
                'knowledge', 'security', 'reports']
SUPERUSER_ONLY = ['core:settings_general', 'core:system_updates', 'core:system_status',
                  'accounts:access_management', 'accounts:user_list', 'core:settings_security',
                  'core:firewall_settings', 'core:maintenance', 'core:settings_ai',
                  'integrations:integration_list', 'core:settings_features']


def frame(html):
    m = re.search(r'<div class="page-frame[^"]*">(.*?)</nav>\s*(?:<nav class="section-tabs|</div>)', html, re.S)
    return m.group(0) if m else ''


def strip(html):
    m = re.search(r'<nav class="section-tabs[^"]*"[^>]*>(.*?)</nav>', html, re.S)
    return m.group(1) if m else None


def trail(html):
    m = re.search(r'<ol class="breadcrumb app-trail__list[^"]*">(.*?)</ol>', html, re.S)
    if not m:
        return []
    return [re.sub(r'<[^>]+>', '', li).strip()
            for li in re.findall(r'<li class="breadcrumb-item[^"]*"[^>]*>(.*?)</li>', m.group(1), re.S)]


class RegistryTests(TestCase):

    def test_ten_sections(self):
        self.assertEqual([g.key for g in navigation.PRIMARY], SECTION_KEYS)
        self.assertEqual(navigation.ADMIN.key, 'settings')
        self.assertEqual(len(navigation.PRIMARY) + 1, 10)

    def test_link_only_tabs_point_at_a_page_with_another_home(self):
        for section in navigation.SECTIONS:
            for tab in section.tabs:
                if not tab.link_only:
                    continue
                with self.subTest(section=section.key, tab=tab.url_name):
                    home = navigation.section_for(tab.url_name)
                    self.assertIsNotNone(home, tab.url_name)
                    self.assertNotEqual(home.key, section.key)

    def test_configure_pages_belong_to_their_section(self):
        for name, key, group in (('psa:recurring_list', 'psa_tickets', 'service_desk'),
                                 ('psa:canned_reply_list', 'psa_tickets', 'service_desk'),
                                 ('psa:email_config_list', 'psa_tickets', 'service_desk'),
                                 ('psa:workflow_rule_list', 'psa_tickets', 'service_desk'),
                                 ('ticket_routing:overview', 'psa_dispatch', 'service_desk'),
                                 ('security_alerts:connection_list', 'mod_security', 'security'),
                                 ('security_alerts:siem_endpoint_list', 'mod_security', 'security'),
                                 ('vault:access_rule_list', 'vault_passwords', 'knowledge'),
                                 ('contracts:settings', 'mod_contracts', 'business')):
            with self.subTest(name=name):
                self.assertEqual(navigation.section_for(name).key, key)
                self.assertEqual(navigation.group_for(name), group)
                self.assertIn(name, [t.url_name for t in navigation.SECTIONS_BY_KEY[key].configure])

    def test_one_vlan_list_per_level_and_one_kb_entry(self):
        hw = navigation.SECTIONS_BY_KEY['assets_hardware']
        ipam = navigation.SECTIONS_BY_KEY['assets_ipam']
        self.assertEqual(str(next(t.label for t in hw.tabs if t.url_name == 'hardware:vlan_list')),
                         'VLAN Ports')
        self.assertEqual(str(next(t.label for t in ipam.tabs if t.url_name == 'monitoring:vlan_list')),
                         'VLANs')
        kb = [e for g in navigation.PRIMARY for e in g.entries if str(e.label) == 'Knowledge Base']
        self.assertEqual(len(kb), 1)
        self.assertEqual(kb[0].section, 'docs_kb')

    def test_contracts_heading_keeps_the_two_systems_distinct(self):
        tabs = {t.url_name: str(t.label) for t in navigation.SECTIONS_BY_KEY['mod_contracts'].tabs}
        self.assertEqual(tabs['psa:contract_list'], 'PSA Contracts')
        self.assertEqual(tabs['contracts:dashboard'], 'Contract Documents')

    def test_split_tabs_keeps_the_current_page_visible(self):
        tabs = [{'label': str(i), 'active': i == 7} for i in range(8)]
        visible, more = navigation.split_tabs(tabs)
        self.assertEqual(len(visible), navigation.STRIP_TABS)
        self.assertIn(tabs[7], visible)
        self.assertEqual(len(visible) + len(more), 8)
        self.assertEqual([t['label'] for t in more], ['5', '6'])
        # One over the limit is drawn whole: a More menu would cost as much.
        self.assertEqual(navigation.split_tabs(tabs[:7]), (tabs[:7], []))

    def test_settings_categories(self):
        self.assertEqual(
            [str(navigation.SECTIONS_BY_KEY[k].label) for k in navigation.SETTINGS_CATEGORIES],
            ['General', 'Users & Access', 'Security', 'Integrations', 'AI Configuration', 'Automation',
             'Communications', 'Modules', 'System', 'Maintenance'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SidebarMarkupTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        self.html = self.page(self.make_superuser(), 'psa:recurring_list')

    def test_section_buttons_are_disclosures_that_never_navigate(self):
        aside = aside_of(self.html)
        buttons = re.findall(r'<button type="button" class="app-nav__group-btn[^"]*" id="appNavBtn-(\w+)"\s*'
                             r'aria-expanded="(true|false)" aria-controls="appNavGroup-(\w+)"', aside)
        self.assertEqual([b[0] for b in buttons], list(sidebar(self.html))[:-1])
        for key, expanded, controls in buttons:
            self.assertEqual(key, controls)
            self.assertIn(f'<ul class="app-nav__entries" id="appNavGroup-{key}" aria-labelledby="appNavBtn-{key}"',
                          aside)
        # Only the current section starts expanded.
        self.assertEqual([b[0] for b in buttons if b[1] == 'true'], ['service_desk'])
        self.assertNotIn('app-nav__group-link', aside)

    def test_rail_tooltips_flyout_heads_and_pinned_administration(self):
        aside = aside_of(self.html)
        self.assertIn('data-tip="Service Desk"', aside)
        self.assertIn('<li class="app-nav__flyout-head" aria-hidden="true">Service Desk</li>', aside)
        pinned = aside.split('<nav class="app-nav__pinned"', 1)
        self.assertEqual(len(pinned), 2, 'Administration is pinned below the scrolling list')
        self.assertIn('id="appNavList"', pinned[0])
        self.assertIn(f'href="{reverse("core:settings_home")}"', pinned[1])
        self.assertEqual(sidebar(self.html)['settings'], [reverse('core:settings_home')])
        # The width is applied before first paint (rail on tablets by default).
        self.assertIn("localStorage.getItem('appnav.rail')", self.html)

    def test_configure_pages_are_not_sidebar_links_but_the_filter_finds_them(self):
        aside = aside_of(self.html)
        links = re.findall(r'<a class="app-nav__(?:link|sublink)[^"]*" href="([^"]+)"', aside)
        extra = aside.split('class="app-nav__extra"', 1)[1].split('</ul>', 1)[0]
        for name in ('psa:recurring_list', 'psa:canned_reply_list', 'psa:email_config_list',
                     'psa:workflow_rule_list', 'ticket_routing:overview', 'core:settings_smtp'):
            with self.subTest(name=name):
                self.assertNotIn(reverse(name), links)
                self.assertIn(f'class="app-nav__xlink" href="{reverse(name)}"', extra)

    def test_configure_menu_and_breadcrumb_on_a_configure_page(self):
        pills = strip(self.html)
        self.assertIn('id="sectionConfigure"', pills)
        self.assertIn('aria-haspopup="true"', pills)
        self.assertRegex(pills, r'class="dropdown-item active" href="%s" aria-current="page"'
                         % re.escape(reverse('psa:recurring_list')))
        for name in ('psa:canned_reply_list', 'psa:email_config_list', 'psa:workflow_rule_list'):
            self.assertIn(f'href="{reverse(name)}"', pills)
        self.assertEqual(trail(self.html)[:3], ['Service Desk', 'Tickets', 'Recurring Tickets'])

    def test_strip_overflows_into_more_not_a_second_row(self):
        html = self.client.get(reverse('psa:my_work')).content.decode()
        pills = strip(html)
        self.assertNotIn('flex-wrap"', pills.split('section-tabs__list', 1)[1][:40])
        more = pills.split('class="nav-item dropdown section-tabs__more"', 1)[1]
        self.assertFalse(more.lstrip().startswith('hidden'))
        self.assertIn('data-bs-toggle="dropdown" aria-expanded="false"', more)
        visible = pills.split('section-tabs__more', 1)[0]
        self.assertEqual(visible.count('class="nav-item section-tabs__item"'), navigation.STRIP_TABS)
        self.assertRegex(visible, r'class="nav-link active" href="%s" aria-current="page"'
                         % re.escape(reverse('psa:my_work')))
        self.assertEqual(trail(html), ['My Work', 'My Queue'])

    def test_my_work_reaches_the_work_details_pages(self):
        nav = sidebar(self.html)
        for name in ('psa:my_work', 'psa:my_timesheet', 'resourcing:my_leave', 'resourcing:my_resourcing',
                     'resourcing:my_billable_target', 'scheduling:my_tasks', 'resourcing:shift_schedule'):
            self.assertIn(reverse(name), nav['my_work'], name)

    def test_client_workspace_lights_clients_without_a_second_strip(self):
        """The workspace draws its own ?tab= strip; the frame adds none, the
        Clients section is current and only Client Workspace is lit."""
        for name in ('accounts:organization_detail', 'accounts:organization_edit',
                     'accounts:organization_create', 'accounts:organization_delete',
                     'accounts:organization_service_info', 'accounts:ownership_transfer',
                     'accounts:member_add', 'accounts:member_edit', 'accounts:member_remove'):
            self.assertEqual(navigation.section_for(name).key, 'clients_all', name)
        html = self.client.get(reverse('accounts:organization_detail', args=[self.org.id])).content.decode()
        self.assertIn('<li class="app-nav__group is-active" data-group="clients"', html)
        active = re.findall(r'class="app-nav__(?:link|sublink) active" href="([^"]+)"', aside_of(html))
        self.assertEqual(active, [reverse('accounts:organization_detail', args=[self.org.id])])
        self.assertIsNone(strip(html))
        # breadcrumb_tail sits inside the trail's <ol>, after the section crumbs.
        base = (Path(django_settings.BASE_DIR) / 'templates/base.html').read_text()
        ol = base.split('<ol class="breadcrumb app-trail__list', 1)[1].split('</ol>', 1)[0]
        self.assertIn('{% endfor %}{% block breadcrumb_tail %}{% endblock %}', ol)

    def test_a_link_only_page_lights_one_place(self):
        html = self.client.get(reverse('scheduling:my_tasks')).content.decode()
        self.assertIn('<li class="app-nav__group is-active" data-group="my_work"', html)
        self.assertEqual(len(re.findall(r'class="app-nav__(?:link|sublink) active"', aside_of(html))), 1)
        # The strip is the page's home section's (Scheduling).
        self.assertIn(f'href="{reverse("scheduling:task_calendar")}"', strip(html))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BreadcrumbTailTests(NavbarTestBase):

    def test_a_page_can_add_its_own_last_crumb(self):
        su = self.make_superuser()
        request = RequestFactory().get(reverse('psa:ticket_list'))
        request.resolver_match = resolve(request.path)
        request.user = su
        request.session = {}
        html = Template(
            '{% extends "base.html" %}{% block breadcrumb_tail %}'
            '<li class="breadcrumb-item active" aria-current="page">T-10482</li>{% endblock %}'
        ).render(RequestContext(request, {}))
        self.assertEqual(trail(html), ['Service Desk', 'Tickets', 'All Tickets', 'T-10482'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsCenterTests(NavbarTestBase):

    def cards(self, html):
        return re.findall(r'<section class="settings-card" data-settings-group="(\w+)"', html)

    def test_superuser_sees_every_category(self):
        html = self.page(self.make_superuser(), 'core:settings_home')
        self.assertEqual(self.cards(html), list(navigation.SETTINGS_CATEGORIES))
        self.assertIn('id="settingsCenterSearch"', html)
        self.assertIn('<label class="visually-hidden" for="settingsCenterSearch">', html)
        self.assertIn('OPTIONAL AI', html)
        self.assertIn('AI features are off', html)       # psa_ai_enabled is off here
        self.assertIn(f'id="topbarSettings"', html)
        self.assertRegex(html, r'href="%s" id="topbarSettings"' % re.escape(reverse('core:settings_home')))
        self.assertEqual(trail(html), ['Administration'])

    def test_ai_note_goes_away_when_ai_is_on(self):
        self.flags(psa_ai_enabled=True)
        html = self.page(self.make_superuser(), 'core:settings_home')
        self.assertNotIn('AI features are off', html)

    def test_technician_gets_only_what_their_checks_allow(self):
        tech = self.make_technician()
        html = self.page(tech, 'core:settings_home')
        cards = self.cards(html)
        self.assertNotIn('settings_system', cards)
        self.assertNotIn('settings_ai', cards)
        main = html.split('id="main-content"', 1)[1]
        for name in SUPERUSER_ONLY:
            self.assertNotIn(f'href="{reverse(name)}"', main, name)
        for href in set(re.findall(r'<li data-filter="[^"]*"><a href="([^"]+)"', main)):
            with self.subTest(href=href):
                self.assertNotIn(self.client.get(href).status_code, (403, 404), href)

    def test_customer_owner_sees_organization_pages_customer_user_is_refused(self):
        owner = self.make_customer('owner', 'sc_owner')
        self.client.force_login(owner)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))
        html = self.client.get(reverse('core:settings_home')).content.decode()
        self.assertIn('data-settings-group="settings_access"', html)
        for name in SUPERUSER_ONLY:
            self.assertNotIn(f'href="{reverse(name)}"', html.split('id="main-content"', 1)[1], name)
        reader = self.make_customer('readonly', 'sc_reader')
        self.client.force_login(reader)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.assertEqual(self.client.get(reverse('core:settings_home')).status_code, 403)

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get(reverse('core:settings_home')).status_code, 302)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DestinationsTests(NavbarTestBase):

    def destinations(self, user, name='core:dashboard'):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        r = self.client.get(reverse(name), follow=True)
        self.assertEqual(r.status_code, 200)
        return navigation.destinations_for(None, r.context['pnav'])

    def test_shape_and_one_entry_per_url(self):
        dests = self.destinations(self.make_superuser())
        self.assertTrue(dests)
        for d in dests:
            self.assertEqual(set(d) >= {'label', 'href', 'icon', 'group', 'section'}, True, d)
            self.assertTrue(d['href'].startswith('/'), d)
        hrefs = [d['href'] for d in dests]
        self.assertEqual(len(hrefs), len(set(hrefs)))

    def test_superuser_gets_settings_configure_and_account_pages(self):
        hrefs = {d['href']: d for d in self.destinations(self.make_superuser())}
        for name in ('core:settings_general', 'core:settings_home', 'security_alerts:connection_list',
                     'psa:recurring_list', 'accounts:profile', 'resourcing:my_leave', 'crm:pipeline'):
            self.assertIn(reverse(name), hrefs, name)
        # A link-only shortcut is listed under its page's home.
        self.assertEqual(hrefs[reverse('psa:kb_browse')]['group'], 'Knowledge & Vault')

    def test_plain_technician_gets_no_superuser_destinations(self):
        hrefs = {d['href'] for d in self.destinations(self.make_technician())}
        for name in SUPERUSER_ONLY:
            self.assertNotIn(reverse(name), hrefs, name)
        self.assertIn(reverse('psa:recurring_list'), hrefs)
        for href in sorted(hrefs):
            with self.subTest(href=href):
                self.assertNotIn(self.client.get(href).status_code, (403, 404), href)

    def test_customer_user_gets_no_staff_or_admin_destinations(self):
        hrefs = {d['href'] for d in self.destinations(self.make_customer('readonly', 'dst_cust'))}
        # (Recurring / Canned / Email Ingestion keep the gates they had as
        # Tickets tabs: PSA on, checked again by the views.)
        for name in STAFF_ONLY + SUPERUSER_ONLY + ['core:settings_home']:
            self.assertNotIn(reverse(name), hrefs, name)
        for href in sorted(hrefs):
            with self.subTest(href=href):
                self.assertNotEqual(self.client.get(href).status_code, 403, href)

    def test_disabled_modules_are_absent(self):
        self.flags(crm_enabled=False, vehicles_enabled=False, psa_enabled=False)
        hrefs = {d['href'] for d in self.destinations(self.make_superuser())}
        for name in ('crm:home', 'crm:pipeline', 'vehicles:vehicle_list', 'psa:ticket_list',
                     'psa:recurring_list', 'psa:my_work', 'core:settings_psa'):
            self.assertNotIn(reverse(name), hrefs, name)

    def test_request_context_matches_the_template_context(self):
        su = self.make_superuser()
        request = RequestFactory().get(reverse('core:dashboard'))
        request.resolver_match = resolve(request.path)
        request.user = su
        from_view = {d['href'] for d in navigation.destinations_for(navigation.request_context(request))}
        from_page = {d['href'] for d in self.destinations(su)}
        self.assertEqual(from_view - from_page, set())
