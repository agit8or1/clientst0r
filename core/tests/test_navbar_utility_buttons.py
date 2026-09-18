"""The utility controls are visible buttons, not an overflow menu.

Beta app, Install app and Support this project sat behind an ellipsis
dropdown between the star and the search box (v3.17.559). A control nobody
can see is a control nobody uses, and v3.17.580 freed the room by grouping
Security, CRM and Reports under the main navigation's More menu.

They are now individual buttons in their original order, with their original
icons and behaviour. This is deliberately NOT the main navigation's More menu
(`moreNavDropdown`), which stays a dropdown — see `test_navbar_grouping.py`.
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


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UtilityControlsAreVisibleTests(TestCase):

    def setUp(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.crm_enabled = True
        row.save()
        self.org = Organization.objects.create(name='Nav Co', slug='util-co')
        self.user = get_user_model().objects.create_user(
            'util_su', 'u@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _html(self):
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    # -- the ellipsis menu is gone -------------------------------------------

    def test_the_ellipsis_trigger_and_its_container_are_gone(self):
        html = self._html()
        self.assertNotIn('id="moreMenu"', html)
        self.assertNotIn('aria-labelledby="moreMenu"', html)

    def _utility_cluster(self, html):
        """The stretch of markup between the star and the search box.

        The user/account menu keeps its own copies of these destinations and
        always has — those are legitimate, so assertions have to be scoped to
        the cluster rather than to the whole page.
        """
        start = html.index(reverse('core:favorite_list'))
        end = html.index('class="nav-search"', start)
        return html[start:end]

    def test_no_dropdown_wraps_the_utility_controls(self):
        """
        The three used to be `dropdown-item`s behind an ellipsis. If a
        dropdown reappears in this stretch, something has put them back
        behind a click.
        """
        cluster = self._utility_cluster(self._html())
        self.assertNotIn('dropdown-menu', cluster)
        self.assertNotIn('dropdown-toggle', cluster)
        self.assertNotIn('dropdown-item', cluster)

    def test_the_three_live_in_the_cluster_as_buttons(self):
        cluster = self._utility_cluster(self._html())
        self.assertEqual(cluster.count('nav-link nav-util'), 3,
                         'expected beta app, install app and support as peers '
                         'of the star')
        self.assertIn(reverse('core:beta_test_signup'), cluster)
        self.assertIn(reverse('core:install_app'), cluster)
        self.assertIn('data-bs-target="#supportProjectModal"', cluster)

    # -- the controls themselves ---------------------------------------------

    def test_all_three_are_present_as_utility_buttons(self):
        html = self._html()
        cluster = html.split('nav-util', 1)[1]
        self.assertIn(reverse('core:beta_test_signup'), cluster)
        self.assertIn(reverse('core:install_app'), cluster)
        self.assertIn('data-bs-target="#supportProjectModal"', cluster)

    def test_they_keep_their_original_order(self):
        html = self._html()
        star = html.index(reverse('core:favorite_list'))
        beta = html.index(reverse('core:beta_test_signup'), star)
        install = html.index(reverse('core:install_app'), star)
        support = html.index('data-bs-target="#supportProjectModal"', star)
        self.assertLess(star, beta)
        self.assertLess(beta, install)
        self.assertLess(install, support)

    def test_support_still_opens_the_modal(self):
        html = self._html()
        self.assertIn('data-bs-toggle="modal"', html)
        self.assertIn('id="supportProjectModal"', html)

    # -- accessibility --------------------------------------------------------

    def test_each_button_has_an_accessible_name(self):
        html = self._html()
        for label in ('Beta app', 'Install app', 'Support this project'):
            self.assertIn(f'aria-label="{label}"', html)

    def test_each_button_has_a_descriptive_tooltip(self):
        """The accessible name is terse; the tooltip says what it does."""
        html = self._html()
        for phrase in ('Beta-test the Android app',
                       'Install the app on your phone or desktop',
                       'Support this open-source project'):
            self.assertIn(phrase, html)

    def test_the_modal_button_gets_a_tooltip_despite_its_toggle_being_taken(self):
        """
        `data-bs-toggle` is spoken for by the modal, so the tooltip is hooked
        with `data-bs-tooltip` — which the initialiser has to look for.
        """
        html = self._html()
        self.assertIn('data-bs-tooltip', html)
        self.assertIn("'[data-bs-toggle=\"tooltip\"], [data-bs-tooltip]'", html)

    def test_the_icons_are_hidden_from_screen_readers(self):
        html = self._html()
        cluster = html.split('nav-util', 1)[1][:2000]
        self.assertIn('aria-hidden="true"', cluster)

    # -- the main navigation is untouched -------------------------------------

    def test_the_main_navigation_more_menu_is_still_a_dropdown(self):
        """A different control entirely — this change must not touch it."""
        html = self._html()
        self.assertIn('moreNavDropdown', html)
        self.assertIn('id="adminDropdown"', html)
