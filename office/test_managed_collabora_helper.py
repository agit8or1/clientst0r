"""deploy/office-helper/clientst0r-office-helper: the Collabora (CODE) engine,
engine switching, the address layouts (dedicated host name / same host),
the Nginx files the helper manages, capacity refusals and the callback check.

Same harness as office/test_managed_helper.py: the real helper runs in a
subprocess in test mode with fake docker, nft, ip, nginx, systemctl and
openssl on its PATH. Nothing here runs Docker, Nginx or Collabora.
"""
import json
import os
from pathlib import Path

from django.test import SimpleTestCase

from .test_managed_helper import HELPER, HelperHarness

COOL_OLD = 'sha256:c7415b963e32eb0986a562583f154d36d3d7a461e1ddfb660a95e87094328acb'
COOL_NEW = 'sha256:95f29f1c0a1778999125f53f058d968fe0afb37c95e32ebfb9f3444140faebd2'

# Shaped like production's existing site (TLS terminated in front, port 80,
# catch-all server name). The helper must never change it.
ITDOCS = """upstream itdocs_app {
    server unix:/home/administrator/gunicorn.sock fail_timeout=0;
}

server {
    listen 80;
    server_name _;
    add_header X-Frame-Options "DENY" always;
    location / {
        proxy_pass http://itdocs_app;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
"""


