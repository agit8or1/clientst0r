"""End to end with two (or three) in-memory installations built on the SDK."""
import json
import socket
import unittest

from agit8or_connect import keys, pairing, rotation
from agit8or_connect.errors import ConnectError
from agit8or_connect.http import MinimalGuardedTransport, ip_allowed
from agit8or_connect.reference_peer import API, Network, ReferencePeer
from agit8or_connect.scopes import Catalog, Scope, require_subset


class Clock:
    def __init__(self, t=1767225600):
        self.t = t

    def __call__(self):
        return self.t


def paired(net=None, clock=None, initiator_url='https://msp-a.example.test', responder=None,
           tenant='org-1', local_tenant='cust-1'):
    clock = clock or Clock()
    net = net or Network()
    b = responder or ReferencePeer('https://rmm.example.test', net, display_name='RMM', clock=clock)
    a = ReferencePeer(initiator_url, net, display_name='MSP', clock=clock, tenants={tenant: 'MSP side customer'})
    code = b.create_invitation()
    conn = a.start_pairing(b.base, code, requested_scopes=['customers:read', 'connection:read', 'events:publish'],
                           proposed_tenants=[{'id': tenant, 'label': 'Customer'}])
    bconn = b.connections[b.requests[conn.request_id]]
    b.approve(conn.request_id, scopes=['customers:read', 'connection:read', 'events:publish'],
              tenant_grants=[{'remote_tenant': tenant, 'local_tenant': local_tenant,
                              'scopes': ['customers:read', 'events:publish']}],
              requested_scopes=['connection:read'])
    assert a.poll(conn.id) == 'approved'
    a.accept(conn.id, scopes=['connection:read'])
    return a, b, conn, bconn, net, clock


class PairingFlow(unittest.TestCase):
    def test_full_flow_and_sas(self):
        a, b, conn, bconn, net, clock = paired()
        self.assertEqual(conn.sas, bconn.sas)
        self.assertRegex(conn.sas, r'^\d{4}-\d{4}$')
        r = a.call(conn.id, 'GET', b.url(f'{API}/customers/current'), tenant='org-1')
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(json.loads(r.body)['name'], 'Customer One')
        # reverse direction: the responder calls the initiator with what it was granted
        r = b.call(bconn.id, 'POST', a.url(f'{API}/test'))
        self.assertEqual(r.status, 200, r.body)

    def test_code_single_use_and_brute_force(self):
        net, clock = Network(), Clock()
        b = ReferencePeer('https://rmm.example.test', net, clock=clock)
        a = ReferencePeer('https://msp.example.test', net, clock=clock)
        code = b.create_invitation()
        a.start_pairing(b.base, code, requested_scopes=['customers:read'])
        with self.assertRaises(ConnectError) as e:
            a.start_pairing(b.base, code, requested_scopes=['customers:read'])
        self.assertEqual(e.exception.code, 'invalid_pairing_code')
        b.create_invitation()
        codes = []
        for _ in range(5):
            with self.assertRaises(ConnectError) as e:
                a.start_pairing(b.base, '00000-00000', requested_scopes=['customers:read'])
            codes.append(e.exception.code)
        self.assertEqual(codes[-1], 'pairing_locked')
        self.assertTrue(all(i['burned'] or i['used'] for i in b.invitations))

    def test_expired_code(self):
        a_clock = Clock()
        net = Network()
        b = ReferencePeer('https://rmm.example.test', net, clock=a_clock)
        a = ReferencePeer('https://msp.example.test', net, clock=a_clock)
        code = b.create_invitation()
        a_clock.t += pairing.CODE_TTL + 1
        with self.assertRaises(ConnectError):
            a.start_pairing(b.base, code, requested_scopes=['customers:read'])

    def test_unknown_fields_tolerated_in_discovery(self):
        net = Network()
        b = ReferencePeer('https://rmm.example.test', net)
        orig = b.document
        b.document = lambda: dict(orig(), future_member={'x': 1}, app=dict(orig()['app'], extra='y'))
        from agit8or_connect import discovery
        info = discovery.fetch(net, b.base)
        self.assertEqual(info.installation_id, b.installation_id)


