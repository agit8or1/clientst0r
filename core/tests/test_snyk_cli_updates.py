"""Snyk CLI update checks (core.snyk_cli): the daily scheduled check, the
once-per-version superuser alert, Settings -> Snyk showing stored versions, and
the upgrade view installing exactly the version the check found.

No real npm, snyk or network: subprocess, the registry and e-mail are mocked.
"""
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core import snyk_cli
from core.models import ScheduledTask, SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

SNYK = '/fake/bin/snyk'
NPM = '/fake/bin/npm'


def _paths(snyk=SNYK, npm=NPM):
    return lambda cmd: {'snyk': snyk, 'npm': npm}.get(cmd)


def _run(installed='1.1290.0', latest='1.1294.0', npm_rc=0, snyk_rc=0):
    """Fake subprocess.run for `snyk --version` and `npm view snyk version`."""
    def fake(args, **kw):
        if args[0] == SNYK:
            return SimpleNamespace(returncode=snyk_rc, stdout=f'{installed}\n', stderr='')
        if args[:2] == [NPM, 'view']:
            return SimpleNamespace(returncode=npm_rc, stdout=f'{latest}\n', stderr='npm boom')
        raise AssertionError(f'unexpected command {args}')
    return fake


def _registry(version='1.1294.0', exc=None):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {'version': version}
    if exc:
        return mock.patch('requests.get', side_effect=exc)
    return mock.patch('requests.get', return_value=resp)


class VersionHelpersTests(TestCase):

    def test_is_newer(self):
        self.assertTrue(snyk_cli.is_newer('1.1294.0', '1.1290.0'))
        self.assertTrue(snyk_cli.is_newer('1.10.0', '1.9.9'))  # numeric, not string compare
        self.assertFalse(snyk_cli.is_newer('1.1290.0', '1.1290.0'))
        self.assertFalse(snyk_cli.is_newer('1.1289.0', '1.1290.0'))
        self.assertFalse(snyk_cli.is_newer('', '1.0.0'))
        self.assertFalse(snyk_cli.is_newer('1.0.0', ''))
        self.assertFalse(snyk_cli.is_newer('garbage', '1.0.0'))

    def test_version_validation_rejects_injection(self):
        self.assertTrue(snyk_cli.is_valid_version('1.1294.0'))
        for bad in ['1.2.3; rm -rf /', 'latest', '1.2.3 && id', '1.2', '01.2.3',
                    '1.2.3-beta', '$(id)', ' 1.2.3', '1.2.3\n', '', None, 123]:
            with self.subTest(bad=bad):
                self.assertFalse(snyk_cli.is_valid_version(bad))


class CheckVersionsTests(TestCase):

    def test_npm_path_stores_result(self):
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths()), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                mock.patch('requests.get') as rget:
            result = snyk_cli.check_versions()
        rget.assert_not_called()
        self.assertTrue(result['update_available'])
        s = SystemSetting.get_settings()
        self.assertEqual(s.snyk_cli_installed_version, '1.1290.0')
        self.assertEqual(s.snyk_cli_latest_version, '1.1294.0')
        self.assertIsNotNone(s.snyk_cli_checked_at)
        self.assertEqual(s.snyk_cli_check_error, '')
        self.assertTrue(s.snyk_cli_update_available)

    def test_registry_used_when_npm_missing(self):
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths(npm=None)), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                _registry('1.1300.0') as rget:
            result = snyk_cli.check_versions()
        self.assertEqual(rget.call_args.args[0], snyk_cli.REGISTRY_URL)
        self.assertIn('timeout', rget.call_args.kwargs)
        self.assertEqual(result['latest_version'], '1.1300.0')

    def test_registry_bad_version_rejected(self):
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths(npm=None)), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                _registry('1.2.3; rm -rf /'):
            result = snyk_cli.check_versions()
        self.assertIsNone(result['latest_version'])
        self.assertIn('unexpected version', SystemSetting.get_settings().snyk_cli_check_error)

    def test_lookup_failure_records_error_and_keeps_last_known_latest(self):
        s = SystemSetting.get_settings()
        s.snyk_cli_latest_version = '1.1294.0'
        s.save()
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths(npm=None)), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                _registry(exc=ConnectionError('offline')):
            result = snyk_cli.check_versions()
        self.assertIsNone(result['latest_version'])
        s.refresh_from_db()
        self.assertIn('offline', s.snyk_cli_check_error)
        self.assertEqual(s.snyk_cli_latest_version, '1.1294.0')


def _enable_snyk(**extra):
    s = SystemSetting.get_settings()
    s.snyk_enabled = True
    for k, v in extra.items():
        setattr(s, k, v)
    s.save()
    return s


