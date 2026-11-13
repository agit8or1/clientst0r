"""Managed local editor, second engine (Collabora CODE) and the reverse
proxy: the clientst0r side.

``EngineHelper`` extends test_managed.FakeHelper (the helper's socket
protocol) with the engine/layout/proxy verbs and a small state model:
uninstall marks the installation uninstalled, install installs the engine
it is given, set-layout moves the browser address. The helper program itself
is tested in office/test_managed_collabora_helper.py.
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from office import tests as core
from office.managed import checks as managed_checks
from office.managed import ipc, jobs, provision
from office.models import EditorInstance, ManagedOfficeOperation, ManagedOfficeService, OfficeSettings

from .test_managed import APP, BROWSER, SECRET, FakeHelper, ManagedBase

APP_HOST = APP.split('//')[1]
COOL_INTERNAL = 'http://127.0.0.1:9981/'


def cool_config(layout='dedicated'):
    browser = (APP if layout == 'same-host' else BROWSER) + '/'
    return {'engine': 'collabora', 'layout': layout, 'browser_url': browser,
            'internal_url': COOL_INTERNAL, 'engine_memory_mb': 1536, 'engine_cpus': 1.5}


class EngineHelper(FakeHelper):
    def __init__(self):
        super().__init__()
        conf = dict(self.status['config'], engines=['onlyoffice', 'collabora'],
                    layouts=['dedicated', 'same-host'], engine='onlyoffice', layout='dedicated',
                    engine_layouts={'onlyoffice': ['dedicated'], 'collabora': ['dedicated', 'same-host']},
                    engine_memory_mb=4096, engine_cpus=2, proxy_tls='upstream')
        self.status['config'] = conf
        self.status['installed'] = dict(self.status['installed'], engine='onlyoffice')
        self.status['capacity'] = {
            'host': {'cpus': 4, 'mem_total_mb': 7168, 'mem_available_mb': 4096, 'swap_mb': 0},
            'onlyoffice': {'verdict': 'fail', 'memory_limit_mb': 4096, 'cpus': 2, 'checks': [
                {'key': 'memory_available', 'status': 'fail', 'detail': 'only 0 MB would be left'}],
                'recommendation': 'ONLYOFFICE Docs does not fit next to clientst0r on this server'},
            'collabora': {'verdict': 'warn', 'memory_limit_mb': 1536, 'cpus': 1.5, 'checks': [
                {'key': 'swap', 'status': 'warn', 'detail': 'no swap'}],
                'recommendation': 'Collabora CODE fits with little headroom'}}
        self.recreated = True
        self.proxy_installs = []

    def answer(self, req):
        op, args = req.get('op'), req.get('args') or {}
        if op == 'proxy-status':
            conf = self.status['config']
            host = conf['browser_url'].split('//')[1].strip('/')
            return {'ok': True, 'result': {
                'engine': conf['engine'], 'layout': conf['layout'], 'hostname': host, 'tls': 'upstream',
                'layouts_allowed': conf['engine_layouts'][conf['engine']], 'installed': True,
                'problem': '', 'files': {'site': {'path': '/etc/nginx/sites-available/clientst0r-office-managed'},
                                         'snippet': {'path': '/etc/nginx/clientst0r-office/same-host.conf'}},
                'sites': [], 'clientstor_site': {'path': '/etc/nginx/sites-available/itdocs.conf',
                                                 'includes_snippet': False},
                'include_line': 'include /etc/nginx/clientst0r-office/same-host.conf;',
                'include_needed': conf['layout'] == 'same-host', 'include_present': False,
                'dns': {'editor': ['203.0.113.7'], 'clientstor': ['203.0.113.7'], 'points_here': True},
                'certificate': {'detail': 'TLS ends upstream'},
                'preview': {'site': '# site', 'snippet': '# snippet'}}}
        if op == 'proxy-install':
            self.proxy_installs.append(args.get('hostname'))
            return {'ok': True, 'result': {'layout': self.status['config']['layout'], 'note': ''}}
        if op == 'proxy-remove':
            return {'ok': True, 'result': {}}
        if op == 'callback-check':
            return {'ok': True, 'result': {'ok': True, 'target': '203.0.113.7:443', 'route': 'upstream',
                                           'detail': 'TLS verified to ' + APP_HOST}}
        reply = super().answer(req)
        if reply.get('accepted') and self.final_state == 'succeeded':
            self.apply(op, args)
        return reply

    def apply(self, op, args):
        inst = self.status['installed']
        conf = self.status['config']
        if op == 'uninstall':
            self.status['installed'] = dict(inst, state='uninstalled')
            self.status['container'] = {'exists': False}
        elif op == 'install':
            engine = args.get('engine') or inst.get('engine') or 'onlyoffice'
            self.status['installed'] = dict(inst, state='installed', engine=engine,
                                            release='26.04.5.2.1-code' if engine == 'collabora'
                                            else '10.0.0-community')
            if engine == 'collabora':
                conf.update(cool_config(conf.get('layout') if conf.get('layout') == 'same-host' else 'dedicated'))
            self.status['container'] = {'exists': True, 'running': True, 'state': 'running', 'health': 'healthy'}
        elif op == 'set-layout':
            conf.update(cool_config(args['layout']))
            hop = self.status['operation']
            hop['result'] = {'recreated': self.recreated, 'layout': args['layout']}

    def collabora(self, layout='dedicated'):
        self.status['config'].update(cool_config(layout))
        self.status['installed'] = dict(self.status['installed'], engine='collabora',
                                        release='26.04.5.2.1-code', state='installed')


def healthy():
    return mock.patch('office.diagnostics.run_health_check',
                      side_effect=lambda inst, **kw: _mark_ok(inst))


def _mark_ok(inst):
    EditorInstance.objects.filter(pk=inst.pk).update(health_status='ok')
    return SimpleNamespace(status='ok', detail='ok')


def cool_round_trip_ok():
    steps = [SimpleNamespace(key=k, label=k, status='pass', detail='')
             for k in ('create', 'session', 'discovery', 'wopi_checkfileinfo', 'wopi_getfile')]
    steps.append(SimpleNamespace(key='edit_in_browser', label='edit', status='not_run', detail=''))
    return mock.patch('office.diagnostics.run_round_trip', return_value=SimpleNamespace(steps=steps))


class EngineBase(ManagedBase):
    def setUp(self):
        super().setUp()
        self.helper.close()
        self.helper = EngineHelper()
        self.addCleanup(self.helper.close)
        o = override_settings(OFFICE_MANAGED_SOCKET=self.helper.path, ALLOWED_HOSTS=[APP_HOST, 'testserver'])
        o.enable()
        self.addCleanup(o.disable)

    def run_engine_op(self, action, slices=8, **kw):
        op = jobs.enqueue(action, user=self.su, **kw)
        for _ in range(slices):
            jobs.run_pending()
            op.refresh_from_db()
            if not op.is_active:
                break
        return op


# ---------------------------------------------------------------------------
# IPC vocabulary for the new verbs
# ---------------------------------------------------------------------------

class EngineIpcTests(EngineBase):
    def test_engine_layout_and_hostname_are_validated_before_sending(self):
        bad = (('install', {'engine': 'docker'}), ('install', {'engine': 'collabora', 'image': 'x'}),
               ('install', {'engine': ['collabora']}), ('set-layout', {'layout': 'path'}),
               ('set-layout', {'layout': 'same-host; reboot'}), ('set-layout', None))
        for op, args in bad:
            with self.assertRaises(ValueError, msg=(op, args)):
                ipc.submit(op, args)
        for args in ({'hostname': 'office.acme.example;rm -rf /'}, {'hostname': '../etc/passwd'},
                     {'hostname': 'office.acme.example', 'root': '/etc'}, {'hostname': 'a' * 300},
                     {'hostname': '-x.example'}, {'hostname': 'office acme'}, {}):
            with self.assertRaises(ValueError, msg=args):
                ipc.call('proxy-install', args)
        for args in ({'engine': 'x'}, {'x': 1}):
            with self.assertRaises(ValueError, msg=args):
                ipc.call('preflight', args)
        with self.assertRaises(ValueError):
            ipc.call('proxy-remove', {'path': '/etc/nginx/sites-enabled/itdocs.conf'})
        with self.assertRaises(ValueError):
            ipc.call('callback-check', {'url': 'https://evil.example/'})
        self.assertEqual(self.helper.requests, [])

    def test_valid_requests_pass(self):
        ipc.submit('install', {'engine': 'collabora'})
        ipc.call('proxy-install', {'hostname': 'office.acme.example'})
        ipc.call('preflight', {'engine': 'collabora'})
        self.assertEqual([r['op'] for r in self.helper.requests], ['install', 'proxy-install', 'preflight'])


# ---------------------------------------------------------------------------
# Provisioning the Collabora provider
# ---------------------------------------------------------------------------

class CollaboraProvisionTests(EngineBase):
    def test_configures_the_collabora_instance_and_closes_the_other(self):
        oo = self.managed()
        settings_obj = OfficeSettings.get()
        settings_obj.default_instance = oo
        settings_obj.save()
        self.helper.collabora()
        before = len(self.helper.requests)
        with healthy():
            inst, result = provision.configure(self.helper.status, user=self.su)
        self.assertEqual((inst.provider, inst.mode), ('collabora', 'managed_local'))
        self.assertEqual(inst.browser_url, BROWSER + '/')
        self.assertEqual(inst.internal_url, COOL_INTERNAL)
        self.assertEqual(inst.callback_base_url, APP + '/')
        self.assertTrue(inst.provider_options.get('require_proof'))
        self.assertTrue(inst.verify_tls)
        self.assertFalse(inst.ca_bundle)
        self.assertTrue(inst.shared_secret)
        self.assertNotEqual(inst.shared_secret, SECRET, 'the ONLYOFFICE JWT is never reused')
        self.assertNotIn('secret', [r['op'] for r in self.helper.requests[before:]],
                         'Collabora needs no secret from the helper')
        service = ManagedOfficeService.get()
        self.assertEqual((service.instance_id, service.engine), (inst.pk, 'collabora'))
        oo.refresh_from_db()
        self.assertFalse(oo.enabled)
        settings_obj.refresh_from_db()
        self.assertEqual(settings_obj.default_instance_id, inst.pk, 'default followed the engine switch')
        self.assertIn('collabora', settings_obj.enabled_providers)
        placeholder = inst.shared_secret
        with healthy():
            again, _ = provision.configure(self.helper.status, user=self.su)
        self.assertEqual(again.pk, inst.pk)
        self.assertEqual(again.shared_secret, placeholder, 'kept, not regenerated each time')
        blob = json.dumps(list(AuditLog.objects.values('description', 'extra_data')), default=str)
        self.assertNotIn(placeholder, blob)

    def test_an_external_default_is_not_taken_over(self):
        external = EditorInstance.objects.create(
            provider='collabora', name='Licensed Collabora Online', mode='separate_server',
            browser_url='https://cool.partner.example/', shared_secret='x' * 40, enabled=True)
        settings_obj = OfficeSettings.get()
        settings_obj.default_instance = external
        settings_obj.save()
        self.helper.collabora()
        with healthy():
            inst, _ = provision.configure(self.helper.status, user=self.su)
        settings_obj.refresh_from_db()
        self.assertEqual(settings_obj.default_instance_id, external.pk)
        external.refresh_from_db()
        self.assertTrue(external.enabled, 'external instances are never closed by the managed service')

    def test_same_origin_only_for_collabora_same_host(self):
        self.helper.collabora('same-host')
        urls = provision.urls_from_status(self.helper.status)
        self.assertEqual(urls['browser_url'], APP + '/')
        oo = dict(self.helper.status, installed=dict(self.helper.status['installed'], engine='onlyoffice'),
                  config=dict(self.helper.status['config'], engine='onlyoffice', layout='dedicated'))
        with self.assertRaises(provision.ProvisionError):
            provision.urls_from_status(oo)
        wrong = dict(self.helper.status, config=dict(self.helper.status['config'], layout='same-host',
                                                     browser_url=BROWSER + '/'))
        with self.assertRaises(provision.ProvisionError):
            provision.urls_from_status(wrong)
        dedicated_same = dict(self.helper.status, config=dict(self.helper.status['config'],
                                                              layout='dedicated'))
        with self.assertRaises(provision.ProvisionError):
            provision.urls_from_status(dedicated_same)

    def test_unknown_engine_is_refused(self):
        status = dict(self.helper.status, installed=dict(self.helper.status['installed'], engine='other'))
        with self.assertRaises(provision.ProvisionError):
            provision.configure(status)


# ---------------------------------------------------------------------------
# Jobs: engine switch and layout switch
# ---------------------------------------------------------------------------

class EngineSwitchJobTests(EngineBase):
    def test_switch_drains_uninstalls_installs_and_verifies(self):
        oo = self.managed()
        jobs.refresh_status()
        with healthy(), cool_round_trip_ok():
            op = self.run_engine_op('switch_engine', engine='collabora')
        self.assertEqual(op.state, 'succeeded', op.error)
        ops = [r for r in self.helper.requests if r['op'] in ipc.ASYNC_OPS]
        self.assertEqual([(r['op'], r.get('args')) for r in ops],
                         [('uninstall', {}), ('install', {'engine': 'collabora'})])
        cool = provision.managed_instance()
        self.assertEqual(cool.provider, 'collabora')
        self.assertTrue(cool.enabled)
        oo.refresh_from_db()
        self.assertFalse(oo.enabled)
        self.assertEqual(ManagedOfficeService.get().engine, 'collabora')
        self.assertTrue(AuditLog.objects.filter(description__contains='Switch').exists()
                        or AuditLog.objects.filter(extra_data__action='switch_engine').exists())

    def test_switch_waits_for_open_edits(self):
        oo = self.managed()
        jobs.refresh_status()
        t, s, page = self.setup_doc(instance=oo)
        op = jobs.enqueue('switch_engine', user=self.su, engine='collabora')
        with override_settings(OFFICE_MANAGED_SLICE_SECONDS=0.3):
            jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'draining')
        self.assertNotIn('uninstall', self.helper.ops(), 'never uninstalled before the drain is verified')
        self.assertFalse(EditorInstance.objects.get(pk=oo.pk).enabled)

    def test_unknown_session_state_postpones_the_switch(self):
        oo = self.managed()
        jobs.refresh_status()
        self.setup_doc(instance=oo)
        self.ds.reachable = False
        with override_settings(OFFICE_MANAGED_DRAIN_SECONDS=0):
            op = self.run_engine_op('switch_engine', engine='collabora')
        self.assertEqual(op.state, 'postponed')
        self.assertNotIn('uninstall', self.helper.ops())
        self.assertNotIn('install', self.helper.ops())

    def test_failed_install_leaves_both_closed(self):
        oo = self.managed()
        jobs.refresh_status()
        op = jobs.enqueue('switch_engine', user=self.su, engine='collabora')
        # Uninstall succeeds, then the install fails on the server.
        orig = self.helper.answer

        def answer(req):
            if req.get('op') == 'install':
                self.helper.final_state, self.helper.final_error = 'failed', 'capacity: does not fit'
            return orig(req)
        self.helper.answer = answer
        for _ in range(8):
            jobs.run_pending()
            op.refresh_from_db()
            if not op.is_active:
                break
        self.assertEqual(op.state, 'failed')
        self.assertIn('capacity', op.error)
        oo.refresh_from_db()
        self.assertFalse(oo.enabled)

    def test_enqueue_validates(self):
        with self.assertRaises(ValueError):
            jobs.enqueue('switch_engine', user=self.su, engine='docker')
        with self.assertRaises(ValueError):
            jobs.enqueue('set_layout', user=self.su, layout='path')


class LayoutJobTests(EngineBase):
    def cool(self, layout='dedicated'):
        self.helper.collabora(layout)
        jobs.refresh_status()
        with healthy():
            inst, _ = provision.configure(self.helper.status, user=self.su)
        EditorInstance.objects.filter(pk=inst.pk).update(enabled=True)
        return inst

    def test_switch_to_same_host_updates_the_browser_address(self):
        inst = self.cool('dedicated')
        with healthy(), cool_round_trip_ok():
            op = self.run_engine_op('set_layout', layout='same-host')
        self.assertEqual(op.state, 'succeeded', op.error)
        self.assertIn({'op': 'set-layout', 'args': {'layout': 'same-host'}}, self.helper.requests)
        inst.refresh_from_db()
        self.assertEqual(inst.browser_url, APP + '/')
        self.assertTrue(inst.enabled)
        self.assertNotIn('uninstall', self.helper.ops(), 'no reinstall')
        self.assertNotIn('install', self.helper.ops())
        # ... and back to the dedicated name.
        with healthy(), cool_round_trip_ok():
            op = self.run_engine_op('set_layout', layout='dedicated')
        self.assertEqual(op.state, 'succeeded', op.error)
        inst.refresh_from_db()
        self.assertEqual(inst.browser_url, BROWSER + '/')

    def test_not_running_editor_only_saves_the_layout(self):
        self.cool('dedicated')
        self.helper.recreated = False
        op = self.run_engine_op('set_layout', layout='same-host')
        self.assertEqual(op.state, 'succeeded', op.error)
        self.assertIn('Start', op.result.get('note', ''))


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=core.TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EngineViewTests(EngineBase):
    POSTS = (('office:managed_engine', {'engine': 'collabora', 'confirm': 'switch'}),
             ('office:managed_layout', {'layout': 'same-host', 'accept_same_host': '1'}),
             ('office:managed_proxy', {'action': 'install', 'hostname': 'office.acme.example'}),
             ('office:managed_proxy', {'action': 'remove', 'confirm': 'remove'}),
             ('office:managed_probe_result', {'outcome': 'reached'}))

    def setUp(self):
        super().setUp()
        jobs.refresh_status()
        self.client.force_login(self.su)

    def test_non_superusers_are_turned_away(self):
        from accounts.models import UserType
        from django.contrib.auth.models import User
        staff = User.objects.create_user('msp-tech2', 't2@example.com', 'x', is_staff=True)
        staff.profile.user_type = UserType.STAFF
        staff.profile.save()
        for user in (None, self.editor, self.owner, self.reader, self.outsider, staff):
            c = Client()
            if user is not None:
                c.force_login(user)
            for name, data in self.POSTS:
                r = c.post(reverse(name), data)
                self.assertIn(r.status_code, (302, 403), (user, name))
                if r.status_code == 302:
                    self.assertIn('login', r['Location'])
        self.assertFalse(ManagedOfficeOperation.objects.exists())
        self.assertEqual(self.helper.proxy_installs, [])
        self.assertNotIn('proxy-remove', self.helper.ops())
        self.assertFalse(AuditLog.objects.filter(extra_data__office_event='browser_probe').exists())

    def test_csrf_is_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.su)
        for name, data in self.POSTS:
            self.assertEqual(c.post(reverse(name), data).status_code, 403, name)
        self.assertFalse(ManagedOfficeOperation.objects.exists())

    def test_engine_switch_needs_typed_confirmation(self):
        self.managed()
        jobs.refresh_status()
        self.client.post(reverse('office:managed_engine'), {'engine': 'collabora'})
        self.assertFalse(ManagedOfficeOperation.objects.exists())
        self.client.post(reverse('office:managed_engine'), {'engine': 'docker', 'confirm': 'switch'})
        self.assertFalse(ManagedOfficeOperation.objects.exists())
        self.client.post(reverse('office:managed_engine'), {'engine': 'collabora', 'confirm': 'switch'})
        op = ManagedOfficeOperation.objects.get()
        self.assertEqual((op.action, op.target_engine), ('switch_engine', 'collabora'))

    def test_engine_not_allowed_by_root_config_is_refused(self):
        self.helper.status['config']['engines'] = ['onlyoffice']
        jobs.refresh_status()
        self.client.post(reverse('office:managed_engine'), {'engine': 'collabora', 'confirm': 'switch'})
        self.assertFalse(ManagedOfficeOperation.objects.exists())

    def test_engine_choice_without_install_is_saved(self):
        self.helper.status['installed'] = {'state': 'uninstalled'}
        jobs.refresh_status()
        self.client.post(reverse('office:managed_engine'), {'engine': 'collabora'})
        self.assertEqual(ManagedOfficeService.get().engine, 'collabora')
        self.assertFalse(ManagedOfficeOperation.objects.exists())

    def test_same_host_needs_the_acknowledgement(self):
        self.helper.collabora('dedicated')
        jobs.refresh_status()
        self.client.post(reverse('office:managed_layout'), {'layout': 'same-host'})
        self.assertFalse(ManagedOfficeOperation.objects.exists())
        self.assertIsNone(ManagedOfficeService.get().same_host_acknowledged_at)
        self.client.post(reverse('office:managed_layout'), {'layout': 'same-host', 'accept_same_host': '1'})
        op = ManagedOfficeOperation.objects.get()
        self.assertEqual((op.action, op.target_layout), ('set_layout', 'same-host'))
        service = ManagedOfficeService.get()
        self.assertEqual(service.same_host_acknowledged_by, self.su)
        self.assertTrue(AuditLog.objects.filter(description__contains='same-host layout warning').exists())

    def test_same_host_is_refused_for_onlyoffice(self):
        self.client.post(reverse('office:managed_layout'), {'layout': 'same-host', 'accept_same_host': '1'})
        self.assertFalse(ManagedOfficeOperation.objects.exists())

    def test_proxy_install_checks_the_host_name(self):
        self.helper.collabora('dedicated')
        jobs.refresh_status()
        for host in ('evil.example', APP_HOST, 'office.acme.example;id', ''):
            self.client.post(reverse('office:managed_proxy'), {'action': 'install', 'hostname': host})
        self.assertEqual(self.helper.proxy_installs, [])
        self.client.post(reverse('office:managed_proxy'), {'action': 'install', 'hostname': 'office.acme.example'})
        self.assertEqual(self.helper.proxy_installs, ['office.acme.example'])
        self.assertTrue(AuditLog.objects.filter(description__contains='Installed the editor proxy').exists())

    def test_same_host_proxy_needs_allowed_hosts(self):
        self.helper.collabora('same-host')
        jobs.refresh_status()
        with override_settings(ALLOWED_HOSTS=['other.example', 'testserver']):
            self.client.post(reverse('office:managed_proxy'), {'action': 'install', 'hostname': APP_HOST})
        self.assertEqual(self.helper.proxy_installs, [])
        self.client.post(reverse('office:managed_proxy'), {'action': 'install', 'hostname': APP_HOST})
        self.assertEqual(self.helper.proxy_installs, [APP_HOST])

    def test_proxy_remove_needs_confirmation_and_no_active_operation(self):
        self.client.post(reverse('office:managed_proxy'), {'action': 'remove'})
        self.assertNotIn('proxy-remove', self.helper.ops())
        jobs.enqueue('restart', user=self.su)
        self.client.post(reverse('office:managed_proxy'), {'action': 'remove', 'confirm': 'remove'})
        self.assertNotIn('proxy-remove', self.helper.ops())
        ManagedOfficeOperation.objects.update(state='succeeded')
        self.client.post(reverse('office:managed_proxy'), {'action': 'remove', 'confirm': 'remove'})
        self.assertIn('proxy-remove', self.helper.ops())

    def test_probe_result_is_audited_and_validated(self):
        r = self.client.post(reverse('office:managed_probe_result'), {'outcome': 'pwned'})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse('office:managed_probe_result'), {'outcome': 'reached'})
        self.assertEqual(r.json(), {'ok': True})
        entry = AuditLog.objects.get(extra_data__office_event='browser_probe')
        self.assertEqual(entry.extra_data['outcome'], 'reached')
        self.assertTrue(entry.extra_data['url'].endswith('/healthcheck'))

    def test_page_shows_capacity_engine_proxy_and_the_code_label(self):
        self.helper.collabora('same-host')
        jobs.refresh_status()
        with healthy():
            provision.configure(self.helper.status, user=self.su)
        r = self.client.get(reverse('office:managed'))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('evaluation / development', body)
        self.assertIn('does not fit', body)                       # ONLYOFFICE on this host
        self.assertIn('Collabora CODE fits with little headroom', body)
        self.assertIn('1536 MB memory, 1.5 CPU', body)
        self.assertIn('include /etc/nginx/clientst0r-office/same-host.conf;', body)
        self.assertIn('Same host as clientst0r.', body)
        self.assertIn('Cookie and Authorization headers are stripped', body)
        self.assertIn('managed-probe-config', body)
        self.assertIn('/hosting/capabilities', body)
        self.assertIn('--provider collabora', body)
        self.assertIn('--tls upstream', body)
        self.assertIn('connect-src', r.get('Content-Security-Policy', '') or 'connect-src')
        self.assertNotIn(SECRET, body)
        self.assertNotIn('onclick=', body)


# ---------------------------------------------------------------------------
# Setup checks
# ---------------------------------------------------------------------------

class EngineChecksTests(EngineBase):
    def test_capacity_proxy_and_callback_checks_appear(self):
        self.helper.collabora('same-host')
        jobs.refresh_status()
        with healthy():
            provision.configure(self.helper.status, user=self.su)
        results = managed_checks.run(ManagedOfficeService.get())
        text = json.dumps([[getattr(c, 'key', ''), getattr(c, 'label', ''), getattr(c, 'status', ''),
                            getattr(c, 'detail', '')] for c in results], default=str)
        self.assertIn({'op': 'preflight', 'args': {'engine': 'collabora'}}, self.helper.requests)
        self.assertIn('proxy-status', self.helper.ops())
        self.assertIn('callback-check', self.helper.ops())
        self.assertIn('include', text.lower())
        self.assertIn('Collabora CODE fits with little headroom', text)
        self.assertIn('203.0.113.7:443 (upstream): verified TLS', text)

    def test_browser_probe_result_is_shown(self):
        self.helper.collabora('dedicated')
        jobs.refresh_status()
        results = managed_checks.run(ManagedOfficeService.get())
        probe = [c for c in results if c.key == 'browser']
        self.assertTrue(probe)
        AuditLog.objects.create(action='update', object_type='office.managed', object_id=1,
                                extra_data={'office_event': 'browser_probe', 'outcome': 'reached'},
                                timestamp=timezone.now())
        results = managed_checks.run(ManagedOfficeService.get())
        probe = [c for c in results if c.key == 'browser']
        self.assertEqual(probe[0].status, 'pass')


class EngineCommandTests(EngineBase):
    def call(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('office_managed', *args, stdout=out)
        return out.getvalue()

    def test_queue_switch_engine_and_layout(self):
        from django.core.management.base import CommandError
        self.call('--queue', 'switch_engine', '--engine', 'collabora', '--user', self.su.username)
        op = ManagedOfficeOperation.objects.get()
        self.assertEqual((op.action, op.target_engine, op.requested_by), ('switch_engine', 'collabora', self.su))
        ManagedOfficeOperation.objects.update(state='succeeded')
        with self.assertRaises(CommandError):
            self.call('--queue', 'set_layout', '--layout', 'same-host', '--user', self.su.username)
        with self.assertRaises(CommandError):
            self.call('--queue', 'set_layout', '--layout', 'same-host', '--accept-same-host')
        self.assertEqual(ManagedOfficeOperation.objects.count(), 1)
        self.call('--queue', 'set_layout', '--layout', 'same-host', '--accept-same-host',
                  '--user', self.su.username)
        self.assertEqual(ManagedOfficeService.get().same_host_acknowledged_by, self.su)
        self.assertTrue(ManagedOfficeOperation.objects.filter(action='set_layout',
                                                              target_layout='same-host').exists())
