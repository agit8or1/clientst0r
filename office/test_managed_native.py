"""The native (no Docker) Collabora runtime (COLLABORA_RUNTIME=native).

Same harness as office/test_managed_collabora_helper.py: the real helper runs
in a subprocess in test mode. On its PATH are fakes for apt-get, apt-mark,
dpkg-query, systemctl (with a tiny unit state), journalctl, setpriv, adduser,
nft, nginx and openssl. The package step (clientst0r-office-native.service,
`clientst0r-office-helper native-run`) runs in-process in test mode after the
fake `systemctl start`. Nothing here installs a package or starts coolwsd:
see docs/office/MANAGED_LOCAL.md, "Native runtime" (not run on a real host).
"""
import json
import os
import subprocess
import sys

from django.test import SimpleTestCase

from . import test_managed_collabora_helper as cool
from .test_managed_helper import HELPER

NEW = '26.04.6.1-1-code-deb'
OLD = '26.04.5.2-1-code-deb'

# A cut-down coolwsd.xml in the package's shape (comments included).
COOLWSD_XML = """<?xml version="1.0"?>
<config>
    <!-- vendor comment kept -->
    <server_name desc="External hostname" type="string" default=""></server_name>
    <num_prespawn_children type="uint" default="4">4</num_prespawn_children>
    <allow_update_popup type="bool" default="true">true</allow_update_popup>
    <logging>
        <color type="bool">true</color>
        <level type="string" default="warning">warning</level>
        <level_startup type="string" default="trace">trace</level_startup>
        <file enable="false"><property name="path">/var/log/coolwsd.log</property></file>
    </logging>
    <net>
      <proto type="string" default="all">all</proto>
      <listen type="string" default="any">any</listen>
      <content_security_policy></content_security_policy>
    </net>
    <ssl><enable type="bool" default="true">true</enable><termination type="bool">false</termination></ssl>
    <storage><wopi allow="true"><alias_groups mode="first"><!-- example --></alias_groups></wopi></storage>
    <admin_console><enable type="bool" default="true">true</enable><username></username><password></password></admin_console>
    <security><enable_macros_execution type="bool">false</enable_macros_execution></security>
</config>
"""

SECRET_TOKEN = 'TOPSECRETWOPITOKEN123'


