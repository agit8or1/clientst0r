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
        self.h.OFFICE_HELPER_PATH = str(self.tmp / 'installed-office-helper')
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

    def release(self, tag, body, key=None, signed=True, name=None, office=None):
        path = self.origin / 'deploy' / 'root-helper'
        path.mkdir(parents=True, exist_ok=True)
        (path / 'clientst0r-root-helper').write_text(body)
        if office is not None:
            opath = self.origin / 'deploy' / 'office-helper'
            opath.mkdir(parents=True, exist_ok=True)
            (opath / 'clientst0r-office-helper').write_text(office)
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

    def test_office_helper_is_not_installed_by_self_update(self):
        """Only install-editor.sh --mode managed-local installs it."""
        self.release('v1.1.0', "print('root')\n", office="print('office')\n")
        self.h.self_update(self.conf, 'v1.1.0')
        self.assertFalse(os.path.exists(self.h.OFFICE_HELPER_PATH))

    def test_installed_office_helper_is_replaced_from_the_signed_tag(self):
        Path(self.h.OFFICE_HELPER_PATH).write_text("print('old office')\n")
        self.release('v1.1.1', "print('root')\n", office="print('new office')\n")
        self.h.self_update(self.conf, 'v1.1.1')
        self.assertEqual(Path(self.h.OFFICE_HELPER_PATH).read_text(), "print('new office')\n")
        self.assertEqual(os.stat(self.h.OFFICE_HELPER_PATH).st_mode & 0o777, 0o755)

    def test_office_helper_from_an_unsigned_tag_is_not_installed(self):
        Path(self.h.OFFICE_HELPER_PATH).write_text("print('old office')\n")
        self.release('v1.1.2', "print('root')\n", office="print('evil')\n", signed=False)
        with self.assertRaises(self.h.HelperError):
            self.h.self_update(self.conf, 'v1.1.2')
        self.assertEqual(Path(self.h.OFFICE_HELPER_PATH).read_text(), "print('old office')\n")

    def test_unparseable_office_helper_is_refused(self):
        Path(self.h.OFFICE_HELPER_PATH).write_text("print('old office')\n")
        self.release('v1.1.3', "print('root')\n", office="def broken(:\n")
        with self.assertRaises(SyntaxError):
            self.h.self_update(self.conf, 'v1.1.3')
        self.assertEqual(Path(self.h.OFFICE_HELPER_PATH).read_text(), "print('old office')\n")

    def test_office_installer_is_extracted_from_the_verified_tag(self):
        scripts = self.origin / 'scripts' / 'office'
        scripts.mkdir(parents=True)
        (scripts / 'install-editor.sh').write_text('echo signed\n')
        self.release('v1.0.2', "print('two')\n", office="print('office')\n")
        self.h.self_update(self.conf, 'v1.0.2')
        self.h.OFFICE_INSTALLER_DIR = str(self.tmp / 'office-installer')
        script = self.h._extract_office_installer('v1.0.2')
        self.assertEqual(Path(script).read_text(), 'echo signed\n')
        self.assertTrue((self.tmp / 'office-installer' / 'deploy' / 'office-helper' /
                         'clientst0r-office-helper').is_file())
        # a later unsigned tag in the mirror is never used
        (scripts / 'install-editor.sh').write_text('echo evil\n')
        self.release('v1.0.3', "print('three')\n", signed=False)
        self.h._git(os.path.join(self.h.STATE_DIR, 'mirror.git'), 'fetch', '-q', self.conf['REPO_URL'],
                    'refs/tags/v1.0.3:refs/tags/v1.0.3')
        with self.assertRaises(self.h.HelperError):
            self.h._extract_office_installer('v1.0.3')

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


