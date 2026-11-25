"""The top bar: shortcuts, search, bell, help, gear, client switcher, account.

Beta app, Install app and the support heart ("Help Us Grow", v3.17.586) were
visible buttons between the favorites star and the search box (v3.17.559 put
them behind an ellipsis, v3.17.580 brought them back out). The top-bar
redesign moves them into the account menu so the bar can carry the
destinations people use all day: shortcuts derived from the sidebar's
entries, search, the notification bell, help, settings and the client
switcher. These tests pin that move deliberately — the three controls keep
their accessible names, tooltips and behaviour, they are just one click
deeper — and that the bar itself is labelled, ordered and expands at the
992px (lg) breakpoint.
"""
import re

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Organization, SystemSetting


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def account_menu(html):
    return html.split('aria-labelledby="userDropdown"', 1)[1].split('</ul>', 1)[0]


def utility_bar(html):
    return html.split('id="utilityNav"', 1)[1].split('id="userDropdown"', 1)[0]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TopBarTests(TestCase):

    def setUp(self):
        cache.clear()
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.crm_enabled = True
        row.save()
        self.org = Organization.objects.create(name='Nav Co', slug='util-co')
        self.user = get_user_model().objects.create_user(
            'util_su', 'u@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _html(self, name='core:dashboard'):
        r = self.client.get(reverse(name))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    # -- the controls moved into the account menu (the beta sign-up was
    # removed in v3.17.681) ----------------------------------------------------

    def test_the_three_live_in_the_account_menu(self):
        menu = account_menu(self._html())
        self.assertIn(f'href="{reverse("core:install_app")}"', menu)
        self.assertIn('data-bs-target="#supportProjectModal"', menu)

    def test_they_are_no_longer_in_the_bar(self):
        bar = utility_bar(self._html())
        self.assertNotIn(reverse('core:install_app'), bar)
        self.assertNotIn('supportProjectModal', bar)
        self.assertNotIn('id="moreMenu"', bar)

    def test_they_keep_their_original_order(self):
        menu = account_menu(self._html())
        install = menu.index(reverse('core:install_app'))
        support = menu.index('data-bs-target="#supportProjectModal"')
        self.assertLess(install, support)

    def test_each_has_an_accessible_name(self):
        menu = account_menu(self._html())
        for label in ('Install app', 'Help Us Grow'):
            self.assertIn(f'aria-label="{label}"', menu)
            # The visible label is the accessible name.
            self.assertRegex(menu, r'(?s)aria-label="%s">.*?%s\s*</' % (label, label))

    def test_each_has_a_descriptive_tooltip(self):
        menu = account_menu(self._html())
        for phrase in (
                       'Install the app on your phone or desktop',
                       'Help us grow'):
            self.assertIn(phrase, menu)

    def test_support_still_opens_the_modal_with_a_tooltip(self):
        html = self._html()
        self.assertIn('id="supportProjectModal"', html)
        self.assertIn('data-bs-tooltip', account_menu(html))
        self.assertIn("'[data-bs-toggle=\"tooltip\"], [data-bs-tooltip]'", html)

    def test_icons_are_hidden_from_screen_readers(self):
        menu = account_menu(self._html())
        for icon in re.findall(r'<i class="[^"]*"[^>]*>', menu):
            self.assertIn('aria-hidden="true"', icon)

    def test_sign_out_and_theme_toggle_stay(self):
        menu = account_menu(self._html())
        self.assertIn('Sign Out', menu)
        self.assertIn('data-action="toggleTheme"', menu)

    # -- the bar --------------------------------------------------------------

    def test_bar_expands_at_lg(self):
        html = self._html()
        self.assertIn('navbar navbar-expand-lg', html)
        self.assertIn('id="topbarShortcuts"', html)
        self.assertIn('d-lg-flex', html.split('id="topbarShortcuts"', 1)[0][-200:])

    def test_shortcuts_come_from_the_sidebar_entries(self):
        html = self._html('psa:ticket_list')
        bar = html.split('id="topbarShortcuts"', 1)[1].split('</ul>', 1)[0]
        hrefs = re.findall(r'href="([^"]+)"', bar)
        self.assertEqual(hrefs, [reverse(n) for n in (
            'core:dashboard', 'psa:my_work', 'psa:ticket_list', 'accounts:organization_list',
            'assets:asset_list', 'psa:project_list', 'reports:home')])
        self.assertRegex(bar, r'href="%s"[^>]*aria-current="page"' % reverse('psa:ticket_list'))
        self.assertEqual(bar.count('aria-current="page"'), 1)
        # Labels stay in the accessible tree when visually hidden.
        self.assertIn('topbar-link__text', bar)

    def test_order_search_help_settings_switcher_account(self):
        html = self._html()
        bar = html.split('id="utilityNav"', 1)[1]
        positions = [bar.index(marker) for marker in (
            'class="nav-search', 'id="topbarHelp"', 'id="topbarSettings"',
            'id="orgDropdown"', 'id="userDropdown"')]
        self.assertEqual(positions, sorted(positions))

    def test_help_and_gear_are_named_links(self):
        bar = utility_bar(self._html())
        self.assertRegex(bar, r'id="topbarHelp"[^>]*aria-label="Help"')
        self.assertRegex(bar, r'id="topbarSettings"[^>]*aria-label="Administration"')
        self.assertIn(f'href="{reverse("core:settings_home")}"', bar)

    def test_the_main_navigation_is_the_sidebar(self):
        html = self._html()
        self.assertIn('id="appNav"', html)
        self.assertNotIn('app-nav__', utility_bar(html))

    def test_no_shortcut_strip(self):
        self.assertNotIn('id="shortcutStrip"', self._html())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TopBarForOtherUsersTests(TestCase):

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='Cust Co', slug='cust-co')

    def login(self, user):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def test_customer_gets_no_gear_and_no_staff_shortcuts(self):
        from accounts.models import Membership
        u = get_user_model().objects.create_user('tb_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=u, organization=self.org, role='readonly')
        # PSA is on for a new install now; with it on a customer user has
        # My Work (their own tickets, psa.views.my_work). This checks the
        # install with PSA off, where nothing of PSA is offered.
        from core.models import SystemSetting
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        self.login(u)
        html = self.client.get(reverse('core:dashboard'), follow=True).content.decode()
        self.assertNotIn('id="topbarSettings"', html)
        bar = html.split('id="topbarShortcuts"', 1)[1].split('</ul>', 1)[0]
        self.assertNotIn(reverse('reports:home'), bar)
        self.assertNotIn(reverse('psa:my_work'), bar)
        for href in set(re.findall(r'href="(/[^"#?]*)"', bar)):
            with self.subTest(href=href):
                self.assertNotEqual(self.client.get(href).status_code, 403, href)


class BetaTesterProgramRemovedTests(TestCase):
    """v3.17.681: the beta-tester sign-up, its requests page and the upstream
    relay are gone; the stored request rows are kept (no data migration)."""

    def test_routes_no_longer_exist(self):
        from django.urls import NoReverseMatch
        for name in ('core:beta_test_signup', 'core:beta_test_admin', 'core:beta_test_upstream'):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_old_urls_are_not_found(self):
        for path in ('/core/beta-test/', '/core/beta-testers/', '/core/beta-test/upstream/'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_stored_requests_are_kept(self):
        from core.models import BetaTesterRequest
        self.assertTrue(BetaTesterRequest._meta.db_table)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NavigationNeverFailsSilentlyTests(TestCase):
    """v3.17.682: the {% primary_nav %} tag logs and swallows exceptions so a
    broken menu can't take a page down — which also let v3.17.681 ship with no
    sidebar or account menu at all. Pages must render it without that error."""

    def test_sidebar_and_account_menu_render_without_errors(self):
        User = get_user_model()
        su = User.objects.create_user('nav_ok_su', 'n@x.test', 'pw', is_superuser=True, is_staff=True)
        self.client.force_login(su)
        with self.assertNoLogs('core.templatetags.navigation', level='ERROR'):
            html = self.client.get(reverse('core:about')).content.decode()
        self.assertIn('app-nav__group-btn', html)
        self.assertIn('id="userDropdown"', html)
        self.assertIn(reverse('core:install_app'), html)
