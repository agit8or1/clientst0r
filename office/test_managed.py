"""Managed Local ONLYOFFICE: the clientst0r side.

* ``FakeHelper`` is a real Unix-socket server speaking the Office service
  helper's protocol (one JSON request per connection; ``{"ok", "result"}``
  for queries, ``{"ok", "accepted", "operation"}`` for lifecycle verbs,
  ``{"ok": false, "busy": true}`` while another operation runs). It is a
  protocol model, not the helper: the helper itself is tested as a program
  in office/test_managed_helper.py.
* ``ManagedDS`` is tests_onlyoffice.FakeDocumentServer (the ONLYOFFICE Docs
  10.0 protocol model) on the managed instance's loopback address, with
  ``getForgottenList`` added. Every URL still passes office.net.check_url.

Nothing here proves that a real container behaves the same; see
docs/office/MANAGED_LOCAL.md, "Live verification".
"""
import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from office import drain, net, sessions
from office import tests as core
from office.managed import ipc, jobs, provision
from office.models import EditorInstance, EditSession, ManagedOfficeOperation, ManagedOfficeService
from office.providers.onlyoffice import state as oo_state
from office.tests_onlyoffice import FakeDocumentServer, OnlyOfficeTestBase, docx_text

SECRET = 'managed-test-secret-0123456789-abcdef'
INTERNAL = 'http://127.0.0.1:8090'
BROWSER = 'https://office.acme.example'
APP = 'https://app.example.com'


def helper_status(**over):
    status = {
        'helper_version': '1.0.0',
        'config': {'deployment_id': 'acme', 'office_hostname': 'office.acme.example',
                   'clientstor_url': APP + '/', 'browser_url': BROWSER + '/',
                   'internal_url': INTERNAL + '/', 'bind_port': 8090, 'edition': 'community',
                   'cpus': 2, 'memory_mb': 4096, 'reserve_mb': 2048, 'subnet': '172.31.250.0/28',
                   'allow_untested': False, 'private_ca': False, 'maintenance_updates': False},
        'docker': {'available': True, 'version': '27.0', 'compose': '2.29', 'detail': ''},
        'installed': {'state': 'installed', 'release': '10.0.0-community', 'version': '10.0.0',
                      'digest': 'sha256:' + 'a' * 64, 'edition': 'community',
                      'previous_release': '', 'previous_backup': ''},
        'container': {'exists': True, 'running': True, 'state': 'running', 'health': 'healthy',
                      'restart_count': 0, 'oom_killed': False},
        'resources': {}, 'data_bytes': 1024, 'operation': {}, 'update_available': [],
        'backups': [], 'secrets_present': True,
    }
    status.update(over)
    return status


class FakeHelper:
    """The helper's socket protocol, served from a thread."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='cs0h')
        self.path = os.path.join(self.dir, 's')
        self.requests = []
        self.status = helper_status()
        self.secret = SECRET
        self.busy = False
        self.final_state = 'succeeded'      # what a submitted operation ends as
        self.final_error = ''
        self.counter = 0
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline(65536)
                try:
                    req = json.loads(line)
                except ValueError:
                    self.wfile.write(b'{"ok": false, "error": "bad request"}\n')
                    return
                fake.requests.append(req)
                self.wfile.write((json.dumps(fake.answer(req)) + '\n').encode())

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        self.server = Server(self.path, Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def answer(self, req):
        op, args = req.get('op'), req.get('args') or {}
        if op == 'status':
            return {'ok': True, 'result': self.status}
        if op == 'secret':
            return {'ok': True, 'result': {'jwt_secret': self.secret}}
        if op == 'preflight':
            return {'ok': True, 'result': {'checks': [{'key': 'os', 'status': 'pass', 'detail': 'ubuntu 24.04'},
                                                      {'key': 'memory', 'status': 'fail', 'detail': 'short'}]}}
        if op == 'logs':
            return {'ok': True, 'result': {'log': 'line one\nline two', 'lines': args.get('lines')}}
        if op in ipc.ASYNC_OPS:
            if self.busy:
                return {'ok': False, 'busy': True, 'error': 'another operation is running'}
            self.counter += 1
            hop = {'id': f'op-{self.counter}', 'op': op, 'args': args, 'state': self.final_state,
                   'step': 'done', 'error': self.final_error, 'result': {}}
            self.status = dict(self.status, operation=hop)
            return {'ok': True, 'accepted': True, 'operation': {'id': hop['id'], 'op': op,
                                                                'state': 'running'}}
        return {'ok': False, 'error': f'unknown op {op}'}

    def ops(self):
        return [r['op'] for r in self.requests]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)


class ManagedDS(FakeDocumentServer):
    """FakeDocumentServer on the managed loopback address; the browser host
    name reaches the same server through the host's reverse proxy."""

    def __init__(self, **kw):
        super().__init__(secret=SECRET, origin=INTERNAL, **kw)
        self.forgotten = []
        self.reachable = True

    def fetch(self, url, instance, max_bytes, **kw):
        net.check_url(url, instance)
        if not self.reachable:
            raise net.OfficeFetchError('connection refused')
        if url.startswith(BROWSER):
            url = INTERNAL + url[len(BROWSER):]
        return super().fetch(url, instance, max_bytes, **kw)

    def _command(self, headers, data):
        body = json.loads(data)
        if body.get('c') == 'getForgottenList':
            self.commands.append(body)
            if not self._inbox_ok(headers, body, 'command'):
                return {'error': 6}
            return {'error': 0, 'keys': list(self.forgotten)}
        return super()._command(headers, data)