class NotifyOnceTests(TestCase):

    def test_alerts_once_per_version(self):
        s = _enable_snyk(snyk_cli_installed_version='1.1290.0',
                         snyk_cli_latest_version='1.1294.0')
        with mock.patch('core.superuser_alerts.email_superusers', return_value=2) as em:
            self.assertEqual(snyk_cli.notify_if_new(s), 2)
            self.assertEqual(snyk_cli.notify_if_new(s), 0)
        self.assertEqual(em.call_count, 1)
        self.assertIn('Snyk CLI update available: 1.1290.0 → 1.1294.0', em.call_args.args[0])
        s.refresh_from_db()
        self.assertEqual(s.snyk_cli_notified_version, '1.1294.0')

        # A newer release alerts again.
        s.snyk_cli_latest_version = '1.1295.0'
        s.save()
        with mock.patch('core.superuser_alerts.email_superusers', return_value=1) as em:
            snyk_cli.notify_if_new(s)
        self.assertEqual(em.call_count, 1)

    def test_no_alert_when_up_to_date(self):
        s = _enable_snyk(snyk_cli_installed_version='1.1294.0',
                         snyk_cli_latest_version='1.1294.0')
        with mock.patch('core.superuser_alerts.email_superusers') as em:
            self.assertEqual(snyk_cli.notify_if_new(s), 0)
        em.assert_not_called()

    def test_nothing_sent_leaves_version_unmarked(self):
        s = _enable_snyk(snyk_cli_installed_version='1.1290.0',
                         snyk_cli_latest_version='1.1294.0')
        with mock.patch('core.superuser_alerts.email_superusers', return_value=0):
            snyk_cli.notify_if_new(s)
        s.refresh_from_db()
        self.assertEqual(s.snyk_cli_notified_version, '')

    def test_email_goes_to_superusers_through_smtp_settings(self):
        User.objects.create_user('root', 'root@x.com', 'pw', is_superuser=True)
        User.objects.create_user('plain', 'plain@x.com', 'pw')
        s = _enable_snyk(smtp_enabled=True, smtp_host='smtp.example.com',
                         smtp_from_email='alerts@example.com',
                         snyk_cli_installed_version='1.1290.0',
                         snyk_cli_latest_version='1.1294.0')
        with mock.patch('django.core.mail.get_connection') as gc, \
                mock.patch('django.core.mail.send_mail') as sm:
            sent = snyk_cli.notify_if_new(s)
        self.assertEqual(sent, 1)
        self.assertEqual(gc.call_args.kwargs['host'], 'smtp.example.com')
        self.assertEqual(sm.call_args.kwargs['recipient_list'], ['root@x.com'])


