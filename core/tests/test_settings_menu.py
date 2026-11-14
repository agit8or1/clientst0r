"""The settings workspace (templates/core/_settings_menu.html).

Settings used to be a left-hand column of five collapsible groups
(core/settings_groups.py), repeated in every settings template, plus a long
Admin entry in the sidebar. They are now ten categories defined once in
core/navigation.py (sections with menu='settings'): the sidebar's
Administration link opens the settings center (core:settings_home, cards per
category), and every settings page carries a header with the category tabs,
the current category's pages and a search.

These tests pin that nothing from the old menu was dropped, that each page
lights its own category, that a link is only drawn when the page's own check
passes (the gate mismatches of the old menu are fixed), and that the page
frame has one breadcrumb trail and no leftover left-hand menu.
"""
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse

from core import navigation
from core.models import Organization

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# Every link the old settings menu carried (core/settings_groups.py, v3.17.671).
OLD_MENU_URL_NAMES = [
    'core:settings_general', 'core:system_updates', 'core:system_status',
    'core:settings_features', 'core:settings_modules', 'core:settings_psa',
    'core:settings_scheduler', 'core:settings_smtp', 'core:maintenance',
    'imports:import_list', 'core:settings_data_export', 'core:settings_kb_import',
    'core:settings_security', 'tech_access:index', 'rmm_permissions:index',
    'core:security_dashboard', 'core:firewall_settings', 'core:fail2ban_status',
    'core:settings_snyk', 'accounts:access_management', 'core:settings_directory',
    'office:org_policy', 'core:webhook_list', 'integrations:integration_list',
    'integrations:rem0te_setup', 'core:settings_ai', 'psa_ai:profiles', 'core:settings_sms',
    'office:settings', 'core:mobile_apps_admin', 'core:beta_test_admin',
]
# The one old settings entry that moved out: the client list is a work page.
MOVED_OUT = {'accounts:organization_list': 'clients_all'}

CATEGORIES = [
    ('settings_general', 'General'), ('settings_access', 'Users & Access'),
    ('settings_security', 'Security'), ('settings_integrations', 'Integrations'),
    ('settings_ai', 'AI Configuration'), ('settings_automation', 'Automation'),
    ('settings_email', 'Communications'), ('settings_features', 'Modules'),
    ('settings_system', 'System'), ('settings_maintenance', 'Maintenance'),
]

User = get_user_model()


def workspace(html):
    m = re.search(r'<nav class="settings-ws"[^>]*>(.*?)</nav>', html, re.S)
    return m.group(1) if m else None


def index_hrefs(html):
    return re.findall(r'<li data-href="([^"]+)"', workspace(html) or '')


