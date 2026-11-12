"""scripts/office/install-editor.sh, run against a fake host.

Every test runs the real script with OFFICE_INSTALL_ROOT pointing at a
temporary directory (all file paths are prefixed with it) and PATH starting
with stub commands: apt-get, apt-mark, apt-cache, dpkg-query, systemctl,
nginx, curl, ss, getent, ... The stubs log their argv; apt-get "installs" by
creating the vendor config file the real package would. gpg, openssl and
python3 are the real ones, and the signing keys are the vendors' real public
keys, so the fingerprint check is exercised for real.

Nothing here touches the machine running the tests, and nothing proves the
editor works on a real Ubuntu/Debian host: see docs/office/INSTALL.md,
"Manual verification".
"""
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SCRIPT = Path(settings.BASE_DIR) / 'scripts' / 'office' / 'install-editor.sh'
DATA = Path(__file__).resolve().parent / 'test_data' / 'ops'
OO_KEY = DATA / 'onlyoffice-GPG-KEY-ONLYOFFICE.asc'
CO_KEY = DATA / 'collaboraonline-release-keyring.gpg'
CO_XML = DATA / 'coolwsd-minimal.xml'

STUBS = {
    'apt-get': r'''
        log apt-get "$@"
        if [ "${1:-}" = install ]; then
            for a in "$@"; do
                case "$a" in
                    onlyoffice-documentserver=*)
                        mkdir -p "$OFFICE_INSTALL_ROOT/etc/onlyoffice/documentserver"
                        echo '{"services": {"CoAuthoring": {}}}' > "$OFFICE_INSTALL_ROOT/etc/onlyoffice/documentserver/local.json" ;;
                    coolwsd=*)
                        mkdir -p "$OFFICE_INSTALL_ROOT/etc/coolwsd"
                        cp "$STUB_CO_XML" "$OFFICE_INSTALL_ROOT/etc/coolwsd/coolwsd.xml" ;;
                esac
            done
        fi
        exit 0''',
    'apt-mark': 'log apt-mark "$@"',
    'apt-cache': r'''
        log apt-cache "$@"
        if [ "$1" = madison ]; then
            for v in ${STUB_AVAILABLE:-}; do
                case "$v" in "$2="*) echo " $2 | ${v#*=} | https://repo.example main amd64 Packages" ;; esac
            done
        fi''',
    'debconf-set-selections': r'''
        log debconf-set-selections "$@"
        cat > "$STUB_DIR/debconf.in"''',
    'dpkg-query': r'''
        log dpkg-query "$@"
        pkg="${*: -1}"
        while read -r name ver; do
            [ "$name" = "$pkg" ] && { printf 'install ok installed %s' "$ver"; exit 0; }
        done < "${STUB_INSTALLED:-/dev/null}"
        exit 1''',
    'dpkg': r'''
        if [ "$1" = --print-architecture ]; then echo amd64; exit 0; fi
        exec /usr/bin/dpkg "$@"''',
    'systemctl': r'''
        log systemctl "$@"
        if [ "$1" = list-unit-files ]; then
            printf 'ds-docservice.service enabled enabled\nds-converter.service enabled enabled\n'
        fi
        exit 0''',
    'nginx': 'log nginx "$@"; exit "${STUB_NGINX_T:-0}"',
    'curl': r'''
        log curl "$@"
        out=""; url=""
        while [ $# -gt 0 ]; do
            case "$1" in
                -o) out="$2"; shift ;;
                --proto|--max-time|-H|--resolve|--cacert|-w) shift ;;
                -*) ;;
                *) url="$1" ;;
            esac
            shift
        done
        case "$url" in
            *GPG-KEY*|*keyring.gpg) cp "$STUB_KEY_FILE" "$out" ;;
            *healthcheck) body=true ;;
            *discovery) body='<wopi-discovery></wopi-discovery>' ;;
            *) body='' ;;
        esac
        case "$url" in
            *GPG-KEY*|*keyring.gpg) ;;
            *) if [ -n "$out" ]; then printf '%s' "$body" > "$out"; else printf '%s' "$body"; fi ;;
        esac
        exit 0''',
    'ss': '[ -n "${STUB_SS:-}" ] && cat "$STUB_SS"; exit 0',
    'nproc': 'echo "${STUB_NPROC:-8}"',
    'df': r'''printf 'Filesystem 1024-blocks Used Available Capacity Mounted\n'
        printf '/dev/sda1 1000000000 1 %s 1%% /\n' "${STUB_DF_KB:-209715200}"''',
    'getent': 'log getent "$@"; echo "192.0.2.10 STREAM $2"',
    'hostname': 'echo testhost',
    'update-ca-certificates': 'log update-ca-certificates "$@"',
    'coolconfig': r'''
        log coolconfig "$@"
        echo fake > "$OFFICE_INSTALL_ROOT/etc/coolwsd/proof_key"''',
    'certbot': 'log certbot "$@"',
    'docker': 'exit 1',
}


