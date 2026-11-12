"""deploy/office-helper/clientst0r-office-helper, run as a program.

Every test runs the real helper in a subprocess (``python3 -I``) in its test
mode: CLIENTST0R_OFFICE_HELPER_TEST_ROOT prefixes every path and PATH comes
from CLIENTST0R_OFFICE_HELPER_TEST_PATH, which starts with a fake ``docker``
(office/test_data/managed/fake-docker), a fake ``nft`` and a fake ``ip``.
The fake docker logs each argv and simulates pulls, the container and its
health. Socket requests go over a real AF_UNIX socketpair, the way systemd
hands a connection to ``serve`` (Accept=yes), so SO_PEERCRED is exercised.

Test mode is honoured only when the helper does not run as root.

Nothing here runs Docker or ONLYOFFICE: see docs/office/MANAGED_LOCAL.md,
"Live verification" (NOT RUN).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

HELPER = Path(settings.BASE_DIR) / 'deploy' / 'office-helper' / 'clientst0r-office-helper'
FAKE_DOCKER = Path(__file__).resolve().parent / 'test_data' / 'managed' / 'fake-docker'

CE = 'sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3'
EE0 = 'sha256:0c55eb69253012b37e1b0e6f1224e917cb9ba49f317017ac1ee2e52c4d53d666'
EE2 = 'sha256:ca396233b27a2ad19bb2f1eaff32ff1efff9b95114564b4e716613e73e993c0f'

BASE_CONF = {
    'DEPLOYMENT_ID': 'acme-test', 'APP_USER': 'clientstor', 'OFFICE_HOSTNAME': 'office.acme.example',
    'CLIENTSTOR_URL': 'https://docs.acme.example/', 'BIND_PORT': '8090', 'EDITION': 'community',
    'CPUS': '2', 'MEMORY_MB': '4096', 'RESERVE_MB': '2048', 'NETWORK_SUBNET': '172.31.250.0/28',
    'ALLOW_UNTESTED_RELEASES': 'yes', 'PRIVATE_CA': 'no', 'MAINTENANCE_UPDATES': 'no',
}


class HelperHarness(SimpleTestCase):
    """A fake host: config, /proc files and fake tools under a temp root."""

    edition = 'community'

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest('the helper ignores its test mode when run as root')
        self.root = Path(tempfile.mkdtemp(prefix='office-helper-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        shutil.copy(FAKE_DOCKER, self.bin / 'docker')
        (self.bin / 'docker').chmod(0o755)
        self._stub('nft', f'cat > "{self.root}/nft.in"; echo "$@" >> "{self.root}/nft.log"')
        self._stub('ip', 'echo "[]"')
        (self.root / 'proc').mkdir()
        (self.root / 'proc' / 'meminfo').write_text(
            'MemTotal:        7168000 kB\nMemAvailable:    5000000 kB\nSwapTotal:   2097152 kB\n')
        (self.root / 'etc').mkdir()
        (self.root / 'etc' / 'os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        self.docker_log = self.root / 'docker.log'
        self.write_conf()

    def _stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def write_conf(self, **overrides):
        conf = dict(BASE_CONF, EDITION=self.edition)
        conf.update(overrides)
        d = self.root / 'etc' / 'clientst0r'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'office-service.conf').write_text(
            ''.join(f'{k}={v}\n' for k, v in conf.items() if v is not None))

    def env(self, **extra):
        env = {
            'PATH': '/usr/bin:/bin',
            'CLIENTST0R_OFFICE_HELPER_TEST_ROOT': str(self.root),
            'CLIENTST0R_OFFICE_HELPER_TEST_PATH': f'{self.bin}:/usr/bin:/bin',
            'CLIENTST0R_OFFICE_HELPER_TEST_CPUS': '4',
            'CLIENTST0R_OFFICE_HELPER_TEST_HEALTH': 'true',
            'CLIENTST0R_OFFICE_HELPER_TEST_WAIT': '1',
            'FAKE_DOCKER_LOG': str(self.docker_log),
            'FAKE_DOCKER_STATE': str(self.root / 'docker-world.json'),
            'FAKE_NFT_IN': str(self.root / 'nft.in'),
            'FAKE_NFT_LOG': str(self.root / 'nft.log'),
        }
        env.update(extra)
        return env

    def fake_config(self, env):
        (self.bin / 'fake-config.json').write_text(json.dumps(
            {k: v for k, v in env.items() if k.startswith('FAKE_')}))

    def cli(self, *args, **env):
        self.fake_config(self.env(**env))
        return subprocess.run([sys.executable, '-I', str(HELPER), 'cli', *args],
                              env=self.env(**env), capture_output=True, text=True, timeout=60)

    def request(self, payload, *, raw=None, wait=True, **env):
        """Send one request the way systemd does: the connection is the
        helper's stdin. Returns the decoded reply."""
        self.fake_config(self.env(**env))
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        proc = subprocess.Popen([sys.executable, '-I', str(HELPER), 'serve'], stdin=child,
                                stdout=child, stderr=subprocess.PIPE, env=self.env(**env))
        child.close()
        parent.sendall(raw if raw is not None else (json.dumps(payload) + '\n').encode())
        parent.settimeout(30)
        data = b''
        while True:
            chunk = parent.recv(65536)
            if not chunk:
                break
            data += chunk
        parent.close()
        if wait:
            proc.wait(timeout=60)
        else:
            self.addCleanup(proc.wait, 60)
        self.last_stderr = proc.stderr.read().decode() if wait else ''
        proc.stderr.close()
        return json.loads(data.decode()) if data.strip() else {}

    def docker_calls(self):
        if not self.docker_log.exists():
            return []
        return [json.loads(line) for line in self.docker_log.read_text().splitlines()]

    def journal(self):
        return json.loads((self.root / 'var/lib/clientst0r-office/state/operation.json').read_text())

    def installed(self):
        return json.loads((self.root / 'var/lib/clientst0r-office/state/installed.json').read_text())

    def world(self):
        return json.loads((self.root / 'docker-world.json').read_text())

    def run_op(self, op, args=None, **env):
        reply = self.request({'op': op, 'args': args or {}}, **env)
        self.assertTrue(reply.get('ok'), reply)
        self.assertTrue(reply.get('accepted'), reply)
        return self.journal()


