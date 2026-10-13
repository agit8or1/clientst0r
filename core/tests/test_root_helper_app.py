"""
The app's use of the root helper (v3.17.597), and the sudoers rules we ship.
"""
import re
import subprocess
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core import fail2ban_views, root_helper, system_warnings

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def ok(stdout=''):
    return subprocess.CompletedProcess([], 0, stdout, '')


class Fail2banThroughHelperTests(SimpleTestCase):

    def run_cmd(self, command):
        with mock.patch.object(fail2ban_views, '_fail2ban_client_path', return_value='/usr/bin/fail2ban-client'), \
             mock.patch.object(root_helper, 'is_installed', return_value=True), \
             mock.patch.object(root_helper, 'run', return_value=ok('pong')) as run, \
             mock.patch('subprocess.run') as direct:
            result = fail2ban_views.run_fail2ban_command(command)
        direct.assert_not_called()
        return result, run

    def test_page_actions_map_to_helper_actions(self):
        cases = {
            ('ping',): ['fail2ban', 'ping'],
            ('status',): ['fail2ban', 'status'],
            ('status', 'sshd'): ['fail2ban', 'status', 'sshd'],
            ('set', 'sshd', 'unbanip', '10.0.0.5'): ['fail2ban', 'unban', 'sshd', '10.0.0.5'],
            ('start',): ['fail2ban', 'start'],
        }
        for command, expected in cases.items():
            result, run = self.run_cmd(list(command))
            self.assertTrue(result[0])
            self.assertEqual(run.call_args.args[0], expected)

    def test_anything_else_is_not_sent(self):
        result, run = self.run_cmd(['set', 'sshd', 'action', 'x', 'actionban', 'sh'])
        self.assertFalse(result[0])
        run.assert_not_called()


class HelperWrapperTests(SimpleTestCase):

    def test_not_installed_returns_none(self):
        with mock.patch.object(root_helper, 'is_installed', return_value=False):
            self.assertIsNone(root_helper.run(['reload']))

    def test_runs_through_sudo_non_interactively(self):
        with mock.patch.object(root_helper, 'is_installed', return_value=True), \
             mock.patch('subprocess.run', return_value=ok()) as run:
            root_helper.run(['apt', 'update'])
        self.assertEqual(run.call_args.args[0],
                         ['/usr/bin/sudo', '-n', root_helper.HELPER_PATH, 'apt', 'update'])

    def test_bootstrap_passes_password_on_stdin_only(self):
        with mock.patch('subprocess.run', return_value=ok()) as run, \
             mock.patch.object(root_helper, 'is_installed', return_value=True):
            okay, _ = root_helper.bootstrap_with_password('s3cret')
        self.assertTrue(okay)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ['/usr/bin/sudo', '-S', '-k', '-p', ''])
        self.assertEqual(argv[5:], ['/bin/bash', str(root_helper.bootstrap_script())])
        self.assertNotIn('s3cret', ' '.join(argv))
        self.assertEqual(run.call_args.kwargs['input'], 's3cret\n')

    def test_docker_never_needs_bootstrap(self):
        with mock.patch('os.path.exists', side_effect=lambda p: p == '/.dockerenv'):
            self.assertFalse(root_helper.needs_bootstrap())


class SystemWarningTests(SimpleTestCase):

    def test_warning_when_helper_missing(self):
        with mock.patch.object(root_helper, 'needs_bootstrap', return_value=True):
            warnings = system_warnings._warnings_from_root_helper()
        self.assertEqual(warnings[0]['id'], 'root_helper:missing')
        self.assertEqual(warnings[0]['severity'], 'high')

    def test_no_warning_once_installed(self):
        with mock.patch.object(root_helper, 'needs_bootstrap', return_value=False):
            self.assertEqual(system_warnings._warnings_from_root_helper(), [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RootHelperInstallViewTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'rh_su', 'r@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.url = reverse('core:root_helper_install')

    def test_installs_with_the_password(self):
        with mock.patch.object(root_helper, 'is_installed', return_value=False), \
             mock.patch.object(root_helper, 'bootstrap_with_password', return_value=(True, 'done')) as boot:
            r = self.client.post(self.url, {'sudo_password': 'pw1'})
        self.assertEqual(r.status_code, 302)
        boot.assert_called_once_with('pw1')

    def test_needs_a_password(self):
        with mock.patch.object(root_helper, 'is_installed', return_value=False), \
             mock.patch.object(root_helper, 'bootstrap_with_password') as boot:
            self.client.post(self.url, {})
        boot.assert_not_called()

    def test_superuser_only(self):
        staff = get_user_model().objects.create_user('rh_staff', 's@x.com', 'pw', is_staff=True)
        self.client.force_login(staff)
        with mock.patch.object(root_helper, 'bootstrap_with_password') as boot:
            r = self.client.post(self.url, {'sudo_password': 'x'})
        self.assertNotEqual(r.status_code, 200)
        boot.assert_not_called()

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class ShippedSudoersRulesTests(SimpleTestCase):
    """No passwordless rule we ship or generate may be a way to root."""

    UNSAFE = [
        (re.compile(r'\*\s*$'), 'ends in a wildcard'),
        (re.compile(r'\s/tmp/'), 'runs something from /tmp'),
        (re.compile(r'\s/home/|venv/'), 'runs something from a home directory'),
        (re.compile(r'\s/(usr/)?bin/(cp|mv|tee|chmod|chown|install)\s'), 'writes files as root'),
        (re.compile(r'fail2ban-client\s*$'), 'unrestricted fail2ban-client'),
        (re.compile(r'/(bash|sh|python3?|pip3?|systemd-run)\s*(,|$)'), 'unrestricted interpreter'),
    ]

    def files(self):
        base = Path(django_settings.BASE_DIR)
        tracked = subprocess.run(['git', 'ls-files'], cwd=base, capture_output=True,
                                 text=True).stdout.split()
        for name in tracked:
            if name.startswith(('venv/', 'mobile', 'docs/')) or name == 'CHANGELOG.md' \
                    or '/tests' in name or name.endswith(('tests.py', '.png', '.jpg', '.svg')) \
                    or name.startswith('deploy/root-helper/'):
                continue
            path = base / name
            if path.is_file() and path.stat().st_size < 2_000_000:
                yield name, path

    def test_no_unsafe_nopasswd_rules(self):
        problems = []
        for name, path in self.files():
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if 'NOPASSWD:' not in stripped or stripped.startswith('#'):
                    continue
                rule = stripped.split('NOPASSWD:', 1)[1]
                for pattern, why in self.UNSAFE:
                    if pattern.search(' ' + rule):
                        problems.append(f'{name}:{n}: {why}: {stripped[:120]}')
        self.assertEqual(problems, [], '\n'.join(problems))
