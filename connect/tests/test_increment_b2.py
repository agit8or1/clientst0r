"""Quick Connect increment B2 (roadmap 79.12, 79.15): approved outbound
destinations, address pinning, SPKI pins, Security Blocked
(docs/plans/quick-connect/INCREMENTS.md §B2, DESIGN.md §7)."""
import datetime
import ipaddress
import json
import os
import shutil
import socket
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from agit8or_connect.errors import ConnectError

from .base import CS_BASE, PEER_DEST_IP, ConnectTestCase

UI = '/settings/integrations/connected-apps/'


class _Req:
    def __init__(self, user):
        from tech_access import protected
        self.user, self.session = user, {protected.SESSION_KEY: int(time.time())}
        self.META, self.path = {}, '/'


def _pki():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    now = datetime.datetime.now(datetime.timezone.utc)
    name = lambda cn: x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])  # noqa: E731
    pem_key = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,  # noqa: E731
                                        serialization.NoEncryption()).decode()
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM).decode()  # noqa: E731
    ca_k = ec.generate_private_key(ec.SECP256R1())
    ca = (x509.CertificateBuilder().subject_name(name('b2 CA')).issuer_name(name('b2 CA'))
          .public_key(ca_k.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_k.public_key()), critical=False)
          .sign(ca_k, hashes.SHA256()))

    def leaf(san):
        k = ec.generate_private_key(ec.SECP256R1())
        c = (x509.CertificateBuilder().subject_name(name('peer')).issuer_name(ca.subject).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
             .not_valid_after(now + datetime.timedelta(days=1))
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_k.public_key()), critical=False)
             .add_extension(x509.SubjectAlternativeName(san), critical=False).sign(ca_k, hashes.SHA256()))
        return pem(c), pem_key(k)
    with_ip = leaf([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))])
    without_ip = leaf([x509.DNSName('peer.example')])
    return {'ca': pem(ca), 'with_ip': with_ip, 'without_ip': without_ip}


class _Server:
    """HTTPS on 127.0.0.1: /ok answers 200, /redirect answers 302 to /target."""

    def __init__(self, cert_key, tmp):
        cert, key = os.path.join(tmp, f'{id(self)}.pem'), os.path.join(tmp, f'{id(self)}.key')
        with open(cert, 'w') as f:
            f.write(cert_key[0])
        with open(key, 'w') as f:
            f.write(cert_key[1])
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        hits = self.hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/target')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.spki = _spki_of(cert_key[0])
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _spki_of(pem):
    from cryptography import x509
    from core.safe_http import spki_sha256
    from cryptography.hazmat.primitives import serialization
    return spki_sha256(x509.load_pem_x509_certificate(pem.encode()).public_bytes(serialization.Encoding.DER))


