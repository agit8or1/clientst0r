"""Protocol 1.1 (Quick Connect) end to end with in-memory reference peers,
and 1.0 <-> 1.1 compatibility: a v1-only peer and a 1.1 peer still pair over
the v1 code flow in both directions, and negotiation falls back cleanly."""
import json
import unittest

from agit8or_connect import discovery, quick_connect as qc, tokens
from agit8or_connect.errors import ConnectError
from agit8or_connect.jws import unverified_payload
from agit8or_connect.reference_peer import API, Network, ReferencePeer
from agit8or_connect.tests.test_reference_peer import Clock

A_BASE, B_BASE = 'https://msp-a.example.test', 'https://rmm-b.example.test'
A_SRC, B_SRC = '203.0.113.10', '198.51.100.7'
SCOPES = ['connection:read', 'customers:read', 'events:publish']


def peers(a_qc=True, b_qc=True):
    clock, net = Clock(), Network()
    a = ReferencePeer(A_BASE, net, display_name='MSP', clock=clock, tenants={'org-1': 'MSP customer'},
                      quick_connect=a_qc, egress=['203.0.113.10/32'], source_address=A_SRC)
    b = ReferencePeer(B_BASE, net, display_name='RMM', clock=clock, quick_connect=b_qc,
                      egress=['198.51.100.0/28'], source_address=B_SRC)
    return a, b, net, clock


def quick_connect(a, b, **kw):
    url = a.qc_start(b.base, requested_scopes=SCOPES)
    back = b.qc_authorize(b.qc_review(url), **kw)
    return a.qc_callback(back, proposed_tenants=[{'id': 'org-1', 'label': 'Customer'}])


def finish(a, b, conn):
    bconn = b.connections[b.requests[conn.request_id]]
    b.approve(conn.request_id, scopes=SCOPES, tenant_grants=[
        {'remote_tenant': 'org-1', 'local_tenant': 'cust-1', 'scopes': ['customers:read', 'events:publish']}],
        requested_scopes=['connection:read'])
    assert a.poll(conn.id) == 'approved'
    a.accept(conn.id, scopes=['connection:read'])
    return bconn


def code_pair(a, b):
    code = b.create_invitation()
    conn = a.start_pairing(b.base, code, requested_scopes=SCOPES, proposed_tenants=[{'id': 'org-1'}])
    return conn, finish(a, b, conn)


class QuickConnectFlow(unittest.TestCase):
    def test_happy_path_then_v1_from_the_ack_on(self):
        a, b, net, _ = peers()
        conn = quick_connect(a, b)
        bconn = b.connections[b.requests[conn.request_id]]
        self.assertEqual(conn.state, 'awaiting_remote_approval')
        self.assertEqual(bconn.state, 'awaiting_local_approval')
        self.assertRegex(conn.sas, r'^\d{4}-\d{4}$')
        self.assertEqual(conn.sas, bconn.sas)
        finish(a, b, conn)
        r = a.call(conn.id, 'GET', b.url(f'{API}/customers/current'), tenant='org-1')
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(b.call(bconn.id, 'POST', a.url(f'{API}/test')).status, 200)
        # qc-diagnostics/1 both ways: each side sees the other's source address.
        self.assertEqual(a.qc_probe(conn.id, nonce='n' * 22)['observed_source'], A_SRC)
        self.assertEqual(b.qc_probe(bconn.id)['observed_source'], B_SRC)
        # No password anywhere: the only bodies sent to B are the exchange and v1 calls.
        self.assertFalse(any('password' in u.lower() for _, u in net.log))

    def test_exchange_from_unapproved_source_refused_then_approved_source_works(self):
        a, b, net, _ = peers()
        a.source_address = '192.0.2.99'        # A's real egress differs from what it declared
        with self.assertRaises(ConnectError) as e:
            quick_connect(a, b)
        self.assertEqual((e.exception.code, e.exception.status), ('source_not_authorised', 403))
        self.assertFalse(any(c.state == 'awaiting_local_approval' for c in b.connections.values()))

    def test_code_single_use_on_the_server(self):
        a, b, net, clock = peers()
        conn = quick_connect(a, b)
        att = next(x for x in a.qc_attempts.values() if x['conn'] == conn.id)
        _, key = conn.active_key()
        exch, _ = qc.build_exchange(key, invitation=att['claims'], accept=unverified_payload(att['accept']),
                                    accept_jws=att['accept'], code=att['code'], code_verifier=att['verifier'],
                                    initiator_app=a.app, discovery_url=a.url(discovery.WELL_KNOWN),
                                    requested_scopes=SCOPES, now=clock())
        r = net.request('POST', att['exchange_url'], {
            'DPoP': tokens.build_dpop_proof(key, 'POST', att['exchange_url'], now=clock())},
            json.dumps({'exchange': exch}).encode(), source=A_SRC)
        self.assertEqual(r.status, 400, r.body)
        self.assertEqual(json.loads(r.body)['error']['code'], 'code_used')

    def test_invitation_single_use_and_expiry(self):
        a, b, _, clock = peers()
        url = a.qc_start(b.base, requested_scopes=SCOPES)
        b.qc_review(url)
        with self.assertRaises(ConnectError) as e:
            b.qc_review(url)
        self.assertEqual(e.exception.code, 'invitation_used')
        url = a.qc_start(b.base, requested_scopes=SCOPES)
        clock.t += qc.INVITATION_MAX_LIFETIME + qc.SKEW
        with self.assertRaises(ConnectError) as e:
            b.qc_review(url)
        self.assertEqual(e.exception.code, 'invitation_expired')

    def test_code_expires(self):
        a, b, _, clock = peers()
        url = a.qc_start(b.base, requested_scopes=SCOPES)
        back = b.qc_authorize(b.qc_review(url))
        clock.t += qc.CODE_TTL
        with self.assertRaises(ConnectError) as e:
            a.qc_callback(back)
        self.assertEqual(e.exception.code, 'code_expired')

    def test_denied(self):
        a, b, _, _ = peers()
        with self.assertRaises(ConnectError) as e:
            quick_connect(a, b, approve=False)
        self.assertEqual(e.exception.code, 'access_denied')

    def test_discovery_stripped_after_accept_is_a_downgrade(self):
        a, b, _, _ = peers()
        url = a.qc_start(b.base, requested_scopes=SCOPES)
        back = b.qc_authorize(b.qc_review(url))
        b.qc_advertise = False                  # an attacker rewrites B's discovery to v1
        with self.assertRaises(ConnectError) as e:
            a.qc_callback(back)
        self.assertEqual(e.exception.code, 'downgrade_detected')

    def test_callback_replay_refused(self):
        a, b, _, _ = peers()
        url = a.qc_start(b.base, requested_scopes=SCOPES)
        back = b.qc_authorize(b.qc_review(url))
        a.qc_callback(back)
        with self.assertRaises(ConnectError) as e:
            a.qc_callback(back)
        self.assertEqual(e.exception.code, 'state_mismatch')