class NativeHarness(cool.CoolHarness):
    """A prod-like host without Docker: Collabora only, native runtime,
    same-host first, TLS terminated upstream."""

    conf = dict(cool.CoolHarness.conf, ENGINES='collabora', PROXY_LAYOUTS='same-host,dedicated',
                COLLABORA_RUNTIME='native')

    def setUp(self):
        super().setUp()
        root = self.root
        (root / 'dpkg').mkdir()
        # Collabora's repository, as the installer leaves it.
        for rel in ('etc/apt/sources.list.d/clientst0r-office-managed-collabora.sources',
                    'etc/apt/keyrings/clientst0r-office-managed-collabora.gpg'):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text('x')
        (root / 'coolwsd.xml.pkg').write_text(COOLWSD_XML)
        # docker must not be needed: make any call fail loudly
        self._stub('docker', f'echo "$@" >> "{root}/docker-native.log"; exit 1')
        self._stub('apt-get', '\n'.join([
            f'echo "$@" >> "{root}/apt.log"',
            'case "$1" in',
            '  install)',
            '    sim=0; for a; do [ "$a" = -s ] && sim=1; done',
            '    for a; do case "$a" in',
            '      coolwsd=*|code-brand=*) v="${a#*=}"; n="${a%%=*}"',
            '        if [ -n "${STUB_APT_FAIL_VERSION:-}" ] && [ "$v" = "$STUB_APT_FAIL_VERSION" ]; then',
            '          echo "E: Version $v for $n was not found" >&2; exit 100; fi',
            f'        [ $sim = 1 ] || printf "%s" "$v" > "{root}/dpkg/$n" ;;',
            '    esac; done',
            f'    if [ $sim = 0 ] && [ ! -f "{root}/etc/coolwsd/coolwsd.xml" ]; then',
            f'      mkdir -p "{root}/etc/coolwsd"; cp "{root}/coolwsd.xml.pkg" "{root}/etc/coolwsd/coolwsd.xml"; fi ;;',
            '  remove)',
            f'    for a; do case "$a" in coolwsd|code-brand) rm -f "{root}/dpkg/$a" ;; esac; done ;;',
            'esac',
            'exit 0']))
        self._stub('apt-mark', f'echo "$@" >> "{root}/apt-mark.log"')
        self._stub('dpkg-query', '\n'.join([
            'for a; do pkg="$a"; done',
            'case "$pkg" in',
            f'  "collaboraoffice*") [ -f "{root}/dpkg/coolwsd" ] || exit 1',
            '     printf "collaboraoffice install ok installed\\ncollaboraofficebasis-core install ok installed\\n" ;;',
            f'  *) [ -f "{root}/dpkg/$pkg" ] || exit 1; printf "install ok installed|%s" "$(cat "{root}/dpkg/$pkg")" ;;',
            'esac']))
        self._stub('systemctl', '\n'.join([
            f'echo "$@" >> "{root}/systemctl.log"',
            f'state="{root}/coolwsd.state"',
            'case "$1" in',
            '  start|restart) [ "$2" != coolwsd.service ] || echo active > "$state" ;;',
            '  stop) [ "$2" != coolwsd.service ] || echo inactive > "$state" ;;',
            '  disable) [ "$2" != --now ] || echo inactive > "$state" ;;',
            '  show) a=inactive; [ -f "$state" ] && a="$(cat "$state")"',
            '        printf "ActiveState=%s\\nSubState=running\\nResult=success\\nNRestarts=0\\n" "$a"',
            '        printf "MemoryCurrent=314572800\\nTasksCurrent=12\\nCPUUsageNSec=1000\\nUnitFileState=enabled\\n" ;;',
            'esac',
            'exit 0']))
        self._stub('journalctl', f'echo "$@" >> "{root}/journalctl.log"\n'
                                 f'echo "2026-11-13T10:00:00 coolwsd[1]: GET /cool/x?access_token={SECRET_TOKEN}&v=1"\n'
                                 'echo "2026-11-13T10:00:01 coolwsd[1]: ready"')
        self._stub('setpriv', f'echo "$@" >> "{root}/setpriv.log"; echo "CONNECTION ESTABLISHED"; '
                              'echo "Verification: OK"')
        self._stub('adduser', f'echo "$@" >> "{root}/adduser.log"')

    def env(self, **extra):
        return super().env(**dict({'CLIENTST0R_OFFICE_HELPER_TEST_COOL_UID': '999'}, **extra))

    def path(self, rel):
        return self.root / rel

    def pretend_installed(self, release_id, coolwsd, brand):
        """An earlier native install of release_id (packages present, running)."""
        (self.root / 'dpkg/coolwsd').write_text(coolwsd)
        (self.root / 'dpkg/code-brand').write_text(brand)
        (self.root / 'etc/coolwsd').mkdir(parents=True, exist_ok=True)
        (self.root / 'etc/coolwsd/coolwsd.xml').write_text(COOLWSD_XML)
        (self.root / 'coolwsd.state').write_text('active\n')
        state = self.root / 'var/lib/clientst0r-office/state'
        state.mkdir(parents=True, exist_ok=True)
        (state / 'installed.json').write_text(json.dumps({
            'state': 'installed', 'engine': 'collabora', 'runtime': 'native', 'release': release_id,
            'version': '26.04.5.2.1', 'digest': '', 'edition': 'code',
            'packages': {'coolwsd': coolwsd, 'code-brand': brand}}))


class NativeConfigTests(NativeHarness):

    def test_runtime_values(self):
        self.write_conf(COLLABORA_RUNTIME='podman')
        reply = self.request({'op': 'status', 'args': {}})
        self.assertFalse(reply['ok'])
        self.assertIn('COLLABORA_RUNTIME', reply['error'])

    def test_status_without_docker(self):
        reply = self.request({'op': 'status', 'args': {}})
        self.assertTrue(reply['ok'], reply)
        st = reply['result']
        self.assertEqual(st['runtime'], 'native')
        self.assertEqual(st['config']['runtime'], 'native')
        self.assertEqual(st['config']['collabora_runtime'], 'native')
        self.assertFalse(st['docker']['used'])
        self.assertEqual(st['container']['state'], 'not installed')
        self.assertFalse(self.path('docker-native.log').exists(), 'native status must not run docker')

    def test_docker_releases_are_refused_for_native(self):
        reply = self.request({'op': 'releases', 'args': {}})
        rels = {r['id']: r for r in reply['result']['releases']}
        self.assertIn('runtime', rels['26.04.6.1.1-code']['problem'])
        self.assertEqual(rels[NEW]['problem'], '')
        self.assertEqual(rels[NEW]['packages'], {'coolwsd': '26.04.6.1-1', 'code-brand': '26.04.6-1'})
        self.assertEqual(rels[NEW]['runtime'], 'native')

    def test_untested_gate_applies(self):
        self.write_conf(ALLOW_UNTESTED_RELEASES='no')
        j = self.install_cool()
        self.assertEqual(j['state'], 'failed')
        self.assertIn('live verification', j['error'])
        self.assertFalse(self.path('apt.log').exists())


