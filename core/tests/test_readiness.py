"""Phase 96.1: default administrator password warning and install readiness."""
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core import readiness
from core.models import ReadinessResult
from core.tests._r681_fixture import TEST_MIDDLEWARE


def _client(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s['global_view_mode'] = True
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DefaultPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('admin', 'a@example.com', readiness.INSTALLER_PASSWORD)

    def test_detected_and_remembered_per_password(self):
        self.assertTrue(readiness.default_password_in_use(self.admin))
        row = ReadinessResult.objects.get(key=f'default_password:{self.admin.pk}')
        self.assertTrue(row.data['in_use'])
        self.assertNotIn(readiness.INSTALLER_PASSWORD, str(row.data))
        # A second call (fresh cache) uses the stored row, not a new hash.
        cache.clear()
        with mock.patch('core.readiness.check_password') as cp:
            self.assertTrue(readiness.default_password_in_use(self.admin))
            cp.assert_not_called()

    def test_password_change_clears_it(self):
        self.assertTrue(readiness.default_password_in_use(self.admin))
        self.admin.set_password('A-much-better-passphrase-91')
        self.admin.save()
        self.assertFalse(readiness.default_password_in_use(self.admin))

    def test_only_superusers(self):
        u = User.objects.create_user('tech', password=readiness.INSTALLER_PASSWORD)
        self.assertFalse(readiness.default_password_in_use(u))

    def test_banner_shown_and_gone_after_change(self):
        c = _client(self.admin)
        r = c.get(reverse('core:settings_home'))
        self.assertContains(r, 'data-default-password-warning')
        self.admin.set_password('A-much-better-passphrase-91')
        self.admin.save()
        c = _client(self.admin)
        r = c.get(reverse('core:settings_home'))
        self.assertNotContains(r, 'data-default-password-warning')

    def test_system_warning(self):
        from core.system_warnings import _warnings_from_default_password
        rows = _warnings_from_default_password()
        self.assertEqual(rows[0]['id'], 'default_admin_password')
        self.assertEqual(rows[0]['severity'], 'high')
        self.assertIn('admin', rows[0]['detail'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReadinessRunTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('boss', 'b@example.com', 'A-much-better-passphrase-91')

    def test_run_stores_and_settings_home_shows_it(self):
        c = _client(self.admin)
        r = c.get(reverse('core:settings_home'))
        self.assertContains(r, 'Run the check')
        with mock.patch('core.readiness._check_app_version',
                        return_value=readiness._check('app_version', True, 'Application version', 'x')):
            r = c.post(reverse('core:readiness_run'))
        self.assertRedirects(r, reverse('core:settings_home'), fetch_redirect_response=False)
        checks, at = readiness.latest()
        self.assertIsNotNone(at)
        ids = {ch['id'] for ch in checks}
        self.assertTrue({'default_password', 'superuser_2fa', 'site_url', 'mail', 'backup_destination',
                         'scheduler', 'migrations', 'disk', 'app_version'} <= ids)
        by = {ch['id']: ch for ch in checks}
        self.assertTrue(by['default_password']['ok'])
        self.assertFalse(by['superuser_2fa']['ok'])  # no authenticator in the test
        self.assertEqual(by['superuser_2fa']['action_url'], reverse('accounts:two_factor_setup'))
        self.assertTrue(by['migrations']['ok'])
        r = c.get(reverse('core:settings_home'))
        self.assertContains(r, 'data-readiness-check="scheduler"')

    def test_non_superuser_refused(self):
        u = User.objects.create_user('tech', password='x-Long-passphrase-1')
        c = _client(u)
        r = c.post(reverse('core:readiness_run'))
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ReadinessResult.objects.filter(key='install').exists())

    def test_get_not_allowed(self):
        r = _client(self.admin).get(reverse('core:readiness_run'))
        self.assertEqual(r.status_code, 405)

    def test_broken_check_does_not_hide_others(self):
        with mock.patch('core.upgrade.preflight.check_disk', side_effect=OSError('boom')), \
                mock.patch('core.readiness._check_app_version',
                           return_value=readiness._check('app_version', True, 'Application version', 'x')):
            checks = readiness.run_checks()
        by = {ch['id']: ch for ch in checks}
        self.assertFalse(by['disk']['ok'])
        self.assertIn('could not run', by['disk']['detail'])
        self.assertIn('site_url', by)