class Compatibility(unittest.TestCase):
    """1.0 (v1-only, e.g. any Rem0te build on the current handoff contract) <-> 1.1."""

    def test_v1_peer_document_unchanged(self):
        _, b, _, _ = peers(b_qc=False)
        doc = b.document()
        self.assertNotIn('revision', doc)
        self.assertNotIn('extensions', doc)
        self.assertFalse(any(k.startswith('qc_') for k in doc['endpoints']))

    def test_1_1_initiator_v1_responder_falls_back_to_code_flow(self):
        a, b, net, _ = peers(a_qc=True, b_qc=False)
        with self.assertRaises(ConnectError) as e:
            a.qc_start(b.base, requested_scopes=SCOPES)
        self.assertEqual(e.exception.code, 'extension_not_negotiated')
        self.assertFalse(any(u.endswith(qc.EXCHANGE_PATH) for _, u in net.log))
        conn, bconn = code_pair(a, b)
        self.assertEqual(conn.sas, bconn.sas)
        self.assertEqual(a.call(conn.id, 'GET', b.url(f'{API}/customers/current'), tenant='org-1').status, 200)

    def test_v1_initiator_1_1_responder_code_flow(self):
        a, b, _, _ = peers(a_qc=False, b_qc=True)
        conn, bconn = code_pair(a, b)
        self.assertEqual(conn.sas, bconn.sas)
        self.assertEqual(b.call(bconn.id, 'POST', a.url(f'{API}/test')).status, 200)
        # The v1 peer's discovery parser accepts the 1.1 document and negotiates v1.
        info = discovery.fetch(net_of(a), b.base)
        self.assertEqual(info.version, '1')

    def test_both_1_1_can_still_use_the_code_flow(self):
        a, b, _, _ = peers()
        conn, bconn = code_pair(a, b)
        self.assertEqual(conn.sas, bconn.sas)

    def test_v1_peer_has_no_quick_connect_surface(self):
        a, b, net, _ = peers(a_qc=True, b_qc=False)
        url = a.qc_start(b.base, requested_scopes=SCOPES, authorize_url=b.base + qc.AUTHORIZE_ENTRY_PATH)
        with self.assertRaises(ConnectError) as e:
            b.qc_review(url)
        self.assertEqual(e.exception.code, 'not_found')
        r = net.request('POST', b.url(qc.EXCHANGE_PATH), {}, b'{}', source=A_SRC)
        self.assertEqual(r.status, 404)

    def test_v1_initiator_cannot_start_quick_connect(self):
        a, b, _, _ = peers(a_qc=False)
        with self.assertRaises(ConnectError) as e:
            a.qc_start(b.base, requested_scopes=SCOPES)
        self.assertEqual(e.exception.code, 'extension_not_negotiated')


def net_of(peer):
    return peer.network