class NativeInstallTests(NativeHarness):

    def test_install_pins_holds_configures_and_starts(self):
        j = self.install_cool()
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertEqual(j['result']['runtime'], 'native')
        inst = self.installed()
        self.assertEqual((inst['runtime'], inst['release'], inst['state']), ('native', NEW, 'installed'))
        self.assertEqual(inst['packages'], {'coolwsd': '26.04.6.1-1', 'code-brand': '26.04.6-1'})
        apt = self.calls('apt')
        self.assertIn('coolwsd=26.04.6.1-1 code-brand=26.04.6-1', apt)
        self.assertIn('--no-install-recommends', apt)
        self.assertIn('Dpkg::Options::=--force-confold', apt)
        self.assertIn('hold coolwsd code-brand collaboraoffice collaboraofficebasis-core',
                      self.calls('apt-mark'))
        pref = self.path('etc/apt/preferences.d/clientst0r-office-managed-collabora').read_text()
        self.assertIn('Package: coolwsd\nPin: version 26.04.6.1-1\nPin-Priority: 1001', pref)
        self.assertIn('Package: code-brand\nPin: version 26.04.6-1\nPin-Priority: 1001', pref)
        self.assertIn('Pin: origin "www.collaboraoffice.com"\nPin-Priority: 100', pref)
        # The package cannot start coolwsd before it is configured.
        sysctl = self.calls('systemctl').splitlines()
        mask = sysctl.index('mask --runtime coolwsd.service')
        unmask = sysctl.index('unmask --runtime coolwsd.service')
        self.assertLess(mask, unmask)
        self.assertIn('start clientst0r-office-native.service', sysctl)
        self.assertIn('restart coolwsd.service', sysctl[unmask:])
        # The drop-in: loopback port, limits, hardening, no NoNewPrivileges.
        dropin = self.path('etc/systemd/system/coolwsd.service.d/clientst0r-office.conf').read_text()
        self.assertIn('ExecStart=\nExecStart=/usr/bin/coolwsd --version '
                      '--o:sys_template_path=/opt/cool/systemplate', dropin)
        self.assertIn('--port=9981 --o:net.listen=loopback --o:ssl.enable=false --o:ssl.termination=true',
                      dropin)
        for line in ('MemoryMax=1536M', 'MemorySwapMax=0', 'CPUQuota=150%', 'TasksMax=2048',
                     'ProtectKernelModules=yes', 'LockPersonality=yes'):
            self.assertIn(line + '\n', dropin)
        self.assertNotIn('NoNewPrivileges', dropin)
        # coolwsd.xml: what the container gets, through an XML edit.
        xml = self.path('etc/coolwsd/coolwsd.xml').read_text()
        self.assertIn('<!-- vendor comment kept -->', xml)
        for frag in ('<server_name desc="External hostname" type="string" default="">docs.acme.example</server_name>',
                     '<listen type="string" default="any">loopback</listen>',
                     '<proto type="string" default="all">IPv4</proto>',
                     '<content_security_policy>frame-ancestors https://docs.acme.example</content_security_policy>',
                     '<alias_groups mode="groups">', '<host allow="true">https://docs.acme.example:443</host>',
                     '<termination type="bool">true</termination>',
                     '<enable type="bool" default="true">false</enable></admin_console>'.replace(
                         '</admin_console>', '<username />'),
                     '<enable_macros_execution type="bool">false</enable_macros_execution>',
                     '<num_prespawn_children type="uint" default="4">1</num_prespawn_children>',
                     '<level_startup type="string" default="trace">warning</level_startup>',
                     '<allow_update_popup type="bool" default="true">false</allow_update_popup>'):
            self.assertIn(frag, xml)
        self.assertEqual(xml.count('<group>'), 1)
        # Proof key: generated and kept root-only, a copy for coolwsd.
        master = self.path('var/lib/clientst0r-office/collabora/proof_key')
        copy = self.path('etc/coolwsd/proof_key')
        self.assertEqual(master.read_text(), copy.read_text())
        self.assertEqual(copy.stat().st_mode & 0o777, 0o400)
        self.assertEqual(master.stat().st_mode & 0o777, 0o400)
        # Firewall: by owner, HTTPS to the upstream device only.
        rules = self.path('nft.in').read_text()
        self.assertIn('chain output {', rules)
        self.assertIn('meta skuid 999 ip daddr { 203.0.113.7 } tcp dport 443 accept', rules)
        self.assertIn('meta skuid 999 oifname "lo" udp dport 53 accept', rules)
        self.assertIn('meta skuid 999 oifname "lo" tcp dport 9981 accept', rules)
        self.assertTrue(rules.rstrip().endswith('meta skuid 999 drop\n    }\n}'.rstrip()))
        # One-shot request: consumed; no Docker anywhere.
        self.assertFalse(self.path('var/lib/clientst0r-office/state/native-request.json').exists())
        self.assertFalse(self.path('docker-native.log').exists())
        st = self.request({'op': 'status', 'args': {}})['result']
        self.assertTrue(st['container']['running'])
        self.assertEqual(st['container']['release_label'], NEW)
        self.assertEqual(st['installed']['runtime'], 'native')
        self.assertEqual(st['resources']['memory'], '300MiB / 1536MiB')

    def test_cool_user_is_created_first_when_missing(self):
        j = self.install_cool(CLIENTST0R_OFFICE_HELPER_TEST_COOL_UID='')
        # Without the user the configuration step cannot chown: the install fails
        # cleanly, but adduser ran before apt and the runtime mask was lifted.
        self.assertEqual(self.calls('adduser').strip(),
                         '--quiet --system --group --home /opt/cool cool')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('unmask --runtime coolwsd.service', self.calls('systemctl'))

    def test_foreign_coolwsd_is_not_taken_over(self):
        (self.root / 'dpkg/coolwsd').write_text('25.04.1-1')
        pre = self.request({'op': 'preflight', 'args': {'engine': 'collabora'}})['result']
        checks = {c['key']: c for c in pre['checks']}
        self.assertEqual(checks['packages']['status'], 'fail')
        self.assertNotIn('docker', checks)
        self.assertNotIn('subnet', checks)
        j = self.install_cool()
        self.assertEqual(j['state'], 'failed')
        self.assertIn('not by this helper', j['error'])
        self.assertFalse(self.path('apt.log').exists())

    def test_preflight_needs_the_repository(self):
        pre = self.request({'op': 'preflight', 'args': {'engine': 'collabora'}})['result']
        checks = {c['key']: c for c in pre['checks']}
        self.assertEqual(checks['repository']['status'], 'pass')
        self.assertEqual(pre['runtime'], 'native')
        self.path('etc/apt/sources.list.d/clientst0r-office-managed-collabora.sources').unlink()
        pre = self.request({'op': 'preflight', 'args': {'engine': 'collabora'}})['result']
        self.assertEqual({c['key']: c for c in pre['checks']}['repository']['status'], 'fail')
        j = self.install_cool()
        self.assertEqual(j['state'], 'failed')
        self.assertIn('repository is not set up', j['error'])