FAST = dict(OFFICE_MANAGED_SLICE_SECONDS=3, OFFICE_MANAGED_POLL_SECONDS=0,
            OFFICE_MANAGED_LEASE_SECONDS=300)


class ManagedBase(OnlyOfficeTestBase):
    def setUp(self):
        super().setUp()
        self.helper = FakeHelper()
        self.addCleanup(self.helper.close)
        o = override_settings(OFFICE_MANAGED_SOCKET=self.helper.path, **FAST)
        o.enable()
        self.addCleanup(o.disable)
        self.ds = ManagedDS()
        self.fetch_mock.side_effect = self.ds.fetch
        self.service = ManagedOfficeService.get()
        self.service.enabled = True
        self.service.updated_by = self.su
        self.service.save()

    def managed(self, **kw):
        """The managed instance as provision.configure creates it."""
        inst, result = provision.configure(self.helper.status, user=self.su)
        self.assertEqual(result.status, 'ok', result.detail)
        EditorInstance.objects.filter(pk=inst.pk).update(enabled=True, **kw)
        inst.refresh_from_db()
        return inst

    def run_op(self, action, *, release='', user=None, slices=5):
        op = jobs.enqueue(action, user=user or self.su, release=release)
        for _ in range(slices):
            jobs.run_pending()
            op.refresh_from_db()
            if not op.is_active:
                break
        return op

    def round_trip_ok(self):
        steps = [SimpleNamespace(key=k, label=k, status='pass', detail='')
                 for k in ('create', 'open', 'edit', 'save', 'reopen')]
        steps.append(SimpleNamespace(key='callback', label='callback', status='warn', detail=''))
        return mock.patch('office.diagnostics.run_round_trip', return_value=SimpleNamespace(steps=steps))


# ---------------------------------------------------------------------------
# IPC
# ---------------------------------------------------------------------------

