"""Theme, density and the Professional Dark default (v3.17.677).

* Professional Dark is a dark palette: the page gets Bootstrap's dark mode.
* Nord is a light palette and was misfiled as dark by the theme toggle and two
  stylesheets; it now renders light and the toggle treats it as light.
* The interface density comes from the profile (compact unless chosen).
* The navbar toggle switches between Professional Dark and Default Blue.
* Existing profiles keep the theme and background they hold.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.context_processors import DARK_THEMES, is_dark_theme, user_theme
from accounts.models import UserProfile

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
CSS = Path(django_settings.BASE_DIR) / 'static' / 'css'


def _html_tag(response):
    return re.search(r'<html[^>]*>', response.content.decode()).group(0)


class ThemeClassificationTests(TestCase):

    def test_professional_is_dark_and_nord_is_light(self):
        self.assertTrue(is_dark_theme('professional'))
        self.assertFalse(is_dark_theme('nord'))
        self.assertEqual(DARK_THEMES, {'professional', 'dark', 'dracula', 'monokai'})

    def test_every_dark_theme_has_a_palette(self):
        css = (CSS / 'themes.css').read_text()
        for name in DARK_THEMES:
            self.assertIn(f'[data-theme="{name}"] {{', css)

    def test_no_stylesheet_files_nord_with_the_dark_themes(self):
        for name in ('custom.css', 'ticket_conversation.css'):
            with self.subTest(sheet=name):
                self.assertNotIn('[data-theme="nord"]', (CSS / name).read_text())

    def test_density_has_both_variants_in_the_tokens(self):
        css = (CSS / 'ui.css').read_text()
        self.assertIn('html[data-density="comfortable"]', css)
        self.assertIn('--ui-control-h', css)


class ThemeContextTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def _ctx(self, user):
        request = self.factory.get('/')
        request.user = User.objects.get(pk=user.pk) if user.is_authenticated else user
        return user_theme(request)

    def test_anonymous_gets_light_compact(self):
        ctx = self._ctx(AnonymousUser())
        self.assertEqual(ctx['user_theme'], 'default')
        self.assertFalse(ctx['user_theme_is_dark'])
        self.assertEqual(ctx['user_density'], 'compact')

    def test_new_profile_is_professional_compact_no_wallpaper(self):
        user = User.objects.create_user('fresh', 'f@x.com', 'pw')
        ctx = self._ctx(user)
        self.assertEqual(ctx['user_theme'], 'professional')
        self.assertTrue(ctx['user_theme_is_dark'])
        self.assertEqual(ctx['user_density'], 'compact')
        self.assertEqual(ctx['user_background_mode'], 'none')

    def test_stored_density_is_used_and_garbage_falls_back(self):
        user = User.objects.create_user('roomy', 'r@x.com', 'pw')
        UserProfile.objects.filter(user=user).update(ui_density='comfortable')
        self.assertEqual(self._ctx(user)['user_density'], 'comfortable')
        UserProfile.objects.filter(user=user).update(ui_density='huge')
        self.assertEqual(self._ctx(user)['user_density'], 'compact')

    def test_existing_profile_keeps_its_theme(self):
        """A field default fills new rows only; nobody is moved to the new
        theme, and saving the profile for another reason does not move them."""
        user = User.objects.create_user('settled', 's@x.com', 'pw')
        UserProfile.objects.filter(user=user).update(theme='default', background_mode='preset')
        profile = UserProfile.objects.get(user=user)
        profile.timezone = 'UTC'
        profile.save()
        profile.refresh_from_db()
        self.assertEqual(profile.theme, 'default')
        self.assertEqual(profile.background_mode, 'preset')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ThemeRenderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('themer', 't@x.com', 'pw')

    def _set(self, **fields):
        UserProfile.objects.filter(user=self.user).update(**fields)
        self.client.force_login(User.objects.get(pk=self.user.pk))

    def _page(self):
        r = self.client.get(reverse('accounts:profile_edit'))
        self.assertEqual(r.status_code, 200)
        return r

    def test_professional_renders_bootstrap_dark(self):
        self._set(theme='professional')
        tag = _html_tag(self._page())
        self.assertIn('data-theme="professional"', tag)
        self.assertIn('data-bs-theme="dark"', tag)

    def test_nord_renders_bootstrap_light(self):
        self._set(theme='nord')
        tag = _html_tag(self._page())
        self.assertIn('data-theme="nord"', tag)
        self.assertIn('data-bs-theme="light"', tag)

    def test_density_attribute_comes_from_the_profile(self):
        self._set(ui_density='comfortable')
        self.assertIn('data-density="comfortable"', _html_tag(self._page()))
        self._set(ui_density='compact')
        self.assertIn('data-density="compact"', _html_tag(self._page()))

    def test_no_wallpaper_means_no_background_attributes(self):
        self._set(background_mode='none')
        body = re.search(r'<body[^>]*>', self._page().content.decode()).group(0)
        self.assertNotIn('has-background', body)
        self.assertNotIn('background-image', body)

    def test_profile_form_offers_and_saves_density(self):
        self._set(ui_density='compact')
        self.assertContains(self._page(), 'name="ui_density"')
        r = self.client.post(reverse('accounts:profile_edit'), {
            'theme': 'professional', 'ui_density': 'comfortable',
            'timezone': 'UTC', 'time_format': '24', 'locale': 'en-us',
            'notification_frequency': 'realtime', 'email': 't@x.com',
            'background_mode': 'none', 'background_color': '#1a1a2e',
            'preset_background': 'abstract-12',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(UserProfile.objects.get(user=self.user).ui_density, 'comfortable')

    def test_profile_save_without_density_keeps_it(self):
        self._set(ui_density='comfortable')
        r = self.client.post(reverse('accounts:profile_edit'), {
            'theme': 'dark', 'timezone': 'UTC', 'time_format': '24',
            'locale': 'en-us', 'notification_frequency': 'realtime',
            'email': 't@x.com', 'background_mode': 'none',
            'background_color': '#1a1a2e', 'preset_background': 'abstract-12',
        })
        self.assertEqual(r.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.ui_density, 'comfortable')
        self.assertEqual(profile.theme, 'dark')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ToggleThemeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('toggler', 'tg@x.com', 'pw')

    def _toggle_from(self, theme):
        UserProfile.objects.filter(user=self.user).update(theme=theme)
        self.client.force_login(User.objects.get(pk=self.user.pk))
        r = self.client.post(reverse('accounts:toggle_theme'))
        self.assertEqual(r.status_code, 200)
        stored = UserProfile.objects.get(user=self.user).theme
        self.assertEqual(r.json()['theme'], stored)
        return stored

    def test_dark_themes_go_to_the_light_default(self):
        for theme in ('professional', 'dark', 'dracula', 'monokai'):
            with self.subTest(theme=theme):
                self.assertEqual(self._toggle_from(theme), 'default')

    def test_light_themes_go_to_professional_dark(self):
        for theme in ('default', 'nord', 'solarized', 'ocean'):
            with self.subTest(theme=theme):
                self.assertEqual(self._toggle_from(theme), 'professional')

    def test_get_is_refused(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('accounts:toggle_theme')).status_code, 405)


class SystemThemeContextTests(TestCase):
    """113.5: the System theme follows the device's prefers-color-scheme."""

    def setUp(self):
        self.factory = RequestFactory()

    def _ctx(self, theme):
        user = User.objects.create_user('sys-%s' % theme, 's@x.com', 'pw')
        UserProfile.objects.filter(user=user).update(theme=theme)
        request = self.factory.get('/')
        request.user = User.objects.get(pk=user.pk)
        return user_theme(request)

    def test_system_renders_the_light_palette_and_marks_the_mode(self):
        ctx = self._ctx('system')
        self.assertEqual(ctx['user_theme'], 'default')
        self.assertFalse(ctx['user_theme_is_dark'])
        self.assertEqual(ctx['user_theme_mode'], 'system')
        self.assertEqual(ctx['user_theme_system_light'], 'default')
        self.assertEqual(ctx['user_theme_system_dark'], 'professional')

    def test_fixed_themes_map_to_light_or_dark_tokens(self):
        for theme, mode in (('professional', 'dark'), ('dracula', 'dark'), ('nord', 'light'),
                            ('default', 'light'), ('solarized', 'light')):
            with self.subTest(theme=theme):
                ctx = self._ctx(theme)
                self.assertEqual(ctx['user_theme'], theme)
                self.assertEqual(ctx['user_theme_mode'], mode)

    def test_anonymous_tokens_are_light(self):
        request = self.factory.get('/')
        request.user = AnonymousUser()
        self.assertEqual(user_theme(request)['user_theme_mode'], 'light')

    def test_choice_exists_and_default_is_unchanged(self):
        field = UserProfile._meta.get_field('theme')
        self.assertIn('system', dict(field.choices))
        self.assertEqual(field.default, 'professional')

    def test_every_theme_choice_has_a_palette_or_is_system(self):
        css = (CSS / 'themes.css').read_text()
        for value, _label in UserProfile._meta.get_field('theme').choices:
            with self.subTest(theme=value):
                if value != 'system':
                    self.assertIn(f'[data-theme="{value}"] {{', css)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SystemThemeRenderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('sysrender', 'sr@x.com', 'pw')

    def _page(self, theme):
        UserProfile.objects.filter(user=self.user).update(theme=theme)
        self.client.force_login(User.objects.get(pk=self.user.pk))
        r = self.client.get(reverse('accounts:profile_edit'))
        self.assertEqual(r.status_code, 200)
        return r

    def test_system_page_starts_light_and_loads_the_follower_first(self):
        r = self._page('system')
        tag = _html_tag(r)
        for attr in ('data-theme="default"', 'data-bs-theme="light"', 'data-cs-theme="system"',
                     'data-theme-mode="system"', 'data-theme-light="default"',
                     'data-theme-dark="professional"'):
            self.assertIn(attr, tag)
        html = r.content.decode()
        self.assertLess(html.index('js/theme_system.js'), html.index('bootstrap.min.css'))
        self.assertLess(html.index('css/tokens.css'), html.index('css/themes.css'))
        self.assertIn('data-light="#58a6ff" data-dark="#0a0e14"', html)

    def test_fixed_theme_has_no_system_mode(self):
        tag = _html_tag(self._page('professional'))
        self.assertIn('data-cs-theme="dark"', tag)
        self.assertNotIn('data-theme-mode', tag)
        tag = _html_tag(self._page('nord'))
        self.assertIn('data-cs-theme="light"', tag)

    def test_profile_form_offers_and_saves_system(self):
        r = self._page('professional')
        self.assertContains(r, '<option value="system"')
        r = self.client.post(reverse('accounts:profile_edit'), {
            'theme': 'system', 'ui_density': 'compact',
            'timezone': 'UTC', 'time_format': '24', 'locale': 'en-us',
            'notification_frequency': 'realtime', 'email': 'sr@x.com',
            'background_mode': 'none', 'background_color': '#1a1a2e',
            'preset_background': 'abstract-12',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(UserProfile.objects.get(user=self.user).theme, 'system')

    def test_follower_script_is_csp_safe(self):
        js = (Path(django_settings.BASE_DIR) / 'static' / 'js' / 'theme_system.js').read_text()
        self.assertIn("prefers-color-scheme: dark", js)
        self.assertIn("data-theme-mode", js)
        self.assertNotIn('eval(', js)
        self.assertNotIn('innerHTML', js)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SystemThemeToggleTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('systoggle', 'st@x.com', 'pw')

    def _toggle(self, body=None):
        UserProfile.objects.filter(user=self.user).update(theme='system')
        self.client.force_login(User.objects.get(pk=self.user.pk))
        kwargs = {'content_type': 'application/json'}
        if body is not None:
            kwargs['data'] = body
        r = self.client.post(reverse('accounts:toggle_theme'), **kwargs)
        self.assertEqual(r.status_code, 200)
        return UserProfile.objects.get(user=self.user).theme

    def test_showing_dark_goes_light(self):
        self.assertEqual(self._toggle('{"dark": true}'), 'default')

    def test_showing_light_goes_dark(self):
        self.assertEqual(self._toggle('{"dark": false}'), 'professional')

    def test_no_or_bad_body_counts_as_light(self):
        self.assertEqual(self._toggle(), 'professional')
        self.assertEqual(self._toggle('not json'), 'professional')
        self.assertEqual(self._toggle('[1, 2]'), 'professional')
        self.assertEqual(self._toggle('{"dark": "yes"}'), 'professional')

    def test_body_is_ignored_for_a_fixed_theme(self):
        UserProfile.objects.filter(user=self.user).update(theme='nord')
        self.client.force_login(User.objects.get(pk=self.user.pk))
        self.client.post(reverse('accounts:toggle_theme'), data='{"dark": true}',
                         content_type='application/json')
        self.assertEqual(UserProfile.objects.get(user=self.user).theme, 'professional')


class PortalSystemThemeTagTests(TestCase):

    def test_system_follows_the_visitor_device(self):
        from portal.templatetags.portal_theme import portal_theme_mode
        user = User.objects.create_user('psys', 'ps@x.com', 'pw')
        UserProfile.objects.filter(user=user).update(theme='system')
        request = RequestFactory().get('/portal/')
        request.user = User.objects.get(pk=user.pk)
        self.assertEqual(portal_theme_mode({'request': request, 'system_settings': None}), '')
