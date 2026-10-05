"""SSRF guard for user-supplied URLs (core.safe_http).

Two layers are tested separately because each must hold on its own:

  * `validate_public_url` — the URL text, every spelling of an internal
    address, and every non-http(s) scheme.
  * the connection guard — real HTTP through requests/urllib3 against a
    local server, with DNS (`socket.getaddrinfo`) and the connect step
    faked. This proves that what is *connected to* is the address that was
    validated, that redirects are re-checked, and that a name re-resolving
    to an internal address (DNS rebinding) is refused.

The local server listens on 127.0.0.1. The fake connect reports the peer as
the public IP that was asked for, so the guard's own peer check passes only
when it should.
"""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import requests
from django.test import SimpleTestCase

from core import safe_http
from core.safe_http import (
    FetchError, UnsafeURLError, fetch_public_url, is_public_ip, validate_public_url,
)

PUBLIC_IP = '93.184.215.14'
PUBLIC_IP_2 = '151.101.1.1'


class IsPublicIPTests(SimpleTestCase):
    def test_public_addresses_allowed(self):
        for ip in (PUBLIC_IP, '8.8.8.8', '172.32.0.1', '2606:4700:4700::1111',
                   '64:ff9b::808:808'):
            with self.subTest(ip=ip):
                self.assertTrue(is_public_ip(ip))

    def test_internal_addresses_blocked(self):
        for ip in (
            '127.0.0.1', '127.255.255.254', '0.0.0.0', '0.1.2.3',
            '10.0.0.1', '10.255.255.255', '172.16.0.1', '172.31.255.255',
            '192.168.0.1', '192.168.255.255', '169.254.169.254', '169.254.0.1',
            '100.64.0.1', '100.100.100.200', '192.0.0.192', '192.0.2.1',
            '198.51.100.1', '203.0.113.1', '198.18.0.1', '224.0.0.1',
            '239.255.255.250', '240.0.0.1', '255.255.255.255',
            '::', '::1', 'fe80::1', 'fe80::1%eth0', 'fc00::1', 'fd00:ec2::254',
            'fec0::1', 'ff02::1', '2001:db8::1', '::ffff:127.0.0.1',
            '::ffff:10.0.0.1', '::ffff:169.254.169.254', '::127.0.0.1',
            '64:ff9b::a00:1', '64:ff9b::7f00:1', '2002:7f00:1::1', '2001::1',
            'not-an-ip', '',
        ):
            with self.subTest(ip=ip):
                self.assertFalse(is_public_ip(ip))


