"""Quick Connect increment A (roadmap 79.8): fixes for audit findings QC-03,
QC-04, QC-08, QC-09, QC-10, QC-11, QC-12 and QC-14
(docs/plans/quick-connect/AUDIT.md, INCREMENTS.md §A)."""
import base64
import datetime
import json
import os
import shutil
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from agit8or_connect.errors import ConnectError
from agit8or_connect.reference_peer import ReferencePeer

from .base import CS_BASE, PEER_BASE, ConnectTestCase

UI = '/settings/integrations/connected-apps/'


def _get(client, path):
    return client.get(path, secure=True, HTTP_HOST='clientst0r.test')


def _post(client, path, data):
    return client.post(path, data, secure=True, HTTP_HOST='clientst0r.test')


class _Req:
    """Enough of a request for tech_access.protected with a fresh re-auth."""

    def __init__(self, user):
        from tech_access import protected
        self.user, self.session = user, {protected.SESSION_KEY: int(time.time())}
        self.META, self.path = {}, '/'


class _StubSession:
    """Stands in for the guarded requests session once validation passed."""

    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, **kw):
        self.calls.append(url)
        return SimpleNamespace(status_code=200, headers={}, iter_content=lambda n: iter([b'{}']), close=lambda: None)


# --- QC-04 ---------------------------------------------------------------------------

@override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=True)
class OutboundPolicyIgnoresSiteOptIn(SimpleTestCase):
    """The site-wide private-IP opt-in never widens what Connect may reach.
    (Since increment B2 a connection's transport is also pinned to its
    approved destination; these tests check the policy layer under it.)"""

    def refused(self, t, url):
        calls = []
        with mock.patch.object(type(t), '_session', lambda self, ctx: _StubSession(calls)):
            with self.assertRaises(ConnectError) as e:
                t.request('GET', url)
        self.assertEqual(e.exception.code, 'blocked_destination', url)
        self.assertEqual(calls, [], url)

    def allowed(self, t, url):
        calls = []
        with mock.patch.object(type(t), '_session', lambda self, ctx: _StubSession(calls)):
            self.assertEqual(t.request('GET', url).status, 200)
        self.assertEqual(calls, [url])

    def test_private_network_off(self):
        for url in ('https://127.0.0.1/', 'https://[::1]/', 'https://169.254.1.1/', 'https://10.0.0.5:8443/',
                    'https://10.0.0.5/', 'https://localhost/'):
            from connect import transport
            self.refused(transport.for_destination(url), url)

    def test_private_network_on(self):
        from connect import transport
        for url in ('https://127.0.0.1/', 'https://169.254.1.1/', 'https://[::1]/', 'https://localhost/',
                    'https://169.254.169.254/latest/meta-data'):
            self.refused(transport.for_destination(url, allow_private=True), url)
        self.allowed(transport.for_destination('https://10.0.0.5:443/', allow_private=True),
                     'https://10.0.0.5:443/.well-known/agit8or-connect')
        self.allowed(transport.for_destination('https://10.0.0.5/', allow_private=True), 'https://10.0.0.5/x')

    def test_connect_time_guard_refuses_loopback_with_private_on(self):
        from core import safe_http
        from connect import transport
        policy = transport.for_destination('https://peer.example/', allow_private=True)._policy()
        self.assertFalse(policy.allow_local)
        for ip in ('127.0.0.1', '169.254.1.1', '::1', 'fe80::1'):
            self.assertFalse(safe_http.is_allowed_ip(ip, policy), ip)
        self.assertTrue(safe_http.is_allowed_ip('10.0.0.5', policy))

    def test_ports(self):
        from connect import transport
        t = transport.for_destination('https://peer.example:8443/')
        self.assertEqual(t._policy().allowed_ports, frozenset({443, 8443}))
        self.refused(t, 'https://peer.example:9443/connect/v1/token')
        self.refused(t, 'https://peer.example:80/connect/v1/token')
        self.allowed(t, 'https://peer.example:8443/connect/v1/token')
        self.allowed(t, 'https://peer.example/connect/v1/token')
        plain = transport.for_destination('https://peer.example/')
        self.assertEqual(plain._policy().allowed_ports, frozenset({443}))
        self.refused(plain, 'https://peer.example:8443/')
        self.assertEqual(transport.for_settings(base_url='https://peer.example:7443')._policy().allowed_ports,
                         frozenset({443, 7443}))

    def test_sdk_adapter_never_allow_local(self):
        from agit8or_connect.adapters.safe_http import SafeHttpTransport
        for private in (False, True):
            p = SafeHttpTransport(allow_private=private)._policy()
            self.assertFalse(p.allow_local)
            self.assertEqual(p.allow_lan, private)
            self.assertEqual(p.allowed_ports, frozenset({443}))


