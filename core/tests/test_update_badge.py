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
        # "Available" is its own span so phones can show just "Update".
        self.assertIn('Update<span class="update-pill__more"> Available</span>', html)
        self.assertIn(f'v{newer}', html)
        self.assertIn(reverse('core:system_updates'), html.split('id="navUpdateBadge"', 1)[0][-400:])

    def test_pill_sits_outside_the_collapsible_menu(self):
        """v3.17.678: beside the brand, so it shows at every width."""
        self._seen(_bump(get_version()))
        html = self._page(self.su)
        self.assertIn('class="update-pill"', html)
        self.assertLess(html.index('id="navUpdateBadge"'), html.index('id="navbarNav"'))

    def test_bell_lists_the_update_for_superusers(self):
        newer = _bump(get_version())
        self._seen(newer)
        html = self._page(self.su)
        self.assertIn('data-note="update"', html)
        self.assertIn(f'Update available: v{newer}', html)
        self.assertNotIn('data-note="update"', self._page(self.plain))

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
        self.assertEqual(task.interval_minutes, 15)  # v3.17.678: was hourly


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecurityUpdateBadgeTests(TestCase):
    """v3.17.682: the pill is red while a release with security fixes is newer
    than the running version (even when a later, ordinary release is the
    newest), and amber otherwise."""

    def setUp(self):
        self.su = get_user_model().objects.create_user('sec_su', 'ss@x.test', 'pw', is_superuser=True, is_staff=True)

    def _seen(self, latest, security=''):
        s = SystemSetting.get_settings()
        s.latest_release_version = latest
        s.latest_security_release_version = security
        s.save()

    def _page(self):
        self.client.force_login(self.su)
        with patch('core.upgrade.channels.requests.get',
                   side_effect=AssertionError('network call while rendering')):
            return self.client.get(reverse('core:about')).content.decode()

    def test_red_when_a_newer_release_has_security_fixes(self):
        self._seen(_bump(get_version(), 2), security=_bump(get_version(), 1))
        html = self._page()
        self.assertIn('update-pill update-pill--security', html)
        self.assertIn('Security<span class="update-pill__more"> Update</span>', html)
        self.assertIn('Security update available', html)

    def test_amber_when_the_security_release_is_already_installed(self):
        self._seen(_bump(get_version(), 1), security=get_version())
        html = self._page()
        self.assertIn('id="navUpdateBadge"', html)
        self.assertNotIn('update-pill--security', html)
        self.assertIn('Update<span class="update-pill__more"> Available</span>', html)

    def test_amber_without_security_releases(self):
        self._seen(_bump(get_version(), 1))
        self.assertNotIn('update-pill--security', self._page())

    def test_check_records_the_newest_security_release(self):
        from core.upgrade import channels
        base = get_version()
        rels = [
            {'tag_name': f'v{_bump(base, 3)}', 'name': 'Ordinary', 'body': '### Added\n- x'},
            {'tag_name': f'v{_bump(base, 2)}', 'name': 'Fixes', 'body': '### Fixed\n- y\n\n### Security\n- z'},
            {'tag_name': f'v{_bump(base, 1)}', 'name': 'Security hardening', 'body': ''},
            {'tag_name': f'v{_bump(base, 4)}', 'name': 'Draft', 'body': '### Security', 'draft': True},
        ]

        def fake_get(url):
            return rels if url.endswith('releases?per_page=30') else None
        with patch('core.upgrade.channels._get', side_effect=fake_get):
            stable = channels._stable_release('o', 'n')
        self.assertEqual(stable['version'], _bump(base, 3))
        self.assertEqual(stable['security_version'], _bump(base, 2))
        channels._record_stable(stable)
        self.assertEqual(SystemSetting.objects.get(pk=1).latest_security_release_version, _bump(base, 2))

    def test_detection_rules(self):
        from core.upgrade.channels import is_security_release
        self.assertTrue(is_security_release({'body': '## [1.2.3]\n\n### Security\n- fix'}))
        self.assertTrue(is_security_release({'name': 'v1 — Security fixes', 'body': ''}))
        self.assertFalse(is_security_release({'name': 'v1', 'body': 'Improves security of nothing in prose'}))
        self.assertFalse(is_security_release(None))