@unittest.skipUnless(shutil.which('gpg') and shutil.which('openssl') and Path('/usr/bin/dpkg').exists(),
                     'needs gpg, openssl and dpkg')
class InstallerHarness(SimpleTestCase):
    """Builds a fake host per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='office-installer-'))
        self.root = self.tmp / 'root'
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        self.root.mkdir()
        self.log = self.tmp / 'stub.log'
        for name, body in STUBS.items():
            f = self.bin / name
            f.write_text('#!/bin/bash\nlog() { printf "%s\\n" "$*" >> "$STUB_LOG"; }\n'
                         + textwrap.dedent(body).strip() + '\n')
            f.chmod(0o755)
        (self.root / 'etc').mkdir()
        (self.root / 'proc').mkdir()
        (self.root / 'etc/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        (self.root / 'proc/meminfo').write_text('MemTotal: 16384000 kB\nSwapTotal: 4194304 kB\n')
        # A clientst0r install on this host: helper config, app dir with
        # documents and .env, and its Nginx site.
        self.app = self.root / 'home/app/clientst0r'
        self.docs = self.app / 'media/office/revisions/1/doc-1'
        self.docs.mkdir(parents=True)
        (self.docs / 'r1.docx').write_bytes(b'PK document')
        (self.app / '.env').write_text('SECRET_KEY=x\n')
        (self.root / 'etc/clientst0r').mkdir()
        (self.root / 'etc/clientst0r/root-helper.conf').write_text(
            'APP_USER=app\nAPP_DIR=/home/app/clientst0r\nSERVICE=clientst0r-gunicorn.service\n')
        sites = self.root / 'etc/nginx/sites-available'
        sites.mkdir(parents=True)
        (self.root / 'etc/nginx/sites-enabled').mkdir()
        self.cs_site = sites / 'clientst0r'
        self.cs_site_text = ('upstream clientst0r_app { server unix:/home/app/gunicorn.sock; }\n'
                             'server { listen 443 ssl; server_name app.example.com; }\n')
        self.cs_site.write_text(self.cs_site_text)
        (self.root / 'etc/nginx/sites-enabled/clientst0r').symlink_to('/etc/nginx/sites-available/clientst0r')
        certs = self.root / 'etc/ssl/clientst0r-office'
        certs.mkdir(parents=True)
        (certs / 'docs.example.com.crt').write_text('cert')
        (certs / 'docs.example.com.key').write_text('key')
        self.installed = self.tmp / 'installed'
        self.installed.write_text('nginx 1.24.0-2ubuntu7.19\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args, key=OO_KEY, env=None):
        e = {
            'PATH': f'{self.bin}:/usr/bin:/bin',
            'HOME': str(self.tmp),
            'LANG': 'C.UTF-8',
            'OFFICE_INSTALL_ROOT': str(self.root),
            'OFFICE_INSTALL_HEALTH_WAIT': '0',
            'STUB_LOG': str(self.log),
            'STUB_DIR': str(self.tmp),
            'STUB_KEY_FILE': str(key),
            'STUB_CO_XML': str(CO_XML),
            'STUB_INSTALLED': str(self.installed),
            'STUB_AVAILABLE': ('onlyoffice-documentserver=10.0.0-169 onlyoffice-documentserver=10.0.2-5 '
                               'coolwsd=26.04.6.1-1 code-brand=26.04.6-1 '
                               'coolwsd=26.04.7.1-1 code-brand=26.04.7-1'),
        }
        e.update(env or {})
        p = subprocess.run(['bash', str(SCRIPT), *args], env=e, capture_output=True, text=True,
                           timeout=120, stdin=subprocess.DEVNULL)
        self.out = p.stdout + p.stderr
        return p

    def stub_log(self):
        return self.log.read_text() if self.log.exists() else ''

    def files_under_root(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))

    OO_ARGS = ('--provider', 'onlyoffice', '--mode', 'separate-server', '--hostname', 'docs.example.com',
               '--clientstor-url', 'https://app.example.com')

    def install_onlyoffice(self, *extra):
        p = self.run_script(*self.OO_ARGS, '--accept-mscorefonts-eula', *extra)
        self.assertEqual(p.returncode, 0, self.out)
        return p

    def secret(self):
        return (self.root / 'etc/clientst0r-office/secret').read_text().strip()


class DryRunTests(InstallerHarness):

    def test_dry_run_changes_nothing_and_runs_no_package_commands(self):
        before = self.files_under_root()
        p = self.run_script(*self.OO_ARGS, '--dry-run')
        self.assertEqual(p.returncode, 0, self.out)
        self.assertEqual(self.files_under_root(), before)
        self.assertIn('DRY RUN complete: nothing was changed.', self.out)
        self.assertIn('Signing key fingerprint verified: E09CA29F6E178040EF22B4098320CA65CB2DE8E5', self.out)
        # Printed, not executed.
        self.assertIn('+ apt-get install', self.out)
        self.assertIn('onlyoffice-documentserver=10.0.0-169', self.out)
        log = self.stub_log()
        for cmd in ('apt-get', 'apt-mark', 'systemctl restart', 'systemctl reload', 'debconf-set-selections',
                    'update-ca-certificates'):
            self.assertNotIn(cmd, log)
        self.assertIn('Browser URL:   https://docs.example.com/', self.out)
        self.assertIn('Callback URL:  https://app.example.com/', self.out)

    def test_preflight_only_reports_and_stops(self):
        p = self.run_script(*self.OO_ARGS, '--preflight-only')
        self.assertEqual(p.returncode, 0, self.out)
        self.assertIn('Preflight passed', self.out)
        self.assertIn('Ubuntu 24.04 is not named on ONLYOFFICE', self.out)
        self.assertNotIn('Fetching the signing key', self.out)
        self.assertNotIn('curl', self.stub_log())

    def test_secret_on_command_line_is_refused(self):
        for flag in ('--secret', '--jwt-secret'):
            p = self.run_script(*self.OO_ARGS, flag, 'abc123', '--dry-run')
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('never accepted on the command line', self.out)

    def test_old_onlyoffice_version_refused(self):
        p = self.run_script(*self.OO_ARGS, '--version', '9.4.0-1', '--dry-run')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('requires 10.0.0 or later', self.out)


class SigningKeyTests(InstallerHarness):

    def test_wrong_key_is_rejected(self):
        before = self.files_under_root()
        p = self.run_script(*self.OO_ARGS, '--dry-run', key=CO_KEY)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Signing key fingerprint mismatch: expected E09CA29F6E178040EF22B4098320CA65CB2DE8E5, '
                      'got 7EB1530818B7683284483B7BD8915E456E7C440E', self.out)
        self.assertEqual(self.files_under_root(), before)

    def test_wrong_key_rejected_on_real_run_writes_no_repo(self):
        p = self.run_script(*self.OO_ARGS, '--accept-mscorefonts-eula', key=CO_KEY)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.root / 'etc/apt').exists())
        self.assertNotIn('apt-get', self.stub_log())

    def test_keyring_with_an_extra_key_is_rejected(self):
        both = self.tmp / 'both.gpg'
        home = self.tmp / 'gnupg'
        home.mkdir(mode=0o700)
        subprocess.run(['gpg', '--batch', '--homedir', str(home), '--dearmor', '-o', str(self.tmp / 'oo.gpg'),
                        str(OO_KEY)], check=True, capture_output=True)
        both.write_bytes((self.tmp / 'oo.gpg').read_bytes() + CO_KEY.read_bytes())
        p = self.run_script(*self.OO_ARGS, '--dry-run', key=both)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('holds 2 primary keys', self.out)

    def test_collabora_key_accepted_for_collabora(self):
        p = self.run_script('--provider', 'collabora-code', '--mode', 'separate-server',
                            '--hostname', 'docs.example.com', '--clientstor-url', 'https://app.example.com',
                            '--dry-run', key=CO_KEY)
        self.assertEqual(p.returncode, 0, self.out)
        self.assertIn('fingerprint verified: 7EB1530818B7683284483B7BD8915E456E7C440E', self.out)


class SameServerTests(InstallerHarness):

    SAME = ('--provider', 'onlyoffice', '--mode', 'same-server', '--clientstor-url', 'https://app.example.com')

    def test_refuses_clientstor_host_name(self):
        p = self.run_script(*self.SAME, '--hostname', 'app.example.com', '--preflight-only')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("is clientst0r's own host name", self.out)

    def test_refuses_host_served_by_clientstor_site(self):
        self.cs_site.write_text(self.cs_site_text.replace('server_name app.example.com;',
                                                          'server_name app.example.com docs.example.com;'))
        before = self.cs_site.read_text()
        p = self.run_script(*self.SAME, '--hostname', 'docs.example.com', '--preflight-only')
        self.assertEqual(p.returncode, 3, self.out)
        self.assertIn("served by clientst0r's own Nginx site", self.out)
        self.assertEqual(self.cs_site.read_text(), before)

    def test_refuses_host_used_by_another_site(self):
        (self.root / 'etc/nginx/sites-available/other').write_text('server { server_name docs.example.com; }\n')
        p = self.run_script(*self.SAME, '--hostname', 'docs.example.com', '--preflight-only')
        self.assertEqual(p.returncode, 3, self.out)
        self.assertIn('already used by /etc/nginx/sites-available/other', self.out)

    def test_short_resources_recommend_separate_vm(self):
        (self.root / 'proc/meminfo').write_text('MemTotal: 3000000 kB\nSwapTotal: 4194304 kB\n')
        p = self.run_script(*self.SAME, '--hostname', 'docs.example.com', '--preflight-only')
        self.assertEqual(p.returncode, 3, self.out)
        self.assertIn('use a separate VM', self.out)

    def test_port_conflict_detected(self):
        ss = self.tmp / 'ss.txt'
        ss.write_text('LISTEN 0 511 0.0.0.0:8083 0.0.0.0:* users:(("node",pid=1,fd=3))\n'
                      'LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("apache2",pid=2,fd=4))\n')
        p = self.run_script(*self.SAME, '--hostname', 'docs.example.com', '--preflight-only',
                            env={'STUB_SS': str(ss)})
        self.assertEqual(p.returncode, 3, self.out)
        self.assertIn('Port 8083', self.out)
        self.assertIn("Port 443 is used by 'apache2'", self.out)

    def test_same_server_install_leaves_clientstor_alone(self):
        env_before = (self.app / '.env').read_text()
        p = self.run_script(*self.SAME, '--hostname', 'docs.example.com', '--accept-mscorefonts-eula')
        self.assertEqual(p.returncode, 0, self.out)
        self.assertEqual(self.cs_site.read_text(), self.cs_site_text)
        self.assertEqual((self.app / '.env').read_text(), env_before)
        site = (self.root / 'etc/nginx/sites-available/clientst0r-office-docs.example.com.conf').read_text()
        self.assertIn('server_name docs.example.com;', site)
        self.assertNotIn('app.example.com', site)
        self.assertIn('proxy_set_header Upgrade $http_upgrade;', site)
        self.assertTrue((self.root / 'etc/nginx/sites-enabled/clientst0r-office-docs.example.com.conf').is_symlink())
        self.assertIn('Internal URL:  http://127.0.0.1:8083/', self.out)


class InstallTests(InstallerHarness):

    def test_secret_never_in_output_or_command_lines(self):
        self.install_onlyoffice()
        secret = self.secret()
        self.assertEqual(len(secret), 64)
        self.assertNotIn(secret, self.out)
        self.assertNotIn(secret, self.stub_log())
        mode = stat.S_IMODE((self.root / 'etc/clientst0r-office/secret').stat().st_mode)
        self.assertEqual(mode, 0o600)
        # The secret is preseeded through stdin, not argv.
        self.assertIn(f'onlyoffice/jwt-secret password {secret}', (self.tmp / 'debconf.in').read_text())

    def test_version_pin_and_hold_written(self):
        self.install_onlyoffice('--version', '10.0.2-5')
        pref = (self.root / 'etc/apt/preferences.d/clientst0r-office-onlyoffice.pref').read_text()
        self.assertIn('Package: onlyoffice-documentserver\nPin: version 10.0.2-5\nPin-Priority: 1001', pref)
        self.assertIn('Pin: origin "download.onlyoffice.com"\nPin-Priority: 100', pref)
        log = self.stub_log()
        self.assertIn('onlyoffice-documentserver=10.0.2-5', log)
        self.assertIn('apt-mark hold onlyoffice-documentserver', log)

    def test_default_version_pinned(self):
        self.install_onlyoffice()
        pref = (self.root / 'etc/apt/preferences.d/clientst0r-office-onlyoffice.pref').read_text()
        self.assertIn('Pin: version 10.0.0-169', pref)

    def test_unavailable_version_refused(self):
        p = self.run_script(*self.OO_ARGS, '--accept-mscorefonts-eula', '--version', '10.0.9-1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('is not available from the repository', self.out)

    def test_repo_uses_signed_by_keyring(self):
        self.install_onlyoffice()
        src = (self.root / 'etc/apt/sources.list.d/clientst0r-office-onlyoffice.list').read_text()
        self.assertIn('deb [signed-by=/etc/apt/keyrings/clientst0r-office-onlyoffice.gpg] '
                      'https://download.onlyoffice.com/repo/debian squeeze main', src)
        self.assertTrue((self.root / 'etc/apt/keyrings/clientst0r-office-onlyoffice.gpg').stat().st_size > 1000)

    def test_onlyoffice_local_json(self):
        import json
        self.install_onlyoffice()
        data = json.loads((self.root / 'etc/onlyoffice/documentserver/local.json').read_text())
        co = data['services']['CoAuthoring']
        secret = self.secret()
        for kind in ('browser', 'inbox', 'outbox'):
            self.assertEqual(co['secret'][kind]['string'], secret)
        self.assertNotEqual(co['secret']['session']['string'], secret)
        self.assertEqual(co['token']['enable'], {'browser': True, 'request': {'inbox': True, 'outbox': True}})
        self.assertEqual(co['token']['inbox']['header'], 'Authorization')
        rfa = co['request-filtering-agent']
        self.assertEqual(rfa['allowPrivateIPAddress'], False)
        self.assertEqual(rfa['allowIPAddressList'], ['192.0.2.10'])
        self.assertNotEqual(data['storage']['fs']['secretString'], 'verysecretstring')
        self.assertEqual(data['aiSettings']['enable'], False)

    def test_private_ca_for_onlyoffice(self):
        ca = self.tmp / 'ca.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout',
                        str(self.tmp / 'ca.key'), '-out', str(ca), '-subj', '/CN=Test CA', '-days', '2'],
                       check=True, capture_output=True)
        self.install_onlyoffice('--ca-file', str(ca))
        drop = self.root / 'etc/systemd/system/ds-docservice.service.d/clientst0r-office-ca.conf'
        self.assertIn('NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/clientst0r-office-ca.crt',
                      drop.read_text())
        self.assertIn('update-ca-certificates', self.stub_log())

    def test_ca_file_with_private_key_refused(self):
        bad = self.tmp / 'bad.pem'
        bad.write_text('-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n')
        p = self.run_script(*self.OO_ARGS, '--ca-file', str(bad), '--dry-run')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('contains a private key', self.out)

    def test_import_file_root_only(self):
        self.install_onlyoffice()
        f = self.root / 'var/lib/clientst0r-office-import/import-docs.example.com.env'
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        text = f.read_text()
        self.assertIn(f'SECRET={self.secret()}', text)
        self.assertIn('PROVIDER=onlyoffice', text)
        self.assertIn('BROWSER_URL=https://docs.example.com/', text)
        self.assertIn('CALLBACK_URL=https://app.example.com/', text)

    def test_nginx_failure_rolls_back_site(self):
        p = self.run_script(*self.OO_ARGS, '--accept-mscorefonts-eula', env={'STUB_NGINX_T': '1'})
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.root / 'etc/nginx/sites-available/clientst0r-office-docs.example.com.conf').exists())
        self.assertNotIn('systemctl reload nginx', self.stub_log())

    def test_eula_must_be_accepted_explicitly(self):
        p = self.run_script(*self.OO_ARGS)
        self.assertEqual(p.returncode, 3, self.out)
        self.assertIn('--accept-mscorefonts-eula', self.out)

    def test_collabora_code_install(self):
        p = self.run_script('--provider', 'collabora-code', '--mode', 'separate-server',
                            '--hostname', 'docs.example.com', '--clientstor-url', 'https://app.example.com',
                            key=CO_KEY)
        self.assertEqual(p.returncode, 0, self.out)
        import xml.etree.ElementTree as ET
        root = ET.parse(self.root / 'etc/coolwsd/coolwsd.xml').getroot()
        groups = root.find('storage/wopi/alias_groups')
        self.assertEqual(groups.get('mode'), 'groups')
        self.assertEqual([h.text for h in groups.findall('group/host')], ['https://app.example.com:443'])
        self.assertEqual(root.find('net/content_security_policy').text, 'frame-ancestors https://app.example.com;')
        self.assertEqual(root.findall('net/lok_allow/host'), [])
        self.assertEqual([h.text for h in root.findall('net/post_allow/host')],
                         ['127.0.0.1/32', '::1/128', '192.0.2.10/32'])
        self.assertEqual(root.find('ssl/enable').text, 'false')
        self.assertEqual(root.find('ssl/termination').text, 'true')
        self.assertEqual(root.find('net/listen').text, 'loopback')
        self.assertEqual(root.find('security/enable_macros_execution').text, 'false')
        self.assertEqual(root.find('admin_console/enable').text, 'false')
        self.assertIn('coolconfig generate-proof-key', self.stub_log())
        pref = (self.root / 'etc/apt/preferences.d/clientst0r-office-collabora-code.pref').read_text()
        self.assertIn('Package: coolwsd\nPin: version 26.04.6.1-1', pref)
        self.assertIn('Package: code-brand\nPin: version 26.04.6-1', pref)
        src = (self.root / 'etc/apt/sources.list.d/clientst0r-office-collabora-code.sources').read_text()
        self.assertIn('Signed-By: /etc/apt/keyrings/clientst0r-office-collabora-code.gpg', src)
        site = (self.root / 'etc/nginx/sites-available/clientst0r-office-docs.example.com.conf').read_text()
        self.assertIn('location ^~ /cool/', site)
        self.assertIn('evaluation and testing, not production', self.out)

    def test_collabora_online_needs_root_only_repo_file(self):
        url = self.tmp / 'repo-url'
        url.write_text('https://customer.example/repo/secret-key/\n')
        url.chmod(0o644)
        p = self.run_script('--provider', 'collabora-online', '--mode', 'separate-server',
                            '--hostname', 'docs.example.com', '--clientstor-url', 'https://app.example.com',
                            '--version', '26.04.5.3-1', '--brand-version', '26.04.5-1',
                            '--repo-url-file', str(url), '--dry-run', key=CO_KEY)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('chmod 600', self.out)


class UpgradeUninstallTests(InstallerHarness):

    def test_uninstall_leaves_documents_and_clientstor(self):
        self.install_onlyoffice()
        self.installed.write_text('nginx 1.24.0\nonlyoffice-documentserver 10.0.0-169\n')
        p = self.run_script('--uninstall')
        self.assertEqual(p.returncode, 0, self.out)
        self.assertIn("never touches clientst0r's documents, versions", self.out)
        self.assertEqual((self.docs / 'r1.docx').read_bytes(), b'PK document')
        self.assertTrue((self.app / '.env').exists())
        self.assertEqual(self.cs_site.read_text(), self.cs_site_text)
        self.assertTrue((self.root / 'etc/nginx/sites-enabled/clientst0r').is_symlink())
        self.assertFalse((self.root / 'etc/nginx/sites-available/clientst0r-office-docs.example.com.conf').exists())
        self.assertFalse((self.root / 'etc/apt/preferences.d/clientst0r-office-onlyoffice.pref').exists())
        self.assertTrue((self.root / 'etc/clientst0r-office/secret').exists())   # kept without --purge-state
        log = self.stub_log()
        self.assertIn('apt-get remove -y -q onlyoffice-documentserver', log)
        self.assertNotIn('media', log)

    def test_uninstall_dry_run_changes_nothing(self):
        self.install_onlyoffice()
        before = self.files_under_root()
        p = self.run_script('--uninstall', '--dry-run', '--purge-state')
        self.assertEqual(p.returncode, 0, self.out)
        self.assertEqual(self.files_under_root(), before)

    def test_uninstall_without_record_refuses(self):
        p = self.run_script('--uninstall')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('No install record', self.out)

    def test_upgrade_requires_drain_confirmation(self):
        self.install_onlyoffice()
        self.log.write_text('')
        p = self.run_script('--upgrade', '--version', '10.0.2-5')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('DRAIN FIRST', self.out)
        self.assertIn('--confirm-drained', self.out)
        self.assertNotIn('apt-get', self.stub_log())

    def test_upgrade_moves_pin_explicitly(self):
        self.install_onlyoffice()
        self.installed.write_text('nginx 1.24.0\nonlyoffice-documentserver 10.0.0-169\n')
        secret = self.secret()
        p = self.run_script('--upgrade', '--version', '10.0.2-5', '--confirm-drained')
        self.assertEqual(p.returncode, 0, self.out)
        pref = (self.root / 'etc/apt/preferences.d/clientst0r-office-onlyoffice.pref').read_text()
        self.assertIn('Pin: version 10.0.2-5', pref)
        log = self.stub_log()
        self.assertIn('apt-mark unhold onlyoffice-documentserver', log)
        self.assertIn('onlyoffice-documentserver=10.0.2-5', log)
        self.assertEqual(self.secret(), secret)
        self.assertNotIn(secret, self.out)

    def test_upgrade_refuses_downgrade(self):
        self.install_onlyoffice()
        self.installed.write_text('onlyoffice-documentserver 10.0.0-169\n')
        p = self.run_script('--upgrade', '--version', '10.0.0-169', '--confirm-drained')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('only moves forward', self.out)


@unittest.skipUnless(shutil.which('shellcheck'), 'shellcheck is not installed')
class ShellcheckTests(SimpleTestCase):
    def test_installer_is_shellcheck_clean(self):
        p = subprocess.run(['shellcheck', '-x', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)


class SyntaxTests(SimpleTestCase):
    def test_bash_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)

    def test_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