class NativeLifecycleTests(NativeHarness):

    def setUp(self):
        super().setUp()
        j = self.install_cool()
        self.assertEqual(j['state'], 'succeeded', j)
        for name in ('apt', 'apt-mark', 'systemctl'):
            p = self.path(f'{name}.log')
            if p.exists():
                p.unlink()

    def test_stop_start_restart(self):
        self.assertEqual(self.run_op('stop')['state'], 'succeeded')
        self.assertEqual(self.path('coolwsd.state').read_text().strip(), 'inactive')
        self.assertEqual(self.run_op('start')['state'], 'succeeded')
        self.assertEqual(self.run_op('restart')['state'], 'succeeded')
        calls = self.calls('systemctl')
        self.assertIn('stop coolwsd.service', calls)
        self.assertIn('start coolwsd.service', calls)
        self.assertEqual(self.calls('apt'), '', 'start/stop never touch packages')
        self.assertFalse(self.path('docker-native.log').exists())

    def test_logs_come_from_the_journal_redacted(self):
        reply = self.request({'op': 'logs', 'args': {'lines': 50}})
        self.assertTrue(reply['ok'], reply)
        self.assertNotIn(SECRET_TOKEN, reply['result']['log'])
        self.assertIn('access_token=[redacted]', reply['result']['log'])
        self.assertIn('--unit=coolwsd.service --lines=50 --no-pager', self.calls('journalctl'))

    def test_callback_check_runs_as_the_cool_user(self):
        reply = self.request({'op': 'callback-check', 'args': {}})
        self.assertTrue(reply['ok'], reply)
        r = reply['result']
        self.assertTrue(r['ok'])
        self.assertEqual((r['runtime'], r['target']), ('native', '203.0.113.7:443'))
        self.assertIn('as user cool', r['from'])
        self.assertIn('--reuid=999 --regid=999 --clear-groups -- openssl s_client -connect '
                      'docs.acme.example:443 -servername docs.acme.example -verify_hostname '
                      'docs.acme.example -verify_return_error', self.calls('setpriv'))

    def test_set_layout_rewrites_server_name_and_restarts(self):
        j = self.run_op('set-layout', {'layout': 'dedicated'})
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertTrue(j['result']['recreated'])
        xml = self.path('etc/coolwsd/coolwsd.xml').read_text()
        self.assertIn('>office.acme.example</server_name>', xml)
        self.assertIn('restart coolwsd.service', self.calls('systemctl'))

    def test_uninstall_removes_packages_keeps_data(self):
        j = self.run_op('uninstall')
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertEqual(j['result']['runtime'], 'native')
        self.assertIn('remove -y -q coolwsd code-brand', self.calls('apt'))
        self.assertIn('unhold coolwsd code-brand', self.calls('apt-mark'))
        self.assertIn('disable --now coolwsd.service', self.calls('systemctl'))
        self.assertFalse(self.path('etc/systemd/system/coolwsd.service.d/clientst0r-office.conf').exists())
        self.assertTrue(self.path('var/lib/clientst0r-office/collabora/proof_key').exists())
        self.assertEqual(self.installed()['state'], 'uninstalled')
        st = self.request({'op': 'status', 'args': {}})['result']
        self.assertFalse(st['container']['exists'])

    def test_update_to_a_docker_release_is_refused(self):
        j = self.run_op('update', {'release': '26.04.6.1.1-code'})
        self.assertEqual(j['state'], 'failed')
        self.assertIn('runtime', j['error'])
        self.assertEqual(self.calls('apt'), '')