class TenantIsolation(unittest.TestCase):
    def test_customer_vs_customer_within_one_connection(self):
        a, b, conn, *_ = paired()
        for t in ('org-2', 'cust-1', 'cust-2', ''):
            r = a.call(conn.id, 'GET', b.url(f'{API}/customers/current'), tenant=t)
            self.assertEqual(r.status, 403, t)

    def test_two_msps_on_one_responder(self):
        """Two installations (two MSPs) both use tenant id 'org-1'; each only
        ever reaches the customer its own connection was granted."""
        a, b, conn_a, bconn_a, net, clock = paired()
        c, _, conn_c, bconn_c, *_ = paired(net=net, clock=clock, initiator_url='https://msp-c.example.test',
                                           responder=b, tenant='org-1', local_tenant='cust-2')
        ra = a.call(conn_a.id, 'GET', b.url(f'{API}/customers/current'), tenant='org-1')
        rc = c.call(conn_c.id, 'GET', b.url(f'{API}/customers/current'), tenant='org-1')
        self.assertEqual(json.loads(ra.body)['name'], 'Customer One')
        self.assertEqual(json.loads(rc.body)['name'], 'Customer Two')
        # A's token presented with C's DPoP key, or A's key against C's client id: refused
        tok_a = a.get_token(conn_a.id)['access_token']
        _, key_c = conn_c.active_key()
        r = c.call(conn_c.id, 'GET', b.url(f'{API}/customers/current'), tenant='org-1', token=tok_a, key=key_c)
        self.assertEqual(r.status, 401)
        conn_a.remote_connection_id = bconn_c.id  # A pretends to be C's client
        with self.assertRaises(ConnectError) as e:
            a.get_token(conn_a.id)
        self.assertEqual(e.exception.code, 'invalid_client')


class TokensAndScopes(unittest.TestCase):
    def test_scope_escalation(self):
        a, b, conn, *_ = paired()
        for s in (['tickets:write'], ['remote_actions:execute'], ['connection:admin']):
            with self.assertRaises(ConnectError) as e:
                a.get_token(conn.id, s)
            self.assertEqual(e.exception.code, 'invalid_scope')

    def test_expired_token_and_dpop_replay(self):
        a, b, conn, bconn, net, clock = paired()
        tok = a.get_token(conn.id)['access_token']
        _, key = conn.active_key()
        from agit8or_connect import tokens
        url = b.url(f'{API}/test')
        proof = tokens.build_dpop_proof(key, 'POST', url, now=clock(), access_token=tok)
        h = {'Authorization': f'DPoP {tok}', 'DPoP': proof}
        self.assertEqual(net.request('POST', url, h).status, 200)
        self.assertEqual(net.request('POST', url, h).status, 401)  # proof replay
        clock.t += 301
        self.assertEqual(a.call(conn.id, 'POST', url, token=tok).status, 401)
        r = net.request('POST', url, {'Authorization': f'Bearer {tok}'})
        self.assertEqual(r.status, 401)

    def test_revocation_immediate(self):
        a, b, conn, bconn, *_ = paired()
        tok = a.get_token(conn.id)['access_token']
        b.revoke(bconn.id)
        self.assertEqual(a.call(conn.id, 'POST', b.url(f'{API}/test'), token=tok).status, 401)
        with self.assertRaises(ConnectError):
            a.get_token(conn.id)

    def test_high_risk_never_default(self):
        cat = Catalog([Scope('a:read', 'x', 'read'), Scope('a:run', 'x', 'high_risk'), Scope('a:cfg', 'x', 'admin'),
                       Scope('a:write', 'x', 'write')])
        self.assertEqual(cat.default_set(), ['a:read'])
        self.assertEqual(cat.elevated(['a:run', 'a:read', 'a:cfg']), ['a:cfg', 'a:run'])
        with self.assertRaises(ConnectError):
            require_subset(['a:run'], ['a:read'])