class ManagedOfficeEngineGuardTests(SimpleTestCase):
    """With Managed Local ONLYOFFICE configured, package updates from the app
    must not restart dockerd (and the editor container) without a drain."""

    def setUp(self):
        self.h = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.h.OFFICE_SERVICE_CONF = str(self.tmp / 'office-service.conf')

    def configure(self):
        Path(self.h.OFFICE_SERVICE_CONF).write_text('DEPLOYMENT_ID=x\n')

    def test_engine_packages_allowed_without_the_service(self):
        argv = self.h.apt_argv(['upgrade-packages', 'docker.io', 'containerd', 'runc'])
        self.assertEqual(argv[-3:], ['docker.io', 'containerd', 'runc'])

    def test_engine_packages_refused_with_the_service(self):
        self.configure()
        for pkg in ('docker.io', 'containerd', 'containerd.io', 'runc', 'docker-ce',
                    'docker-ce-cli', 'docker-compose-v2', 'docker-compose-plugin', 'docker.io:amd64'):
            with self.assertRaisesRegex(self.h.HelperError, 'managed ONLYOFFICE', msg=pkg):
                self.h.apt_argv(['upgrade-packages', 'openssl', pkg])
        self.assertEqual(self.h.apt_argv(['upgrade-packages', 'openssl', 'docker-doc'])[-1], 'docker-doc')

    def test_full_upgrade_holds_back_engine_and_editor(self):
        sim = ('Reading package lists...\n'
               'Inst openssl [3.0.2] (3.0.3 Ubuntu:22.04/jammy-security [amd64])\n'
               'Inst docker.io [24.0] (24.1 Ubuntu [amd64])\n'
               'Inst containerd [1.7] (1.7.1 Ubuntu [amd64])\n'
               'Inst libc6:amd64 [2.35] (2.35.1 Ubuntu [amd64])\n'
               'Inst onlyoffice-documentserver [9] (10 x [amd64])\n'
               'Conf openssl (3.0.3 Ubuntu [amd64])\n')
        argv, skipped = self.h.held_back_upgrade_argv(sim)
        self.assertEqual(argv[-2:], ['openssl', 'libc6:amd64'])
        self.assertIn('--only-upgrade', argv)
        self.assertEqual(skipped, ['docker.io', 'containerd', 'onlyoffice-documentserver'])
        self.assertEqual(self.h.held_back_upgrade_argv('Inst runc [1] (2 x)\n'), (None, ['runc']))

    def test_cmd_apt_upgrade_uses_the_held_back_plan(self):
        self.configure()
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, 'Inst openssl [1] (2 x)\nInst runc [1] (2 x)\n', '')
        with mock.patch.object(self.h, '_run', side_effect=run):
            self.assertEqual(self.h.cmd_apt(['upgrade']), 0)
        self.assertEqual(calls[0], ['apt-get', '-s', '-q', 'upgrade'])
        self.assertEqual(calls[1][-1], 'openssl')
        self.assertNotIn('runc', calls[1])
        self.assertNotIn('upgrade', calls[1][-2:])

    def test_cmd_apt_upgrade_unchanged_without_the_service(self):
        with mock.patch.object(self.h, '_run',
                               return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            self.h.cmd_apt(['upgrade'])
        self.assertEqual(run.call_args[0][0][-1], 'upgrade')

    def test_app_package_updater_skips_engine_with_the_service(self):
        from core.management.commands.update_system_packages import without_editor_packages
        kept, skipped = without_editor_packages(['openssl', 'docker.io', 'runc'], managed_office=True)
        self.assertEqual((kept, skipped), (['openssl'], ['docker.io', 'runc']))
        kept, skipped = without_editor_packages(['openssl', 'docker.io'], managed_office=False)
        self.assertEqual(skipped, [])


class OfficeSetupTests(SimpleTestCase):
    """office-setup: the installer runs with checked arguments only, and the
    app can extend an office install but never re-point it."""

    CONF = {'APP_USER': 'administrator', 'APP_DIR': '/home/administrator'}

    def setUp(self):
        self.h = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.h.OFFICE_SERVICE_CONF = str(self.tmp / 'office-service.conf')

    def argv(self, *args):
        return self.h.office_setup_argv(self.CONF, list(args), '/x/install-editor.sh')

    def test_same_host_collabora(self):
        argv = self.argv('collabora', 'same-host', 'docs.example.com', 'prod-1', '-', 'untested')
        self.assertEqual(argv, [
            '/bin/bash', '/x/install-editor.sh', '--provider', 'collabora', '--mode', 'managed-local',
            '--layouts', 'same-host', '--clientstor-url', 'https://docs.example.com/',
            '--deployment-id', 'prod-1', '--tls', 'upstream', '--app-user', 'administrator',
            '--install-docker', '--allow-untested-releases'])

    def test_dedicated_needs_its_own_host(self):
        argv = self.argv('onlyoffice', 'dedicated', 'docs.example.com', 'prod-1', 'office.example.com', 'tested')
        self.assertEqual(argv[-2:], ['--hostname', 'office.example.com'])
        self.assertNotIn('--allow-untested-releases', argv)
        for bad in (('onlyoffice', 'dedicated', 'docs.example.com', 'prod-1', '-', 'tested'),
                    ('onlyoffice', 'dedicated', 'docs.example.com', 'prod-1', 'docs.example.com', 'tested')):
            with self.assertRaises(self.h.HelperError, msg=bad):
                self.argv(*bad)

    def test_bad_arguments_are_refused(self):
        good = ['collabora', 'same-host', 'docs.example.com', 'prod-1', '-', 'tested']
        for i, bad in [(0, 'docker'), (1, 'same-host;id'), (2, 'docs.example.com/x'),
                       (2, '--hostname'), (2, 'localhost'), (3, '-rf'), (3, 'Prod 1'),
                       (4, 'office.example.com'), (5, 'yes')]:
            args = list(good)
            args[i] = bad
            with self.assertRaises(self.h.HelperError, msg=args):
                self.argv(*args)
        with self.assertRaises(self.h.HelperError):
            self.argv('onlyoffice', 'same-host', 'docs.example.com', 'prod-1', '-', 'tested')
        with self.assertRaises(self.h.HelperError):
            self.argv(*good, '--dry-run')

    def test_existing_install_cannot_be_repointed(self):
        Path(self.h.OFFICE_SERVICE_CONF).write_text(
            'DEPLOYMENT_ID=prod-1\nCLIENTSTOR_URL=https://docs.example.com/\n')
        self.argv('collabora', 'same-host,dedicated', 'docs.example.com', 'prod-1', 'office.example.com', 'tested')
        for host, dep in (('evil.example.com', 'prod-1'), ('docs.example.com', 'prod-2')):
            with self.assertRaises(self.h.HelperError):
                self.argv('collabora', 'same-host', host, dep, '-', 'tested')

    def test_main_refuses_bad_office_setup_before_extracting(self):
        with mock.patch.object(self.h, 'load_config', return_value=dict(self.CONF)), \
                mock.patch.object(self.h, 'LOCK_PATH', str(self.tmp / 'lock')), \
                mock.patch.object(self.h, '_extract_office_installer') as extract, \
                mock.patch.object(self.h, '_run') as run:
            rc = self.h.main(['office-setup', 'collabora', 'same-host', 'docs.example.com', 'x;id', '-', 'tested'])
        self.assertEqual(rc, 1)
        extract.assert_not_called()
        run.assert_not_called()


SITE = """upstream itdocs_app {
    server unix:/home/administrator/gunicorn.sock fail_timeout=0;
}

server {
    listen 80;
    location /static/ {
        alias /home/administrator/static_collected/;
    }
    location / {
        proxy_pass http://itdocs_app;
    }
}

# server {
#     listen 443 ssl http2;
#     location / {
# }
"""


class OfficeSiteIncludeTests(SimpleTestCase):

    CONF = {'APP_USER': 'administrator', 'APP_DIR': '/home/administrator'}

    def setUp(self):
        self.h = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        nginx = self.tmp / 'nginx'
        (nginx / 'sites-available').mkdir(parents=True)
        (nginx / 'sites-enabled').mkdir()
        (nginx / 'clientst0r-office').mkdir()
        self.site = nginx / 'sites-available' / 'itdocs.conf'
        self.site.write_text(SITE)
        os.symlink(self.site, nginx / 'sites-enabled' / 'itdocs.conf')
        other = nginx / 'sites-available' / 'other'
        other.write_text('server { listen 8080; location / { return 204; } }\n')
        os.symlink(other, nginx / 'sites-enabled' / 'other')
        self.h.NGINX_DIR = str(nginx)
        self.h.NGINX_SITES_ENABLED = str(nginx / 'sites-enabled')
        self.h.OFFICE_SNIPPET = str(nginx / 'clientst0r-office' / 'same-host.conf')
        Path(self.h.OFFICE_SNIPPET).write_text('')

    def run_include(self, on, nginx_ok=True):
        calls = []

        def fake_run(argv, env=None, timeout=600, capture=False):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0 if (nginx_ok or argv[0] != 'nginx') else 1, '', 'emerg')
        with mock.patch.object(self.h, '_run', side_effect=fake_run):
            if nginx_ok:
                self.assertEqual(self.h.cmd_office_site_include(self.CONF, ['on' if on else 'off']), 0)
            else:
                with self.assertRaises(self.h.HelperError):
                    self.h.cmd_office_site_include(self.CONF, ['on' if on else 'off'])
        return calls

    def test_include_goes_before_the_active_root_location_only(self):
        calls = self.run_include(True)
        text = self.site.read_text()
        self.assertEqual(text.count(f'include {self.h.OFFICE_SNIPPET};'), 1)
        self.assertIn(f'    include {self.h.OFFICE_SNIPPET};  {self.h.INCLUDE_MARKER}\n    location / {{', text)
        self.assertIn('#     location / {', text)
        self.assertEqual(calls, [['nginx', '-t'], ['systemctl', 'reload', 'nginx']])
        # the other site is not clientst0r's and is left alone
        self.assertNotIn('include', (Path(self.h.NGINX_DIR) / 'sites-available' / 'other').read_text())

    def test_second_run_changes_nothing_and_off_restores(self):
        self.run_include(True)
        self.assertEqual(self.run_include(True), [])
        self.run_include(False)
        self.assertEqual(self.site.read_text(), SITE)

    def test_failed_nginx_test_puts_the_site_back(self):
        calls = self.run_include(True, nginx_ok=False)
        self.assertEqual(self.site.read_text(), SITE)
        self.assertEqual(calls, [['nginx', '-t']])

    def test_needs_the_snippet_and_one_app_site(self):
        os.unlink(self.h.OFFICE_SNIPPET)
        with self.assertRaises(self.h.HelperError):
            self.h.cmd_office_site_include(self.CONF, ['on'])
        Path(self.h.OFFICE_SNIPPET).write_text('')
        second = Path(self.h.NGINX_DIR) / 'sites-available' / 'copy.conf'
        second.write_text(SITE)
        os.symlink(second, Path(self.h.NGINX_SITES_ENABLED) / 'copy.conf')
        with self.assertRaises(self.h.HelperError):
            self.h.cmd_office_site_include(self.CONF, ['on'])

    def test_bad_arguments(self):
        for bad in ([], ['yes'], ['on', 'x']):
            with self.assertRaises(self.h.HelperError):
                self.h.cmd_office_site_include(self.CONF, bad)
