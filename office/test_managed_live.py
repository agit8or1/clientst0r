"""Managed Local ONLYOFFICE against a real container: opt-in, NOT RUN by default.

These tests drive the real Office service helper and a real ONLYOFFICE Docs
container. They install, restart, update, roll back and uninstall it, so run
them only on a disposable VM that has had
``scripts/office/install-editor.sh --mode managed-local`` run on it, as the
clientst0r app user (the only account the helper socket accepts):

    OFFICE_E2E_MANAGED_HOST=office.test.example \\
    OFFICE_E2E_MANAGED_DISPOSABLE=yes \\
    [OFFICE_E2E_MANAGED_UPDATE_TO=<release id>]   # update + rollback steps
    python manage.py test office.test_managed_live

They use the real socket (settings.OFFICE_MANAGED_SOCKET or
/run/clientst0r-office/helper.sock) and the real network: no fakes. Checks
that need root (container hardening, loopback-only publish, egress firewall)
and the browser checks are in docs/office/MANAGED_LOCAL.md, "Live
verification"; Playwright is not installed in this project, so the browser
part is a manual checklist.

Status: written, never run (no Docker on the development machine).
"""
import os
import socket
import time
import unittest
from urllib.parse import urlsplit

from django.contrib.auth.models import User
from django.test import TransactionTestCase

HOST = os.environ.get('OFFICE_E2E_MANAGED_HOST', '')
DISPOSABLE = os.environ.get('OFFICE_E2E_MANAGED_DISPOSABLE', '') == 'yes'
UPDATE_TO = os.environ.get('OFFICE_E2E_MANAGED_UPDATE_TO', '')
TIMEOUT = int(os.environ.get('OFFICE_E2E_MANAGED_TIMEOUT', '1800'))


@unittest.skipUnless(HOST and DISPOSABLE, 'set OFFICE_E2E_MANAGED_HOST and OFFICE_E2E_MANAGED_DISPOSABLE=yes '
                                          'on a disposable VM (docs/office/MANAGED_LOCAL.md)')
class ManagedLiveTests(TransactionTestCase):
    """In order: preflight, install, verify, restart, (update, rollback),
    stop/start, uninstall. One test method so the order is fixed."""

    def setUp(self):
        from office.models import ManagedOfficeService
        self.su = User.objects.create_superuser('live-su', 'live@example.com', 'x')
        service = ManagedOfficeService.get()
        service.enabled = True
        service.updated_by = self.su
        service.save()

    def run_to_end(self, action, release=''):
        from office.managed import jobs
        op = jobs.enqueue(action, user=self.su, release=release)
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            jobs.run_pending()
            op.refresh_from_db()
            if not op.is_active:
                return op
            time.sleep(2)
        self.fail(f'{action} did not finish in {TIMEOUT} s: {op.progress}')

    def assert_ok(self, op):
        self.assertEqual(op.state, 'succeeded', f'{op.action}: {op.error}\n{op.progress}')

    def test_lifecycle(self):
        from office import diagnostics
        from office.managed import checks, ipc, provision

        status = ipc.call('status')
        self.assertEqual(status['config']['office_hostname'], HOST)
        pre = {c['key']: c for c in ipc.call('preflight')['checks']}
        failed = {k: c['detail'] for k, c in pre.items() if c['status'] == 'fail'}
        self.assertEqual(failed, {}, 'preflight')

        # Install: pinned digest, healthy, configured, round trip passed.
        self.assert_ok(self.run_to_end('install'))
        status = ipc.call('status')
        inst = provision.managed_instance()
        self.assertTrue(status['installed']['digest'].startswith('sha256:'))
        self.assertIn('@' + status['installed']['digest'], status['container']['image'])
        self.assertTrue(status['container']['running'])
        self.assertEqual(status['container']['health'], 'healthy')
        self.assertTrue(inst.enabled)
        self.assertEqual(inst.health_status, 'ok')

        # Loopback-only publish, from clientst0r's side: the port answers on
        # 127.0.0.1 and not on the host's other addresses.
        port = status['config']['bind_port']
        socket.create_connection(('127.0.0.1', port), timeout=5).close()
        for addr in {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}:
            if addr.startswith('127.'):
                continue
            with self.assertRaises(OSError, msg=addr):
                socket.create_connection((addr, port), timeout=3).close()

        # All checks, including ONLYOFFICE -> clientst0r (conversion
        # download) and verified HTTPS on the office host name.
        results = {c.key: c for c in checks.run()}
        bad = {k: c.detail for k, c in results.items() if c.status == 'fail'}
        self.assertEqual(bad, {}, 'setup checks')
        self.assertEqual(urlsplit(inst.browser_url).hostname, HOST)

        # Restart drains and verifies again.
        self.assert_ok(self.run_to_end('restart'))
        report = diagnostics.run_round_trip(provision.managed_instance(), self.su)
        self.assertEqual([s.key for s in report.steps if s.status == 'fail'], [])

        if UPDATE_TO:
            before = ipc.call('status')['installed']
            self.assert_ok(self.run_to_end('update', UPDATE_TO))
            after = ipc.call('status')['installed']
            self.assertEqual(after['release'], UPDATE_TO)
            self.assertEqual(after['previous_release'], before['release'])
            self.assertTrue(ipc.call('status')['backups'], 'a pre-update backup exists')
            self.assert_ok(self.run_to_end('rollback'))
            self.assertEqual(ipc.call('status')['installed']['release'], before['release'])

        # Stop keeps users out; start brings the editor back verified.
        self.assert_ok(self.run_to_end('stop'))
        self.assertFalse(provision.managed_instance().enabled)
        self.assert_ok(self.run_to_end('start'))
        self.assertTrue(provision.managed_instance().enabled)

        # Uninstall keeps data and secrets.
        self.assert_ok(self.run_to_end('uninstall'))
        status = ipc.call('status')
        self.assertFalse(status['container'].get('exists'))
        self.assertTrue(status['secrets_present'])
        self.assertGreater(status['data_bytes'], 0)