class Events(unittest.TestCase):
    def test_delivery_dedup_loop_and_tenant(self):
        a, b, conn, bconn, *_ = paired()
        r = a.send_event(conn.id, 'alert.raised', 'org-1', {'alert_id': '1'},
                         event_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        self.assertEqual(json.loads(r.body)['status'], 'accepted')
        r = a.send_event(conn.id, 'alert.raised', 'org-1', {'alert_id': '1'},
                         event_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        self.assertEqual(json.loads(r.body)['status'], 'duplicate')
        self.assertEqual(len(bconn.received_events), 1)
        r = a.send_event(conn.id, 'alert.raised', 'org-1', {}, origin=b.installation_id)
        self.assertEqual(json.loads(r.body)['status'], 'ignored_loop')
        r = a.send_event(conn.id, 'alert.raised', 'org-9', {})
        self.assertEqual(r.status, 403)

    def test_timestamp_skew_refused(self):
        a, b, conn, bconn, net, clock = paired()
        from agit8or_connect import webhooks
        _, key = conn.active_key()
        env = webhooks.envelope(event_type='alert.raised', tenant='org-1', data={}, sender=a.installation_id)
        body = webhooks.body_of(env)
        h = webhooks.sign(key, connection_id=bconn.id, event_id=env['id'], sender=a.installation_id,
                          receiver=b.installation_id, body=body, timestamp=clock() - 200)
        self.assertEqual(net.request('POST', b.url(f'{API}/events'), h, body).status, 401)


class Rotation(unittest.TestCase):
    def test_rotation_success(self):
        a, b, conn, *_ = paired()
        old, _ = conn.active_key()
        self.assertTrue(a.rotate(conn.id))
        new, _ = conn.active_key()
        self.assertNotEqual(old, new)
        self.assertEqual(conn.keys[old]['state'], rotation.RETIRING)
        self.assertEqual(a.call(conn.id, 'POST', b.url(f'{API}/test')).status, 200)

    def test_rotation_failure_keeps_old_key(self):
        a, b, conn, bconn, net, clock = paired()
        old, _ = conn.active_key()
        net.down.add('https://msp-a.example.test:443')  # B cannot fetch A's JWKS -> new key unverifiable
        self.assertFalse(a.rotate(conn.id))
        self.assertEqual(conn.active_key()[0], old)
        self.assertIn(rotation.FAILED, [k['state'] for k in conn.keys.values()])
        net.down.clear()
        self.assertEqual(a.call(conn.id, 'POST', b.url(f'{API}/test')).status, 200)

    def test_unendorsed_key_refused(self):
        a, b, conn, bconn, net, clock = paired()
        rogue = keys.generate_private_key()
        with self.assertRaises(ConnectError):
            a.get_token(conn.id, key=rogue)

    def test_state_machine(self):
        self.assertEqual(rotation.transition('staged', 'validated'), 'active')
        with self.assertRaises(rotation.RotationError):
            rotation.transition('retired', 'validated')


class Transport(unittest.TestCase):
    def test_blocked_addresses(self):
        for ip in ('169.254.169.254', '127.0.0.1', '10.0.0.5', '192.168.1.1', '::1', 'fd00:ec2::254'):
            self.assertFalse(ip_allowed(ip, False), ip)
        self.assertTrue(ip_allowed('10.0.0.5', True))
        self.assertFalse(ip_allowed('169.254.169.254', True))
        # Loopback, link-local, unspecified and metadata stay refused even
        # with private networks allowed; only RFC1918, CGNAT and ULA open up.
        for ip in ('127.0.0.1', '::1', '169.254.1.1', 'fe80::1', '0.0.0.0', '::', '::ffff:127.0.0.1',
                   'fd00:ec2::254', '100.100.100.200', '224.0.0.1', '64:ff9b::7f00:1'):
            self.assertFalse(ip_allowed(ip, True), ip)
        for ip in ('10.0.0.5', '172.16.1.1', '192.168.1.1', '100.64.0.1', 'fd12:3456::1'):
            self.assertTrue(ip_allowed(ip, True), ip)
        self.assertTrue(ip_allowed('93.184.216.34', False))

    def test_dns_rebinding_and_scheme(self):
        def rebinding(host, port, *a):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.1.2.3', port))]
        t = MinimalGuardedTransport(resolver=rebinding)
        with self.assertRaises(ConnectError) as e:
            t.request('GET', 'https://rebind.example.test/')
        self.assertEqual(e.exception.code, 'blocked_destination')
        with self.assertRaises(ConnectError):
            t.request('GET', 'http://example.test/')
        with self.assertRaises(ConnectError):
            t.request('GET', 'https://user:pw@example.test/')

    def test_tls_always_verified(self):
        import ssl
        t = MinimalGuardedTransport()
        self.assertEqual(t.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(t.context.check_hostname)
        self.assertGreaterEqual(t.context.minimum_version, ssl.TLSVersion.TLSv1_2)


if __name__ == '__main__':
    unittest.main()
