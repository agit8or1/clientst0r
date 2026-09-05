"""
System-wide background policy (v3.17.527).

The app background used to be entirely per-user. An administrator can now set a
policy in General Settings: leave it user-controlled, or enforce a static image,
a colour/pattern, or random images for everyone.

Two behaviours carry the risk and are pinned here: the policy actually wins over
a user's own choice, and turning it on does not destroy what users had set.
"""
from __future__ import annotations

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.context_processors import background_is_locked, user_theme
from accounts.models import UserProfile
from core.backgrounds import (
    DEFAULT_COLOR, DEFAULT_PRESET, PRESET_BACKGROUNDS, PRESET_CHOICES,
    preset_url,
)
from core.models import Organization, SystemSetting

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class PresetTableTests(TestCase):
    """The twelve presets were defined in two places that nothing kept in step."""

    def test_every_choice_has_a_url(self):
        for key, _label in PRESET_CHOICES:
            self.assertIn(key, PRESET_BACKGROUNDS)
            self.assertTrue(preset_url(key).startswith('http'))

    def test_unknown_key_falls_back_rather_than_returning_blank(self):
        """A missing background reads as a bug; a wrong-but-present one does not."""
        self.assertEqual(preset_url('no-such-preset'), preset_url(DEFAULT_PRESET))
        self.assertEqual(preset_url(None), preset_url(DEFAULT_PRESET))


class BackgroundPolicyTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('bg', 'bg@x.com', 'pw')
        cls.profile, _ = UserProfile.objects.get_or_create(user=cls.user)
        cls.profile.background_mode = 'solid_color'
        cls.profile.background_color = '#abcdef'
        cls.profile.save()

    def setUp(self):
        self.factory = RequestFactory()

    def _context(self):
        request = self.factory.get('/')
        # Load the user fresh, as an authentication backend does on a real
        # request. Reusing the setUpTestData instance can carry a `profile`
        # cached by the post-save signal that created it — i.e. the row as it
        # was before this class set a background on it.
        request.user = User.objects.get(pk=self.user.pk)
        return user_theme(request)

    def _policy(self, **kwargs):
        s = SystemSetting.get_settings()
        for k, v in kwargs.items():
            setattr(s, k, v)
        s.save()
        return s

    def test_a_fresh_install_starts_on_the_navy_space_preset(self):
        """v3.17.551 — an install with no settings row yet gets the Navy Space
        preset rather than deferring to each user's own choice."""
        s = SystemSetting.get_settings()
        self.assertEqual(s.background_policy, 'color')
        self.assertEqual(s.background_color_style, 'preset')
        self.assertEqual(s.background_preset, 'abstract-12')

    def test_an_upgrade_does_not_change_an_existing_install(self):
        """The reason the original default was 'user'. A field default applies
        only to a row that does not exist yet, so an install already carrying a
        policy keeps it — changing the default must not repaint a running
        system."""
        s = SystemSetting.get_settings()
        s.background_policy = 'user'
        s.save(update_fields=['background_policy'])

        refetched = SystemSetting.get_settings()
        self.assertEqual(refetched.background_policy, 'user')
        ctx = self._context()
        self.assertFalse(ctx['background_locked'])
        self.assertEqual(ctx['user_background_color'], '#abcdef')

    def test_colour_policy_overrides_the_users_own_choice(self):
        self._policy(background_policy='color',
                     background_color_style='solid',
                     background_color='#112233')
        ctx = self._context()
        self.assertTrue(ctx['background_locked'])
        self.assertEqual(ctx['user_background_color'], '#112233')

    def test_preset_policy_resolves_to_a_url(self):
        self._policy(background_policy='color',
                     background_color_style='preset',
                     background_preset='abstract-4')
        ctx = self._context()
        self.assertEqual(ctx['user_background_url'], preset_url('abstract-4'))
        self.assertEqual(ctx['user_background_mode'], 'preset')

    def test_random_policy_changes_between_renders(self):
        self._policy(background_policy='random')
        first = self._context()['user_background_url']
        second = self._context()['user_background_url']
        self.assertTrue(first.startswith('https://picsum.photos/'))
        self.assertNotEqual(first, second, 'random should not be sticky')

    def test_image_policy_with_no_upload_degrades_to_no_background(self):
        """The admin picked the mode but has not finished; better blank than broken."""
        self._policy(background_policy='image', background_image=None)
        ctx = self._context()
        self.assertEqual(ctx['user_background_mode'], 'none')
        self.assertIsNone(ctx['user_background_url'])

    def test_locked_flag_tracks_the_policy(self):
        # Set the policy explicitly rather than leaning on the install
        # default, which since v3.17.551 is an enforced one.
        self._policy(background_policy='user')
        self.assertFalse(background_is_locked())
        self._policy(background_policy='random')
        self.assertTrue(background_is_locked())

    def test_anonymous_user_still_gets_the_enforced_background(self):
        """The policy is system-wide — a login page should honour it too."""
        from django.contrib.auth.models import AnonymousUser
        self._policy(background_policy='color', background_color_style='solid',
                     background_color='#654321')
        request = self.factory.get('/')
        request.user = AnonymousUser()
        self.assertEqual(user_theme(request)['user_background_color'], '#654321')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BackgroundPolicyViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='BgCo', slug='bg-co')
        cls.admin = User.objects.create_superuser('bgadmin', 'a@x.com', 'pw')
        cls.member = User.objects.create_user('bgmember', 'm@x.com', 'pw')
        cls.profile, _ = UserProfile.objects.get_or_create(user=cls.member)

    def test_settings_page_saves_a_policy(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('core:settings_general'), {
            'site_name': 'Client St0r',
            'background_policy': 'color',
            'background_color_style': 'solid',
            'background_color': '#0a0b0c',
            'background_preset': 'abstract-2',
            'map_default_zoom': '4',
        })
        self.assertEqual(r.status_code, 302)
        s = SystemSetting.get_settings()
        self.assertEqual(s.background_policy, 'color')
        self.assertEqual(s.background_color, '#0a0b0c')

    def test_a_bogus_colour_is_rejected(self):
        """The value lands in a style attribute; <input type=color> is bypassable."""
        s = SystemSetting.get_settings()
        s.background_color = DEFAULT_COLOR
        s.save()
        self.client.force_login(self.admin)
        self.client.post(reverse('core:settings_general'), {
            'site_name': 'Client St0r',
            'background_policy': 'color',
            'background_color': 'red; background-image:url(//evil)',
            'map_default_zoom': '4',
        })
        self.assertEqual(SystemSetting.get_settings().background_color, DEFAULT_COLOR)

    def test_an_unknown_policy_is_ignored(self):
        """A bogus value leaves the stored policy alone. Asserted against the
        value actually in place beforehand rather than a hardcoded 'user',
        which was only ever the install default."""
        before = SystemSetting.get_settings().background_policy
        self.client.force_login(self.admin)
        self.client.post(reverse('core:settings_general'), {
            'site_name': 'Client St0r',
            'background_policy': 'whatever-i-like',
            'map_default_zoom': '4',
        })
        self.assertEqual(SystemSetting.get_settings().background_policy, before)

    def test_profile_save_under_a_policy_keeps_the_users_settings(self):
        """A disabled <fieldset> submits nothing.

        Without the view preserving them, any unrelated profile save while a
        policy was active would blank the user's background — and they would
        only find out when the policy was lifted.
        """
        # Log in first, then set the profile. `save_user_profile` saves
        # `instance.profile` on every User.save(), and logging in updates
        # last_login — so a login after this would write the User object's
        # stale cached profile straight back over these values.
        self.client.force_login(self.member)

        self.profile.background_mode = 'preset'
        self.profile.preset_background = 'abstract-7'
        self.profile.background_color = '#abcdef'
        self.profile.save()

        s = SystemSetting.get_settings()
        s.background_policy = 'random'
        s.save()
        # A profile POST with none of the background fields, as the browser
        # would send it with the fieldset disabled.
        r = self.client.post(reverse('accounts:profile_edit'), {
            'theme': 'dark', 'timezone': 'UTC', 'time_format': '24',
            'locale': 'en-us', 'notification_frequency': 'realtime',
            'email': 'm@x.com',
        })
        self.assertEqual(r.status_code, 302,
                         f'form rejected the POST: {r.context["form"].errors if r.context and "form" in r.context else ""}')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.background_mode, 'preset')
        self.assertEqual(self.profile.preset_background, 'abstract-7')
        self.assertEqual(self.profile.background_color, '#abcdef')
        # The rest of the form must still have saved: a locked background must
        # not make the whole profile page unusable, which is what a required
        # `background_mode` inside a disabled fieldset would have caused.
        self.assertEqual(self.profile.theme, 'dark')

    def test_profile_save_without_a_policy_still_updates_background(self):
        """The preservation must not become a permanent lock."""
        s = SystemSetting.get_settings()
        s.background_policy = 'user'
        s.save()
        self.client.force_login(self.member)
        self.client.post(reverse('accounts:profile_edit'), {
            'theme': 'dark', 'timezone': 'UTC', 'time_format': '24',
            'locale': 'en-us', 'notification_frequency': 'realtime',
            'email': 'm@x.com',
            'background_mode': 'solid_color', 'background_color': '#010203',
            'preset_background': 'abstract-1',
        })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.background_mode, 'solid_color')
        self.assertEqual(self.profile.background_color, '#010203')
