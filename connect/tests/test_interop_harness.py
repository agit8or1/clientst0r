"""Integration: the two-installation interoperability harness
(scripts/connect_interop/run.py, Quick Connect increment G / roadmap 79.23).

Skipped unless CONNECT_INTEROP=1: it migrates throwaway databases and runs
two gunicorn servers over HTTPS on 127.0.0.1 for several minutes. Run it with

    CONNECT_INTEROP=1 DB_ENGINE=sqlite3 venv/bin/python manage.py test connect.tests.test_interop_harness

or directly with ``venv/bin/python scripts/connect_interop/run.py``.
The fast tests below check the harness's address simulation on its own.
"""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from django.conf import settings
from django.test import SimpleTestCase

HARNESS = os.path.join(settings.BASE_DIR, 'scripts', 'connect_interop')


class NetshimTests(SimpleTestCase):
    """The simulation maps names and addresses only for the harness's own
    names and range; everything else goes to the real resolver."""

    def setUp(self):
        sys.path.insert(0, HARNESS)
        self.addCleanup(sys.path.remove, HARNESS)
        import netshim
        self.netshim = netshim
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.unlink, self.path)
        os.environ['INTEROP_NET_FILE'] = self.path
        self.addCleanup(os.environ.pop, 'INTEROP_NET_FILE', None)

    def write(self, data):
        import json
        with open(self.path, 'w') as f:
            json.dump(data, f)

    def test_resolution_and_nat(self):
        self.write({'hosts': {'b.interop.test': ['10.231.0.2']}, 'nat': {'127.0.0.12': '10.231.0.2'}})
        infos = self.netshim.getaddrinfo('b.interop.test', 8443)
        self.assertEqual([i[4] for i in infos], [('10.231.0.2', 8443)])
        with self.assertRaises(socket.gaierror):
            self.netshim.getaddrinfo('missing.interop.test', 443)
        self.assertEqual(self.netshim.translate_remote_addr('127.0.0.12'), '10.231.0.2')
        self.assertEqual(self.netshim.translate_remote_addr('127.0.0.1'), '127.0.0.1')

    def test_dial_reports_the_simulated_peer(self):
        srv = socket.socket()
        srv.bind(('127.0.0.1', 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        seen = {}

        def accept():
            c, addr = srv.accept()
            seen['addr'] = addr
            c.close()
        t = threading.Thread(target=accept)
        t.start()
        self.write({'hosts': {}, 'nat': {}})
        s = self.netshim.create_connection(('10.231.0.9', port), 5)
        try:
            self.assertEqual(s.getpeername(), ('10.231.0.9', port))
        finally:
            s.close()
        t.join(5)
        srv.close()
        self.assertEqual(seen['addr'][0], os.environ.get('INTEROP_SOURCE', '127.0.0.1'))


@unittest.skipUnless(os.environ.get('CONNECT_INTEROP') == '1', 'set CONNECT_INTEROP=1 to run the two-installation '
                                                                'harness (several minutes)')
class TwoInstallationInterop(SimpleTestCase):
    def test_harness_passes(self):
        out = tempfile.mkdtemp(prefix='interop-report-')
        r = subprocess.run([sys.executable, os.path.join(HARNESS, 'run.py'), '--out', out],
                           cwd=str(settings.BASE_DIR), capture_output=True, text=True, timeout=3600)
        self.assertEqual(r.returncode, 0, r.stderr[-4000:])
