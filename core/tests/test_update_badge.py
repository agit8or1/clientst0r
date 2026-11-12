"""The navbar's "update available" badge (v3.17.649).

It shows superusers a newer release than the one running, from what the
scheduled update check stored on SystemSetting — never from a network call
while rendering a page — and disappears once that version is running.
"""
from unittest.mock import patch

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from config.version import get_version
from core.models import ScheduledTask, SystemSetting
from core.updater import UpdateService

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _bump(v, by=1):
    major, minor, patch_ = (int(x) for x in v.split('.')[:3])
    return f'{major}.{minor}.{patch_ + by}'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UpdateBadgeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.su = User.objects.create_user('badge_su', 'su@x.test', 'pw', is_superuser=True, is_staff=True)
        self.plain = User.objects.create_user('badge_plain', 'p@x.test', 'pw')

    def _seen(self, latest):
        s = SystemSetting.get_settings()
        s.latest_release_version = latest
        s.save()

    def _page(self, user):
        self.client.force_login(user)
        # Rendering the navbar must not reach GitHub.
        with patch('core.upgrade.channels.requests.get',
                   side_effect=AssertionError('network call while rendering')):
            return self.client.get(reverse('core:about')).content.decode()

    def test_superuser_sees_newer_release_linking_to_updates(self):
        newer = _bump(get_version())
        self._seen(newer)
        html = self._page(self.su)
        self.assertIn('id="navUpdateBadge"', html)
        self.assertIn(f'Update {newer}', html)
        self.assertIn(reverse('core:system_updates'), html.split('id="navUpdateBadge"', 1)[0][-400:])

    def test_hidden_when_running_that_version_or_newer(self):
        for seen in (get_version(), _bump(get_version(), -1), '', 'not-a-version'):
            self._seen(seen)
            self.assertNotIn('navUpdateBadge', self._page(self.su), seen)

    def test_hidden_from_everyone_but_superusers(self):
        self._seen(_bump(get_version()))
        self.assertNotIn('navUpdateBadge', self._page(self.plain))

    def test_update_check_records_the_latest_release_for_every_process(self):
        """The badge shows the latest published (stable) release."""
        import shutil
        import tempfile
        from pathlib import Path
        tmp = tempfile.mkdtemp(prefix='cs0r-badge-test-')
        self.addCleanup(shutil.rmtree, tmp, True)
        o = override_settings(UPGRADE_BACKUP_DIR=Path(tmp))
        o.enable()
        self.addCleanup(o.disable)
        newer = _bump(get_version(), 3)
        remote = {'stable': {'tag': f'v{newer}', 'version': newer, 'sha': 'a' * 40},
                  'preview': None}
        with patch('core.upgrade.channels._fetch_remote_state', return_value=remote):
            info = UpdateService().check_for_updates(force_refresh=True)
        self.assertTrue(info['update_available'])
        s = SystemSetting.objects.get(pk=1)
        self.assertEqual(s.latest_release_version, newer)
        self.assertIsNotNone(s.latest_release_checked_at)

    def test_update_check_is_scheduled_by_default(self):
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='update_check')
        self.assertTrue(task.enabled)
        self.assertEqual(task.interval_minutes, 60)