class IpcTests(TestCase):
    def setUp(self):
        self.helper = FakeHelper()
        self.addCleanup(self.helper.close)
        o = override_settings(OFFICE_MANAGED_SOCKET=self.helper.path)
        o.enable()
        self.addCleanup(o.disable)

    def test_query_and_submit(self):
        self.assertEqual(ipc.call('status')['helper_version'], '1.0.0')
        hop = ipc.submit('restart')
        self.assertEqual(hop['op'], 'restart')
        self.assertEqual(self.helper.requests[-1], {'op': 'restart', 'args': {}})

    def test_busy_is_reported(self):
        self.helper.busy = True
        with self.assertRaises(ipc.HelperRefused) as cm:
            ipc.submit('stop')
        self.assertTrue(cm.exception.busy)

    def test_vocabulary_is_fixed_before_anything_is_sent(self):
        for op, args in (('exec', None), ('purge', {'confirm': 'acme'}), ('update', {'release': 1}),
                         ('update', {'release': 'x', 'image': 'evil'}), ('status', {'x': 1}),
                         ('logs', {'lines': '5; id'})):
            with self.assertRaises(ValueError, msg=op):
                (ipc.submit if op in ipc.ASYNC_OPS else ipc.call)(op, args)
        with self.assertRaises(ValueError):
            ipc.call('install')       # lifecycle verbs only through submit
        with self.assertRaises(ValueError):
            ipc.submit('status')
        self.assertEqual(self.helper.requests, [])

    def test_missing_socket_is_unavailable_not_a_crash(self):
        with override_settings(OFFICE_MANAGED_SOCKET=self.helper.path + '-missing'):
            with self.assertRaises(ipc.HelperUnavailable):
                ipc.call('status')

    def test_garbage_reply_is_unavailable(self):
        d = tempfile.mkdtemp(prefix='cs0g')
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, 's')
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)

        def serve():
            conn, _ = srv.accept()
            conn.recv(1000)
            conn.sendall(b'not json')
            conn.close()
            srv.close()
        threading.Thread(target=serve, daemon=True).start()
        with override_settings(OFFICE_MANAGED_SOCKET=path):
            with self.assertRaises(ipc.HelperUnavailable):
                ipc.call('status', timeout=5)


# ---------------------------------------------------------------------------
# The SSRF exception
# ---------------------------------------------------------------------------

class ManagedNetTests(TestCase):
    def inst(self, **kw):
        d = dict(provider='onlyoffice', name='m', mode='managed_local', browser_url=BROWSER + '/',
                 internal_url=INTERNAL + '/', callback_base_url=APP + '/')
        d.update(kw)
        return EditorInstance(**d)

    def test_loopback_only_on_the_managed_ports(self):
        i = self.inst()
        self.assertTrue(net.allowed_fetch(INTERNAL + '/healthcheck', i))
        self.assertTrue(net.ip_allowed('127.0.0.1', i, 8090))
        self.assertTrue(net.ip_allowed('127.0.0.1', i, 443), 'browser host name pinned to loopback')
        for port in (22, 80, 5432, 6379, 8000, 8091, None):
            self.assertFalse(net.ip_allowed('127.0.0.1', i, port), port)
        self.assertFalse(net.ip_allowed('::1', i, 22))

    def test_other_destinations_unchanged(self):
        i = self.inst()
        for url in ('http://127.0.0.1:8000/admin/', 'http://127.0.0.1:22/', 'http://localhost:8090/',
                    'http://169.254.169.254/latest/meta-data/', 'https://evil.example/',
                    'http://127.0.0.1:8090@evil.example/'):
            self.assertFalse(net.allowed_fetch(url, i), url)
        for ip in ('169.254.169.254', 'fd00:ec2::254', '100.100.100.200', '0.0.0.0'):
            self.assertFalse(net.ip_allowed(ip, i, 8090), ip)

    def test_other_modes_unchanged(self):
        same = self.inst(mode='same_server')
        self.assertTrue(net.ip_allowed('127.0.0.1', same, 22), 'same-server rule as before')
        remote = self.inst(mode='separate_server')
        self.assertFalse(net.ip_allowed('127.0.0.1', remote, 8090))


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

