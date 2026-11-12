"""scripts/office/install-managed-local.sh (install-editor.sh --mode
managed-local), run against a fake host.

OFFICE_INSTALL_ROOT prefixes every path; PATH starts with stubs for docker,
nft, nginx, systemctl, apt-get, getent, nproc and certbot that only log their
argv. Nothing here touches this machine, installs Docker or starts a
container (the script itself never pulls or starts one).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
SCRIPT = BASE / 'scripts' / 'office' / 'install-managed-local.sh'
EDITOR_SCRIPT = BASE / 'scripts' / 'office' / 'install-editor.sh'

STUBS = {
    'docker': 'log docker "$@"; [ -z "${STUB_NO_COMPOSE:-}" ] || [ "$1" != compose ] || exit 1; exit 0',
    'nft': 'log nft "$@"',
    'nginx': 'log nginx "$@"; exit "${STUB_NGINX_T:-0}"',
    'systemctl': 'log systemctl "$@"',
    'apt-get': 'log apt-get "$@"',
    'getent': 'echo "192.0.2.10 $2"',
    'nproc': 'echo 4',
    'certbot': 'log certbot "$@"',
}


class ManagedInstallerTests(SimpleTestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'root'
        (self.root / 'etc/nginx/sites-available').mkdir(parents=True)
        (self.root / 'etc/nginx/sites-enabled').mkdir(parents=True)
        (self.root / 'etc/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        (self.root / 'etc/clientst0r').mkdir(parents=True)
        (self.root / 'etc/clientst0r/root-helper.conf').write_text('APP_USER=clientstor\nAPP_DIR=/srv/app\n')
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        self.log = self.tmp / 'calls.log'
        for name, body in STUBS.items():
            f = self.bin / name
            f.write_text('#!/bin/bash\nlog() { printf "%s\\n" "$*" >> "$STUB_LOG"; }\n' + body + '\n')
            f.chmod(0o755)
        self.cert = self.tmp / 'cert.pem'
        self.key = self.tmp / 'key.pem'
        self.cert.write_text('cert')
        self.key.write_text('key')

    def run_script(self, *args, script=SCRIPT, env=None):
        e = {'PATH': f'{self.bin}:/usr/bin:/bin', 'OFFICE_INSTALL_ROOT': str(self.root),
             'STUB_LOG': str(self.log), 'HOME': str(self.tmp)}
        e.update(env or {})
        return subprocess.run(['bash', str(script), *args], env=e, capture_output=True, text=True,
                              timeout=60)

    def args(self, *extra):
        return ['--hostname', 'office.acme.example', '--clientstor-url', 'https://docs.acme.example',
                '--deployment-id', 'acme-prod', '--tls', 'existing-cert', '--cert-file', str(self.cert),
                '--key-file', str(self.key), *extra]

    def calls(self):
        return self.log.read_text() if self.log.exists() else ''

    def test_install_writes_config_units_site_and_starts_only_the_socket(self):
        r = self.run_script(*self.args())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conf = (self.root / 'etc/clientst0r/office-service.conf').read_text()
        for line in ('DEPLOYMENT_ID=acme-prod', 'APP_USER=clientstor', 'OFFICE_HOSTNAME=office.acme.example',
                     'CLIENTSTOR_URL=https://docs.acme.example/', 'BIND_PORT=8090', 'EDITION=community',
                     'CPUS=3', 'MEMORY_MB=4096', 'ALLOW_UNTESTED_RELEASES=no', 'MAINTENANCE_UPDATES=no'):
            self.assertIn(line + '\n', conf)
        sock = (self.root / 'etc/systemd/system/clientst0r-office-helper.socket').read_text()
        self.assertIn('SocketUser=clientstor', sock)
        self.assertNotIn('@APP_USER@', sock)
        helper = self.root / 'usr/local/sbin/clientst0r-office-helper'
        self.assertEqual(helper.read_bytes(),
                         (BASE / 'deploy/office-helper/clientst0r-office-helper').read_bytes())
        self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
        site = (self.root / 'etc/nginx/sites-available/clientst0r-office-managed').read_text()
        self.assertIn('server_name office.acme.example;', site)
        self.assertIn('proxy_pass http://127.0.0.1:8090;', site)
        self.assertIn('proxy_set_header Upgrade $http_upgrade;', site)
        self.assertIn('X-Forwarded-Proto https', site)
        self.assertTrue((self.root / 'etc/nginx/sites-enabled/clientst0r-office-managed').is_symlink())
        hold = (self.root / 'etc/apt/apt.conf.d/51clientst0r-office-engine').read_text()
        self.assertIn('"docker.io"', hold)
        calls = self.calls()
        self.assertIn('systemctl enable --now clientst0r-office-helper.socket', calls)
        self.assertIn('nginx -t', calls)
        # Docker is present: never installed, changed, restarted; no container work.
        self.assertNotIn('apt-get install', calls.replace('apt-get install -y -q nftables', ''))
        self.assertNotIn('docker.service', calls)
        for verb in ('docker pull', 'docker run', 'docker compose up', 'docker restart'):
            self.assertNotIn(verb, calls)

    def test_existing_docker_without_compose_v2_is_not_changed(self):
        r = self.run_script(*self.args(), env={'STUB_NO_COMPOSE': '1'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('does not change an existing Docker install', r.stdout)
        self.assertFalse((self.root / 'etc/clientst0r/office-service.conf').exists())
        self.assertNotIn('apt-get', self.calls())

    def test_absent_docker_needs_the_flag_and_uses_the_ubuntu_archive(self):
        (self.bin / 'docker').unlink()
        r = self.run_script(*self.args())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--install-docker', r.stdout)
        r = self.run_script(*self.args('--install-docker'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('install -y -q --no-install-recommends docker.io docker-compose-v2', self.calls())

    def test_refuses_shared_origin_secrets_and_bad_values(self):
        for extra, msg in (
                (['--hostname', 'docs.acme.example'], 'must differ'),
                (['--clientstor-url', 'https://docs.acme.example:8443'], 'port 443'),
                (['--clientstor-url', 'https://10.0.0.5/'], 'host name'),
                (['--bind-port', '80'], 'bind-port'),
                (['--edition', 'enterprise'], 'license-file'),
                (['--jwt-secret', 'x'], 'never accepted'),
                (['--provider', 'collabora-code'], 'onlyoffice only'),
                (['--tls', 'none-behind-proxy'], 'HTTPS')):
            args = self.args()
            args += extra
            r = self.run_script(*args)
            self.assertNotEqual(r.returncode, 0, extra)
            self.assertIn(msg, r.stderr, extra)
        self.assertFalse((self.root / 'etc/clientst0r/office-service.conf').exists())

    def test_host_name_already_served_elsewhere_is_refused(self):
        (self.root / 'etc/nginx/sites-enabled/other').write_text('server { server_name office.acme.example; }\n')
        r = self.run_script(*self.args())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('already served by other', r.stdout)

    def test_failed_nginx_test_removes_the_new_block(self):
        r = self.run_script(*self.args(), env={'STUB_NGINX_T': '1'})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.root / 'etc/nginx/sites-available/clientst0r-office-managed').exists())
        self.assertNotIn('systemctl reload nginx', self.calls())

    def test_enterprise_license_and_private_ca_are_root_only(self):
        lic = self.tmp / 'license.lic'
        lic.write_text('{"license": "x"}')
        ca = self.tmp / 'ca.pem'
        ca.write_text('-----BEGIN CERTIFICATE-----\nAA\n-----END CERTIFICATE-----\n')
        r = self.run_script(*self.args('--edition', 'enterprise', '--license-file', str(lic),
                                       '--ca-file', str(ca)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in ('license.lic', 'extra-ca-certs.pem'):
            self.assertEqual((self.root / 'etc/clientst0r/office' / name).stat().st_mode & 0o777, 0o600)
        self.assertIn('PRIVATE_CA=yes', (self.root / 'etc/clientst0r/office-service.conf').read_text())

    def test_dry_run_changes_nothing(self):
        r = self.run_script(*self.args('--dry-run'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.root / 'etc/clientst0r/office-service.conf').exists())
        self.assertFalse((self.root / 'usr/local/sbin').exists())
        self.assertIn('DRY RUN', r.stdout)

    def test_install_editor_dispatches_managed_local(self):
        r = self.run_script('--provider', 'onlyoffice', '--mode', 'managed-local', *self.args('--dry-run'),
                            script=EDITOR_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Host checks', r.stdout)

    def test_remove_units_keeps_data_and_secrets(self):
        self.assertEqual(self.run_script(*self.args()).returncode, 0)
        data = self.root / 'var/lib/clientst0r-office/data'
        data.mkdir(parents=True)
        secret = self.root / 'etc/clientst0r/office/jwt.secret'
        secret.write_text('s')
        r = self.run_script('--remove-units')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.root / 'usr/local/sbin/clientst0r-office-helper').exists())
        self.assertFalse((self.root / 'etc/nginx/sites-enabled/clientst0r-office-managed').exists())
        self.assertFalse((self.root / 'etc/clientst0r/office-service.conf').exists())
        self.assertTrue(data.exists())
        self.assertTrue(secret.exists())