class RealTls(SimpleTestCase):
    """Local TLS servers with a test CA; loopback is never allowed for Connect,
    so only these test servers are let through the address check."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pki = _pki()
        cls.tmp = tempfile.mkdtemp(prefix='qcb2-')
        cls.good = _Server(cls.pki['with_ip'], cls.tmp)
        cls.noip = _Server(cls.pki['without_ip'], cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.good.close()
        cls.noip.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        p = mock.patch('core.safe_http.is_allowed_ip', lambda *a, **k: True)
        p.start()
        self.addCleanup(p.stop)

    def t(self, server, **kw):
        from agit8or_connect.adapters.safe_http import SafeHttpTransport
        args = dict(ca_pem=self.pki['ca'], allowed_ports={server.port}, timeout=5, pinned=['127.0.0.1/32'])
        args.update(kw)
        return SafeHttpTransport(**args)

    def test_ip_literal_needs_ip_san(self):
        r = self.t(self.good).request('GET', f'https://127.0.0.1:{self.good.port}/ok')
        self.assertEqual(r.status, 200)
        with self.assertRaises(ConnectError) as e:
            self.t(self.noip).request('GET', f'https://127.0.0.1:{self.noip.port}/ok')
        self.assertEqual(e.exception.code, 'certificate_name_mismatch')

    def test_spki_pin(self):
        self.assertEqual(self.t(self.good, spki_pins=[self.good.spki]).request(
            'GET', f'https://127.0.0.1:{self.good.port}/ok').status, 200)
        before = len(self.good.hits)
        with self.assertRaises(ConnectError) as e:
            self.t(self.good, spki_pins=['AAAA' + self.good.spki[4:]]).request(
                'GET', f'https://127.0.0.1:{self.good.port}/ok')
        self.assertEqual(e.exception.code, 'spki_mismatch')
        self.assertEqual(e.exception.evidence['spki'], self.good.spki)
        self.assertEqual(len(self.good.hits), before)    # nothing sent after the handshake

    def test_redirect_not_followed_and_proxy_env_ignored(self):
        with mock.patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:9', 'https_proxy': 'http://127.0.0.1:9',
                                          'ALL_PROXY': 'http://127.0.0.1:9'}):
            r = self.t(self.good).request('GET', f'https://127.0.0.1:{self.good.port}/redirect')
        self.assertEqual(r.status, 302)
        self.assertNotIn('/target', self.good.hits)

    def test_connected_address_outside_pin(self):
        with self.assertRaises(ConnectError) as e:
            self.t(self.good, pinned=['127.0.0.2/32']).request('GET', f'https://127.0.0.1:{self.good.port}/ok')
        self.assertEqual(e.exception.code, 'destination_changed')


class Rebinding(SimpleTestCase):
    def _gai(self, ip):
        return lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]

    def test_resolution_outside_pin_refused_before_any_byte(self):
        from agit8or_connect.adapters.safe_http import SafeHttpTransport
        connect = mock.Mock(side_effect=AssertionError('connected'))
        with mock.patch('core.safe_http.socket.getaddrinfo', self._gai('93.184.216.41')), \
                mock.patch('core.safe_http.urllib3_connection.create_connection', connect):
            with self.assertRaises(ConnectError) as e:
                SafeHttpTransport(pinned=['93.184.216.40/32']).request('GET', 'https://peer.example/x')
        self.assertEqual(e.exception.code, 'destination_changed')
        self.assertEqual(e.exception.evidence['addresses'], ['93.184.216.41'])
        connect.assert_not_called()

    def test_peer_recheck(self):
        from agit8or_connect.adapters.safe_http import SafeHttpTransport
        sock = mock.Mock()
        sock.getpeername.return_value = ('93.184.216.99', 443)
        with mock.patch('core.safe_http.socket.getaddrinfo', self._gai('93.184.216.40')), \
                mock.patch('core.safe_http.urllib3_connection.create_connection', return_value=sock):
            with self.assertRaises(ConnectError) as e:
                SafeHttpTransport(pinned=['93.184.216.40/32']).request('GET', 'https://peer.example/x')
        self.assertIn(e.exception.code, ('destination_changed', 'blocked_destination'))
        sock.sendall.assert_not_called()
        sock.close.assert_called()

    def test_unpinned_callers_unchanged(self):
        from core.safe_http import OutboundPolicy, PUBLIC_WEB, configured_service_policy
        self.assertIsNone(PUBLIC_WEB.pinned)
        self.assertIsNone(OutboundPolicy().spki_pins)
        self.assertIsNone(configured_service_policy().pinned)


class AddressValidation(SimpleTestCase):
    def test_sizes_and_kinds(self):
        from connect import destinations
        self.assertEqual(destinations.validate_address('93.184.216.0/24')[0], '93.184.216.0/24')
        self.assertEqual(destinations.validate_address('2606:4700:1::/48')[0], '2606:4700:1::/48')
        for bad in ('93.184.216.0/23', '2606:4700::/47', '0.0.0.0/0', '::/0'):
            with self.assertRaises(ValidationError, msg=bad):
                destinations.validate_address(bad)
        for never in ('127.0.0.1', '169.254.169.254', '169.254.1.1', '::1', 'fe80::1', '::ffff:127.0.0.1'):
            with self.assertRaises(ValidationError, msg=never):
                destinations.validate_address(never, private=True)
        with self.assertRaises(ValidationError):
            destinations.validate_address('10.0.0.5')
        self.assertEqual(destinations.validate_address('10.0.0.5', private=True), ('10.0.0.5/32', True))

    def test_widening(self):
        from connect import destinations
        old = destinations.entries_for(['93.184.216.40'])
        self.assertFalse(destinations.is_widening(old, destinations.entries_for(['93.184.216.41'])))
        self.assertTrue(destinations.is_widening(old, destinations.entries_for(['93.184.216.0/24'])))
        self.assertTrue(destinations.is_widening(old, destinations.entries_for(['10.0.0.5'], private=True)))


class SecurityBlocked(ConnectTestCase):
    def setUp(self):
        super().setUp()
        self.pconn, self.conn = self.pair_inbound()

    def _changed(self, *a, **k):
        e = ConnectError('destination_changed', 'outside the approved set', 502)
        e.evidence = {'addresses': ['93.184.216.77']}
        raise e

    def test_pinned_transport_used_for_connection(self):
        from connect import transport
        seen = {}
        with mock.patch('connect.transport.factory', lambda **kw: seen.update(kw) or self.net):
            transport.for_connection(self.conn)
        self.assertEqual(seen['pinned'], frozenset({ipaddress.ip_network(PEER_DEST_IP + '/32')}))
        self.assertFalse(seen['allow_private'])

    def test_unapproved_destination_makes_no_request(self):
        from connect import events, transport
        from connect.models import ApprovedDestination
        ApprovedDestination.objects.filter(connection=self.conn).update(addresses=[])
        with self.assertRaises(ConnectError) as e:
            transport.for_connection(self.conn)
        self.assertEqual(e.exception.code, 'destination_unapproved')
        ev = events.enqueue(self.conn, 'connect.test', {})
        self.assertFalse(events.deliver(ev))
        ev.refresh_from_db()
        self.assertEqual(ev.attempts, 0)       # not counted against the event

    def test_dynamic_ip_change_blocks_until_approved_and_retested(self):
        from connect import client, destinations, events
        from connect.models import ConnectAuditEvent, Connection
        calls = []
        with mock.patch.object(type(self.net), 'request', lambda *a, **k: calls.append(a) or self._changed()):
            with self.assertRaises(ConnectError):
                client.call(self.conn, 'GET', self.conn.endpoint('capabilities'))
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.state, Connection.SECURITY_BLOCKED)
        self.assertEqual(self.conn.security_block_code, 'destination_changed')
        self.assertEqual(self.conn.security_block_detail['addresses'], ['93.184.216.77'])
        self.assertIn('93.184.216.77', self.conn.last_error)
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='connection.security_blocked').exists())
        # No automatic retry, inbound refused too.
        n = len(calls)
        events.enqueue(self.conn, 'connect.test', {})
        with mock.patch.object(type(self.net), 'request', lambda *a, **k: calls.append(a) or self._changed()):
            events.deliver_due()
            with self.assertRaises(ConnectError):
                client.get_token(self.conn)
        self.assertEqual(len(calls), n)
        with self.assertRaises(ConnectError):
            self.peer.get_token(self.pconn.id)
        page = self.ui.get(UI + f'{self.conn.pk}/', secure=True, HTTP_HOST='clientst0r.test').content.decode()
        self.assertIn('data-connect-state="security_blocked"', page)
        self.assertIn('Approve new address', page)
        # Retest without an approval: still blocked.
        self.assertFalse(destinations.retest(self.conn, self.admin))
        # Approve the new (exact public) address: one administrator, fresh re-auth; then the retest passes.
        ch = destinations.propose_change(self.conn, ['93.184.216.77'], self.admin)
        self.assertFalse(ch.widening)
        self.assertIsNone(destinations.approve(ch, _Req(self.admin)))
        # D: the retest is the full commit-gate test (DNS included), so the
        # name now resolves to the approved new address.
        host = destinations.host_port(self.conn.base_url)
        with mock.patch('connect.transport.probe', lambda url, **kw: destinations.Preview(
                host=host[0], port=host[1], addresses=['93.184.216.77'], cert_names=[host[0]])):
            self.assertTrue(destinations.retest(self.conn, self.admin))
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.state, Connection.ACTIVE)
        self.assertEqual(self.conn.security_block_code, 'destination_changed')   # evidence kept

    def test_private_or_range_needs_second_admin(self):
        from connect import destinations
        from tech_access import protected
        ch = destinations.propose_change(self.conn, ['93.184.216.0/24'], self.admin)
        self.assertTrue(ch.widening)
        pc = destinations.approve(ch, _Req(self.admin))
        protected.confirm(pc, _Req(self.admin))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(pc, _Req(self.admin))
        protected.approve(pc, _Req(self.admin2))
        self.assertEqual(destinations.get(self.conn).nets, ['93.184.216.0/24'])
        with self.assertRaises(ValidationError):
            destinations.propose_change(self.conn, ['93.184.216.0/23'], self.admin)

    def test_spki_mismatch_blocks_without_retry(self):
        from connect import lifecycle
        from connect.models import Connection

        def spki(*a, **k):
            e = ConnectError('spki_mismatch', 'pin', 502)
            e.evidence = {'spki': 'abc='}
            raise e
        with mock.patch.object(type(self.net), 'request', spki):
            lifecycle.test_connection(self.conn, self.admin)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.state, Connection.SECURITY_BLOCKED)
        self.assertEqual(self.conn.security_block_code, 'spki_mismatch')


class PairingDestinations(ConnectTestCase):
    def test_outbound_destination_approved_in_wizard(self):
        from connect import destinations
        conn, pconn = self.pair_outbound()
        d = destinations.get(conn)
        self.assertEqual(d.nets, [PEER_DEST_IP + '/32'])
        self.assertEqual(d.status, 'active')
        self.assertEqual(d.host, 'rmm.test')

    def test_inbound_requires_destination_addresses(self):
        from connect import pairing
        from connect.models import PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=self.SCOPES, proposed_tenants=[])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        with self.assertRaises(pairing.PairingFailed):
            pairing.approve_inbound(preq, scopes=self.SCOPES, grants=[], user=self.admin)
        with self.assertRaises(pairing.PairingFailed):
            pairing.approve_inbound(preq, scopes=self.SCOPES, grants=[], user=self.admin,
                                    destination_addresses=['127.0.0.1'])

    def test_wizard_shows_destination_preview(self):
        r = self.ui.post(UI + 'new/rem0te/', {'url': self.peer.base, 'op': 'verify'}, secure=True,
                         HTTP_HOST='clientst0r.test')
        self.assertContains(r, PEER_DEST_IP)
        self.assertContains(r, 'data-connect-destination')


class MigrationFromBaseUrl(TestCase):
    def test_existing_connections_get_staged_destination(self):
        import importlib
        from django.apps import apps
        from connect.models import ApprovedDestination, Connection
        c = Connection.objects.create(direction='outbound', state='active', remote_app_type='rem0te',
                                      remote_installation_id='x', base_url='https://peer.example:8443/',
                                      tls_ca_bundle='-----BEGIN CERTIFICATE-----')
        Connection.objects.create(direction='outbound', state='revoked', remote_app_type='rem0te',
                                  remote_installation_id='y', base_url='https://old.example/')
        mig = importlib.import_module('connect.migrations.0003_approved_destinations')
        ApprovedDestination.objects.all().delete()
        mig.from_base_url(apps, None)
        d = ApprovedDestination.objects.get()
        self.assertEqual((d.connection_id, d.host, d.port, d.addresses, d.status, d.trust),
                         (c.pk, 'peer.example', 8443, [], 'staged', 'private_ca'))