class ProvisionTests(ManagedBase):
    def test_configure_creates_one_instance_and_never_logs_the_secret(self):
        with self.assertLogs('office', level='DEBUG') as logs:
            import logging
            logging.getLogger('office').debug('start')
            inst = self.managed()
        self.assertEqual((inst.mode, inst.provider), ('managed_local', 'onlyoffice'))
        self.assertEqual(inst.internal_url, INTERNAL + '/')
        self.assertEqual(inst.browser_url, BROWSER + '/')
        self.assertEqual(inst.callback_base_url, APP + '/')
        self.assertEqual(inst.shared_secret, SECRET)
        self.assertTrue(inst.verify_tls)
        self.assertEqual(ManagedOfficeService.get().instance_id, inst.pk)
        again, _ = provision.configure(self.helper.status, user=self.su)
        self.assertEqual(again.pk, inst.pk)
        self.assertEqual(EditorInstance.objects.filter(mode='managed_local').count(), 1)
        blob = json.dumps(list(AuditLog.objects.values('description', 'extra_data')), default=str)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn(SECRET, '\n'.join(logs.output))

    def test_unusable_secret_or_addresses_are_refused(self):
        self.helper.secret = 'secret'
        with self.assertRaises(provision.ProvisionError):
            provision.configure(self.helper.status)
        self.helper.secret = SECRET
        for key, value in (('internal_url', 'http://10.0.0.5:8090/'), ('browser_url', 'http://office.acme.example/'),
                           ('browser_url', 'https://127.0.0.1/'), ('clientstor_url', 'http://app.example.com/')):
            bad = helper_status()
            bad['config'] = dict(bad['config'], **{key: value})
            with self.assertRaises(provision.ProvisionError, msg=key):
                provision.configure(bad)
        self.assertFalse(EditorInstance.objects.filter(mode='managed_local').exists())

    def test_managed_instance_is_not_editable_in_the_manual_form(self):
        inst = self.managed()
        self.client.force_login(self.su)
        r = self.client.get(reverse('office:instance_edit', args=[inst.pk]))
        self.assertRedirects(r, reverse('office:managed'), fetch_redirect_response=False)
        from office.forms import EditorInstanceForm
        self.assertNotIn('managed_local', dict(EditorInstanceForm().fields['mode'].choices))


# ---------------------------------------------------------------------------
# Editing through the managed instance (the existing provider, unchanged)
# ---------------------------------------------------------------------------

class ManagedEditingTests(ManagedBase):
    def test_save_callback_and_jwt_on_the_managed_instance(self):
        inst = self.managed()
        t, s, page = self.setup_doc(instance=inst)
        self.assertTrue(page.config['docConfig']['document']['url'].startswith(APP + '/'))
        r = self.ds.callback(self.client, s, 6, data=docx_text('forced'))
        self.assertEqual(r.json(), {'error': 0})
        from office import storage
        self.assertEqual(storage.current(t).revision_number, 2)
        # Wrong secret: refused, nothing stored.
        r = self.ds.callback(self.client, s, 6, data=docx_text('evil'), secret='x' * 40)
        self.assertNotEqual(r.json(), {'error': 0})
        self.assertEqual(storage.current(t).revision_number, 2)

    def test_cross_organization_session_cannot_save_into_another_target(self):
        inst = self.managed()
        t1, s1, _ = self.setup_doc(instance=inst)
        t2, s2, _ = self.setup_doc(user=self.outsider, org=self.other_org, instance=inst)
        r = self.ds.callback(self.client, s1, 6, key=self.key(s2), data=docx_text('mix'))
        self.assertNotEqual(r.json(), {'error': 0})
        from office import storage
        self.assertEqual(storage.current(t2).revision_number, 1)


# ---------------------------------------------------------------------------
# Operations: locking, leases, drain, verify
# ---------------------------------------------------------------------------

class OperationLockTests(ManagedBase):
    def test_one_active_operation(self):
        jobs.enqueue('restart', user=self.su)
        with self.assertRaises(jobs.AlreadyActive):
            jobs.enqueue('stop', user=self.su)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ManagedOfficeOperation.objects.create(action='start', state='draining')
        self.assertTrue(AuditLog.objects.filter(object_type='office.managed',
                                                description__contains='Queued').exists())

    def test_finished_operations_do_not_block(self):
        ManagedOfficeOperation.objects.create(action='start', state='failed')
        ManagedOfficeOperation.objects.create(action='start', state='succeeded')
        jobs.enqueue('start', user=self.su)

    def test_cancel_only_while_queued(self):
        op = jobs.enqueue('stop', user=self.su)
        self.assertTrue(jobs.cancel(op, user=self.su))
        op.refresh_from_db()
        self.assertEqual(op.state, 'cancelled')
        op2 = jobs.enqueue('stop', user=self.su)
        ManagedOfficeOperation.objects.filter(pk=op2.pk).update(state='running')
        self.assertFalse(jobs.cancel(op2, user=self.su))

    def test_live_lease_is_not_taken_and_stale_lease_is_recovered(self):
        op = jobs.enqueue('start', user=self.su)
        token = jobs.claim(op.pk)
        self.assertTrue(token)
        self.assertIsNone(jobs.claim(op.pk), 'second runner while the lease is fresh')
        ManagedOfficeOperation.objects.filter(pk=op.pk).update(
            heartbeat_at=timezone.now() - timedelta(seconds=301))
        token2 = jobs.claim(op.pk)
        self.assertTrue(token2)
        self.assertNotEqual(token, token2)
        with self.assertRaises(jobs.LeaseLost):
            jobs.Runner(ManagedOfficeOperation.objects.get(pk=op.pk), token).save(error='x')

    def test_resumed_run_polls_the_same_helper_operation(self):
        self.managed()
        op = jobs.enqueue('start', user=self.su)
        token = jobs.claim(op.pk)
        r = jobs.Runner(op, token)
        r.start()
        r.submit()
        self.assertEqual(self.helper.ops().count('start'), 1)
        # The runner process dies here; the lease goes stale.
        ManagedOfficeOperation.objects.filter(pk=op.pk).update(
            heartbeat_at=timezone.now() - timedelta(seconds=301))
        with self.round_trip_ok():
            jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'succeeded', op.error)
        self.assertEqual(self.helper.ops().count('start'), 1, 'not submitted twice')

    def test_turned_off_service_fails_the_operation(self):
        op = jobs.enqueue('start', user=self.su)
        ManagedOfficeService.objects.filter(pk=1).update(enabled=False)
        jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'failed')
        self.assertEqual(self.helper.ops().count('start'), 0)