class RequestValidationTests(HelperHarness):

    def test_unknown_and_malformed_requests_are_refused(self):
        bad = [
            {'op': 'exec', 'args': {}},
            {'op': 'install', 'args': {'image': 'evil/image:latest'}},
            {'op': 'install', 'args': {'compose': 'services: {}'}},
            {'op': 'start', 'args': {'env': {'LD_PRELOAD': '/tmp/x.so'}}},
            {'op': 'update', 'args': {'release': '10.0.0-community; rm -rf /'}},
            {'op': 'update', 'args': {'release': '../../etc/passwd'}},
            {'op': 'update', 'args': {'release': '99.0.0-community'}},
            {'op': 'update', 'args': {'release': '10.0.0-community', 'digest': 'sha256:' + 'a' * 64}},
            {'op': 'update', 'args': {'release': ['10.0.0-community']}},
            {'op': 'logs', 'args': {'lines': 100000}},
            {'op': 'logs', 'args': {'lines': '10; id'}},
            {'op': 'logs', 'args': {'lines': True}},
            {'op': 'logs', 'args': {'lines': 10, 'container': 'other'}},
            {'op': 'status', 'args': {'path': '/etc/shadow'}},
            {'op': 'purge', 'args': {'confirm': 'acme-test'}},
            {'op': 'apply-firewall', 'args': {}},
            {'op': 'status', 'extra': 1},
            {'op': {'nested': 'x'}},
        ]
        for payload in bad:
            reply = self.request(payload)
            self.assertFalse(reply.get('ok'), payload)
            self.assertNotIn('result', reply)
        self.assertEqual(self.docker_calls(), [], 'no refused request may reach docker')

    def test_non_json_and_oversized_requests_are_refused(self):
        self.assertFalse(self.request(None, raw=b'not json\n')['ok'])
        reply = self.request(None, raw=b'{"op": "status", "args": {"x": "' + b'a' * 6000 + b'"}}\n')
        self.assertFalse(reply['ok'])
        self.assertIn('too large', reply['error'])

    def test_purge_only_from_root_shell(self):
        reply = self.request({'op': 'purge', 'args': {'confirm': 'acme-test'}})
        self.assertIn('root shell', reply['error'])

    def test_status_works_and_shows_no_secret(self):
        reply = self.request({'op': 'status', 'args': {}})
        self.assertTrue(reply['ok'], reply)
        r = reply['result']
        self.assertEqual(r['config']['internal_url'], 'http://127.0.0.1:8090/')
        self.assertEqual(r['config']['browser_url'], 'https://office.acme.example/')
        self.assertTrue(r['docker']['available'])
        self.assertFalse(r['container']['exists'])
        self.assertNotIn('jwt', json.dumps(r).lower().replace('jwt_secret', ''))


