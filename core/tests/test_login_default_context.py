"""A new session opens where the user left off: last client, or Global View."""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from core.models import Organization, RecentClient

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LoginDefaultContextTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Alpha', slug='alpha')
        cls.b = Organization.objects.create(name='Bravo', slug='bravo')
        cls.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pw')
        UserProfile.objects.get_or_create(user=cls.admin)

    def _fresh_session(self):
        self.client.logout()
        self.client.force_login(self.admin)
        self.client.get(reverse('core:dashboard'))
        return self.client.session

    def test_no_history_opens_first_client(self):
        s = self._fresh_session()
        self.assertFalse(s.get('global_view_mode', False))
        self.assertIn(s.get('current_organization_id'), {self.a.id, self.b.id})

    def test_global_view_with_no_client_history_reopens_global(self):
        UserProfile.objects.filter(user=self.admin).update(last_global_view_at=timezone.now())
        s = self._fresh_session()
        self.assertTrue(s.get('global_view_mode'))
        self.assertNotIn('current_organization_id', s)

    def test_last_client_reopens(self):
        RecentClient.objects.create(user=self.admin, organization=self.b, switched_at=timezone.now())
        s = self._fresh_session()
        self.assertEqual(s.get('current_organization_id'), self.b.id)
        self.assertFalse(s.get('global_view_mode', False))

    def test_global_view_more_recent_than_client_reopens_global(self):
        RecentClient.objects.create(user=self.admin, organization=self.b,
                                    switched_at=timezone.now() - timedelta(hours=1))
        self.client.force_login(self.admin)
        self.client.get(reverse('accounts:switch_to_global_view'))
        self.assertIsNotNone(UserProfile.objects.get(user=self.admin).last_global_view_at)
        s = self._fresh_session()
        self.assertTrue(s.get('global_view_mode'))
        self.assertNotIn('current_organization_id', s)

    def test_client_after_global_view_reopens_client(self):
        UserProfile.objects.filter(user=self.admin).update(
            last_global_view_at=timezone.now() - timedelta(hours=1))
        RecentClient.objects.create(user=self.admin, organization=self.a, switched_at=timezone.now())
        s = self._fresh_session()
        self.assertEqual(s.get('current_organization_id'), self.a.id)

    def test_preferred_organization_still_wins(self):
        UserProfile.objects.filter(user=self.admin).update(
            preferred_organization=self.a, last_global_view_at=timezone.now())
        s = self._fresh_session()
        self.assertEqual(s.get('current_organization_id'), self.a.id)
