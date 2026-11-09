"""Grouped Settings sidebar (templates/core/_settings_menu.html).

The sidebar used to be one long list with three inline sub-headings. It is now
five collapsible groups — System, Security, Organizations & Access,
Integrations, Mobile — with only the group holding `active_page` expanded.
These tests pin that nothing from the old list was dropped, that the template
and core/settings_groups.py agree, and that gating still holds.
"""
import re

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse

from core import settings_groups

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# Every link the menu carried before the regroup (v3.17.645).
OLD_MENU_URL_NAMES = [
    'core:settings_general', 'core:settings_features', 'core:settings_psa',
    'core:settings_smtp', 'core:settings_sms', 'core:settings_scheduler',
    'core:settings_security', 'core:firewall_settings', 'core:fail2ban_status',
    'core:settings_snyk', 'integrations:integration_list',
    'core:settings_directory', 'core:settings_ai', 'core:system_status',
    'core:settings_kb_import', 'imports:import_list',
    'core:settings_data_export', 'core:maintenance',
]

GROUP_HEADINGS = {
    'system': 'System',
    'security': 'Security',
    'access': 'Organizations & Access',
    'integrations': 'Integrations',
    'mobile': 'Mobile',
}

User = get_user_model()


def render_menu(user, active_page='', psa_enabled=True):
    return render_to_string('core/_settings_menu.html', {
        'user': user, 'active_page': active_page, 'psa_enabled': psa_enabled,
    })


def group_block(html, key):
    """The HTML of one group's collapse body."""
    m = re.search(
        r'<div class="collapse[^"]*" id="settings-group-%s">(.*?)</div>\s*</div>' % key,
        html, re.S,
    )
    assert m, key
    return m.group(1)


def hrefs(html):
    return re.findall(r'<a href="([^"]+)"', html)


class SettingsMenuStructureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser('menu-su', 'su@example.com', 'x')
        cls.staff = User.objects.create_user('menu-staff', 'st@example.com', 'x', is_staff=True)
        cls.plain = User.objects.create_user('menu-plain', 'pl@example.com', 'x')

    def test_every_old_link_still_present_for_superuser(self):
        html = render_menu(self.su)
        links = hrefs(html)
        for name in OLD_MENU_URL_NAMES:
            self.assertIn(reverse(name), links, name)

    def test_template_matches_settings_groups_module(self):
        html = render_menu(self.su)
        for key in settings_groups.GROUP_ORDER:
            expected = [reverse(u) for _p, u, _g in settings_groups.SETTINGS_GROUPS[key]]
            self.assertEqual(hrefs(group_block(html, key)), expected, key)

    def test_group_headings_order_and_counts(self):
        html = render_menu(self.su)
        positions = []
        for key in settings_groups.GROUP_ORDER:
            m = re.search(
                r'data-settings-group="%s">.*?%s</span>.*?badge[^>]*>(\d+)<'
                % (key, re.escape(GROUP_HEADINGS[key])), html, re.S)
            self.assertIsNotNone(m, key)
            positions.append(m.start())
            self.assertEqual(int(m.group(1)), len(settings_groups.SETTINGS_GROUPS[key]), key)
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            {k: len(v) for k, v in settings_groups.SETTINGS_GROUPS.items()},
            {'system': 11, 'security': 5, 'access': 3, 'integrations': 4, 'mobile': 2},
        )

    def test_priority_entries_head_their_group(self):
        g = settings_groups.SETTINGS_GROUPS
        self.assertEqual(g['security'][0][1], 'core:settings_security')
        self.assertEqual(g['access'][0][1], 'accounts:access_management')
        self.assertEqual(g['integrations'][0][1], 'core:webhook_list')
        self.assertIn('core:system_updates', [u for _p, u, _g in g['system'][:2]])

    def test_all_groups_collapsed_without_active_page(self):
        html = render_menu(self.su, active_page='')
        self.assertNotIn('collapse show', html)
        self.assertNotIn('aria-expanded="true"', html)
        self.assertEqual(html.count('aria-expanded="false"'), 5)

    def test_active_group_expanded_and_item_highlighted(self):
        cases = {
            'general': ('system', 'core:settings_general'),
            'firewall': ('security', 'core:firewall_settings'),
            'directory': ('access', 'core:settings_directory'),
            'ai': ('integrations', 'core:settings_ai'),
            'kb_import': ('system', 'core:settings_kb_import'),
            'snyk': ('security', 'core:settings_snyk'),
        }
        for page, (group, url_name) in cases.items():
            with self.subTest(page=page):
                html = render_menu(self.su, active_page=page)
                self.assertIn('class="collapse show" id="settings-group-%s"' % group, html)
                self.assertEqual(html.count('collapse show'), 1)
                self.assertEqual(html.count('aria-expanded="true"'), 1)
                self.assertIn('data-bs-target="#settings-group-%s"\n' % group
                              + '                aria-expanded="true"', html)
                active = re.findall(r'<a href="([^"]+)"[^>]*\bactive\b[^>]*aria-current="page"', html)
                self.assertEqual(active, [reverse(url_name)])

    def test_psa_entry_hidden_when_psa_disabled(self):
        url = reverse('core:settings_psa')
        self.assertIn(url, hrefs(render_menu(self.su, psa_enabled=True)))
        html = render_menu(self.su, psa_enabled=False)
        self.assertNotIn(url, hrefs(html))
        self.assertRegex(html, r'(?s)data-settings-group="system">.*?badge[^>]*>10<')

    def test_superuser_entries_hidden_for_non_superuser(self):
        html = render_menu(self.staff)
        links = hrefs(html)
        self.assertNotIn(reverse('core:settings_general'), links)
        self.assertNotIn(reverse('core:beta_test_admin'), links)
        self.assertIn(reverse('core:mobile_apps_admin'), links)
        self.assertIn(reverse('accounts:access_management'), links)
        plain = hrefs(render_menu(self.plain))
        self.assertNotIn(reverse('core:mobile_apps_admin'), plain)
        self.assertEqual(hrefs(render_menu(AnonymousUser())), [])


class SettingsGroupLandingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser('land-su', 'lsu@example.com', 'x')
        cls.staff = User.objects.create_user('land-staff', 'ls@example.com', 'x', is_staff=True)

    def test_static_mapping_covers_five_groups_and_resolves(self):
        self.assertEqual(tuple(settings_groups.GROUP_LANDING_URL_NAMES), settings_groups.GROUP_ORDER)
        for key, name in settings_groups.GROUP_LANDING_URL_NAMES.items():
            self.assertTrue(reverse(name).startswith('/'), key)

    def test_landing_for_superuser(self):
        expect = {
            'system': 'core:settings_general',
            'security': 'core:settings_security',
            'access': 'accounts:access_management',
            'integrations': 'core:webhook_list',
            'mobile': 'core:mobile_apps_admin',
        }
        for key, name in expect.items():
            self.assertEqual(settings_groups.landing_url_name(key, self.su), name)
            self.assertEqual(settings_groups.landing_url(key, self.su), reverse(name))

    def test_landing_skips_pages_user_cannot_open(self):
        self.assertIsNone(settings_groups.landing_url_name('system', self.staff))
        self.assertEqual(settings_groups.landing_url('security', self.staff), '')
        self.assertEqual(settings_groups.landing_url_name('mobile', self.staff), 'core:mobile_apps_admin')
        self.assertIsNone(settings_groups.landing_url_name('system', AnonymousUser()))

    def test_every_active_page_maps_to_one_group(self):
        pages = [p for entries in settings_groups.SETTINGS_GROUPS.values() for p, _u, _g in entries]
        self.assertEqual(len(pages), len(set(pages)))
        self.assertEqual(settings_groups.group_for_active_page('firewall'), 'security')
        self.assertIsNone(settings_groups.group_for_active_page('nope'))

    def test_template_tag(self):
        from django.template import Context, Template
        out = Template(
            "{% load settings_menu %}{% settings_group_url 'integrations' %}|"
            "{% settings_open_group 'ai' %}"
        ).render(Context({'user': self.su}))
        self.assertEqual(out, reverse('core:webhook_list') + '|integrations')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsMenuOnRealPageTests(TestCase):
    def test_general_settings_page_expands_system(self):
        su = User.objects.create_superuser('page-su', 'p@example.com', 'x')
        self.client.force_login(su)
        resp = self.client.get(reverse('core:settings_general'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('class="collapse show" id="settings-group-system"', html)
        for key in settings_groups.GROUP_ORDER:
            self.assertIn('id="settings-group-%s"' % key, html)