class ConfigValidationTests(HelperHarness):

    def assertConfRefused(self, fragment, **overrides):
        self.write_conf(**overrides)
        reply = self.request({'op': 'status', 'args': {}})
        self.assertFalse(reply['ok'], overrides)
        self.assertIn(fragment, reply['error'])

    def test_invalid_settings_are_refused(self):
        self.assertConfRefused('APP_USER must not be root', APP_USER='root')
        self.assertConfRefused('OFFICE_HOSTNAME', OFFICE_HOSTNAME='office.acme.example;id')
        self.assertConfRefused('OFFICE_HOSTNAME must differ', OFFICE_HOSTNAME='docs.acme.example')
        self.assertConfRefused('CLIENTSTOR_URL', CLIENTSTOR_URL='http://docs.acme.example/')
        self.assertConfRefused('CLIENTSTOR_URL', CLIENTSTOR_URL='https://10.0.0.5/')
        self.assertConfRefused('CLIENTSTOR_URL', CLIENTSTOR_URL='https://docs.acme.example/sub/')
        self.assertConfRefused('port 443', CLIENTSTOR_URL='https://docs.acme.example:8443/')
        self.assertConfRefused('BIND_PORT', BIND_PORT='80')
        self.assertConfRefused('EDITION', EDITION='developer')
        self.assertConfRefused('MEMORY_MB must be at least', MEMORY_MB='512')
        self.assertConfRefused("host's", MEMORY_MB='6144')        # 6144 + 2048 > 7000
        self.assertConfRefused('RESERVE_MB', RESERVE_MB='100')
        self.assertConfRefused('CPUS', CPUS='4')                   # leaves no core
        self.assertConfRefused('CPUS', CPUS='1.234')
        self.assertConfRefused('NETWORK_SUBNET', NETWORK_SUBNET='8.8.8.0/28')
        self.assertConfRefused('NETWORK_SUBNET', NETWORK_SUBNET='169.254.0.0/28')
        self.assertConfRefused('NETWORK_SUBNET', NETWORK_SUBNET='10.0.0.0/8')
        self.assertConfRefused('unknown setting', IMAGE='evil/image')
        self.assertConfRefused('yes or no', ALLOW_UNTESTED_RELEASES='maybe')