def load_helper_module():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader('office_helper_cool', str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class CoolHarness(HelperHarness):
    """A prod-like host: Collabora allowed, TLS terminated upstream."""

    conf = {
        'ENGINES': 'onlyoffice,collabora', 'PROXY_LAYOUTS': 'dedicated,same-host',
        'PROXY_TLS': 'upstream', 'CALLBACK_ROUTE': 'upstream', 'CALLBACK_UPSTREAM_IP': '203.0.113.7',
    }

    def setUp(self):
        super().setUp()
        root = self.root
        self._stub('nginx', f'echo "$@" >> "{root}/nginx.log"\n'
                            f'[ "$1" != -t ] || [ ! -f "{root}/nginx-fail" ] || exit 1\nexit 0')
        self._stub('systemctl', f'echo "$@" >> "{root}/systemctl.log"')
        self._stub('openssl', '\n'.join([
            'case "$1" in',
            '  genrsa) out=""; while [ $# -gt 0 ]; do [ "$1" = -out ] && out="$2"; shift; done',
            '          printf -- "-----BEGIN RSA PRIVATE KEY-----\\nfake\\n-----END RSA PRIVATE KEY-----\\n" > "$out" ;;',
            '  version) echo "OpenSSL 3.0.13" ;;',
            f'  x509) for a; do last="$a"; done; if [ -f "{root}/cert-ok" ]; then',
            '          echo "notAfter=Feb  1 00:00:00 2027 GMT"; echo "Certificate will not expire"',
            '          echo "Hostname $last does match certificate"',
            '        else echo "Certificate will expire"; echo "Hostname $last does NOT match certificate"; fi ;;',
            'esac']))
        self.nginx = root / 'etc/nginx'
        (self.nginx / 'sites-available').mkdir(parents=True)
        (self.nginx / 'sites-enabled').mkdir(parents=True)
        (self.nginx / 'sites-available/itdocs.conf').write_text(ITDOCS)
        os.symlink(self.nginx / 'sites-available/itdocs.conf', self.nginx / 'sites-enabled/itdocs.conf')
        # prod-like memory: 7.75 GB total, ~4.6 GB available, no swap
        (root / 'proc' / 'meminfo').write_text(
            'MemTotal:        8131584 kB\nMemAvailable:    4718592 kB\nSwapTotal:   0 kB\n')
        self.write_conf()

    def write_conf(self, **overrides):
        merged = dict(self.conf)
        merged.update(overrides)
        super().write_conf(**merged)

    def site(self):
        return self.nginx / 'sites-available/clientst0r-office-managed'

    def snippet(self):
        return self.nginx / 'clientst0r-office/same-host.conf'

    def compose_text(self):
        return (self.root / 'var/lib/clientst0r-office/compose/collabora.yaml').read_text()

    def calls(self, name):
        p = self.root / f'{name}.log'
        return p.read_text() if p.exists() else ''

    def install_cool(self, **env):
        return self.run_op('install', {'engine': 'collabora'}, **env)


class CoolRequestValidationTests(CoolHarness):

    def test_injection_into_new_verbs_is_refused(self):
        bad = [
            {'op': 'install', 'args': {'engine': 'collabora; rm -rf /'}},
            {'op': 'install', 'args': {'engine': 'docker.io/evil/code'}},
            {'op': 'install', 'args': {'engine': ['collabora']}},
            {'op': 'install', 'args': {'engine': 'collabora', 'image': 'evil:latest'}},
            {'op': 'preflight', 'args': {'engine': '../../etc'}},
            {'op': 'set-layout', 'args': {'layout': 'same-host\nlisten 0.0.0.0:22'}},
            {'op': 'set-layout', 'args': {'layout': 'subpath'}},
            {'op': 'set-layout', 'args': {}},
            {'op': 'set-layout', 'args': {'layout': 'dedicated', 'hostname': 'x.example'}},
            {'op': 'proxy-install', 'args': {}},
            {'op': 'proxy-install', 'args': {'hostname': 'office.acme.example; include /etc/shadow'}},
            {'op': 'proxy-install', 'args': {'hostname': 'office.acme.example', 'path': '/etc/nginx/x'}},
            {'op': 'proxy-install', 'args': {'hostname': '../../etc/passwd'}},
            {'op': 'proxy-install', 'args': {'hostname': 'OFFICE ACME'}},
            {'op': 'proxy-install', 'args': {'hostname': 'a' * 300 + '.example'}},
            {'op': 'proxy-install', 'args': {'hostname': {'x': 1}}},
            {'op': 'proxy-remove', 'args': {'file': 'itdocs.conf'}},
            {'op': 'proxy-status', 'args': {'site': '/etc/nginx/sites-enabled/itdocs.conf'}},
            {'op': 'callback-check', 'args': {'url': 'http://169.254.169.254/'}},
            {'op': 'update', 'args': {'release': '26.04.6.1.1-code; id'}},
            {'op': 'update', 'args': {'release': '99.04.6.1.1-code'}},
        ]
        for payload in bad:
            reply = self.request(payload)
            self.assertFalse(reply.get('ok'), payload)
            self.assertNotIn('result', reply)
        self.assertEqual(self.docker_calls(), [], 'no refused request may reach docker')
        self.assertEqual(self.calls('nginx'), '', 'no refused request may reach nginx')
        self.assertFalse(self.site().exists())
        self.assertEqual((self.nginx / 'sites-available/itdocs.conf').read_text(), ITDOCS)

    def test_proxy_install_refuses_a_host_name_other_than_the_configured_one(self):
        for host in ('evil.example', 'docs.acme.example'):     # dedicated layout serves office.acme.example
            reply = self.request({'op': 'proxy-install', 'args': {'hostname': host}})
            self.assertFalse(reply['ok'], host)
            self.assertIn('serves office.acme.example', reply['error'])
        self.assertFalse(self.site().exists())
        self.assertEqual(self.calls('nginx'), '')


class CoolConfigTests(CoolHarness):

    def assertConfRefused(self, fragment, **overrides):
        self.write_conf(**overrides)
        reply = self.request({'op': 'status', 'args': {}})
        self.assertFalse(reply['ok'], overrides)
        self.assertIn(fragment, reply['error'])

    def test_invalid_engine_layout_tls_and_route_settings(self):
        self.assertConfRefused('ENGINES', ENGINES='collabora,libreoffice')
        self.assertConfRefused('ENGINES', ENGINES='collabora,collabora')
        self.assertConfRefused('Collabora only', ENGINES='onlyoffice', PROXY_LAYOUTS='dedicated,same-host')
        self.assertConfRefused('dedicated host name', PROXY_LAYOUTS='same-host')
        self.assertConfRefused('PROXY_TLS', PROXY_TLS='none')
        self.assertConfRefused('PROXY_CERT_FILE', PROXY_TLS='local-cert', PROXY_CERT_FILE='/home/app/cert.pem')
        self.assertConfRefused('PROXY_CERT_FILE', PROXY_TLS='local-cert',
                               PROXY_CERT_FILE='/etc/ssl/../shadow')
        self.assertConfRefused('PROXY_KEY_FILE', PROXY_TLS='local-cert', PROXY_KEY_FILE='/etc/ssl/k ey')
        self.assertConfRefused('CALLBACK_UPSTREAM_IP', CALLBACK_UPSTREAM_IP=None)
        self.assertConfRefused('CALLBACK_UPSTREAM_IP', CALLBACK_UPSTREAM_IP='127.0.0.1')
        self.assertConfRefused('CALLBACK_UPSTREAM_IP', CALLBACK_UPSTREAM_IP='169.254.169.254')
        self.assertConfRefused('CALLBACK_UPSTREAM_IP', CALLBACK_UPSTREAM_IP='172.31.250.5')
        self.assertConfRefused('CALLBACK_ROUTE', CALLBACK_ROUTE='direct')
        self.assertConfRefused('COLLABORA_MEMORY_MB must be at least', COLLABORA_MEMORY_MB='256')
        self.assertConfRefused('COLLABORA_CPUS', COLLABORA_CPUS='4')
        self.assertConfRefused('COLLABORA_BIND_PORT must differ', COLLABORA_BIND_PORT='8090')

    def test_same_host_only_needs_no_office_host_name(self):
        self.write_conf(ENGINES='collabora', PROXY_LAYOUTS='same-host', OFFICE_HOSTNAME=None)
        reply = self.request({'op': 'status', 'args': {}})
        self.assertTrue(reply['ok'], reply)
        conf = reply['result']['config']
        self.assertEqual(conf['engine'], 'collabora')
        self.assertEqual(conf['layout'], 'same-host')
        self.assertEqual(conf['browser_url'], 'https://docs.acme.example/')
        self.assertEqual(conf['internal_url'], 'http://127.0.0.1:9981/')


class CoolComposeTests(CoolHarness):

    def test_install_writes_a_pinned_restricted_compose_file(self):
        j = self.install_cool()
        self.assertEqual(j['state'], 'succeeded', j)
        text = self.compose_text()
        self.assertIn(f'image: "docker.io/collabora/code@{COOL_NEW}"', text)
        self.assertNotIn(':latest', text)
        self.assertIn('"127.0.0.1:9981:9980"', text)
        self.assertIn('aliasgroup1: "https://docs.acme.example:443"', text)
        self.assertIn('server_name: "office.acme.example"', text)
        self.assertIn('DONT_GEN_SSL_CERT: "1"', text)
        self.assertIn('"--o:net.content_security_policy=frame-ancestors https://docs.acme.example"', text)
        self.assertIn('"--o:admin_console.enable=false"', text)
        self.assertIn('"--o:ssl.termination=true"', text)
        self.assertIn('"--o:storage.wopi.alias_groups[@mode]=groups"', text)
        self.assertIn('mem_limit: 1536m', text)
        self.assertIn('memswap_limit: 1536m', text)
        self.assertIn('cpus: 1.5', text)
        self.assertIn('restart: unless-stopped', text)
        self.assertIn('max-size: "10m"', text)
        self.assertIn('- NET_RAW', text)
        self.assertIn('"docs.acme.example:203.0.113.7"', text)       # upstream callback route
        for forbidden in ('privileged', 'docker.sock', 'network_mode', 'cap_add', 'pid:', '/:/',
                          'password', 'watchtower', 'extra_params'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(self.installed()['engine'], 'collabora')
        self.assertEqual(self.installed()['release'], '26.04.6.1.1-code')

    def test_admin_secret_and_proof_key_are_generated_once_and_root_only(self):
        self.install_cool()
        d = self.root / 'etc/clientst0r/office'
        pw = (d / 'collabora-admin.secret').read_text().strip()
        self.assertGreaterEqual(len(pw), 32)
        self.assertEqual((d / 'collabora-admin.secret').stat().st_mode & 0o777, 0o600)
        self.assertEqual((d / 'collabora.env').stat().st_mode & 0o777, 0o600)
        key = self.root / 'var/lib/clientst0r-office/collabora/proof_key'
        self.assertEqual(key.stat().st_mode & 0o777, 0o400)
        first = key.read_text()
        self.run_op('restart')
        self.assertEqual((d / 'collabora-admin.secret').read_text().strip(), pw)
        self.assertEqual(key.read_text(), first, 'proof key never regenerated')
        self.assertNotIn(pw, self.compose_text())
        self.assertNotIn(pw, json.dumps(self.journal()))
        log = self.request({'op': 'logs', 'args': {'lines': 10}}, FAKE_DOCKER_LOG_SECRET=pw)
        self.assertNotIn(pw, log['result']['log'])
        self.assertIn(['logs', '--tail', '10', '--timestamps', 'clientst0r-office-cool'], self.docker_calls())

    def test_upstream_route_firewall_allows_only_the_tls_device_on_443(self):
        self.install_cool()
        rules = (self.root / 'nft.in').read_text()
        self.assertIn('iifname "cs0office0" ip daddr 203.0.113.7 tcp dport 443 accept', rules)
        self.assertNotIn('172.31.250.1 tcp dport 443', rules)
        self.assertEqual(rules.count('iifname "cs0office0" drop'), 2)

    def test_stop_has_no_vendor_exec_and_uses_the_cool_project(self):
        self.install_cool()
        j = self.run_op('stop')
        self.assertEqual(j['state'], 'succeeded', j)
        calls = self.docker_calls()
        self.assertFalse(any(c[:1] == ['exec'] for c in calls))
        stop = [c for c in calls if c[:1] == ['compose'] and 'stop' in c]
        self.assertEqual(stop[0][2], 'clientst0r-office-cool')

    def test_update_and_rollback_within_the_code_releases(self):
        state = self.root / 'var/lib/clientst0r-office/state'
        state.mkdir(parents=True, exist_ok=True)
        (state / 'installed.json').write_text(json.dumps(
            {'engine': 'collabora', 'release': '26.04.5.2.1-code', 'state': 'installing'}))
        self.assertEqual(self.install_cool()['state'], 'succeeded')
        self.assertIn(COOL_OLD, self.world()['container']['image'])
        reply = self.request({'op': 'status', 'args': {}})
        self.assertEqual([u['id'] for u in reply['result']['update_available']], ['26.04.6.1.1-code'])
        j = self.run_op('update', {'release': '26.04.6.1.1-code'})
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertIn(COOL_NEW, self.world()['container']['image'])
        self.assertEqual(self.installed()['previous_release'], '26.04.5.2.1-code')
        j = self.run_op('rollback')
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertIn(COOL_OLD, self.world()['container']['image'])

    def test_an_onlyoffice_release_is_not_an_update_for_collabora(self):
        self.install_cool()
        j = self.run_op('update', {'release': '10.0.0-community'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('other engine', j['error'])


class EngineSwitchTests(CoolHarness):

    def setUp(self):
        super().setUp()
        (self.root / 'proc' / 'meminfo').write_text(
            'MemTotal:        8131584 kB\nMemAvailable:    7340032 kB\nSwapTotal:   2097152 kB\n')

    def test_one_engine_at_a_time_and_switching_keeps_records(self):
        self.assertEqual(self.run_op('install', {'engine': 'onlyoffice'})['state'], 'succeeded')
        (self.root / 'var/lib/clientst0r-office/data/lib/working.bin').write_text('x')
        j = self.install_cool()
        self.assertEqual(j['state'], 'failed')
        self.assertIn('Uninstall it first', j['error'])
        self.assertIn('documentserver', self.world()['container']['image'])
        self.assertEqual(self.run_op('uninstall')['state'], 'succeeded')
        j = self.install_cool()
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertEqual(self.world()['container']['name'], 'clientst0r-office-cool')
        self.assertTrue((self.root / 'var/lib/clientst0r-office/data/lib/working.bin').exists())
        kept = json.loads((self.root / 'var/lib/clientst0r-office/state/installed-onlyoffice.json')
                          .read_text())
        self.assertEqual(kept['release'], '10.0.0-community')
        status = self.request({'op': 'status', 'args': {}})['result']
        self.assertEqual(status['engine'], 'collabora')
        self.assertEqual(status['config']['internal_url'], 'http://127.0.0.1:9981/')
        # and back again
        self.assertEqual(self.run_op('uninstall')['state'], 'succeeded')
        self.assertEqual(self.run_op('install', {'engine': 'onlyoffice'})['state'], 'succeeded')
        self.assertEqual(self.installed()['release'], '10.0.0-community')

    def test_engine_not_listed_in_root_config_is_refused(self):
        self.write_conf(ENGINES='onlyoffice', PROXY_LAYOUTS='dedicated')
        j = self.install_cool()
        self.assertEqual(j['state'], 'failed')
        self.assertIn('not listed in ENGINES', j['error'])


class CapacityTests(CoolHarness):

    def test_prod_like_host_fits_code_but_not_onlyoffice(self):
        cap = self.request({'op': 'status', 'args': {}})['result']['capacity']
        self.assertEqual(cap['onlyoffice']['verdict'], 'fail')
        self.assertIn('separate VM', cap['onlyoffice']['recommendation'])
        self.assertIn(cap['collabora']['verdict'], ('pass', 'warn'))
        self.assertTrue(any(c['key'] == 'swap' and c['status'] == 'warn' for c in cap['collabora']['checks']))
        j = self.run_op('install', {'engine': 'onlyoffice'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('starve', j['error'])
        self.assertFalse(any(c[:1] == ['pull'] for c in self.docker_calls()))
        self.assertEqual(self.install_cool()['state'], 'succeeded')

    def test_code_is_refused_when_too_little_memory_is_available(self):
        (self.root / 'proc' / 'meminfo').write_text(
            'MemTotal:        8131584 kB\nMemAvailable:    2097152 kB\nSwapTotal:   0 kB\n')
        j = self.install_cool()
        self.assertEqual(j['state'], 'failed')
        self.assertIn('starve', j['error'])

    def test_preflight_for_collabora_reports_capacity_and_tools(self):
        pre = self.request({'op': 'preflight', 'args': {'engine': 'collabora'}})['result']
        keys = {c['key'] for c in pre['checks']}
        for key in ('memory', 'memory_available', 'cpu', 'capacity', 'openssl', 'nginx', 'proxy',
                    'callback', 'release'):
            self.assertIn(key, keys)
        self.assertEqual(pre['engine'], 'collabora')


class ProxyTests(CoolHarness):

    def test_dedicated_upstream_block_is_written_tested_and_reloaded(self):
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertTrue(reply['ok'], reply)
        site = self.site().read_text()
        self.assertTrue(site.startswith('# Managed by clientst0r-office-helper'))
        self.assertIn('server_name office.acme.example;', site)
        self.assertIn('listen 80;', site)
        self.assertNotIn('ssl_certificate', site)          # TLS ends upstream
        self.assertIn('proxy_set_header X-Forwarded-Proto https;', site)
        self.assertTrue((self.nginx / 'sites-enabled/clientst0r-office-managed').is_symlink())
        self.assertEqual(self.snippet().read_text().count('location'), 0)
        nginx, sysd = self.calls('nginx'), self.calls('systemctl')
        self.assertIn('-t', nginx)
        self.assertIn('reload nginx', sysd)
        self.assertEqual((self.nginx / 'sites-available/itdocs.conf').read_text(), ITDOCS)

    def test_collabora_paths_websocket_and_header_stripping(self):
        self.install_cool()
        self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        site = self.site().read_text()
        for needle in ('location ^~ /browser/ {', 'location ^~ /hosting/discovery {',
                       'location ^~ /hosting/capabilities {', 'location ~ ^/cool/(.*/)?ws$ {',
                       'location ~ ^/(cool|lool)/ {', 'proxy_set_header Upgrade $http_upgrade;',
                       'proxy_set_header Connection "Upgrade";', 'proxy_read_timeout 36000s;',
                       'proxy_pass http://127.0.0.1:9981;', 'proxy_set_header Cookie "";',
                       'proxy_set_header Authorization "";', 'proxy_hide_header Set-Cookie;',
                       'access_log off;', 'client_max_body_size 100m;'):
            self.assertIn(needle, site)
        for blocked in ('location ^~ /cool/adminws {', 'location = /cool/getMetrics {',
                        'location ^~ /browser/dist/admin {'):
            self.assertIn(blocked + '\n        return 403;', site)

    def test_onlyoffice_block_keeps_websocket_map(self):
        self.write_conf(ENGINES='onlyoffice', PROXY_LAYOUTS='dedicated')
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertTrue(reply['ok'], reply)
        site = self.site().read_text()
        self.assertIn('map $http_upgrade $clientst0r_office_managed_upgrade', site)
        self.assertIn('proxy_pass http://127.0.0.1:8090;', site)
        self.assertNotIn('/hosting/discovery', site)

    def test_failed_nginx_test_restores_and_does_not_reload(self):
        (self.root / 'nginx-fail').write_text('')
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertFalse(reply['ok'])
        self.assertIn('nginx -t rejected', reply['error'])
        self.assertFalse(self.site().exists())
        self.assertFalse((self.nginx / 'sites-enabled/clientst0r-office-managed').exists())
        self.assertNotIn('reload', self.calls('systemctl'))

    def test_failed_test_on_update_puts_previous_block_back(self):
        self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        before = self.site().read_text()
        self.write_conf(PROXY_MAX_BODY_MB='50')
        (self.root / 'nginx-fail').write_text('')
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertFalse(reply['ok'])
        self.assertEqual(self.site().read_text(), before)

    def test_files_not_written_by_clientst0r_are_never_replaced(self):
        self.site().write_text('server { server_name mine.example; }\n')
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertFalse(reply['ok'])
        self.assertIn('not written by clientst0r', reply['error'])
        self.assertEqual(self.site().read_text(), 'server { server_name mine.example; }\n')

    def test_host_name_served_by_another_site_is_refused(self):
        (self.nginx / 'sites-enabled/other').write_text('server { server_name office.acme.example; }\n')
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertFalse(reply['ok'])
        self.assertIn('already served by other', reply['error'])

    def test_local_certificate_modes(self):
        self.write_conf(PROXY_TLS='letsencrypt', CALLBACK_ROUTE='gateway', CALLBACK_UPSTREAM_IP=None)
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertTrue(reply['ok'], reply)
        site = self.site().read_text()
        self.assertIn('ACME-only', site)              # first run: only the challenge is served
        self.assertNotIn('ssl_certificate', site)
        self.assertNotIn('proxy_pass', site)
        self.write_conf(PROXY_TLS='local-cert', PROXY_CERT_FILE='/etc/ssl/certs/office.pem',
                        PROXY_KEY_FILE='/etc/ssl/private/office.key', CALLBACK_ROUTE='gateway',
                        CALLBACK_UPSTREAM_IP=None)
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertFalse(reply['ok'])
        self.assertIn('/etc/ssl/certs/office.pem is missing', reply['error'])
        self.write_conf(PROXY_TLS='letsencrypt', CALLBACK_ROUTE='gateway', CALLBACK_UPSTREAM_IP=None)
        le = self.root / 'etc/letsencrypt/live/office.acme.example'
        le.mkdir(parents=True)
        (le / 'fullchain.pem').write_text('c')
        (le / 'privkey.pem').write_text('k')
        reply = self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertTrue(reply['ok'], reply)
        site = self.site().read_text()
        self.assertIn('listen 443 ssl;', site)
        self.assertIn('ssl_certificate /etc/letsencrypt/live/office.acme.example/fullchain.pem;', site)
        self.assertIn('return 301 https://$host$request_uri;', site)
        status = self.request({'op': 'proxy-status', 'args': {}})['result']
        self.assertFalse(status['certificate']['ok'])
        (self.root / 'cert-ok').write_text('')
        status = self.request({'op': 'proxy-status', 'args': {}})['result']
        self.assertTrue(status['certificate']['ok'], status['certificate'])

    def test_proxy_status_detects_the_existing_site_without_changing_it(self):
        status = self.request({'op': 'proxy-status', 'args': {}})['result']
        self.assertEqual(status['clientstor_site']['file'], 'itdocs.conf')
        self.assertTrue(status['clientstor_site']['default'])
        self.assertFalse(status['installed'])
        self.assertIn('server_name office.acme.example;', status['preview']['site'])
        self.assertEqual((self.nginx / 'sites-available/itdocs.conf').read_text(), ITDOCS)

    def test_proxy_remove_keeps_an_empty_snippet(self):
        self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        reply = self.request({'op': 'proxy-remove', 'args': {}})
        self.assertTrue(reply['ok'], reply)
        self.assertFalse(self.site().exists())
        self.assertTrue(self.snippet().exists())
        self.assertNotIn('location', self.snippet().read_text())


class LayoutSwitchTests(CoolHarness):

    def test_same_host_layout_snippet_include_and_switch_back(self):
        self.assertEqual(self.install_cool()['state'], 'succeeded')
        self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        self.assertIn('server_name: "office.acme.example"', self.compose_text())
        self.docker_log.write_text('')
        j = self.run_op('set-layout', {'layout': 'same-host'})
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertTrue(j['result']['recreated'])
        self.assertEqual(j['result']['browser_url'], 'https://docs.acme.example/')
        self.assertIn('server_name: "docs.acme.example"', self.compose_text())
        self.assertFalse(self.site().exists(), 'dedicated block removed for the same-host layout')
        snippet = self.snippet().read_text()
        self.assertIn('location ^~ /browser/ {', snippet)
        self.assertIn('proxy_set_header Cookie "";', snippet)
        self.assertIn('WARNING', snippet)
        self.assertNotIn('server {', snippet)
        self.assertEqual((self.nginx / 'sites-available/itdocs.conf').read_text(), ITDOCS)
        # No pull, no uninstall: the container is only re-created.
        calls = self.docker_calls()
        self.assertFalse(any(c[:1] == ['pull'] for c in calls))
        self.assertFalse(any(c[:1] == ['compose'] and 'down' in c for c in calls))
        status = self.request({'op': 'proxy-status', 'args': {}})['result']
        self.assertTrue(status['include_needed'])
        self.assertFalse(status['include_present'])
        self.assertEqual(status['include_line'], 'include /etc/nginx/clientst0r-office/same-host.conf;')
        # The administrator adds the include once; the helper sees it.
        (self.nginx / 'sites-available/itdocs.conf').write_text(ITDOCS.replace(
            '    location / {', '    include /etc/nginx/clientst0r-office/same-host.conf;\n    location / {'))
        status = self.request({'op': 'proxy-status', 'args': {}})['result']
        self.assertTrue(status['include_present'])
        self.assertTrue(status['installed'])
        # switch to the dedicated host name later, data kept
        j = self.run_op('set-layout', {'layout': 'dedicated'})
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertIn('server_name: "office.acme.example"', self.compose_text())
        self.assertTrue(self.site().exists())
        self.assertNotIn('location', self.snippet().read_text(), 'snippet emptied, include still valid')
        self.assertEqual(self.installed()['release'], '26.04.6.1.1-code')

    def test_layout_not_allowed_by_root_config_or_engine(self):
        self.write_conf(PROXY_LAYOUTS='dedicated')
        self.install_cool()
        j = self.run_op('set-layout', {'layout': 'same-host'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('PROXY_LAYOUTS', j['error'])

    def test_onlyoffice_has_no_same_host_layout(self):
        (self.root / 'proc' / 'meminfo').write_text(
            'MemTotal:        8131584 kB\nMemAvailable:    7340032 kB\nSwapTotal:   2097152 kB\n')
        self.run_op('install', {'engine': 'onlyoffice'})
        j = self.run_op('set-layout', {'layout': 'same-host'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('dedicated host name', j['error'])

    def test_failed_proxy_switch_keeps_the_old_layout(self):
        self.install_cool()
        self.request({'op': 'proxy-install', 'args': {'hostname': 'office.acme.example'}})
        (self.root / 'nginx-fail').write_text('')
        j = self.run_op('set-layout', {'layout': 'same-host'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('server_name: "office.acme.example"', self.compose_text())
        self.assertTrue(self.site().exists())
        status = self.request({'op': 'status', 'args': {}})['result']
        self.assertEqual(status['config']['layout'], 'dedicated')


class CallbackCheckTests(CoolHarness):

    def test_callback_check_runs_a_fixed_command_in_the_container(self):
        reply = self.request({'op': 'callback-check', 'args': {}})
        self.assertFalse(reply['ok'])
        self.assertIn('not running', reply['error'])
        self.install_cool()
        reply = self.request({'op': 'callback-check', 'args': {}})
        self.assertTrue(reply['result']['ok'], reply)
        self.assertEqual(reply['result']['target'], '203.0.113.7:443')
        execs = [c for c in self.docker_calls() if c[:1] == ['exec']]
        self.assertEqual(execs[-1][:4], ['exec', 'clientst0r-office-cool', 'openssl', 's_client'])
        self.assertIn('-verify_return_error', execs[-1])
        reply = self.request({'op': 'callback-check', 'args': {}}, FAKE_DOCKER_CALLBACK_RC='1')
        self.assertFalse(reply['result']['ok'])
        self.assertIn('timed out', reply['result']['detail'])


class CoolReleaseListTests(SimpleTestCase):

    def test_code_releases_are_pinned_official_and_untested(self):
        mod = load_helper_module()
        self.assertTrue(mod.COLLABORA_RELEASES)
        for r in mod.COLLABORA_RELEASES:
            self.assertEqual(r['image'], 'docker.io/collabora/code')
            self.assertRegex(r['digest'], r'^sha256:[0-9a-f]{64}$')
            self.assertRegex(r['id'], mod.RELEASE_RE)
            self.assertFalse(r['tested'], 'no CODE release has passed the live checklist yet')
            self.assertEqual(r['engine'], 'collabora')
        conf = {'edition': 'community', 'allow_untested': False, 'engines': ('collabora',)}
        self.assertIn('live verification', mod.release_problem(mod.COLLABORA_RELEASES[0], conf))
        evil = dict(mod.COLLABORA_RELEASES[0], image='docker.io/evil/code')
        self.assertIn('official', mod.release_problem(evil, dict(conf, allow_untested=True)))

    def test_rendered_nginx_text_contains_only_validated_values(self):
        mod = load_helper_module()
        conf = {'cool_bind_port': 9981, 'max_body_mb': 100, 'office_hostname': 'office.acme.example',
                'proxy_tls': 'upstream', 'bind_port': 8090, 'memory_mb': 0, 'cpus': 0,
                'cool_memory_mb': 1536, 'cool_cpus': 1.5}
        text = mod.render_dedicated(conf, 'collabora', 'office.acme.example')
        self.assertEqual(text.count('{'), text.count('}'))
        with self.assertRaises(mod.HelperError):
            mod.render_dedicated(conf, 'collabora', 'office.acme.example;\n}server{')
        snippet = mod.render_snippet(conf)
        self.assertEqual(snippet.count('{'), snippet.count('}'))
        self.assertNotIn('server_name', snippet)