class ValidatePublicURLTests(SimpleTestCase):
    def test_public_urls_allowed(self):
        for url in (
            'http://example.com/', 'https://example.com/parcel?id=1',
            'HTTPS://Example.COM./x', 'https://example.com:443/', 'http://example.com:80/',
            f'http://{PUBLIC_IP}/', 'https://[2606:4700:4700::1111]/',
            '  https://example.com/padded  ',
        ):
            with self.subTest(url=url):
                self.assertEqual(validate_public_url(url), url.strip())

    def test_missing_or_malformed(self):
        for url in (None, '', '   ', 123, 'example.com', '//example.com/', 'http://',
                    'http:///path', 'http://[::1', 'http://exa mple.com/',
                    'http://example.com\\@127.0.0.1/', 'http://example.com:99999/',
                    'http://example.com:abc/', 'http://a\x00b/', 'https://' + 'a' * 3000,
                    'http://..'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(url)

    def test_unsupported_schemes(self):
        for url in ('file:///etc/passwd', 'ftp://example.com/', 'gopher://example.com:70/_x',
                    'dict://example.com:11211/stat', 'javascript:alert(1)',
                    'data:text/html,hi', 'ldap://example.com/', 'jar:http://example.com!/'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(url)

    def test_embedded_credentials(self):
        for url in ('http://user:pass@example.com/', 'http://user@example.com/',
                    'http://example.com@127.0.0.1/', 'http://@example.com/'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(url)

    def test_ports_other_than_80_443(self):
        for port in (0, 21, 22, 25, 3306, 5432, 6379, 8000, 8080, 8443, 11211):
            with self.subTest(port=port):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(f'http://example.com:{port}/')

    def test_localhost_names(self):
        for url in ('http://localhost/', 'http://LOCALHOST/', 'http://localhost./',
                    'http://api.localhost/', 'http://localhost.localdomain/',
                    'http://ip6-localhost/', 'http://metadata.google.internal/computeMetadata/v1/',
                    'http://metadata/', 'http://printer.local/', 'http://db.internal/',
                    'http://1.0.0.127.in-addr.arpa/'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(url)

    def test_internal_ip_literals(self):
        for host in ('127.0.0.1', '127.0.0.1.', '0.0.0.0', '169.254.169.254', '10.0.0.1',
                     '10.20.30.40', '172.16.0.1', '172.31.0.1', '192.168.1.1', '100.64.0.1',
                     '[::1]', '[::]', '[fe80::1]', '[fe80::1%25eth0]', '[fc00::1]',
                     '[fd12:3456::1]', '[fd00:ec2::254]', '[::ffff:127.0.0.1]',
                     '[::ffff:192.168.0.1]', '[::ffff:a9fe:a9fe]', '[0:0:0:0:0:ffff:7f00:1]'):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(f'http://{host}/')

    def test_non_canonical_numeric_ip_forms(self):
        # Every one of these is 127.0.0.1 or 169.254.169.254 to inet_aton/glibc.
        for host in ('2130706433', '0x7f000001', '0x7F000001', '0177.0.0.1', '0177.1',
                     '127.1', '127.0.1', '0x7f.0.0.1', '0x7f.1', '017700000001',
                     '2852039166', '0xa9fea9fe', '0251.0376.0251.0376', '08.1'):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeURLError):
                    validate_public_url(f'http://{host}/')


# --- connection guard ------------------------------------------------------

ROUTES = {
    '/ok': (200, {'Content-Type': 'text/html; charset=utf-8'}, b'<html><body>Parcel 42</body></html>'),
    '/no-type': (200, {}, b'<html>untyped</html>'),
    '/json': (200, {'Content-Type': 'application/json'}, b'{"a": 1}'),
    '/png': (200, {'Content-Type': 'image/png'}, b'\x89PNG\r\n\x1a\n'),
    '/binary-html': (200, {'Content-Type': 'text/html'}, b'<html>\x00\x01\x02</html>'),
    '/bad-charset': (200, {'Content-Type': 'text/html; charset=nope-9'}, b'<html>ok \xff</html>'),
    '/500': (500, {'Content-Type': 'text/html'}, b'internal secret stacktrace'),
    '/204': (204, {}, b''),
    '/to-ok': (302, {'Location': '/ok'}, b''),
    '/to-ok-close': (302, {'Location': '/ok', 'Connection': 'close'}, b''),
    '/to-localhost': (302, {'Location': 'http://localhost/admin'}, b''),
    '/to-loopback-ip': (301, {'Location': 'http://127.0.0.1/'}, b''),
    '/to-private-ip': (307, {'Location': 'http://10.0.0.5/'}, b''),
    '/to-metadata': (308, {'Location': 'http://169.254.169.254/latest/meta-data/'}, b''),
    '/to-mapped-v6': (302, {'Location': 'http://[::ffff:10.0.0.1]/'}, b''),
    '/to-decimal-ip': (302, {'Location': 'http://2130706433/'}, b''),
    '/to-file': (302, {'Location': 'file:///etc/passwd'}, b''),
    '/to-gopher': (302, {'Location': 'gopher://public.example:70/_INFO'}, b''),
    '/to-port': (302, {'Location': 'http://public.example:6379/'}, b''),
    '/to-internal-name': (302, {'Location': 'http://internal.example/'}, b''),
    '/to-creds': (302, {'Location': 'http://u:p@public.example/ok'}, b''),
    '/loop': (302, {'Location': '/loop'}, b''),
    '/hop1': (302, {'Location': '/hop2'}, b''),
    '/hop2': (302, {'Location': '/hop3'}, b''),
    '/hop3': (302, {'Location': '/hop4'}, b''),
    '/hop4': (302, {'Location': '/ok'}, b''),
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.seen_paths.append(self.path)
        if self.path == '/big-declared':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(50 * 1024 * 1024))
            self.end_headers()
            return
        if self.path == '/big-undeclared':
            # No Content-Length: body delimited by close. Streams past the cap.
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                for _ in range(64):
                    self.wfile.write(b'A' * 65536)
            except OSError:
                pass
            self.close_connection = True
            return
        if self.path == '/slow':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', '100')
            self.end_headers()
            time.sleep(2)
            return
        status, headers, body = ROUTES.get(self.path, (404, {}, b'nope'))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        if status != 204:
            self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if headers.get('Connection') == 'close':
            self.close_connection = True


class _PeerOverrideSocket:
    """A real socket to the local server that reports a chosen peer address."""

    def __init__(self, sock, peer):
        self._sock = sock
        self._peer = peer

    def getpeername(self):
        return (self._peer, 80)

    def __getattr__(self, name):
        return getattr(self._sock, name)


class _FakeNetworkTestCase(SimpleTestCase):
    """A local HTTP server, with DNS and the connect step faked (see module docstring)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        cls.server.seen_paths = []
        cls.server.daemon_threads = True
        cls.server.handle_error = lambda *args: None  # client resets are expected here
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        self.server.seen_paths.clear()
        # name -> list of answers; each lookup pops the next answer (last one sticks)
        self.dns = {
            'public.example': [[PUBLIC_IP]],
            'internal.example': [['10.0.0.7']],
            'v6internal.example': [['fd00::7']],
            'mixed.example': [[PUBLIC_IP, '10.0.0.7']],
            'mixed-v6.example': [[PUBLIC_IP, '::1']],
            'mapped.example': [['::ffff:127.0.0.1']],
            'metadata.example': [['169.254.169.254']],
            'twopublic.example': [[PUBLIC_IP, PUBLIC_IP_2]],
        }
        self.lookups = []
        self.connected_to = []
        self.peer_override = None
        self.connect_error = None

        real_getaddrinfo = socket.getaddrinfo
        real_create_connection = safe_http.urllib3_connection.create_connection

        def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            try:
                # IP literals: numeric only, never DNS.
                return real_getaddrinfo(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)
            except socket.gaierror:
                pass
            self.lookups.append(host)
            if host not in self.dns:
                raise socket.gaierror(socket.EAI_NONAME, 'Name or service not known')
            answers = self.dns[host]
            ips = answers.pop(0) if len(answers) > 1 else answers[0]
            out = []
            for ip in ips:
                fam = socket.AF_INET6 if ':' in ip else socket.AF_INET
                sa = (ip, port, 0, 0) if fam == socket.AF_INET6 else (ip, port)
                out.append((fam, socket.SOCK_STREAM, 6, '', sa))
            return out

        def fake_create_connection(address, timeout=None, source_address=None, socket_options=None):
            ip, port = address
            self.connected_to.append((ip, port))
            if self.connect_error is not None:
                raise self.connect_error
            sock = real_create_connection(('127.0.0.1', self.server.server_address[1]), timeout)
            return _PeerOverrideSocket(sock, self.peer_override or ip)

        patches = [
            mock.patch('socket.getaddrinfo', side_effect=fake_getaddrinfo),
            mock.patch.object(safe_http.urllib3_connection, 'create_connection',
                              side_effect=fake_create_connection),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)



class ConnectionGuardTests(_FakeNetworkTestCase):
    """End-to-end through requests + urllib3, with DNS and connect faked."""

    # -- valid ---------------------------------------------------------------
    def test_public_http_url_fetched(self):
        result = fetch_public_url('http://public.example/ok')
        self.assertIn('Parcel 42', result.text)
        self.assertEqual(result.content_type, 'text/html')
        # Connected to the validated IP literal, on the URL's port.
        self.assertEqual(self.connected_to, [(PUBLIC_IP, 80)])
        self.assertEqual(self.lookups, ['public.example'])

    def test_https_connection_keeps_hostname_for_sni_and_cert_check(self):
        import requests
        session = safe_http.build_guarded_session()
        adapter = session.get_adapter('https://public.example/')
        prepared = session.prepare_request(requests.Request('GET', 'https://public.example/'))
        pool = adapter.get_connection_with_tls_context(prepared, verify=True)
        self.assertIsInstance(pool, safe_http._GuardedHTTPSConnectionPool)
        self.assertEqual(pool.cert_reqs, 'CERT_REQUIRED')
        conn = pool._new_conn()
        self.assertIsInstance(conn, safe_http._GuardedHTTPSConnection)
        self.assertEqual(conn.host, 'public.example')   # SNI + hostname verification
        self.assertTrue(session.verify)
        self.assertFalse(session.trust_env)

    def test_https_url_to_internal_name_blocked_before_tls(self):
        with self.assertRaises(UnsafeURLError):
            fetch_public_url('https://internal.example/')
        self.assertEqual(self.connected_to, [])

    def test_public_redirect_followed(self):
        result = fetch_public_url('http://public.example/to-ok')
        self.assertIn('Parcel 42', result.text)
        self.assertEqual(self.server.seen_paths, ['/to-ok', '/ok'])

    def test_missing_content_type_accepted(self):
        self.assertIn('untyped', fetch_public_url('http://public.example/no-type').text)

    def test_unknown_charset_falls_back(self):
        self.assertIn('ok', fetch_public_url('http://public.example/bad-charset').text)

    # -- DNS -------------------------------------------------------------------
    def test_name_resolving_to_private_ip_blocked(self):
        for host in ('internal.example', 'v6internal.example', 'mapped.example', 'metadata.example'):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeURLError):
                    fetch_public_url(f'http://{host}/ok')
        self.assertEqual(self.connected_to, [])

    def test_name_with_one_blocked_address_among_several_blocked(self):
        for host in ('mixed.example', 'mixed-v6.example'):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeURLError):
                    fetch_public_url(f'http://{host}/ok')
        self.assertEqual(self.connected_to, [])

    def test_unresolvable_name_is_fetch_error(self):
        with self.assertRaises(FetchError):
            fetch_public_url('http://nxdomain.example/ok')

    def test_dns_rebinding_connects_to_validated_ip_only(self):
        # First answer public, every later answer internal. The guard must do
        # exactly one lookup and connect to that answer's IP — a second
        # lookup (as a validate-then-requests.get design would do) would get
        # the internal one.
        self.dns['rebind.example'] = [[PUBLIC_IP], ['127.0.0.1']]
        result = fetch_public_url('http://rebind.example/ok')
        self.assertIn('Parcel 42', result.text)
        self.assertEqual(self.lookups, ['rebind.example'])
        self.assertEqual(self.connected_to, [(PUBLIC_IP, 80)])

    def test_dns_rebinding_on_new_connection_after_redirect_blocked(self):
        # Same host redirects to itself and closes the connection, so the
        # next hop must reconnect; by then the name points at loopback.
        self.dns['rebind.example'] = [[PUBLIC_IP], ['127.0.0.1']]
        with self.assertRaises(UnsafeURLError):
            fetch_public_url('http://rebind.example/to-ok-close')
        self.assertEqual(self.lookups, ['rebind.example', 'rebind.example'])
        self.assertEqual(self.connected_to, [(PUBLIC_IP, 80)])
        self.assertEqual(self.server.seen_paths, ['/to-ok-close'])

    def test_connected_peer_must_match_validated_address(self):
        self.peer_override = '10.0.0.9'
        with self.assertRaises(UnsafeURLError):
            fetch_public_url('http://public.example/ok')
        self.assertEqual(self.server.seen_paths, [])

    def test_validated_url_bypassed_at_connection_layer_still_blocked(self):
        # Even a caller that skips validate_public_url and uses the guarded
        # session directly cannot reach an internal address or port.
        session = safe_http.build_guarded_session()
        with self.assertRaises(UnsafeURLError):
            session.get('http://internal.example/ok', timeout=2)
        with self.assertRaises(UnsafeURLError):
            session.get('http://public.example:6379/', timeout=2)
        with self.assertRaises(UnsafeURLError):
            session.get('http://127.0.0.1/', timeout=2)
        self.assertEqual(self.connected_to, [])

    def test_proxies_refused(self):
        session = safe_http.build_guarded_session()
        with self.assertRaises(UnsafeURLError):
            session.get('http://public.example/ok', proxies={'http': 'http://10.0.0.1:3128'}, timeout=2)

    # -- redirects ---------------------------------------------------------------
    def test_redirects_to_internal_targets_blocked(self):
        for path in ('/to-localhost', '/to-loopback-ip', '/to-private-ip', '/to-metadata',
                     '/to-mapped-v6', '/to-decimal-ip', '/to-internal-name', '/to-port',
                     '/to-creds'):
            with self.subTest(path=path):
                self.connected_to.clear()
                with self.assertRaises(UnsafeURLError):
                    fetch_public_url(f'http://public.example{path}')
                self.assertEqual(self.connected_to, [(PUBLIC_IP, 80)])

    def test_redirect_to_non_http_scheme_blocked(self):
        for path in ('/to-file', '/to-gopher'):
            with self.subTest(path=path):
                with self.assertRaises(UnsafeURLError):
                    fetch_public_url(f'http://public.example{path}')

    def test_redirect_loop_stops(self):
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/loop')
        self.assertEqual(len(self.server.seen_paths), safe_http.MAX_REDIRECTS + 1)

    def test_too_many_redirects(self):
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/hop1')
        self.assertNotIn('/ok', self.server.seen_paths)

    # -- response handling -------------------------------------------------------
    def test_oversized_declared_response_rejected(self):
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/big-declared')

    def test_oversized_streamed_response_rejected(self):
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/big-undeclared', max_bytes=256 * 1024)

    def test_non_html_rejected(self):
        for path in ('/json', '/png', '/binary-html'):
            with self.subTest(path=path):
                with self.assertRaises(FetchError):
                    fetch_public_url(f'http://public.example{path}')

    def test_error_and_odd_statuses_rejected(self):
        for path in ('/500', '/204', '/missing'):
            with self.subTest(path=path):
                with self.assertRaises(FetchError):
                    fetch_public_url(f'http://public.example{path}')

    def test_read_timeout(self):
        with mock.patch.object(safe_http, 'READ_TIMEOUT', 0.3):
            with self.assertRaises(FetchError):
                fetch_public_url('http://public.example/slow')

    def test_total_deadline(self):
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/slow', total_timeout=0.3)

    def test_connect_timeout(self):
        self.connect_error = socket.timeout('timed out')
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/ok')

    def test_connection_refused(self):
        self.connect_error = ConnectionRefusedError(111, 'Connection refused')
        with self.assertRaises(FetchError):
            fetch_public_url('http://public.example/ok')

    def test_second_address_tried_after_first_fails(self):
        calls = []

        def flaky(address, *a, **k):
            calls.append(address[0])
            if len(calls) == 1:
                raise ConnectionRefusedError(111, 'refused')
            sock = socket.create_connection(('127.0.0.1', self.server.server_address[1]), 2)
            return _PeerOverrideSocket(sock, address[0])

        with mock.patch.object(safe_http.urllib3_connection, 'create_connection', side_effect=flaky):
            result = fetch_public_url('http://twopublic.example/ok')
        self.assertIn('Parcel 42', result.text)
        self.assertEqual(calls, [PUBLIC_IP, PUBLIC_IP_2])


# --- policies for operator-configured endpoints -----------------------------

from django.test import override_settings  # noqa: E402
from urllib3.util.retry import Retry  # noqa: E402

from core.safe_http import (  # noqa: E402
    BlockedDestinationError, OutboundPolicy, configured_service_policy, guard_session,
    is_allowed_ip, lan_controller_policy, validate_url,
)

METADATA_IPS = ('169.254.169.254', '169.254.170.2', 'fd00:ec2::254', '100.100.100.200',
                '192.0.0.192', '::ffff:169.254.169.254', '64:ff9b::a9fe:a9fe')
NON_UNICAST = ('0.0.0.0', '224.0.0.1', '255.255.255.255', '240.0.0.1', '::', 'ff02::1')


class PolicyTests(SimpleTestCase):
    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_configured_service_without_opt_in_is_public_only_any_port(self):
        policy = configured_service_policy()
        self.assertIsNone(policy.allowed_ports)
        self.assertEqual(validate_url('https://psa.example.com:8443/api', policy),
                         'https://psa.example.com:8443/api')
        for ip in ('10.0.0.5', '192.168.1.1', '127.0.0.1', '169.254.1.1', 'fd12::1', '100.64.0.1'):
            with self.subTest(ip=ip):
                self.assertFalse(is_allowed_ip(ip, policy))
        for url in ('http://localhost:8000/', 'http://unifi.local/', 'http://10.0.0.5:8443/'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_url(url, policy)

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=True)
    def test_configured_service_with_opt_in_allows_internal_but_not_metadata(self):
        policy = configured_service_policy()
        for ip in ('10.0.0.5', '192.168.1.1', '127.0.0.1', '::1', '169.254.1.1', 'fd12::1', '100.64.0.1'):
            with self.subTest(ip=ip):
                self.assertTrue(is_allowed_ip(ip, policy))
        for ip in METADATA_IPS + NON_UNICAST:
            with self.subTest(ip=ip):
                self.assertFalse(is_allowed_ip(ip, policy))
        validate_url('http://localhost:8000/', policy)
        for url in ('http://169.254.169.254/latest/meta-data/', 'http://metadata.google.internal/',
                    'http://[fd00:ec2::254]/', 'http://2130706433/'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_url(url, policy)

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_lan_controller_allows_lan_but_not_loopback_or_metadata(self):
        policy = lan_controller_policy()
        for ip in ('192.168.1.1', '10.1.2.3', '172.20.0.1', '100.64.0.1', 'fd12::1', '::ffff:192.168.1.1'):
            with self.subTest(ip=ip):
                self.assertTrue(is_allowed_ip(ip, policy))
        for ip in ('127.0.0.1', '::1', '169.254.1.1', 'fe80::1') + METADATA_IPS + NON_UNICAST:
            with self.subTest(ip=ip):
                self.assertFalse(is_allowed_ip(ip, policy))
        validate_url('https://192.168.1.1:8443/', policy)
        validate_url('https://unifi.local/', policy)
        validate_url('https://omada.home.arpa:8043/', policy)
        for url in ('https://localhost:8443/', 'http://127.0.0.1/', 'http://169.254.169.254/',
                    'http://metadata.google.internal/'):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_url(url, policy)

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=True)
    def test_lan_controller_with_opt_in_allows_loopback_not_metadata(self):
        policy = lan_controller_policy()
        self.assertTrue(is_allowed_ip('127.0.0.1', policy))
        validate_url('https://localhost:8443/', policy)
        for ip in METADATA_IPS:
            with self.subTest(ip=ip):
                self.assertFalse(is_allowed_ip(ip, policy))

    def test_public_web_unchanged(self):
        self.assertEqual(safe_http.PUBLIC_WEB, OutboundPolicy())
        self.assertFalse(is_allowed_ip('192.168.1.1'))
        with self.assertRaises(UnsafeURLError):
            validate_public_url('https://example.com:8443/')


class GuardedSessionTests(_FakeNetworkTestCase):
    """guard_session() on a plain requests.Session, as integrations use it."""

    def _session(self, policy, **kwargs):
        return guard_session(requests.Session(), policy, **kwargs)

    def test_lan_name_reachable_under_lan_policy_any_port(self):
        self.dns['controller.example'] = [['192.168.1.20']]
        with override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False):
            resp = self._session(lan_controller_policy()).get('http://controller.example:8443/ok', timeout=2)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.connected_to, [('192.168.1.20', 8443)])

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_lan_name_refused_under_configured_policy_without_opt_in(self):
        self.dns['controller.example'] = [['192.168.1.20']]
        with self.assertRaises(BlockedDestinationError) as ctx:
            self._session(configured_service_policy()).get('http://controller.example:8443/ok', timeout=2)
        # Existing `except requests.ConnectionError` handlers catch it unchanged.
        self.assertIsInstance(ctx.exception, requests.exceptions.ConnectionError)
        self.assertEqual(self.connected_to, [])

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=True)
    def test_opt_in_allows_internal_but_metadata_still_refused(self):
        self.dns['controller.example'] = [['10.0.0.20']]
        resp = self._session(configured_service_policy()).get('http://controller.example:8080/ok', timeout=2)
        self.assertEqual(resp.status_code, 200)
        with self.assertRaises(BlockedDestinationError):
            self._session(configured_service_policy()).get('http://metadata.example/latest/', timeout=2)
        with self.assertRaises(BlockedDestinationError):
            self._session(lan_controller_policy()).get('http://169.254.169.254/latest/', timeout=2)

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_redirect_followed_by_requests_is_guarded_per_hop(self):
        session = self._session(configured_service_policy())
        with self.assertRaises(BlockedDestinationError):
            session.get('http://public.example/to-private-ip', timeout=2)  # allow_redirects defaults on
        self.assertEqual(self.connected_to, [(PUBLIC_IP, 80)])

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_blocked_connection_is_not_retried(self):
        session = self._session(configured_service_policy(),
                                max_retries=Retry(total=3, backoff_factor=0))
        with self.assertRaises(BlockedDestinationError):
            session.get('http://internal.example/ok', timeout=2)
        self.assertEqual(self.lookups, ['internal.example'])

    def test_session_settings_survive_guarding(self):
        session = requests.Session()
        session.headers['X-API-Key'] = 'k'
        session.verify = False
        guarded = guard_session(session, lan_controller_policy())
        self.assertIs(guarded, session)
        self.assertEqual(session.headers['X-API-Key'], 'k')
        self.assertFalse(session.verify)
        self.assertIsInstance(session.get_adapter('https://x.example/'), safe_http.GuardedHTTPAdapter)