class ScheduledTaskTests(TestCase):

    def _run(self):
        out = io.StringIO()
        call_command('check_snyk_cli_update', stdout=out)
        return out.getvalue()

    def test_task_is_seeded_daily_and_dispatched(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='snyk_cli_update_check')
        self.assertEqual(task.interval_minutes, 1440)
        self.assertTrue(task.enabled)
        self.assertEqual(COMMAND_TASKS['snyk_cli_update_check'][0], 'check_snyk_cli_update')

    def test_disabled_does_nothing(self):
        with mock.patch.object(snyk_cli, 'find_command') as fc, \
                mock.patch.object(snyk_cli.subprocess, 'run') as run, \
                mock.patch('requests.get') as rget:
            out = self._run()
        self.assertIn('Snyk is disabled', out)
        fc.assert_not_called()
        run.assert_not_called()
        rget.assert_not_called()
        self.assertIsNone(SystemSetting.get_settings().snyk_cli_checked_at)

    def test_cli_missing_does_nothing(self):
        _enable_snyk()
        with mock.patch.object(snyk_cli, 'find_command', return_value=None), \
                mock.patch.object(snyk_cli.subprocess, 'run') as run, \
                mock.patch('requests.get') as rget:
            out = self._run()
        self.assertIn('not installed', out)
        run.assert_not_called()
        rget.assert_not_called()

    def test_registry_error_never_raises(self):
        _enable_snyk()
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths(npm=None)), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                _registry(exc=TimeoutError('slow')), \
                mock.patch('core.superuser_alerts.email_superusers') as em:
            out = self._run()
        self.assertIn('slow', out)
        em.assert_not_called()
        self.assertIn('slow', SystemSetting.get_settings().snyk_cli_check_error)

    def test_unexpected_exception_never_raises(self):
        _enable_snyk()
        with mock.patch.object(snyk_cli, 'find_command', side_effect=RuntimeError('boom')):
            out = self._run()
        self.assertIn('failed: boom', out)

    def test_update_found_alerts(self):
        _enable_snyk()
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths()), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                mock.patch('core.superuser_alerts.email_superusers', return_value=1) as em:
            out = self._run()
            self._run()  # second day: same version, no second alert
        self.assertIn('update available', out)
        self.assertEqual(em.call_count, 1)

    def test_scheduler_records_success(self):
        _enable_snyk()
        ScheduledTask.get_or_create_defaults()
        ScheduledTask.objects.update(enabled=False)
        task = ScheduledTask.objects.get(task_type='snyk_cli_update_check')
        task.enabled = True
        task.next_run_at = timezone.now() - timedelta(minutes=1)
        task.save()
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths(npm=None)), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()), \
                _registry(exc=ConnectionError('offline')):
            call_command('run_scheduler', stdout=io.StringIO())
        task.refresh_from_db()
        self.assertEqual(task.last_status, 'success')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SnykViewsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_user('su', 'su@x.com', 'pw', is_superuser=True, is_staff=True)
        cls.regular = User.objects.create_user('reg', 'r@x.com', 'pw')

    def _client(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_page_renders_stored_versions(self):
        s = SystemSetting.get_settings()
        s.snyk_cli_installed_version = '1.1290.0'
        s.snyk_cli_latest_version = '1.1294.0'
        s.snyk_cli_checked_at = timezone.now()
        s.save()
        with mock.patch.object(snyk_cli.subprocess, 'run') as run:
            r = self._client(self.superuser).get('/core/settings/snyk/')
        run.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Snyk CLI update available: 1.1290.0 → 1.1294.0')
        self.assertContains(r, '>1.1290.0</code>')
        self.assertContains(r, 'data-version="1.1294.0"')
        self.assertNotContains(r, 'Last checked:</strong> <span id="snykCheckedAt" class="text-muted">Never')

    def test_page_without_update_has_no_notice(self):
        r = self._client(self.superuser).get('/core/settings/snyk/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'id="snykCliUpdateNotice"')
        self.assertContains(r, 'Never')

    def test_security_dashboard_shows_notice(self):
        s = SystemSetting.get_settings()
        s.snyk_cli_installed_version = '1.1290.0'
        s.snyk_cli_latest_version = '1.1294.0'
        s.save()
        with mock.patch('core.system_warnings.collect_system_warnings', return_value=[]):
            r = self._client(self.superuser).get('/core/security/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Snyk CLI update available: 1.1290.0 → 1.1294.0')

    def test_check_button_requires_superuser_and_post(self):
        r = self._client(self.regular).post('/core/settings/snyk/check-version/')
        self.assertIn(r.status_code, [302, 403])
        r = self._client(self.superuser).get('/core/settings/snyk/check-version/')
        self.assertEqual(r.status_code, 405)

    def test_check_button_forces_fresh_check(self):
        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths()), \
                mock.patch.object(snyk_cli.subprocess, 'run', side_effect=_run()):
            r = self._client(self.superuser).post('/core/settings/snyk/check-version/')
        data = r.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['current_version'], '1.1290.0')
        self.assertEqual(data['latest_version'], '1.1294.0')
        self.assertTrue(data['update_available'])
        self.assertTrue(data['checked_at'])
        self.assertEqual(SystemSetting.get_settings().snyk_cli_latest_version, '1.1294.0')

    def test_upgrade_requires_superuser(self):
        with mock.patch.object(snyk_cli.subprocess, 'run') as run:
            r = self._client(self.regular).post('/core/settings/snyk/upgrade/')
        self.assertIn(r.status_code, [302, 403])
        run.assert_not_called()

    def test_upgrade_requires_post(self):
        r = self._client(self.superuser).get('/core/settings/snyk/upgrade/')
        self.assertEqual(r.status_code, 405)

    def test_upgrade_enforces_csrf(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.superuser)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        with mock.patch('subprocess.run') as run:
            r = c.post('/core/settings/snyk/upgrade/')
        self.assertEqual(r.status_code, 403)
        run.assert_not_called()

    def test_upgrade_installs_exact_checked_version(self):
        s = SystemSetting.get_settings()
        s.snyk_cli_installed_version = '1.1290.0'
        s.snyk_cli_latest_version = '1.1294.0'
        s.save()
        calls = []

        def fake(args, **kw):
            calls.append(args)
            if args[0] == SNYK:
                return SimpleNamespace(returncode=0, stdout='1.1294.0\n', stderr='')
            if args[:2] == [NPM, 'view']:
                return SimpleNamespace(returncode=0, stdout='1.1294.0\n', stderr='')
            return SimpleNamespace(returncode=0, stdout='added 1 package', stderr='')

        with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths()), \
                mock.patch('subprocess.run', side_effect=fake):
            r = self._client(self.superuser).post('/core/settings/snyk/upgrade/')
        data = r.json()
        self.assertTrue(data['success'], data)
        self.assertIn([NPM, 'install', '-g', 'snyk@1.1294.0'], calls)
        self.assertFalse(any('snyk@latest' in a for c in calls for a in c))
        self.assertEqual(data['new_version'], '1.1294.0')
        self.assertEqual(SystemSetting.get_settings().snyk_cli_installed_version, '1.1294.0')

    def test_upgrade_rejects_invalid_stored_version(self):
        for bad in ['1.2.3; rm -rf /', 'latest']:
            with self.subTest(bad=bad):
                s = SystemSetting.get_settings()
                s.snyk_cli_latest_version = bad
                s.save()
                with mock.patch.object(snyk_cli, 'find_command', side_effect=_paths()), \
                        mock.patch('subprocess.run') as run:
                    r = self._client(self.superuser).post('/core/settings/snyk/upgrade/')
                self.assertEqual(r.status_code, 400)
                self.assertFalse(r.json()['success'])
                run.assert_not_called()

    def test_upgrade_without_check_asks_for_one(self):
        with mock.patch('subprocess.run') as run:
            r = self._client(self.superuser).post('/core/settings/snyk/upgrade/')
        self.assertFalse(r.json()['success'])
        self.assertIn('Check for Updates', r.json()['message'])
        run.assert_not_called()
