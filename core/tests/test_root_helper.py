"""
The root helper (v3.17.597): the only thing the app may run as root.

The helper replaced four passwordless sudo rules that each led to root: a `cp`
of a sudoers file the app user could rewrite, `bash /tmp/...`, `apt-get -o ...
*` and bare `fail2ban-client`. These tests load the real helper script and
check that it only does what it should: fixed actions with checked arguments,
self-update only from a correctly signed, correctly named, non-older tag, and
disabling the unsafe rules wherever they are installed.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.test import SimpleTestCase

HELPER_SRC = Path(django_settings.BASE_DIR) / 'deploy' / 'root-helper' / 'clientst0r-root-helper'


def load_helper():
    loader = importlib.machinery.SourceFileLoader('clientst0r_root_helper', str(HELPER_SRC))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module.REQUIRE_ROOT_OWNED = False
    return module


class ArgumentCheckTests(SimpleTestCase):

    def setUp(self):
        self.h = load_helper()

    def test_fail2ban_actions_map_to_fixed_argv(self):
        self.assertEqual(self.h.fail2ban_argv(['ping']), ['ping'])
        self.assertEqual(self.h.fail2ban_argv(['status', 'sshd']), ['status', 'sshd'])
        self.assertEqual(self.h.fail2ban_argv(['unban', 'sshd', '10.0.0.5']),
                         ['set', 'sshd', 'unbanip', '10.0.0.5'])
        self.assertEqual(self.h.fail2ban_argv(['unban', 'sshd', '2001:db8::1']),
                         ['set', 'sshd', 'unbanip', '2001:db8::1'])

    def test_fail2ban_rejects_anything_else(self):
        """Setting a jail's action is how unrestricted fail2ban-client becomes root."""
        for bad in (['set', 'sshd', 'action', 'x', 'actionban', 'sh'],
                    ['unban', 'sshd', '10.0.0.5; id'],
                    ['unban', 'ss hd', '10.0.0.5'],
                    ['status', '../x y'],
                    ['reload']):
            with self.assertRaises(self.h.HelperError, msg=bad):
                self.h.fail2ban_argv(bad)

    def test_apt_argv_is_fixed(self):
        opts = ['-y', '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold']
        self.assertEqual(self.h.apt_argv(['update']), ['apt-get', '-q', 'update'])
        self.assertEqual(self.h.apt_argv(['upgrade']), ['apt-get', *opts, 'upgrade'])
        self.assertEqual(self.h.apt_argv(['upgrade-packages', 'openssl', 'libc6:amd64']),
                         ['apt-get', *opts, 'install', '--only-upgrade', 'openssl', 'libc6:amd64'])

    def test_apt_rejects_options_disguised_as_packages(self):
        """`-o APT::Update::Pre-Invoke::=...` is how the old wildcard rule became root."""
        for bad in (['upgrade-packages', '-o', 'APT::Update::Pre-Invoke::=id'],
                    ['upgrade-packages', 'APT::Update::Pre-Invoke::=id'],
                    ['upgrade-packages', 'openssl;id'],
                    ['upgrade-packages'],
                    ['install', 'x']):
            with self.assertRaises(self.h.HelperError, msg=bad):
                self.h.apt_argv(bad)


class SudoersCleanupTests(SimpleTestCase):

    def setUp(self):
        self.h = load_helper()

    def test_unsafe_rules_are_commented_out(self):
        unsafe = [
            'administrator ALL=(ALL) NOPASSWD: /bin/cp /home/administrator/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban',
            'administrator ALL=(ALL) NOPASSWD: /bin/chmod 0440 /etc/sudoers.d/clientst0r-fail2ban',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/bash /tmp/nodesource_setup.sh',
            r'administrator ALL=(ALL) NOPASSWD: /usr/bin/apt-get -y -o Dpkg\:\:Options\:\:=--force-confdef -o Dpkg\:\:Options\:\:=--force-confold *',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/fail2ban-client',
            'administrator ALL=(ALL) NOPASSWD: /home/*/venv/bin/python *',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/systemd-run *',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/systemd/system/x.service',
            'administrator ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload, /usr/bin/systemd-run, /bin/true',
        ]
        new, reasons = self.h.neutralize_sudoers('\n'.join(unsafe) + '\n')
        self.assertEqual(len(reasons), len(unsafe))
        for line in new.splitlines():
            self.assertTrue(line.startswith('# disabled by clientst0r-root-helper'), line)

    def test_safe_rules_are_left_alone(self):
        safe = '\n'.join([
            '# comment with NOPASSWD: /bin/cp in it',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload clientst0r-gunicorn.service',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/systemctl is-active clientst0r-*.service',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/systemd-run --on-active\\=3 --system /usr/bin/systemctl restart clientst0r-gunicorn.service',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/apt-get -q update',
            'administrator ALL=(ALL) NOPASSWD: /usr/bin/apt-get install -y fail2ban',
            'administrator ALL=(root) NOPASSWD: /usr/local/sbin/clientst0r-root-helper',
        ]) + '\n'
        new, reasons = self.h.neutralize_sudoers(safe)
        self.assertEqual(reasons, [])
        self.assertEqual(new, safe)

    def test_own_rule_and_unit(self):
        conf = {'APP_USER': 'svc', 'APP_DIR': '/srv/app', 'SERVICE': 'clientst0r-gunicorn.service'}
        self.assertIn('svc ALL=(root) NOPASSWD: /usr/local/sbin/clientst0r-root-helper\n',
                      self.h.own_sudoers_rule(conf))
        unit = self.h.render_auto_update_unit(conf)
        self.assertIn('User=svc', unit)
        self.assertIn('ExecStart=/srv/app/scripts/auto_update.sh', unit)
        self.assertNotRegex(unit, r'(?m)^\s*NoNewPrivileges')