class ComposeTests(HelperHarness):

    def test_install_writes_a_pinned_hardened_compose_file(self):
        j = self.run_op('install')
        self.assertEqual(j['state'], 'succeeded', j)
        text = (self.root / 'var/lib/clientst0r-office/compose/compose.yaml').read_text()
        self.assertIn(f'image: "docker.io/onlyoffice/documentserver@{CE}"', text)
        self.assertNotIn(':latest', text)
        self.assertIn('"127.0.0.1:8090:80"', text)
        self.assertIn('restart: unless-stopped', text)
        self.assertIn('mem_limit: 4096m', text)
        self.assertIn('cpus: 2.0', text)
        self.assertIn('max-size: "10m"', text)
        self.assertIn('healthcheck:', text)
        self.assertIn('no-new-privileges:true', text)
        self.assertIn('stop_grace_period: 6m', text)
        self.assertIn('"docs.acme.example:172.31.250.1"', text)
        self.assertIn('JWT_ENABLED: "true"', text)
        self.assertIn('WOPI_ENABLED: "false"', text)
        self.assertIn('PLUGINS_ENABLED: "false"', text)
        self.assertIn('ALLOW_META_IP_ADDRESS: "false"', text)
        for forbidden in ('privileged', 'docker.sock', 'network_mode', 'cap_add', 'pid:', '/:/',
                          'JWT_SECRET', 'watchtower'):
            self.assertNotIn(forbidden, text)
        mounts = [line for line in text.splitlines() if 'clientst0r-office/data/' in line]
        self.assertEqual(len(mounts), 3, mounts)   # data, lib, logs only

    def test_secret_is_random_persistent_and_only_in_root_files(self):
        self.run_op('install')
        secret_dir = self.root / 'etc/clientst0r/office'
        jwt = (secret_dir / 'jwt.secret').read_text().strip()
        self.assertGreaterEqual(len(jwt), 32)
        self.assertEqual((secret_dir / 'jwt.secret').stat().st_mode & 0o777, 0o600)
        self.assertEqual((secret_dir / 'ds.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual(secret_dir.stat().st_mode & 0o777, 0o700)
        self.assertIn(f'JWT_SECRET={jwt}', (secret_dir / 'ds.env').read_text())
        self.run_op('restart')
        self.assertEqual((secret_dir / 'jwt.secret').read_text().strip(), jwt, 'never regenerated')
        reply = self.request({'op': 'secret', 'args': {}})
        self.assertEqual(reply['result']['jwt_secret'], jwt)
        self.assertNotIn(jwt, json.dumps(self.journal()))
        self.assertNotIn(jwt, (self.root / 'var/lib/clientst0r-office/compose/compose.yaml').read_text())

    def test_firewall_allows_only_gateway_443(self):
        self.run_op('install')
        rules = (self.root / 'nft.in').read_text()
        self.assertIn('table inet clientst0r_office', rules)
        self.assertIn('iifname "cs0office0" ip daddr 172.31.250.1 tcp dport 443 accept', rules)
        self.assertIn('iifname "cs0office0" drop', rules)
        self.assertEqual(rules.count('iifname "cs0office0" drop'), 2)   # input and forward


class LifecycleTests(HelperHarness):

    def test_install_pulls_by_digest_then_starts(self):
        j = self.run_op('install')
        self.assertEqual(j['state'], 'succeeded', j)
        calls = self.docker_calls()
        pull = calls.index(['pull', f'docker.io/onlyoffice/documentserver@{CE}'])
        up = next(i for i, c in enumerate(calls) if c[:1] == ['compose'] and 'up' in c)
        self.assertLess(pull, up)
        self.assertIn('--pull', calls[up])
        self.assertEqual(self.installed()['release'], '10.0.0-community')

    def test_install_is_idempotent(self):
        self.run_op('install')
        j = self.run_op('install')
        self.assertEqual(j['state'], 'succeeded', j)

    def test_untested_release_refused_without_explicit_opt_in(self):
        self.write_conf(ALLOW_UNTESTED_RELEASES='no')
        j = self.run_op('install')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('live verification', j['error'])
        self.assertFalse(any(c[:1] == ['pull'] for c in self.docker_calls()))

    def test_wrong_digest_after_pull_is_refused(self):
        j = self.run_op('install', FAKE_DOCKER_BAD_DIGEST='1')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('pinned digest', j['error'])
        self.assertFalse(any(c[:1] == ['compose'] and 'up' in c for c in self.docker_calls()))

    def test_docker_missing_fails_cleanly(self):
        j = self.run_op('install', FAKE_DOCKER_DOWN='1')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('Docker is not usable', j['error'])

    def test_stop_runs_vendor_shutdown_procedure_first(self):
        self.run_op('install')
        j = self.run_op('stop')
        self.assertEqual(j['state'], 'succeeded', j)
        calls = self.docker_calls()
        shut = calls.index(['exec', 'clientst0r-office-ds', 'documentserver-prepare4shutdown'])
        stop = next(i for i, c in enumerate(calls) if c[:1] == ['compose'] and 'stop' in c)
        self.assertLess(shut, stop)

    def test_failed_shutdown_procedure_leaves_editor_running(self):
        self.run_op('install')
        j = self.run_op('stop', FAKE_DOCKER_SHUTDOWN_RC='1')
        self.assertEqual(j['state'], 'failed')
        self.assertTrue(self.world()['container']['running'])

    def test_second_operation_while_one_runs_is_busy(self):
        import fcntl
        lock_dir = self.root / 'run/clientst0r-office'
        lock_dir.mkdir(parents=True)
        fd = os.open(lock_dir / 'operation.lock', os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            reply = self.request({'op': 'restart', 'args': {}})
        finally:
            os.close(fd)
        self.assertFalse(reply['ok'])
        self.assertTrue(reply['busy'])

    def test_interrupted_operation_is_reported_not_resumed(self):
        state = self.root / 'var/lib/clientst0r-office/state'
        state.mkdir(parents=True)
        (state / 'operation.json').write_text(json.dumps(
            {'id': 'x', 'op': 'update', 'state': 'running', 'step': 'backing up', 'pid': 999999,
             'boot_id': 'old-boot'}))
        reply = self.request({'op': 'status', 'args': {}})
        op = reply['result']['operation']
        self.assertEqual(op['state'], 'interrupted')
        self.assertIn('backing up', op['error'])
        self.assertIn('reboot', op['error'])
        self.assertEqual([c for c in self.docker_calls()
                          if c[:1] == ['pull'] or (c[:1] == ['compose'] and 'version' not in c)], [])

    def test_uninstall_keeps_data_and_secrets(self):
        self.run_op('install')
        (self.root / 'var/lib/clientst0r-office/data/lib/forgotten.docx').write_text('x')
        j = self.run_op('uninstall')
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertIsNone(self.world()['container'])
        self.assertTrue((self.root / 'var/lib/clientst0r-office/data/lib/forgotten.docx').exists())
        self.assertTrue((self.root / 'etc/clientst0r/office/jwt.secret').exists())
        self.assertEqual(self.installed()['state'], 'uninstalled')

    def test_purge_needs_uninstall_and_deployment_id(self):
        self.run_op('install')
        r = self.cli('purge', '--confirm', 'acme-test')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('uninstall first', r.stderr)
        self.run_op('uninstall')
        r = self.cli('purge', '--confirm', 'wrong-id')
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.root / 'var/lib/clientst0r-office/data').exists())
        r = self.cli('purge', '--confirm', 'acme-test')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.root / 'var/lib/clientst0r-office/data').exists())
        self.assertFalse((self.root / 'etc/clientst0r/office').exists())

    def test_logs_are_bounded_and_redacted(self):
        self.run_op('install')
        jwt = (self.root / 'etc/clientst0r/office/jwt.secret').read_text().strip()
        reply = self.request({'op': 'logs', 'args': {'lines': 50}}, FAKE_DOCKER_LOG_SECRET=jwt)
        log = reply['result']['log']
        self.assertNotIn(jwt, log)
        self.assertNotIn('SECRETTOKEN', log)
        self.assertNotIn('eyJhbGciOiJIUzI1NiJ9', log)
        self.assertNotIn('md5=abc123', log)
        self.assertIn('[secret]', log)
        self.assertIn(['logs', '--tail', '50', '--timestamps', 'clientst0r-office-ds'], self.docker_calls())

    def test_connection_from_another_uid_is_refused(self):
        """SO_PEERCRED is read from the real socket; a peer that is neither
        root nor APP_USER gets "not allowed" before its request is parsed."""
        import importlib.machinery
        import importlib.util
        from unittest import mock
        loader = importlib.machinery.SourceFileLoader('office_helper_mod', str(HELPER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.assertEqual(mod.peer_uid(a), os.getuid())
        a.close()
        b.close()
        reply = self.request({'op': 'status', 'args': {}})
        self.assertTrue(reply['ok'])
        # Same program, but the config names a different app account: the
        # helper must then compare against that account's uid.
        with mock.patch.dict(os.environ, self.env()):
            mod._enable_test_mode()
            conf = mod.load_config()
        self.assertEqual(conf['app_uid'], os.getuid())
        stranger = os.getuid() + 1
        self.assertNotIn(stranger, (0, conf['app_uid']))
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        parent.sendall(b'{"op": "status", "args": {}}\n')
        with mock.patch.object(mod, 'peer_uid', return_value=stranger), \
                mock.patch.object(mod, 'load_config', return_value=conf), \
                mock.patch.object(mod.os, 'dup', return_value=os.dup(child.fileno())), \
                mock.patch.object(mod.os, 'close'):
            mod.serve()
        parent.settimeout(5)
        answer = json.loads(parent.recv(4096).decode())
        self.assertEqual(answer, {'ok': False, 'error': 'not allowed'})
        parent.close()
        child.close()


class UpdateRollbackTests(HelperHarness):
    edition = 'enterprise'

    def setUp(self):
        super().setUp()
        d = self.root / 'etc/clientst0r/office'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'license.lic').write_text('LICENSE')

    def test_enterprise_needs_license(self):
        (self.root / 'etc/clientst0r/office/license.lic').unlink()
        j = self.run_op('install')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('license file', j['error'])

    def _install_old(self):
        # Install 10.0.0-ee: point installed.json at it, then converge.
        state = self.root / 'var/lib/clientst0r-office/state'
        state.mkdir(parents=True, exist_ok=True)
        (state / 'installed.json').write_text(json.dumps({'release': '10.0.0-enterprise',
                                                          'state': 'installing'}))
        j = self.run_op('install')
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertIn(EE0, self.world()['container']['image'])
        mounts = (self.root / 'var/lib/clientst0r-office/compose/compose.yaml').read_text()
        self.assertIn('/var/lib/postgresql', mounts)
        (self.root / 'var/lib/clientst0r-office/data/data/marker').write_text('before-update')

    def test_update_pulls_before_downtime_backs_up_and_records_previous(self):
        self._install_old()
        self.docker_log.write_text('')
        j = self.run_op('update', {'release': '10.0.2-enterprise'})
        self.assertEqual(j['state'], 'succeeded', j)
        calls = self.docker_calls()
        pull = calls.index(['pull', f'docker.io/onlyoffice/documentserver-ee@{EE2}'])
        shut = calls.index(['exec', 'clientst0r-office-ds', 'documentserver-prepare4shutdown'])
        self.assertLess(pull, shut, 'the new image is downloaded before any downtime')
        inst = self.installed()
        self.assertEqual(inst['release'], '10.0.2-enterprise')
        self.assertEqual(inst['previous_release'], '10.0.0-enterprise')
        manifest = json.loads((self.root / 'var/lib/clientst0r-office/backups' / inst['previous_backup']
                               / 'manifest.json').read_text())
        self.assertEqual(manifest['digest'], EE0)
        self.assertEqual(manifest['compat'], 'ds10-ee')

    def test_unhealthy_update_restores_previous_release_automatically(self):
        self._install_old()
        j = self.run_op('update', {'release': '10.0.2-enterprise'}, FAKE_DOCKER_UNHEALTHY=EE2)
        self.assertEqual(j['state'], 'failed')
        self.assertIn('previous release is running again', j['error'])
        self.assertIn(EE0, self.world()['container']['image'])
        self.assertEqual(self.installed()['release'], '10.0.0-enterprise')
        self.assertEqual((self.root / 'var/lib/clientst0r-office/data/data/marker').read_text(),
                         'before-update')

    def test_older_release_is_not_an_update(self):
        self._install_old()
        self.run_op('update', {'release': '10.0.2-enterprise'})
        j = self.run_op('update', {'release': '10.0.0-enterprise'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('rollback', j['error'])

    def test_rollback_restores_matching_backup_and_keeps_newer_data(self):
        self._install_old()
        self.run_op('update', {'release': '10.0.2-enterprise'})
        marker = self.root / 'var/lib/clientst0r-office/data/data/marker'
        marker.write_text('after-update')
        j = self.run_op('rollback')
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertEqual(marker.read_text(), 'before-update')
        self.assertIn(EE0, self.world()['container']['image'])
        kept = j['result']['kept_backup']
        self.assertIn('pre-rollback', kept)
        self.assertTrue((self.root / 'var/lib/clientst0r-office/backups' / kept / 'state.tar').exists())
        # Nothing left to roll back to.
        j = self.run_op('rollback')
        self.assertEqual(j['state'], 'failed')

    def test_rollback_refuses_without_matching_backup(self):
        self._install_old()
        self.run_op('update', {'release': '10.0.2-enterprise'})
        inst = self.installed()
        shutil.rmtree(self.root / 'var/lib/clientst0r-office/backups' / inst['previous_backup'])
        j = self.run_op('rollback')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('missing', j['error'])

    def test_status_reports_update_available(self):
        self._install_old()
        reply = self.request({'op': 'status', 'args': {}})
        ids = [u['id'] for u in reply['result']['update_available']]
        self.assertEqual(ids, ['10.0.2-enterprise'])


class PreflightTests(HelperHarness):

    def test_preflight_reports_each_area(self):
        reply = self.request({'op': 'preflight', 'args': {}})
        keys = {c['key'] for c in reply['result']['checks']}
        for key in ('os', 'arch', 'docker', 'nftables', 'memory', 'cpu', 'disk', 'port', 'proxy',
                    'subnet', 'dns', 'release'):
            self.assertIn(key, keys)

    def test_preflight_flags_short_memory(self):
        (self.root / 'proc' / 'meminfo').write_text('MemTotal: 5000000 kB\nMemAvailable: 1 kB\n')
        reply = self.request({'op': 'status', 'args': {}})
        self.assertFalse(reply['ok'])     # config check: 4096 + 2048 > 4882 MB


class ReleaseListTests(SimpleTestCase):

    def test_every_release_is_pinned_to_an_official_image_digest(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader('office_helper_rel', str(HELPER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        conf = {'edition': 'community', 'allow_untested': True}
        for r in mod.RELEASES:
            self.assertRegex(r['digest'], r'^sha256:[0-9a-f]{64}$')
            self.assertNotEqual(r['digest'], mod.PLACEHOLDER_DIGEST)
            self.assertRegex(r['image'], r'^docker\.io/onlyoffice/documentserver(-ee)?$')
            self.assertNotIn(':', r['image'].split('/')[-1])
        placeholder = dict(mod.RELEASES[0], digest=mod.PLACEHOLDER_DIGEST)
        self.assertIn('placeholder', mod.release_problem(placeholder, conf))
        self.assertIn('live verification', mod.release_problem(
            dict(mod.RELEASES[0], tested=False), dict(conf, allow_untested=False)))
