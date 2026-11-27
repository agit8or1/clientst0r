"""Settings → General → Default Timezone is what new profiles start with."""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserProfile
from core.models import SystemSetting


class DefaultTimezoneTests(TestCase):

    def setUp(self):
        s = SystemSetting.get_settings()
        s.default_timezone = 'America/Chicago'
        s.save()

    def test_new_user_profile_uses_the_install_default(self):
        u = User.objects.create_user('tz-new', password='pw')
        self.assertEqual(UserProfile.objects.get(user=u).timezone, 'America/Chicago')

    def test_get_or_create_path_uses_it_too(self):
        u = User.objects.create_user('tz-goc', password='pw')
        UserProfile.objects.filter(user=u).delete()
        profile, created = UserProfile.objects.get_or_create(user=u)
        self.assertTrue(created)
        self.assertEqual(profile.timezone, 'America/Chicago')

    def test_explicit_timezone_is_kept(self):
        u = User.objects.create_user('tz-explicit', password='pw')
        UserProfile.objects.filter(user=u).delete()
        p = UserProfile.objects.create(user=u, timezone='Europe/Paris')
        self.assertEqual(p.timezone, 'Europe/Paris')

    def test_existing_profiles_are_unchanged(self):
        u = User.objects.create_user('tz-old', password='pw')
        UserProfile.objects.filter(user=u).update(timezone='Asia/Tokyo')
        s = SystemSetting.get_settings()
        s.default_timezone = 'Europe/London'
        s.save()
        p = UserProfile.objects.get(user=u)
        p.save()
        User.objects.get(pk=u.pk).save()  # fresh user: no stale cached profile
        self.assertEqual(UserProfile.objects.get(user=u).timezone, 'Asia/Tokyo')

    def test_invalid_setting_falls_back_to_utc(self):
        s = SystemSetting.get_settings()
        s.default_timezone = 'Not/AZone'
        s.save()
        u = User.objects.create_user('tz-bad', password='pw')
        self.assertEqual(UserProfile.objects.get(user=u).timezone, 'UTC')