class ConfigTests(SimpleTestCase):

    def setUp(self):
        self.h = load_helper()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h.CONF_PATH = os.path.join(self.tmp.name, 'conf')

    def write(self, text):
        Path(self.h.CONF_PATH).write_text(text)

    def test_valid_config(self):
        self.write('APP_USER=svc\nAPP_DIR=/srv/app\nREPO_URL=https://github.com/a/b.git\n')
        conf = self.h.load_config()
        self.assertEqual(conf['SERVICE'], 'clientst0r-gunicorn.service')

    def test_bad_values_are_refused(self):
        for text in ('APP_USER=root\nAPP_DIR=/srv/app\nREPO_URL=https://github.com/a/b.git\n',
                     'APP_USER=svc\nAPP_DIR=/srv/app;x\nREPO_URL=https://github.com/a/b.git\n',
                     'APP_USER=svc\nAPP_DIR=/srv/app\nREPO_URL=ssh://evil/x\n',
                     'APP_USER=svc\nAPP_DIR=/srv/app\nREPO_URL=https://github.com/a/b.git\nSERVICE=sshd.service\n'):
            self.write(text)
            with self.assertRaises(self.h.HelperError, msg=text):
                self.h.load_config()


def _have_tools():
    return shutil.which('git') and shutil.which('ssh-keygen')


class SelfUpdateTests(SimpleTestCase):
    """Real git + ssh signatures against a throwaway repository."""

    def setUp(self):
        if not _have_tools():
            self.skipTest('git and ssh-keygen are required')
        self.h = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.trusted = self.keygen('trusted')
        self.other = self.keygen('other')
        signers = self.tmp / 'allowed_signers'
        pub = (self.tmp / 'trusted.pub').read_text().split()[:2]
        signers.write_text(f'releases@test namespaces="git" {" ".join(pub)}\n')

        self.origin = self.tmp / 'origin'
        self.git('init', '-q', str(self.origin), cwd=self.tmp)
        self.h.SIGNERS_PATH = str(signers)
        self.h.STATE_DIR = str(self.tmp / 'state')
        self.h.HELPER_PATH = str(self.tmp / 'installed-helper')
        self.conf = {'REPO_URL': f'file://{self.origin}'}

    def keygen(self, name):
        key = self.tmp / name
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
        return key

    def git(self, *args, cwd=None):
        env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                              cwd=cwd or self.origin, env=env, check=True,
                              capture_output=True, text=True)

    def release(self, tag, body, key=None, signed=True, name=None):
        path = self.origin / 'deploy' / 'root-helper'
        path.mkdir(parents=True, exist_ok=True)
        (path / 'clientst0r-root-helper').write_text(body)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', tag)
        if signed:
            self.git('-c', 'gpg.format=ssh', '-c', f'user.signingkey={key or self.trusted}',
                     'tag', '-s', name or tag, '-m', tag)
        else:
            self.git('tag', '-a', name or tag, '-m', tag)

    def installed(self):
        return Path(self.h.HELPER_PATH).read_text()

    def test_signed_release_is_installed(self):
        self.release('v1.0.2', "print('two')\n")
        self.assertEqual(self.h.self_update(self.conf, 'v1.0.2'), 0)
        self.assertEqual(self.installed(), "print('two')\n")
        self.assertEqual(self.h.installed_version(), 'v1.0.2')

    def test_unsigned_tag_is_refused(self):
        self.release('v1.0.3', "print('unsigned')\n", signed=False)
        with self.assertRaisesRegex(self.h.HelperError, 'not signed'):
            self.h.self_update(self.conf, 'v1.0.3')
        self.assertFalse(os.path.exists(self.h.HELPER_PATH))

    def test_tag_signed_by_an_untrusted_key_is_refused(self):
        self.release('v1.0.4', "print('evil')\n", key=self.other)
        with self.assertRaisesRegex(self.h.HelperError, 'not signed'):
            self.h.self_update(self.conf, 'v1.0.4')
        self.assertFalse(os.path.exists(self.h.HELPER_PATH))

    def test_older_release_is_refused(self):
        self.release('v1.0.5', "print('five')\n")
        self.h.self_update(self.conf, 'v1.0.5')
        self.release('v1.0.1', "print('old')\n")
        with self.assertRaisesRegex(self.h.HelperError, 'downgrade'):
            self.h.self_update(self.conf, 'v1.0.1')
        self.assertEqual(self.installed(), "print('five')\n")

    def test_a_signed_tag_under_another_name_is_refused(self):
        """Replay: a ref named v9.9.9 pointing at the signed v1.0.6 tag object."""
        self.release('v1.0.6', "print('six')\n")
        self.git('tag', 'v9.9.9', 'v1.0.6')   # lightweight ref -> signed tag object
        with self.assertRaisesRegex(self.h.HelperError, 'not named'):
            self.h.self_update(self.conf, 'v9.9.9')

    def test_unparseable_helper_is_refused(self):
        self.release('v1.0.7', "def broken(:\n")
        with self.assertRaises(SyntaxError):
            self.h.self_update(self.conf, 'v1.0.7')
        self.assertFalse(os.path.exists(self.h.HELPER_PATH))

    def test_bad_tag_names_are_refused(self):
        for tag in ('main', 'v1.0', 'v1.0.0; id', '../v1.0.0'):
            with self.assertRaises(self.h.HelperError, msg=tag):
                self.h.self_update(self.conf, tag)


