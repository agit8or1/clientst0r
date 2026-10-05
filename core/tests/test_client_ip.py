"""Client-address resolution behind the real deployment topology (PR #148 + follow-up).

PR #148 replaced "first X-Forwarded-For entry wins" (forgeable by any
client) with a walk from the nearest trusted proxy. Two deployment facts it
didn't account for are pinned here:

  * Native installs proxy nginx -> gunicorn over a unix socket, where
    REMOTE_ADDR is empty. That peer is a local process and must count as a
    trusted proxy; otherwise every request resolves to "no address" and the
    firewall refuses all traffic.
  * nginx always sets X-Real-IP, so "no forwarding headers" can't be the
    test for the LAN exemption. A private address resolved through a
    trusted proxy is a real LAN client; one that is merely the address of
    an untrusted proxy peer is not.
"""
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.client_ip import get_client_ip, is_trusted_peer

# What /etc/nginx's `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`
# produces when a client forges the header: "<forged>, <real peer>".
FORGED = '127.0.0.1'
REAL_PUBLIC = '81.2.69.50'  # a public address
LAN_CLIENT = '192.168.1.50'
DOCKER_NGINX = '172.18.0.5'


def _request(remote_addr, xff=None, real_ip=None):
    meta = {'REMOTE_ADDR': remote_addr}
    if xff is not None:
        meta['HTTP_X_FORWARDED_FOR'] = xff
    if real_ip is not None:
        meta['HTTP_X_REAL_IP'] = real_ip
    request = RequestFactory().get('/', **meta)
    request.user = AnonymousUser()
    return request


@override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '::1/128'])
class ClientIPTests(SimpleTestCase):
    def test_unix_socket_peer_is_trusted_local_proxy(self):
        request = _request('', xff=f'{FORGED}, {REAL_PUBLIC}', real_ip=REAL_PUBLIC)
        self.assertTrue(is_trusted_peer(request))
        self.assertEqual(get_client_ip(request), REAL_PUBLIC)  # forged prefix ignored

    def test_unix_socket_without_chain_is_local(self):
        self.assertEqual(get_client_ip(_request('')), '127.0.0.1')

    def test_loopback_tcp_proxy_same_as_unix_socket(self):
        self.assertEqual(get_client_ip(_request('127.0.0.1', xff=f'{FORGED}, {REAL_PUBLIC}')), REAL_PUBLIC)

    def test_direct_client_cannot_forge(self):
        # e.g. a client reaching gunicorn's TCP port directly, skipping nginx
        request = _request(REAL_PUBLIC, xff=FORGED, real_ip=FORGED)
        self.assertFalse(is_trusted_peer(request))
        self.assertEqual(get_client_ip(request), REAL_PUBLIC)

    def test_untrusted_proxy_peer_is_the_client(self):
        request = _request(DOCKER_NGINX, xff=REAL_PUBLIC)
        self.assertFalse(is_trusted_peer(request))
        self.assertEqual(get_client_ip(request), DOCKER_NGINX)

    @override_settings(TRUSTED_PROXY_CIDRS=['172.18.0.0/16'])
    def test_configured_proxy_cidr_is_honoured(self):
        self.assertEqual(get_client_ip(_request(DOCKER_NGINX, xff=f'{FORGED}, {REAL_PUBLIC}')), REAL_PUBLIC)

    def test_malformed_chain_from_trusted_proxy_fails_closed(self):
        self.assertIsNone(get_client_ip(_request('', xff='not-an-ip')))
        self.assertIsNone(get_client_ip(_request('garbage')))


@override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '::1/128'])
class FirewallLANExemptionTests(TestCase):
    """Allowlist mode with no rules: everything is blocked unless exempt."""

    def setUp(self):
        from core.models import FirewallSettings
        fw = FirewallSettings.get_settings()
        fw.ip_firewall_enabled = True
        fw.ip_firewall_mode = 'allowlist'
        fw.save()

    def _blocked(self, request):
        from core.firewall_middleware import FirewallMiddleware
        mw = FirewallMiddleware(get_response=lambda r: HttpResponse('ok'))
        return mw.process_request(request) is not None

    def test_lan_client_through_local_nginx_is_exempt(self):
        # Unix-socket nginx sets both headers; the client really is on the LAN.
        self.assertFalse(self._blocked(_request('', xff=LAN_CLIENT, real_ip=LAN_CLIENT)))

    def test_public_client_through_local_nginx_is_blocked(self):
        self.assertTrue(self._blocked(_request('', xff=REAL_PUBLIC, real_ip=REAL_PUBLIC)))

    def test_public_client_forging_lan_address_is_blocked(self):
        self.assertTrue(self._blocked(_request('', xff=f'{LAN_CLIENT}, {REAL_PUBLIC}', real_ip=REAL_PUBLIC)))

    def test_direct_lan_client_is_exempt(self):
        self.assertFalse(self._blocked(_request(LAN_CLIENT)))

    def test_untrusted_private_proxy_does_not_exempt_everyone_behind_it(self):
        # An unlisted proxy container forwarding a public client: the address
        # resolved is the container's own private IP, which must not count as LAN.
        self.assertTrue(self._blocked(_request(DOCKER_NGINX, xff=REAL_PUBLIC, real_ip=REAL_PUBLIC)))

    def test_unresolvable_address_is_refused(self):
        self.assertTrue(self._blocked(_request('', xff='not-an-ip')))