class InstallVerifyTests(ManagedBase):
    def test_install_configures_verifies_and_opens_the_editor(self):
        with self.round_trip_ok() as rt:
            op = self.run_op('install')
        self.assertEqual(op.state, 'succeeded', op.error)
        rt.assert_called_once()
        self.assertTrue(rt.call_args.kwargs.get('maintenance'))
        inst = provision.managed_instance()
        self.assertTrue(inst.enabled)
        self.assertEqual(inst.health_status, 'ok')
        self.assertIsNotNone(ManagedOfficeService.get().last_connection_ok_at)
        self.assertIn('install', self.helper.ops())

    def test_failed_round_trip_keeps_users_out(self):
        steps = [SimpleNamespace(key='save', label='Save', status='fail', detail='no callback')]
        with mock.patch('office.diagnostics.run_round_trip', return_value=SimpleNamespace(steps=steps)):
            op = self.run_op('install')
        self.assertEqual(op.state, 'failed')
        self.assertIn('Round trip failed', op.error)
        self.assertFalse(provision.managed_instance().enabled)

    def test_unhealthy_update_keeps_users_out_and_points_at_rollback(self):
        inst = self.managed()
        self.ds.healthy = False
        with self.round_trip_ok() as rt:
            op = self.run_op('update', release='10.0.2-community')
        self.assertEqual(op.state, 'failed')
        self.assertIn('Roll back', op.error)
        rt.assert_not_called()
        inst.refresh_from_db()
        self.assertFalse(inst.enabled)
        self.assertIn('update', self.helper.ops())

    def test_server_side_failure_is_reported(self):
        self.managed()
        self.helper.final_state = 'failed'
        self.helper.final_error = 'pull failed: digest mismatch'
        op = self.run_op('start')
        self.assertEqual(op.state, 'failed')
        self.assertIn('digest mismatch', op.error)

    def test_interrupted_helper_operation_is_resubmitted_then_gives_up(self):
        self.managed()
        self.helper.final_state = 'interrupted'
        self.helper.final_error = 'reboot'
        op = self.run_op('start', slices=10)
        self.assertEqual(op.state, 'failed')
        self.assertEqual(self.helper.ops().count('start'), jobs.MAX_SUBMITS)

    def test_busy_helper_waits(self):
        self.managed()
        self.helper.busy = True
        op = jobs.enqueue('start', user=self.su)
        with override_settings(OFFICE_MANAGED_SLICE_SECONDS=0.3):
            jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'running')
        self.assertIn('busy', op.progress['message'])
        self.helper.busy = False
        with self.round_trip_ok():
            jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'succeeded', op.error)

    def test_helper_unreachable_does_not_break_the_app(self):
        self.helper.close()
        self.assertIsNone(jobs.refresh_status())
        service = ManagedOfficeService.get()
        self.assertFalse(service.helper_reachable)
        self.assertTrue(service.status_error)
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(reverse('office:managed')).status_code, 200)
        self.assertEqual(self.client.get(reverse('office:settings')).status_code, 200)