class HelperCommandTests(SimpleTestCase):

    def setUp(self):
        self.h = load_helper()

    def test_main_refuses_unknown_commands(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.h.CONF_PATH = os.path.join(tmp.name, 'conf')
        self.h.LOCK_PATH = os.path.join(tmp.name, 'lock')
        Path(self.h.CONF_PATH).write_text(
            'APP_USER=svc\nAPP_DIR=/srv/app\nREPO_URL=https://github.com/a/b.git\n')
        with mock.patch.object(self.h, '_run') as run:
            self.assertEqual(self.h.main(['bash', '-c', 'id']), 1)
            self.assertEqual(self.h.main(['reload', 'extra']), 1)
            run.assert_not_called()


class ApplySystemConfigTests(SimpleTestCase):
    """Runs against temp copies of /etc/sudoers.d and /etc/systemd/system,
    with the real visudo; systemctl is stubbed."""

    def setUp(self):
        if not shutil.which('visudo') and not os.path.exists('/usr/sbin/visudo'):
            self.skipTest('visudo is required')
        self.h = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for d in ('sudoers.d', 'systemd', 'state'):
            (self.tmp / d).mkdir()
        self.h.SUDOERS_DIR = str(self.tmp / 'sudoers.d')
        self.h.SYSTEMD_DIR = str(self.tmp / 'systemd')
        self.h.STATE_DIR = str(self.tmp / 'state')
        self.conf = {'APP_USER': 'svc', 'APP_DIR': '/srv/app', 'SERVICE': 'clientst0r-gunicorn.service'}
        real_run = self.h._run
        self.systemctl = []

        def run(argv, **kw):
            if argv[0] == 'systemctl':
                self.systemctl.append(argv)
                return subprocess.CompletedProcess(argv, 0, '', '')
            return real_run(argv, **kw)
        self.h._run = run

    def test_disables_unsafe_rules_and_installs_own_rule(self):
        sudoers = self.tmp / 'sudoers.d'
        (sudoers / 'clientst0r-install').write_text(
            'svc ALL=(ALL) NOPASSWD: /usr/bin/apt-get update\n'
            'svc ALL=(ALL) NOPASSWD: /bin/cp /srv/app/deploy/x /etc/sudoers.d/y\n')
        (sudoers / 'other-package').write_text('svc ALL=(ALL) NOPASSWD: /usr/bin/systemd-run *\n')
        (self.tmp / 'systemd' / 'clientst0r-auto-update.service').write_text('NoNewPrivileges=true\n')

        self.assertEqual(self.h.apply_system_config(self.conf), 0)

        install = (sudoers / 'clientst0r-install').read_text()
        self.assertIn('svc ALL=(ALL) NOPASSWD: /usr/bin/apt-get update\n', install)
        self.assertIn('# disabled by clientst0r-root-helper', install)
        self.assertIn('/usr/local/sbin/clientst0r-root-helper',
                      (sudoers / 'clientst0r-root-helper').read_text())
        # Not ours: left alone.
        self.assertEqual((sudoers / 'other-package').read_text(),
                         'svc ALL=(ALL) NOPASSWD: /usr/bin/systemd-run *\n')
        # Backup kept outside /etc/sudoers.d.
        self.assertFalse([p for p in sudoers.iterdir() if '.' in p.name])
        self.assertTrue((self.tmp / 'state' / 'sudoers-backup' / 'clientst0r-install').exists())
        unit = (self.tmp / 'systemd' / 'clientst0r-auto-update.service').read_text()
        self.assertNotIn('NoNewPrivileges', unit.split('# No NoNewPrivileges')[0])
        self.assertIn(['systemctl', 'daemon-reload'], self.systemctl)

    def test_second_run_changes_nothing(self):
        self.h.apply_system_config(self.conf)
        self.systemctl.clear()
        before = {p.name: p.read_text() for p in (self.tmp / 'sudoers.d').iterdir()}
        self.h.apply_system_config(self.conf)
        after = {p.name: p.read_text() for p in (self.tmp / 'sudoers.d').iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(self.systemctl, [])