class SettingsRegistryTests(TestCase):

    def test_ten_categories_in_order(self):
        self.assertEqual(
            [(k, str(navigation.SECTIONS_BY_KEY[k].label)) for k in navigation.SETTINGS_CATEGORIES],
            CATEGORIES)

    def test_every_old_menu_page_has_a_category(self):
        for name in OLD_MENU_URL_NAMES:
            with self.subTest(name=name):
                self.assertEqual(navigation.VIEW_INDEX[name].menu, 'settings', name)
        for name, key in MOVED_OUT.items():
            self.assertEqual(navigation.VIEW_INDEX[name].key, key)

    def test_each_page_has_one_category(self):
        seen = {}
        for key in navigation.SETTINGS_CATEGORIES:
            for tab in navigation.SECTIONS_BY_KEY[key].tabs:
                self.assertNotIn(tab.url_name, seen, tab.url_name)
                seen[tab.url_name] = key

    def test_the_old_module_is_gone(self):
        import importlib.util
        self.assertIsNone(importlib.util.find_spec('core.settings_groups'))

    def test_include_without_the_frame_renders_nothing(self):
        """Old `{% include "core/_settings_menu.html" with active_page=… %}`
        calls are harmless: only base.html's frame draws the header."""
        su = User.objects.create_superuser('inc-su', 'i@x.com', 'x')
        self.assertEqual(render_to_string('core/_settings_menu.html',
                                          {'user': su, 'active_page': 'general'}).strip(), '')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsWorkspaceOnPagesTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Set Co', slug='set-co')
        from core.models import SystemSetting
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.save()

    def login(self, user, org=True):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        if org:
            self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))

    def get(self, name, *args):
        r = self.client.get(reverse(name, args=args))
        self.assertEqual(r.status_code, 200, name)
        return r.content.decode()

    def test_superuser_reaches_every_old_page_from_the_workspace(self):
        self.login(User.objects.create_superuser('ws-su', 'su@x.com', 'x'))
        hrefs = index_hrefs(self.get('core:settings_general'))
        for name in OLD_MENU_URL_NAMES:
            with self.subTest(name=name):
                self.assertIn(reverse(name), hrefs)

    def test_each_page_lights_its_category_and_itself(self):
        self.login(User.objects.create_superuser('ws-su2', 'su2@x.com', 'x'))
        for name, key in (('core:settings_general', 'settings_general'),
                          ('core:firewall_settings', 'settings_security'),
                          ('core:settings_directory', 'settings_access'),
                          ('core:settings_ai', 'settings_ai'),
                          ('psa_ai:profiles', 'settings_ai'),
                          ('core:settings_kb_import', 'settings_maintenance'),
                          ('core:settings_snyk', 'settings_security'),
                          ('core:settings_smtp', 'settings_email'),
                          ('core:system_updates', 'settings_system')):
            with self.subTest(name=name):
                ws = workspace(self.get(name))
                self.assertIsNotNone(ws, name)
                self.assertRegex(ws, r'data-settings-group="%s">\s*<a class="nav-link active"[^>]*'
                                     r'aria-current="true"' % key)
                self.assertEqual(len(re.findall(r'class="nav-link[^"]*\bactive\b', ws)), 2, name)
                self.assertIn('class="nav-link settings-menu-item active" href="%s" '
                              'aria-current="page"' % reverse(name), ws)

    def test_sub_pages_keep_their_category(self):
        self.login(User.objects.create_superuser('ws-su3', 'su3@x.com', 'x'))
        ws = workspace(self.get('core:firewall_ip_rules'))
        self.assertRegex(ws, r'data-settings-group="settings_security">\s*<a class="nav-link active"')
        self.assertIn('href="%s"' % reverse('core:firewall_settings'), ws)

    def test_frame_has_one_trail_and_no_left_column(self):
        self.login(User.objects.create_superuser('ws-su4', 'su4@x.com', 'x'))
        for name in ('core:settings_general', 'core:firewall_settings', 'tech_access:index',
                     'rmm_permissions:index', 'office:settings', 'core:security_dashboard',
                     'accounts:role_list', 'core:tag_list'):
            with self.subTest(name=name):
                html = self.get(name)
                main = html.split('id="main-content"', 1)[1]
                self.assertEqual(len(re.findall(r'<ol class="breadcrumb', main)), 1, name)
                self.assertNotIn('settings-group-system', html)
                self.assertNotIn('class="col-md-3', main.split('settingsWorkspace', 1)[-1][:4000])

    def test_search_and_unsaved_changes_guard(self):
        self.login(User.objects.create_superuser('ws-su5', 'su5@x.com', 'x'))
        html = self.get('core:settings_general')
        ws = workspace(html)
        self.assertIn('id="settingsSearch"', ws)
        self.assertIn('<label class="visually-hidden" for="settingsSearch">', ws)
        self.assertIn('role="status"', ws)
        self.assertIn('js/settings_ws.js', html)
        # Index entries carry their category and keywords for the filter.
        self.assertRegex(ws, r'data-label="SMTP / Email" data-where="Communications" '
                             r'data-filter="SMTP / Email mail outgoing smtp')
        js = (Path(django_settings.BASE_DIR) / 'static/js/settings_ws.js').read_text()
        self.assertIn('beforeunload', js)
        self.assertIn('data-no-dirty-check', js)

    def test_psa_off_drops_the_psa_page(self):
        from core.models import SystemSetting
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        self.login(User.objects.create_superuser('ws-su6', 'su6@x.com', 'x'))
        self.assertNotIn(reverse('core:settings_psa'), index_hrefs(self.get('core:settings_general')))

    def test_django_staff_gets_only_their_pages(self):
        """Django is_staff (not superuser) opens Mobile Apps, not Access
        Management (superuser-only in the view; the old menu showed it)."""
        staff = User.objects.create_user('ws-staff', 'st@x.com', 'x', is_staff=True)
        self.login(staff, org=False)
        hrefs = index_hrefs(self.get('core:mobile_apps_admin'))
        self.assertIn(reverse('core:mobile_apps_admin'), hrefs)
        for name in ('core:settings_general', 'core:beta_test_admin', 'accounts:access_management',
                     'integrations:integration_list'):
            self.assertNotIn(reverse(name), hrefs, name)
        for href in hrefs:
            with self.subTest(href=href):
                self.assertNotEqual(self.client.get(href).status_code, 403, href)

    def test_customer_owner_sees_only_organization_pages(self):
        from accounts.models import Membership
        owner = User.objects.create_user('ws-owner', 'o@x.com', 'x')
        Membership.objects.create(user=owner, organization=self.org, role='owner')
        self.login(owner)
        html = self.get('accounts:member_list')
        hrefs = index_hrefs(html)
        self.assertIn(reverse('accounts:member_list'), hrefs)
        self.assertIn(reverse('core:webhook_list'), hrefs)   # require_admin: owners pass
        for name in OLD_MENU_URL_NAMES:
            if name in ('core:webhook_list', 'office:org_policy'):
                continue
            self.assertNotIn(reverse(name), hrefs, name)
        for href in hrefs:
            with self.subTest(href=href):
                self.assertNotEqual(self.client.get(href).status_code, 403, href)
        # No Administration group in the sidebar for a customer user.
        self.assertNotIn('data-group="settings"', html)

    def test_editor_is_not_offered_webhooks(self):
        """The old menu showed Webhooks to every signed-in user; the list needs
        the admin role now (core.webhook_views.webhook_list)."""
        from accounts.models import Membership
        editor = User.objects.create_user('ws-editor', 'e@x.com', 'x')
        Membership.objects.create(user=editor, organization=self.org, role='editor')
        self.login(editor)
        html = self.get('core:dashboard')
        self.assertNotIn(f'href="{reverse("core:webhook_list")}"', html)