# --- QC-09 ---------------------------------------------------------------------------

def _pki():
    """A throw-away CA, a server certificate for 127.0.0.1, a client
    certificate, and a second unrelated CA. PEM strings."""
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def name(cn):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    def key():
        return ec.generate_private_key(ec.SECP256R1())

    def pem_key(k):
        return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()

    def pem_cert(c):
        return c.public_bytes(serialization.Encoding.PEM).decode()

    def ca(cn):
        k = key()
        c = (x509.CertificateBuilder().subject_name(name(cn)).issuer_name(name(cn)).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
             .not_valid_after(now + datetime.timedelta(days=1))
             .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
             .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                          content_commitment=False, key_encipherment=False,
                                          data_encipherment=False, key_agreement=False, encipher_only=False,
                                          decipher_only=False), critical=True)
             .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
             .sign(k, hashes.SHA256()))
        return k, c

    def leaf(ca_key, ca_cert, cn, usage, san=None):
        k = key()
        b = (x509.CertificateBuilder().subject_name(name(cn)).issuer_name(ca_cert.subject)
             .public_key(k.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                            critical=False))
        if san:
            b = b.add_extension(x509.SubjectAlternativeName(san), critical=False)
        return k, b.sign(ca_key, hashes.SHA256())

    ca_k, ca_c = ca('a8c test CA')
    other_k, other_c = ca('unrelated CA')
    srv_k, srv_c = leaf(ca_k, ca_c, '127.0.0.1', ExtendedKeyUsageOID.SERVER_AUTH,
                        [x509.IPAddress(ipaddress.ip_address('127.0.0.1'))])
    cli_k, cli_c = leaf(ca_k, ca_c, 'clientst0r-test-client', ExtendedKeyUsageOID.CLIENT_AUTH)
    return {'ca': pem_cert(ca_c), 'other_ca': pem_cert(other_c), 'server_cert': pem_cert(srv_c),
            'server_key': pem_key(srv_k), 'client_cert': pem_cert(cli_c), 'client_key': pem_key(cli_k)}