class NativeUpdateTests(NativeHarness):

    def setUp(self):
        super().setUp()
        self.pretend_installed(OLD, '26.04.5.2-1', '26.04.5-3')

    def test_update_checks_first_then_installs_and_can_roll_back(self):
        j = self.run_op('update', {'release': NEW})
        self.assertEqual(j['state'], 'succeeded', j)
        apt = self.calls('apt').splitlines()
        sim = [n for n, line in enumerate(apt) if line.startswith('install -s ')]
        real = [n for n, line in enumerate(apt) if line.startswith('install -y ')]
        self.assertTrue(sim and real and sim[0] < real[0], apt)
        self.assertIn('coolwsd=26.04.6.1-1 code-brand=26.04.6-1', apt[real[0]])
        calls = self.calls('systemctl').splitlines()
        self.assertLess(calls.index('start clientst0r-office-native.service'),
                        calls.index('stop coolwsd.service'), 'the availability check runs before downtime')
        inst = self.installed()
        self.assertEqual((inst['release'], inst['previous_release']), (NEW, OLD))
        self.assertTrue(inst['previous_backup'])
        manifest = json.loads((self.root / 'var/lib/clientst0r-office/backups' / inst['previous_backup']
                               / 'manifest.json').read_text())
        self.assertEqual((manifest['runtime'], manifest['release']), ('native', OLD))

        j = self.run_op('rollback')
        self.assertEqual(j['state'], 'succeeded', j)
        self.assertIn('coolwsd=26.04.5.2-1 code-brand=26.04.5-3', self.calls('apt'))
        self.assertIn('--allow-downgrades', self.calls('apt'))
        self.assertEqual(self.installed()['release'], OLD)

    def test_unavailable_version_fails_before_downtime(self):
        j = self.run_op('update', {'release': NEW}, STUB_APT_FAIL_VERSION='26.04.6.1-1')
        self.assertEqual(j['state'], 'failed')
        self.assertIn('was not found', j['error'])
        self.assertNotIn('stop coolwsd.service', self.calls('systemctl'))
        self.assertEqual(self.installed()['release'], OLD)