class DrainTests(ManagedBase):
    def open_edit(self, inst):
        t, s, page = self.setup_doc(instance=inst)
        return t, s

    def test_stop_waits_for_the_requested_save(self):
        inst = self.managed()
        t, s = self.open_edit(inst)
        op = jobs.enqueue('stop', user=self.su)
        with override_settings(OFFICE_MANAGED_SLICE_SECONDS=0.3):
            jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'draining')
        self.assertFalse(EditorInstance.objects.get(pk=inst.pk).enabled, 'new sessions blocked')
        self.assertIn({'c': 'forcesave', 'key': self.key(s)},
                      [{k: c[k] for k in ('c', 'key') if k in c} for c in self.ds.commands])
        self.assertNotIn('stop', self.helper.ops(), 'never stopped before the drain is verified')
        # The editor delivers the save (status 6), then the drain completes.
        self.assertEqual(self.ds.callback(self.client, s, 6, data=docx_text('saved')).json(), {'error': 0})
        jobs.run_pending()
        op.refresh_from_db()
        self.assertEqual(op.state, 'succeeded', op.error)
        self.assertIn('stop', self.helper.ops())
        self.assertFalse(EditorInstance.objects.get(pk=inst.pk).enabled)

    def test_no_changes_answer_counts_as_safe(self):
        inst = self.managed()
        self.open_edit(inst)
        self.ds.no_changes = True
        with self.round_trip_ok():
            op = self.run_op('restart')
        self.assertEqual(op.state, 'succeeded', op.error)
        self.assertIn('restart', self.helper.ops())
        self.assertTrue(EditorInstance.objects.get(pk=inst.pk).enabled)

    def test_unknown_state_postpones_and_reopens(self):
        inst = self.managed()
        self.open_edit(inst)
        self.ds.reachable = False
        with override_settings(OFFICE_MANAGED_DRAIN_SECONDS=0):
            op = self.run_op('update', release='10.0.2-community')
        self.assertEqual(op.state, 'postponed')
        self.assertNotIn('update', self.helper.ops())
        self.assertTrue(EditorInstance.objects.get(pk=inst.pk).enabled, 'reopened after postponing')

    def test_forgotten_files_postpone(self):
        inst = self.managed()
        self.ds.forgotten = ['k1']
        with override_settings(OFFICE_MANAGED_DRAIN_SECONDS=0):
            op = self.run_op('stop')
        self.assertEqual(op.state, 'postponed')
        self.assertIn('forgotten', op.error)
        self.assertNotIn('stop', self.helper.ops())

    def test_expired_session_is_still_counted(self):
        inst = self.managed()
        t, s = self.open_edit(inst)
        EditSession.objects.filter(pk=s.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        st = drain.verify(inst, timezone.now())
        self.assertFalse(st.drained)
        self.assertTrue(st.pending)
        # Once the editor says it no longer has the key, the group is closed.
        self.ds.open_keys.clear()
        st = drain.verify(inst, timezone.now())
        self.assertTrue(st.drained, st.pending)
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'closed')

    def test_session_never_loaded_by_the_editor_is_safe(self):
        inst = self.managed()
        t = self.target()
        s = sessions.open_session(t, self.editor, mode='edit', instance=inst)
        EditSession.objects.filter(pk=s.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        st = drain.verify(inst, timezone.now())
        self.assertTrue(st.drained, st.pending)

    def test_viewers_do_not_block(self):
        inst = self.managed()
        t = self.target()
        s = sessions.open_session(t, self.reader, mode='view', instance=inst)
        oo_state.update(s.pk, oo_key='view-key')
        self.assertTrue(drain.verify(inst, timezone.now()).drained)


class MaintenanceWindowTests(ManagedBase):
    def setUp(self):
        super().setUp()
        self.helper.status = helper_status(update_available=[
            {'id': '10.0.2-community', 'version': '10.0.2', 'installable': True, 'problem': ''},
            {'id': '10.1.0-community', 'version': '10.1.0', 'installable': False, 'problem': 'untested'}])
        jobs.refresh_status()
        self.now = timezone.localtime().replace(hour=3, minute=30)
        ManagedOfficeService.objects.filter(pk=1).update(maintenance_hour=3, maintenance_hours=2,
                                                         maintenance_weekday=None)

    def test_off_by_default(self):
        self.assertIsNone(jobs.maybe_schedule_update(self.now))

    def test_needs_both_the_app_and_the_root_setting(self):
        ManagedOfficeService.objects.filter(pk=1).update(maintenance_updates=True)
        self.assertIsNone(jobs.maybe_schedule_update(self.now), 'root config still says no')
        st = helper_status(update_available=self.helper.status['update_available'])
        st['config']['maintenance_updates'] = True
        self.helper.status = st
        jobs.refresh_status()
        self.assertIsNone(jobs.maybe_schedule_update(self.now.replace(hour=9)), 'outside the window')
        op = jobs.maybe_schedule_update(self.now)
        self.assertEqual((op.action, op.target_release, op.source), ('update', '10.0.2-community', 'maintenance'))
        ManagedOfficeOperation.objects.filter(pk=op.pk).update(state='postponed')
        self.assertIsNone(jobs.maybe_schedule_update(self.now), 'one attempt per window')

    def test_window_bounds(self):
        svc = ManagedOfficeService.get()
        self.assertTrue(jobs.in_window(svc, self.now))
        self.assertFalse(jobs.in_window(svc, self.now.replace(hour=5)))
        svc.maintenance_weekday = (self.now.weekday() + 1) % 7
        self.assertFalse(jobs.in_window(svc, self.now))


class CommandTests(ManagedBase):
    def test_run_pending_and_queue(self):
        out = StringIO()
        call_command('office_managed', '--queue', 'restart', '--user', self.su.username, stdout=out)
        self.assertTrue(ManagedOfficeOperation.objects.filter(action='restart').exists())
        call_command('office_managed', '--status', stdout=out)
        self.assertIn('10.0.0-community', out.getvalue())

    def test_queue_refused_when_off(self):
        ManagedOfficeService.objects.filter(pk=1).update(enabled=False)
        with self.assertRaises(Exception):
            call_command('office_managed', '--queue', 'restart', stdout=StringIO(), stderr=StringIO())
        self.assertFalse(ManagedOfficeOperation.objects.exists())

    def test_scheduler_knows_the_task(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['office_managed_operations'][0], 'office_managed')
        self.assertIn('office_managed_operations', dict(ScheduledTask.TASK_TYPES))


# ---------------------------------------------------------------------------
# Views: superusers only, CSRF, audit
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=core.TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ManagedViewTests(ManagedBase):
    POSTS = (('office:managed_toggle', {'enabled': '0'}), ('office:managed_action', {'action': 'restart'}),
             ('office:managed_checks', {}), ('office:managed_test', {}),
             ('office:managed_maintenance', {'maintenance_hour': '2', 'maintenance_hours': '1'}))
    GETS = ('office:managed', 'office:managed_progress', 'office:managed_diagnostics')

    def staff_user(self):
        from accounts.models import UserType
        u = User.objects.create_user('msp-tech', 'tech@example.com', 'x', is_staff=True)
        u.profile.user_type = UserType.STAFF
        u.profile.save()
        return u

    def test_everyone_but_superusers_is_turned_away(self):
        users = [None, self.editor, self.owner, self.reader, self.outsider, self.staff_user()]
        for user in users:
            c = Client()
            if user is not None:
                c.force_login(user)
            for name in self.GETS:
                r = c.get(reverse(name))
                self.assertIn(r.status_code, (302, 403), (user, name))
                if r.status_code == 302:
                    self.assertIn('login', r['Location'])
            for name, data in self.POSTS:
                r = c.post(reverse(name), data)
                self.assertIn(r.status_code, (302, 403), (user, name))
                if r.status_code == 302:
                    self.assertIn('login', r['Location'])
        self.assertFalse(ManagedOfficeOperation.objects.exists())
        self.assertTrue(ManagedOfficeService.get().enabled)
        self.assertNotIn('restart', self.helper.ops())

    def test_csrf_is_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.su)
        for name, data in self.POSTS:
            self.assertEqual(c.post(reverse(name), data).status_code, 403, name)
        self.assertFalse(ManagedOfficeOperation.objects.exists())

    def test_page_renders_status_and_no_secret(self):
        self.managed()
        self.client.force_login(self.su)
        r = self.client.get(reverse('office:managed'))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('10.0.0-community', body)
        self.assertIn('sha256:' + 'a' * 64, body)
        self.assertIn('install-editor.sh', body)
        self.assertNotIn(SECRET, body)
        self.assertNotIn('<script>', body.split('</nav>')[-1].replace('<script src=', ''))
        self.assertNotIn('onclick=', body)

    def test_queue_action_and_audit(self):
        self.client.force_login(self.su)
        r = self.client.post(reverse('office:managed_action'), {'action': 'restart'})
        self.assertRedirects(r, reverse('office:managed'), fetch_redirect_response=False)
        op = ManagedOfficeOperation.objects.get()
        self.assertEqual((op.action, op.requested_by), ('restart', self.su))
        self.assertTrue(AuditLog.objects.filter(user=self.su, object_type='office.managed').exists())
        data = self.client.get(reverse('office:managed_progress')).json()['operation']
        self.assertEqual(data['state'], 'queued')
        self.assertTrue(data['active'])
        # A second lifecycle action while one is active is refused.
        self.client.post(reverse('office:managed_action'), {'action': 'stop'})
        self.assertEqual(ManagedOfficeOperation.objects.count(), 1)
        # Turning managed mode off while an operation is active is refused.
        self.client.post(reverse('office:managed_toggle'), {'enabled': '0'})
        self.assertTrue(ManagedOfficeService.get().enabled)

    def test_uninstall_needs_typed_confirmation_and_update_an_offered_release(self):
        self.client.force_login(self.su)
        self.client.post(reverse('office:managed_action'), {'action': 'uninstall'})
        self.client.post(reverse('office:managed_action'), {'action': 'update', 'release': 'latest'})
        self.client.post(reverse('office:managed_action'), {'action': 'purge'})
        self.assertFalse(ManagedOfficeOperation.objects.exists())
        self.client.post(reverse('office:managed_action'), {'action': 'uninstall', 'confirm': 'uninstall'})
        self.assertEqual(ManagedOfficeOperation.objects.get().action, 'uninstall')

    def test_toggle_is_audited(self):
        self.client.force_login(self.su)
        self.client.post(reverse('office:managed_toggle'), {'enabled': '0'})
        self.assertFalse(ManagedOfficeService.get().enabled)
        self.assertTrue(AuditLog.objects.filter(description__contains='turned off').exists())
        r = self.client.post(reverse('office:managed_action'), {'action': 'start'})
        self.assertFalse(ManagedOfficeOperation.objects.exists(), 'actions need managed mode on')
        self.assertEqual(r.status_code, 302)

    def test_setup_checks_and_diagnostics(self):
        self.managed()
        self.client.force_login(self.su)
        r = self.client.post(reverse('office:managed_checks'))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Supported operating system', body)
        self.assertIn('clientst0r reaches ONLYOFFICE (loopback)', body)
        r = self.client.get(reverse('office:managed_diagnostics') + '?lines=900&download=1')
        self.assertEqual(r['Content-Disposition'], 'attachment; filename="managed-onlyoffice-diagnostics.txt"')
        self.assertIn('line two', r.content.decode())
        self.assertNotIn(SECRET, r.content.decode())
        self.assertEqual(self.helper.requests[-1], {'op': 'logs', 'args': {'lines': 500}})

    def test_maintenance_form_validation(self):
        self.client.force_login(self.su)
        self.client.post(reverse('office:managed_maintenance'),
                         {'maintenance_hour': '25', 'maintenance_hours': '1'})
        self.assertEqual(ManagedOfficeService.get().maintenance_hour, 3)
        self.client.post(reverse('office:managed_maintenance'),
                         {'maintenance_updates': '1', 'maintenance_hour': '1', 'maintenance_hours': '2',
                          'maintenance_weekday': '6'})
        svc = ManagedOfficeService.get()
        self.assertEqual((svc.maintenance_updates, svc.maintenance_hour, svc.maintenance_weekday),
                         (True, 1, 6))