class _MtlsServer:
    """HTTPS on 127.0.0.1 that requires a client certificate from the CA and
    answers with the client certificate's common name."""

    def __init__(self, pki, tmp):
        cert, key, ca = (os.path.join(tmp, n) for n in ('s.pem', 's.key', 'ca.pem'))
        for path, text in ((cert, pki['server_cert']), (key, pki['server_key']), (ca, pki['ca'])):
            with open(path, 'w') as f:
                f.write(text)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        ctx.load_verify_locations(ca)
        ctx.verify_mode = ssl.CERT_REQUIRED

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                peer = self.connection.getpeercert() or {}
                cn = dict(x[0] for x in peer.get('subject', ())).get('commonName', '')
                body = json.dumps({'client': cn}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class MtlsKeyNeverOnDisk(SimpleTestCase):
    """QC-09: the mTLS client key (and the CA bundle) reach OpenSSL without a
    plaintext file on disk."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pki = _pki()
        cls.tmp = tempfile.mkdtemp(prefix='qc09-')
        cls.server = _MtlsServer(cls.pki, cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        # Loopback is never allowed for Connect; only this test server is let through.
        p = mock.patch('core.safe_http.is_allowed_ip', lambda *a, **k: True)
        p.start()
        self.addCleanup(p.stop)
        self.url = f'https://127.0.0.1:{self.server.port}/hello'

    def transport(self, **kw):
        from agit8or_connect.adapters.safe_http import SafeHttpTransport
        args = dict(ca_pem=self.pki['ca'], client_cert_pem=self.pki['client_cert'],
                    client_key_pem=self.pki['client_key'], allowed_ports={self.server.port}, timeout=5)
        args.update(kw)
        return SafeHttpTransport(**args)

    def test_mtls_from_memory_writes_no_file(self):
        if not hasattr(os, 'memfd_create'):
            self.skipTest('memfd_create not available on this platform')
        boom = mock.Mock(side_effect=AssertionError('TLS material written to a file'))
        with mock.patch('tempfile.mkstemp', boom), mock.patch('tempfile.mkdtemp', boom), \
                mock.patch('tempfile.NamedTemporaryFile', boom):
            r = self.transport().request('GET', self.url)
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.body)['client'], 'clientst0r-test-client')
        boom.assert_not_called()
        # every memfd is closed after the context is built
        self.assertFalse(any('a8c-pem' in os.readlink(f'/proc/self/fd/{fd}')
                             for fd in os.listdir('/proc/self/fd')
                             if os.path.exists(f'/proc/self/fd/{fd}')))

    def test_fallback_private_dir_always_removed(self):
        runtime = tempfile.mkdtemp(prefix='qc09-rt-')
        self.addCleanup(shutil.rmtree, runtime, True)
        seen = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a, **k):
            d = real_mkdtemp(*a, **k)
            seen.append((d, oct(os.stat(d).st_mode & 0o777)))
            return d
        with override_settings(AGIT8OR_CONNECT_RUNTIME_DIR=runtime), \
                mock.patch('os.memfd_create', side_effect=OSError('no memfd')), \
                mock.patch('agit8or_connect.adapters.safe_http.tempfile.mkdtemp', spy):
            r = self.transport().request('GET', self.url)
            self.assertEqual(r.status, 200)
            with self.assertRaises(ConnectError):   # a failing request cleans up too
                self.transport(ca_pem=self.pki['other_ca']).request('GET', self.url)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(d.startswith(runtime) and mode == '0o700' for d, mode in seen))
        self.assertEqual(os.listdir(runtime), [])

    def test_private_ca_only_and_client_cert_required(self):
        with self.assertRaises(ConnectError) as e:
            self.transport(ca_pem=self.pki['other_ca']).request('GET', self.url)
        self.assertEqual(e.exception.code, 'transport_error')
        with self.assertRaises(ConnectError) as e:   # system store only: the test CA is not trusted
            self.transport(ca_pem=None).request('GET', self.url)
        self.assertEqual(e.exception.code, 'transport_error')
        with self.assertRaises(ConnectError):        # no client certificate: the server refuses
            self.transport(client_cert_pem=None, client_key_pem=None).request('GET', self.url)

    def test_startup_sweep_removes_old_leftovers_only(self):
        from agit8or_connect.adapters.safe_http import sweep_leftovers
        runtime = tempfile.mkdtemp(prefix='qc09-sw-')
        self.addCleanup(shutil.rmtree, runtime, True)
        old_dir = os.path.join(runtime, 'a8c-old')
        os.mkdir(old_dir, 0o700)
        with open(os.path.join(old_dir, 'k-1.pem'), 'w') as f:
            f.write('x')
        old_file = os.path.join(runtime, 'a8c-legacy.pem')
        with open(old_file, 'w') as f:
            f.write('x')
        new_dir = os.path.join(runtime, 'a8c-busy')
        os.mkdir(new_dir, 0o700)
        other = os.path.join(runtime, 'unrelated.pem')
        with open(other, 'w') as f:
            f.write('x')
        past = time.time() - 3600
        for p in (old_dir, old_file, other):
            os.utime(p, (past, past))
        with override_settings(AGIT8OR_CONNECT_RUNTIME_DIR=runtime):
            self.assertEqual(sweep_leftovers(), 2)
        self.assertEqual(sorted(os.listdir(runtime)), ['a8c-busy', 'unrelated.pem'])


# --- QC-08 ---------------------------------------------------------------------------

class KillSwitchBlocksApprovals(ConnectTestCase):
    def test_inbound_approval_refused(self):
        from connect import lifecycle, pairing
        from connect.models import Connection, PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=self.SCOPES)
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        lifecycle.engage_kill_switch(self.admin)
        with self.assertRaises(pairing.PairingFailed) as e:
            pairing.approve_inbound(preq, destination_addresses=['93.184.216.40'], scopes=self.SCOPES, grants=[], user=self.admin)
        self.assertEqual(e.exception.code, 'kill_switch')
        with self.assertRaises(pairing.PairingFailed):
            pairing.finalize_inbound(preq, self.SCOPES, [], [], self.admin)
        lifecycle.release_kill_switch(self.admin)
        preq.refresh_from_db()
        self.assertEqual(preq.status, PairingRequest.PENDING)
        self.assertEqual(preq.connection.state, Connection.AWAITING_LOCAL)
        self.assertFalse(preq.result_jws)

    def test_local_approval_refused(self):
        from connect import lifecycle, pairing
        from connect.models import Connection
        code = self.peer.create_invitation()
        conn = pairing.start_outbound(pairing.discover(self.peer.base), code, destination_addresses=['93.184.216.40'], requested_scopes=self.PEER_SCOPES,
                                      organizations=[self.org_a], user=self.admin, peer_sources=[self.peer_ip])
        self.peer.approve(conn.pairing_request_id, scopes=self.PEER_SCOPES, tenant_grants=[],
                          requested_scopes=self.SCOPES)
        self.assertEqual(pairing.poll(conn), 'approved')
        conn.refresh_from_db()
        lifecycle.engage_kill_switch(self.admin)
        for fn in (lambda: pairing.approve_local(conn, scopes=self.SCOPES, grants=[], user=self.admin),
                   lambda: pairing.finalize_local(conn, self.SCOPES, [], self.admin)):
            with self.assertRaises(pairing.PairingFailed) as e:
                fn()
            self.assertEqual(e.exception.code, 'kill_switch')
        lifecycle.release_kill_switch(self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_LOCAL)

    def test_protected_change_refused_and_stays_inactive_after_release(self):
        from agit8or_connect.scopes import Catalog, Scope
        from connect import catalog, lifecycle, pairing
        from connect.models import Connection, PairingRequest
        from tech_access import protected
        from tech_access.models import ProtectedChange
        cat = Catalog(list(catalog.CATALOG.scopes) + [Scope('lab_actions:execute', 'Lab action', 'high_risk')])
        with mock.patch.object(catalog, 'CATALOG', cat):
            _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
            pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read',
                                                                               'lab_actions:execute'])
            preq = PairingRequest.objects.get(pk=pconn.request_id)
            change = pairing.approve_inbound(preq, destination_addresses=['93.184.216.40'], scopes=['customers:read', 'lab_actions:execute'],
                                             grants=[], user=self.admin)
            protected.confirm(change, _Req(self.admin))
            lifecycle.engage_kill_switch(self.admin)
            with self.assertRaises(protected.ProtectedChangeError):
                protected.approve(change, _Req(self.admin2))
            lifecycle.release_kill_switch(self.admin)
        change.refresh_from_db()
        self.assertEqual(change.status, ProtectedChange.PENDING)
        preq.refresh_from_db()
        self.assertNotEqual(preq.connection.state, Connection.ACTIVE)
        self.assertEqual(self.peer.poll(pconn.id), 'pending')

    def test_activate_itself_refuses(self):
        from connect import lifecycle, pairing
        _, conn = self.pair_inbound()
        conn.state = conn.AWAITING_LOCAL
        lifecycle.engage_kill_switch(self.admin)
        with self.assertRaises(pairing.PairingFailed):
            pairing._activate(conn)


# --- QC-10 ---------------------------------------------------------------------------

def _jws_payload(token):
    try:
        part = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


class PublicUrlRequired(ConnectTestCase):
    @override_settings(AGIT8OR_CONNECT_PUBLIC_URL='')
    def test_unset_refuses_invitations_and_pairing(self):
        from connect import identity, pairing
        from connect.models import Connection, PairingInvitation
        for path in (UI + 'invite/', UI + 'new/rem0te/'):
            page = _get(self.ui, path).content.decode()
            self.assertIn('data-connect-not-configured', page, path)
            self.assertIn('AGIT8OR_CONNECT_PUBLIC_URL', page, path)
        before = len(self.net.log)
        _post(self.ui, UI + 'invite/', {'peer_sources': '93.184.216.34', 'label': 'x'})
        code = self.peer.create_invitation()
        r = _post(self.ui, UI + 'new/rem0te/', {'url': self.peer.base, 'op': 'pair', 'destination_addresses': '93.184.216.40', 'peer_sources': '93.184.216.34', 'pairing_secret': code,
                                               'scopes': ['customers:read']})
        self.assertIn('data-connect-not-configured', r.content.decode())
        self.assertEqual(PairingInvitation.objects.count(), 0)
        self.assertEqual(Connection.objects.count(), 0)
        self.assertEqual(len(self.net.log), before)     # nothing was sent
        with self.assertRaises(pairing.PairingFailed):
            pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        with self.assertRaises(ConnectError) as e:
            identity.public_base()
        self.assertEqual(e.exception.code, 'not_configured')
        with self.assertRaises(ConnectError):
            identity.endpoints()

    @override_settings(AGIT8OR_CONNECT_PUBLIC_URL='psa.example.com')
    def test_relative_or_schemeless_value_is_not_accepted(self):
        from connect import identity
        self.assertEqual(identity.configured_public_url(), '')
        self.assertIn('absolute https', identity.public_url_problem())
        with override_settings(AGIT8OR_CONNECT_PUBLIC_URL='/connect'):
            self.assertTrue(identity.public_url_problem())
        with override_settings(AGIT8OR_CONNECT_PUBLIC_URL='https://psa.example.com/'):
            self.assertEqual(identity.public_url_problem(), '')
            self.assertEqual(identity.public_base(), 'https://psa.example.com')

    def test_no_relative_url_in_any_outgoing_jws(self):
        captured = []
        real = self.net.request

        def spy(method, url, headers=None, body=None):
            r = real(method, url, headers, body)
            captured.append((url, body or b'', r.body or b''))
            return r
        self.net.request = spy
        self.pair_outbound()
        self.pair_inbound(peer=ReferencePeer('https://rmm2.test', self.net))
        tokens = []
        for url, req, resp in captured:
            for blob in (req, resp):
                try:
                    data = json.loads(blob or b'{}')
                except ValueError:
                    continue
                for s in _strings(data):
                    if s.count('.') == 2 and s.startswith('eyJ'):
                        payload = _jws_payload(s)
                        if payload is not None:
                            tokens.append(payload)
        self.assertTrue(any('discovery_url' in p for p in tokens))
        self.assertTrue(any('endpoints' in p for p in tokens))
        for p in tokens:
            for s in _strings(p):
                if '/connect/v1' in s or '.well-known' in s or '://' in s:
                    self.assertTrue(s.startswith('https://'), s)
            if p.get('discovery_url'):
                self.assertTrue(p['discovery_url'].startswith('https://'))


# --- QC-11 ---------------------------------------------------------------------------

class ReviewPageGetIsSafe(ConnectTestCase):
    def test_get_makes_no_outbound_request_and_lookup_is_a_post(self):
        from connect import pairing
        from connect.models import PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        made = []

        def counting_factory(**kw):
            made.append(kw)
            return self.net
        with mock.patch('connect.transport.factory', counting_factory):
            page = _get(self.ui, UI + f'requests/{preq.pk}/').content.decode()
            self.assertEqual(made, [])
            self.assertIn('data-connect-lookup', page)
            preq.connection.refresh_from_db()
            self.assertEqual(preq.connection.remote_catalog, [])
            r = _post(self.ui, UI + f'requests/{preq.pk}/', {'op': 'lookup'})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(len(made), 1)
        preq.connection.refresh_from_db()
        self.assertTrue(preq.connection.remote_catalog)
        page = _get(self.ui, UI + f'requests/{preq.pk}/').content.decode()
        self.assertIn('What Clientst0r asks in return', page)
        self.assertNotIn('data-connect-lookup', page)

    def test_lookup_needs_manage_permission(self):
        from connect import pairing
        from connect.models import PairingRequest
        from django.contrib.auth.models import User
        from django.test import Client
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        nobody = User.objects.create_user('nobody', 'n@example.test', 'pw-Nobody-1!x')
        c = Client()
        c.force_login(nobody)
        self.assertEqual(_post(c, UI + f'requests/{pconn.request_id}/', {'op': 'lookup'}).status_code, 403)
        self.assertEqual(PairingRequest.objects.get(pk=pconn.request_id).connection.remote_catalog, [])


# --- QC-12 ---------------------------------------------------------------------------

class DuplicateInstallationId(ConnectTestCase):
    def test_warning_and_second_administrator(self):
        from connect import pairing
        from connect.models import Connection, PairingRequest
        from tech_access import protected
        from tech_access.models import ProtectedChange
        _, genuine = self.pair_inbound()
        rogue = ReferencePeer('https://rogue.test', self.net, app_type='rem0te', display_name='Rem0te lab')
        rogue.installation_id = self.peer.installation_id
        rogue.app['installation_id'] = self.peer.installation_id
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = rogue.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        page = _get(self.ui, UI + f'requests/{preq.pk}/').content.decode()
        self.assertIn('data-connect-duplicate', page)
        self.assertIn('already connected here', page)
        change = pairing.approve_inbound(preq, destination_addresses=['93.184.216.40'], scopes=['customers:read'], grants=[], user=self.admin)
        self.assertIsInstance(change, ProtectedChange)
        self.assertEqual(change.kind, 'app_connection')
        self.assertIn(str(genuine.pk), change.payload['duplicate_of'])
        self.assertTrue(any('already connected' in w for w in change.widening))
        preq.refresh_from_db()
        self.assertEqual(preq.connection.state, Connection.AWAITING_SECOND)
        self.assertEqual(rogue.poll(pconn.id), 'pending')
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(change, _Req(self.admin))     # the proposer cannot approve
        protected.confirm(change, _Req(self.admin))
        protected.approve(change, _Req(self.admin2))
        preq.refresh_from_db()
        self.assertEqual(preq.connection.state, Connection.ACTIVE)

    def test_ui_approval_redirects_to_protected_change(self):
        from connect import pairing
        self.pair_inbound()
        rogue = ReferencePeer('https://rogue.test', self.net)
        rogue.installation_id = rogue.app['installation_id'] = self.peer.installation_id
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = rogue.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        from django.urls import reverse
        from tech_access.models import ProtectedChange
        r = _post(self.ui, UI + f'requests/{pconn.request_id}/', {'op': 'approve', 'destination_addresses': '93.184.216.40', 'scopes': ['customers:read']})
        self.assertEqual(r.status_code, 302)
        change = ProtectedChange.objects.get(kind='app_connection')
        self.assertEqual(r['Location'], reverse('tech_access:change_detail', kwargs={'pk': change.pk}))

    def test_unrelated_request_has_no_warning(self):
        from connect import pairing
        from connect.models import PairingRequest
        self.pair_inbound()
        other = ReferencePeer('https://other.test', self.net)
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = other.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        page = _get(self.ui, UI + f'requests/{pconn.request_id}/').content.decode()
        self.assertNotIn('data-connect-duplicate', page)
        self.assertIsNone(pairing.approve_inbound(PairingRequest.objects.get(pk=pconn.request_id), destination_addresses=['93.184.216.40'],
                                                  scopes=['customers:read'], grants=[], user=self.admin))


# --- QC-03 ---------------------------------------------------------------------------

class UnauthenticatedRefusalsAreFolded(ConnectTestCase):
    def test_unknown_client_flood(self):
        import uuid
        from connect import denials, ratelimit
        from connect.models import ConnectAuditEvent
        from api_access.models import ApiAccessDecision
        start = ConnectAuditEvent.objects.count()
        body = ('grant_type=client_credentials&client_id=' + str(uuid.uuid4()) +
                '&client_assertion_type=urn%3Aietf%3Aparams%3Aoauth%3Aclient-assertion-type%3Ajwt-bearer'
                '&client_assertion=x.y.z').encode()
        with mock.patch.dict(ratelimit.LIMITS, {'token_ip': (10_000, 60), 'token_global': (10_000, 60)}):
            for _ in range(500):
                r = self.net.request('POST', f'{CS_BASE}/connect/v1/token',
                                     {'Content-Type': 'application/x-www-form-urlencoded'}, body)
                # Increment B1: an unknown client_id names no connection, so the
                # source policy refuses it before authentication (403).
                self.assertEqual(r.status, 403)
        self.assertEqual(ConnectAuditEvent.objects.count(), start)       # nothing written per request
        rows = ApiAccessDecision.objects.filter(endpoint_group='connect_api', integration='agit8or_connect')
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().count, 500)
        self.assertEqual(rows.get().reason, 'connect_source_connection')
        self.assertEqual(rows.get().surface, 'connect')
        self.assertIsNone(denials.summarise())          # the minute is still open
        later = timezone.now() + datetime.timedelta(minutes=2)
        ev = denials.summarise(now=later)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.operation, 'refusals.summary')
        self.assertEqual(ev.detail['total'], 500)
        self.assertIn('connect_source_connection=500', ev.detail['counts'])
        self.assertIsNone(denials.summarise(now=later))                     # at most one per minute
        self.assertIsNone(denials.summarise(now=later + datetime.timedelta(minutes=5)))   # nothing new
        self.assertEqual(ConnectAuditEvent.objects.count(), start + 1)
        from connect import audit_log
        self.assertIsNone(audit_log.verify())

    def test_wrong_codes_folded_lockout_kept(self):
        from connect import pairing
        from connect.models import ConnectAuditEvent
        from api_access.models import ApiAccessDecision
        pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        for i in range(6):
            with self.assertRaises(ConnectError):
                self.peer.start_pairing(CS_BASE, '00000-0000' + str(i), requested_scopes=['customers:read'])
        self.assertEqual(ConnectAuditEvent.objects.filter(operation='pairing.code_rejected', result='denied').count(),
                         0)
        self.assertEqual(ConnectAuditEvent.objects.filter(operation='pairing.code_rejected', result='locked').count(),
                         1)
        row = ApiAccessDecision.objects.get(reason='connect_wrong_pairing_code')
        self.assertEqual(row.count, 5)

    def test_known_connection_denials_still_in_chain(self):
        from connect.models import ConnectAuditEvent
        pconn, conn = self.pair_inbound()
        body = (f'grant_type=client_credentials&client_id={conn.pk}&client_assertion_type='
                'urn%3Aietf%3Aparams%3Aoauth%3Aclient-assertion-type%3Ajwt-bearer&client_assertion=x.y.z').encode()
        self.net.request('POST', f'{CS_BASE}/connect/v1/token',
                         {'Content-Type': 'application/x-www-form-urlencoded'}, body)
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='token.issue', connection_id=str(conn.pk))
                        .exclude(result='ok').exists())

    def test_scheduled_task_summarises(self):
        from io import StringIO
        from django.core.management import call_command
        from connect import denials
        from connect.models import ConnectAuditEvent
        denials.note(denials.token_reason('invalid_client'), source_ip='203.0.113.5', path='/connect/v1/token')
        from api_access.models import ApiAccessDecision
        ApiAccessDecision.objects.update(created_at=timezone.now() - datetime.timedelta(minutes=3))
        call_command('connect_deliver_events', stdout=StringIO())
        self.assertEqual(ConnectAuditEvent.objects.filter(operation='refusals.summary').count(), 1)


# --- QC-14 ---------------------------------------------------------------------------

class ClientRequiresActive(ConnectTestCase):
    def test_call_on_suspended_connection(self):
        from connect import client
        from connect.models import Connection
        conn, _ = self.pair_outbound()
        url = f'{PEER_BASE}/connect/v1/test'
        client.get_token(conn)                       # a token is cached in this process
        Connection.objects.filter(pk=conn.pk).update(state=Connection.SUSPENDED)   # "another worker"
        self.assertEqual(conn.state, Connection.ACTIVE)                             # stale copy here
        before = len(self.net.log)
        for fn in (lambda: client.call(conn, 'POST', url), lambda: client.get_token(conn)):
            with self.assertRaises(ConnectError) as e:
                fn()
            self.assertEqual(e.exception.code, 'connection_inactive')
        self.assertEqual(len(self.net.log), before)
        self.assertFalse([k for k in client._cache if k[0] == str(conn.pk)])

    def test_revoked_connection(self):
        from connect import client, lifecycle
        conn, _ = self.pair_outbound()
        lifecycle.revoke(conn, self.admin)
        with self.assertRaises(ConnectError) as e:
            client.get_token(conn)
        self.assertEqual(e.exception.code, 'connection_inactive')