class NativeRunTests(NativeHarness):
    """`native-run` (the unit's ExecStart) trusts nothing in its request."""

    def native_run(self, request):
        state = self.root / 'var/lib/clientst0r-office/state'
        state.mkdir(parents=True, exist_ok=True)
        (state / 'native-request.json').write_text(json.dumps(request))
        if (state / 'native-result.json').exists():
            (state / 'native-result.json').unlink()
        r = subprocess.run([sys.executable, '-I', str(HELPER), 'native-run'], env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertFalse((state / 'native-request.json').exists(), 'a request is used once')
        res = state / 'native-result.json'
        return r.returncode, (json.loads(res.read_text()) if res.exists() else None)

    def test_bad_requests_are_refused(self):
        rid = 'a' * 16
        for req in ({'id': rid, 'action': 'exec', 'release': NEW, 'at': 'x'},
                    {'id': rid, 'action': 'install', 'release': '26.04.6.1.1-code', 'at': 'x'},
                    {'id': rid, 'action': 'install', 'release': '../../etc', 'at': 'x'},
                    {'id': rid, 'action': 'install', 'release': ['x'], 'at': 'x'}):
            rc, res = self.native_run(req)
            self.assertEqual(rc, 1, req)
            self.assertFalse(res['ok'])
            self.assertIn('refused', res['error'])
        for req in ({'id': 'zz', 'action': 'check', 'release': NEW, 'at': 'x'},
                    {'id': rid, 'action': 'check', 'release': NEW, 'at': 'x', 'packages': 'evil=1'}):
            rc, res = self.native_run(req)
            self.assertEqual((rc, res), (1, None), req)
        self.assertFalse(self.path('apt.log').exists())

    def test_check_simulates_only(self):
        rc, res = self.native_run({'id': 'b' * 16, 'action': 'check', 'release': NEW, 'at': 'x'})
        self.assertEqual(rc, 0, res)
        self.assertTrue(res['ok'])
        self.assertIn('install -s ', self.calls('apt'))
        self.assertFalse(self.path('dpkg/coolwsd').exists())


class NativeHelperModuleTests(SimpleTestCase):

    def test_native_release_list(self):
        mod = cool.load_helper_module()
        for r in mod.NATIVE_RELEASES:
            self.assertEqual((r['engine'], r['runtime'], r['edition']), ('collabora', 'native', 'code'))
            self.assertFalse(r['tested'], 'no native release has run on a real host yet')
            self.assertTrue(mod.RELEASE_RE.match(r['id']), r['id'])
            self.assertEqual(set(r['packages']), {'coolwsd', 'code-brand'})
            for v in r['packages'].values():
                self.assertTrue(mod.NATIVE_VERSION_RE.match(v), v)
        for r in mod.RELEASES + mod.COLLABORA_RELEASES:
            self.assertTrue(mod.RELEASE_RE.match(r['id']), r['id'])
            self.assertEqual(r['runtime'], 'docker')

    def test_dropin_cpu_and_memory(self):
        mod = cool.load_helper_module()
        text = mod.render_dropin({'cool_bind_port': 9990, 'cool_memory_mb': 2048, 'cool_cpus': 0.75})
        self.assertIn('MemoryMax=2048M\n', text)
        self.assertIn('CPUQuota=75%\n', text)
        self.assertIn('--port=9990 ', text)

    def test_unit_files(self):
        from .test_managed_helper import HELPER as H
        base = H.parent
        native = (base / 'clientst0r-office-native.service').read_text()
        self.assertIn('ExecStart=/usr/local/sbin/clientst0r-office-helper native-run\n', native)
        self.assertIn('Type=oneshot', native)
        self.assertNotIn('[Install]', native, 'only the helper starts it')
        fw = (base / 'clientst0r-office-firewall.service').read_text()
        self.assertIn('Before=docker.service coolwsd.service', fw)
        self.assertTrue(os.access(H, os.R_OK))
