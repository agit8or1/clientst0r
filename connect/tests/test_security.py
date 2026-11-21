"""Mandatory security tests for Agit8or Connect on Clientst0r."""
import json
import logging
import os
import re
import socket
import time
import uuid
from unittest import mock
from urllib.parse import urlencode

from django.db import connection as db
from django.test import override_settings

from agit8or_connect import keys as sdk_keys
from agit8or_connect import tokens as sdk_tokens
from agit8or_connect import webhooks
from agit8or_connect.errors import ConnectError
from agit8or_connect.reference_peer import API, ReferencePeer
from agit8or_connect.scopes import Catalog, Scope

from .base import CS_BASE, PEER_BASE, ConnectTestCase

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CUSTOMER_URL = f'{CS_BASE}/connect/v1/customers/current'


class TenantIsolation(ConnectTestCase):
    def test_customer_vs_customer_within_one_connection(self):
        pconn, conn = self.pair_inbound()
        ok = self.peer.call(pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1')
        self.assertEqual(ok.status, 200)
        for tampered in ('cust-2', self.org_id(self.org_b), self.org_id(self.org_a), str(self.org_b.pk), '',
                         'cust-1 ', '../cust-1', 'cust-1,cust-2'):
            r = self.peer.call(pconn.id, 'GET', CUSTOMER_URL, tenant=tampered)
            self.assertEqual(r.status, 403, tampered)
            self.assertNotIn(b'Beta Customer', r.body)

    def test_two_peer_installations_on_clientst0r(self):
        """Two RMM installations connected to this Clientst0r, using the same
        tenant id string, each reach only their own grant."""
        peer2 = ReferencePeer('https://rmm2.test', self.net, app_type='rem0te', display_name='Rem0te 2')
        p1, c1 = self.pair_inbound(self.peer, tenant='cust-1', org=self.org_a)
        p2, c2 = self.pair_inbound(peer2, tenant='cust-1', org=self.org_b)
        r1 = self.peer.call(p1.id, 'GET', CUSTOMER_URL, tenant='cust-1')
        r2 = peer2.call(p2.id, 'GET', CUSTOMER_URL, tenant='cust-1')
        self.assertEqual(json.loads(r1.body)['name'], 'Acme Customer')
        self.assertEqual(json.loads(r2.body)['name'], 'Beta Customer')
        # peer 1's token with peer 2's proof key, and peer 1 claiming peer 2's client id
        tok1 = self.peer.get_token(p1.id)['access_token']
        _, key2 = p2.active_key()
        r = peer2.call(p2.id, 'GET', CUSTOMER_URL, tenant='cust-1', token=tok1, key=key2)
        self.assertEqual(r.status, 401)
        p1.remote_connection_id = str(c2.pk)
        with self.assertRaises(ConnectError) as e:
            self.peer.get_token(p1.id)
        self.assertEqual(e.exception.code, 'invalid_client')

    def test_two_msp_installations_on_the_receiving_app(self):
        """A Rem0te-like receiver connected to this Clientst0r (MSP 1) and to
        another installation (MSP 2) that uses the very same tenant id:
        neither MSP reaches the other's customer."""
        conn, pconn = self.pair_outbound(tenant='cust-1', org=self.org_a)
        msp2 = ReferencePeer('https://msp2.test', self.net, app_type='clientst0r', display_name='MSP 2')
        code = self.peer.create_invitation()
        m2 = msp2.start_pairing(PEER_BASE, code, requested_scopes=['customers:read'],
                                proposed_tenants=[{'id': self.org_id(self.org_a)}])
        self.peer.approve(m2.request_id, scopes=['customers:read'],
                          tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-2',
                                          'scopes': ['customers:read']}])
        msp2.poll(m2.id)
        msp2.accept(m2.id)
        from connect import client
        mine = client.call(conn, 'GET', f'{PEER_BASE}{API}/customers/current', tenant_org=self.org_a)
        theirs = msp2.call(m2.id, 'GET', f'{PEER_BASE}{API}/customers/current', tenant=self.org_id(self.org_a))
        self.assertEqual(json.loads(mine.body)['name'], 'Peer Customer One')
        self.assertEqual(json.loads(theirs.body)['name'], 'Peer Customer Two')
        tok = client.get_token(conn)['access_token']
        _, k2 = m2.active_key()
        r = msp2.call(m2.id, 'GET', f'{PEER_BASE}{API}/customers/current', tenant=self.org_id(self.org_a),
                      token=tok, key=k2)
        self.assertEqual(r.status, 401)


class Authentication(ConnectTestCase):
    def setUp(self):
        super().setUp()
        self.pconn, self.conn = self.pair_inbound()

    def raw(self, method, url, headers=None, body=b''):
        return self.net.request(method, url, headers or {}, body)

    def test_unauthorized_calls(self):
        # Increment B1: a request that names no connection is refused by the
        # source policy before authentication (403); one that names this
        # connection from its address still needs valid credentials (401).
        self.assertEqual(self.raw('GET', CUSTOMER_URL).status, 403)
        tok = self.peer.get_token(self.pconn.id)['access_token']
        self.assertEqual(self.raw('GET', CUSTOMER_URL, {'Authorization': f'Bearer {tok}'}).status, 403)
        self.assertEqual(self.raw('GET', CUSTOMER_URL, {'Authorization': f'DPoP {tok}'}).status, 401)
        self.assertEqual(self.raw('POST', f'{CS_BASE}/connect/v1/events', {}, b'{}').status, 403)
        self.assertEqual(self.raw('POST', f'{CS_BASE}/connect/v1/events',
                                  {'Agit8or-Connection': str(self.conn.pk)}, b'{}').status, 401)

    def test_expired_token(self):
        from connect import store
        _, priv = store.active_key(self.conn)
        from connect import identity
        tok, _ = sdk_tokens.issue_access_token(priv, issuer=identity.installation_id(),
                                               client_id=str(self.conn.pk), scopes=['customers:read'],
                                               jkt=list(store.remote_keyring(self.conn))[0],
                                               now=int(time.time()) - 400)
        r = self.peer.call(self.pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1', token=tok)
        self.assertEqual(r.status, 401)

    def test_wrong_issuer_and_audience(self):
        from connect import store
        _, priv = store.active_key(self.conn)
        tok, _ = sdk_tokens.issue_access_token(priv, issuer=str(uuid.uuid4()), client_id=str(self.conn.pk),
                                               scopes=['customers:read'], jkt=list(store.remote_keyring(self.conn))[0])
        self.assertEqual(self.peer.call(self.pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1', token=tok).status, 401)
        # client assertion for another audience (token endpoint)
        _, key = self.pconn.active_key()
        endpoint = f'{CS_BASE}/connect/v1/token'
        form = {'grant_type': 'client_credentials', 'client_id': str(self.conn.pk),
                'client_assertion_type': sdk_tokens.CLIENT_ASSERTION_TYPE,
                'client_assertion': sdk_tokens.build_client_assertion(key, str(self.conn.pk), 'https://evil.test/t')}
        r = self.raw('POST', endpoint, {'Content-Type': 'application/x-www-form-urlencoded',
                                        'DPoP': sdk_tokens.build_dpop_proof(key, 'POST', endpoint)},
                     urlencode(form).encode())
        self.assertEqual(r.status, 401)
        self.assertEqual(json.loads(r.body)['error'], 'invalid_client')

    def test_invalid_signatures(self):
        tok = self.peer.get_token(self.pconn.id)['access_token']
        h, p, s = tok.split('.')
        forged = f'{h}.{p}.{s[:-6]}AAAAAA'
        self.assertEqual(self.peer.call(self.pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1', token=forged).status,
                         401)
        from agit8or_connect.canonical import from_b64url
        claims = json.loads(from_b64url(p))
        claims['scope'] = 'customers:read connection:read events:publish tickets:write'
        from agit8or_connect.canonical import b64url, canonical_bytes
        escalated = f'{h}.{b64url(canonical_bytes(claims))}.{s}'
        self.assertEqual(self.peer.call(self.pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1',
                                        token=escalated).status, 401)

    def test_client_assertion_jti_reuse_and_dpop_replay(self):
        _, key = self.pconn.active_key()
        endpoint = f'{CS_BASE}/connect/v1/token'
        assertion = sdk_tokens.build_client_assertion(key, str(self.conn.pk), endpoint)
        form = urlencode({'grant_type': 'client_credentials', 'client_id': str(self.conn.pk),
                          'client_assertion_type': sdk_tokens.CLIENT_ASSERTION_TYPE,
                          'client_assertion': assertion}).encode()

        def go():
            return self.raw('POST', endpoint, {'Content-Type': 'application/x-www-form-urlencoded',
                                               'DPoP': sdk_tokens.build_dpop_proof(key, 'POST', endpoint)}, form)
        self.assertEqual(go().status, 200)
        r = go()
        self.assertEqual(r.status, 401)
        self.assertEqual(json.loads(r.body)['error'], 'replayed')
        # DPoP proof replay on a resource call
        tok = self.peer.get_token(self.pconn.id)['access_token']
        proof = sdk_tokens.build_dpop_proof(key, 'GET', CUSTOMER_URL, access_token=tok)
        h = {'Authorization': f'DPoP {tok}', 'DPoP': proof, 'Agit8or-Tenant': 'cust-1'}
        self.assertEqual(self.raw('GET', CUSTOMER_URL, h).status, 200)
        self.assertEqual(self.raw('GET', CUSTOMER_URL, h).status, 401)
        # stolen token without the key: proof made with another key
        thief = sdk_keys.generate_private_key()
        h2 = {'Authorization': f'DPoP {tok}', 'Agit8or-Tenant': 'cust-1',
              'DPoP': sdk_tokens.build_dpop_proof(thief, 'GET', CUSTOMER_URL, access_token=tok)}
        self.assertEqual(self.raw('GET', CUSTOMER_URL, h2).status, 401)

    def test_scope_escalation(self):
        for scope in (['tickets:write'], ['remote_actions:execute'], ['connection:admin'], ['nonexistent:x']):
            with self.assertRaises(ConnectError) as e:
                self.peer.get_token(self.pconn.id, scope)
            self.assertEqual(e.exception.code, 'invalid_scope')
        # granted scope, but not for this customer
        tok = self.peer.get_token(self.pconn.id, ['connection:read'])['access_token']
        r = self.peer.call(self.pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1', token=tok)
        self.assertEqual(r.status, 403)

    def test_revoked_connection_and_grant(self):
        from connect import lifecycle
        tok = self.peer.get_token(self.pconn.id)['access_token']
        grant = self.conn.tenant_grants.get()
        lifecycle.revoke_grant(grant, self.admin)
        self.assertEqual(self.peer.call(self.pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1', token=tok).status, 403)
        lifecycle.revoke(self.conn, self.admin)
        # Revoking removes the connection's source rules too (B1): refused before authentication.
        self.assertEqual(self.peer.call(self.pconn.id, 'POST', f'{CS_BASE}/connect/v1/test', token=tok).status, 403)
        with self.assertRaises(ConnectError):
            self.peer.get_token(self.pconn.id)

    def test_tokens_issued_before_suspension_refused(self):
        from connect import lifecycle
        tok = self.peer.get_token(self.pconn.id)['access_token']
        lifecycle.suspend(self.conn, self.admin)
        lifecycle.resume(self.conn, self.admin)
        r = self.peer.call(self.pconn.id, 'POST', f'{CS_BASE}/connect/v1/test', token=tok)
        self.assertEqual(r.status, 401)


class Pairing(ConnectTestCase):
    def test_code_reuse(self):
        from connect import pairing
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        with self.assertRaises(ConnectError) as e:
            self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        # A used invitation's source rule moved to its connection (B1): the code no longer opens pairing_submit.
        self.assertEqual(e.exception.code, 'source_not_authorised')

    def test_brute_force_lockout_burns_open_invitations(self):
        from connect import pairing
        from connect.models import PairingInvitation
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        codes = []
        for i in range(5):
            with self.assertRaises(ConnectError) as e:
                self.peer.start_pairing(CS_BASE, '00000-0000' + str(i), requested_scopes=['customers:read'])
            codes.append(e.exception.code)
        self.assertEqual(codes[-1], 'pairing_locked')
        self.assertIsNotNone(PairingInvitation.objects.get().burned_at)
        with self.assertRaises(ConnectError):
            self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])

    def test_expired_code(self):
        from connect import pairing
        from connect.models import PairingInvitation
        inv, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        PairingInvitation.objects.filter(pk=inv.pk).update(expires_at=inv.created_at)
        with self.assertRaises(ConnectError) as e:
            self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        self.assertEqual(e.exception.code, 'invalid_pairing_code')

    def test_pairing_rate_limit(self):
        from connect import ratelimit
        from django.core.cache import cache
        cache.clear()
        from connect import pairing
        pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        with mock.patch.dict(ratelimit.LIMITS, {'pairing_ip': (2, 600)}):
            for _ in range(2):
                with self.assertRaises(ConnectError):
                    self.peer.start_pairing(CS_BASE, '11111-11111', requested_scopes=['customers:read'])
            with self.assertRaises(ConnectError) as e:
                self.peer.start_pairing(CS_BASE, '11111-11111', requested_scopes=['customers:read'])
            self.assertEqual(e.exception.code, 'rate_limited')
        cache.clear()

    def test_status_poll_needs_initiator_key(self):
        from connect import pairing
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        rogue = sdk_keys.generate_private_key()
        from agit8or_connect import pairing as sp
        proof = sp.build_poll(rogue, initiator_installation=self.peer.installation_id,
                              responder_installation=pconn.remote_installation, request_id=pconn.request_id)
        r = self.net.request('POST', f'{CS_BASE}/connect/v1/pairing/requests/{pconn.request_id}/status',
                             {'Content-Type': 'application/json'}, json.dumps({'proof': proof}).encode())
        self.assertEqual(r.status, 401)

    def test_high_risk_needs_second_admin(self):
        """A high_risk scope is never granted by one administrator."""
        from connect import catalog, pairing
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
                                             grants=[(self.org_a.pk, 'cust-1', ['customers:read'])],
                                             user=self.admin)
            self.assertIsInstance(change, ProtectedChange)
            preq.refresh_from_db()
            self.assertEqual(preq.connection.state, Connection.AWAITING_SECOND)
            self.assertEqual(self.peer.poll(pconn.id), 'pending')

            class Req:
                def __init__(self, user):
                    self.user, self.session = user, {protected.SESSION_KEY: int(time.time())}
                    self.META, self.path = {}, '/'
            with self.assertRaises(protected.ProtectedChangeError):
                protected.approve(change, Req(self.admin))   # the proposer cannot approve
            protected.confirm(change, Req(self.admin))
            protected.approve(change, Req(self.admin2))
            preq.refresh_from_db()
            # C3: approved is not active; the connection test commits it.
            self.assertEqual(preq.connection.state, Connection.TESTING)
            self.assertIn('lab_actions:execute', preq.connection.inbound_scopes)
            self.assertEqual(self.peer.poll(pconn.id), 'approved')

    def test_unavailable_scope_cannot_be_granted(self):
        from connect import pairing
        from connect.models import PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['remote_actions:execute'])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        with self.assertRaises(pairing.PairingFailed):
            pairing.approve_inbound(preq, destination_addresses=['93.184.216.40'], scopes=['remote_actions:execute'], grants=[], user=self.admin)

    def test_sas_mismatch_detectable(self):
        """A man in the middle substituting keys yields different codes."""
        from agit8or_connect import pairing as sp
        a, b, m = (sdk_keys.thumbprint(sdk_keys.generate_private_key()) for _ in range(3))
        t1 = sp.transcript_hash(request_jws='x', request_jti='j', initiator_installation='i', initiator_jkt=a,
                                responder_installation='r', responder_jkt=m)
        t2 = sp.transcript_hash(request_jws='x', request_jti='j', initiator_installation='i', initiator_jkt=m,
                                responder_installation='r', responder_jkt=b)
        self.assertNotEqual(sp.short_authentication_string(t1), sp.short_authentication_string(t2))


class Webhooks(ConnectTestCase):
    def setUp(self):
        super().setUp()
        self.pconn, self.conn = self.pair_inbound()

    def test_duplicate_and_replay(self):
        from connect.models import InboundEvent
        eid = str(uuid.uuid4())
        r1 = self.peer.send_event(self.pconn.id, 'alert.raised', 'cust-1', {'a': 1}, event_id=eid)
        r2 = self.peer.send_event(self.pconn.id, 'alert.raised', 'cust-1', {'a': 1}, event_id=eid)
        self.assertEqual(json.loads(r1.body)['status'], 'accepted')
        self.assertEqual(json.loads(r2.body)['status'], 'duplicate')
        self.assertEqual(InboundEvent.objects.count(), 1)

    def test_timestamp_skew_and_tampering(self):
        _, key = self.pconn.active_key()
        env = webhooks.envelope(event_type='alert.raised', tenant='cust-1', data={},
                                sender=self.peer.installation_id)
        body = webhooks.body_of(env)
        url = f'{CS_BASE}/connect/v1/events'
        from connect import identity
        old = webhooks.sign(key, connection_id=str(self.conn.pk), event_id=env['id'],
                            sender=self.peer.installation_id, receiver=identity.installation_id(), body=body,
                            timestamp=int(time.time()) - 300)
        self.assertEqual(self.net.request('POST', url, old, body).status, 401)
        good = webhooks.sign(key, connection_id=str(self.conn.pk), event_id=env['id'],
                             sender=self.peer.installation_id,
                             receiver=identity.installation_id(), body=body)
        self.assertEqual(self.net.request('POST', url, good, body + b' ').status, 401)
        self.assertEqual(self.net.request('POST', url, good, body).status, 200)

    def test_loop_and_ungranted_tenant(self):
        from connect import identity
        r = self.peer.send_event(self.pconn.id, 'alert.raised', 'cust-1', {}, origin=identity.installation_id())
        self.assertEqual(json.loads(r.body)['status'], 'ignored_loop')
        self.assertEqual(self.peer.send_event(self.pconn.id, 'alert.raised', 'cust-2', {}).status, 403)
        r = self.peer.send_event(self.pconn.id, 'tickets.created', 'cust-1', {})
        self.assertEqual((r.status, json.loads(r.body)['error']['code']), (403, 'event_type_not_allowed'))

    def test_connection_event_from_peer_revokes(self):
        from connect.models import Connection, InboundEvent
        r = self.peer.send_event(self.pconn.id, 'connect.connection.revoked', '', {'reason': 'disconnected'})
        self.assertEqual(json.loads(r.body)['status'], 'accepted', r.body)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.state, Connection.REVOKED)
        self.assertEqual(InboundEvent.objects.filter(connection=self.conn).count(), 1)

    def test_network_interruption_then_recovery(self):
        from connect import events
        from connect.models import OutboundEvent
        grant = self.conn.tenant_grants.get()
        ev = events.enqueue(self.conn, 'alert.raised', {'n': 1}, grant=grant)
        self.net.down.add('https://rmm.test:443')
        self.assertEqual(events.deliver_due()['retry'], 1)
        ev.refresh_from_db()
        # Increment D (QC-06): an attempt that never reached the peer is not counted.
        self.assertEqual((ev.status, ev.attempts), (OutboundEvent.QUEUED, 0))
        self.assertGreater(ev.next_attempt_at.timestamp(), time.time())
        self.net.down.clear()
        OutboundEvent.objects.filter(pk=ev.pk).update(next_attempt_at=ev.created_at)
        self.assertEqual(events.deliver_due()['delivered'], 1)
        # (the connect.test event of the commit-gate test arrived earlier)
        self.assertEqual([e['type'] for e in self.pconn.received_events if e['type'] != 'connect.test'],
                         ['alert.raised'])

    def test_dead_letter_after_max_attempts(self):
        from agit8or_connect.http import Response
        from connect import events
        from connect.models import OutboundEvent
        ev = events.enqueue(self.conn, 'alert.raised', {}, grant=self.conn.tenant_grants.get())
        # Twelve attempts that REACHED the peer (it answers 503) dead-letter the
        # event; a peer that cannot be reached at all never uses them up (D).
        self.net.register('https://rmm.test', lambda m, u, h, b: Response(503, {}, b'{}'))
        OutboundEvent.objects.filter(pk=ev.pk).update(attempts=webhooks.MAX_ATTEMPTS - 1)
        events.deliver_due()
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboundEvent.DEAD)


class Rotation(ConnectTestCase):
    def test_rotation_success(self):
        from connect import client, lifecycle
        from connect.models import ConnectionKey
        conn, pconn = self.pair_outbound()
        old = conn.keys.get(state=ConnectionKey.ACTIVE)
        self.assertTrue(lifecycle.rotate(conn))
        old.refresh_from_db()
        self.assertEqual(old.state, ConnectionKey.RETIRING)
        new = conn.keys.get(state=ConnectionKey.ACTIVE)
        self.assertNotEqual(new.kid, old.kid)
        r = client.call(conn, 'GET', f'{PEER_BASE}{API}/customers/current', tenant_org=self.org_a)
        self.assertEqual(r.status, 200)
        ConnectionKey.objects.filter(pk=old.pk).update(retire_after=old.created_at)
        self.assertEqual(lifecycle.retire_due(), 1)
        old.refresh_from_db()
        self.assertEqual((old.state, old.private_key), (ConnectionKey.RETIRED, ''))

    def test_rotation_failure_keeps_old_key(self):
        from connect import lifecycle
        from connect.models import ConnectionKey
        conn, pconn = self.pair_outbound()
        old = conn.keys.get(state=ConnectionKey.ACTIVE)
        self.net.down.add('https://clientst0r.test:443')  # the peer cannot fetch our endorsed JWKS
        self.assertFalse(lifecycle.rotate(conn))
        self.net.down.clear()
        self.assertEqual(conn.keys.get(state=ConnectionKey.ACTIVE).pk, old.pk)
        self.assertTrue(conn.keys.filter(state=ConnectionKey.FAILED, private_key='').exists())
        conn.refresh_from_db()
        self.assertIn('did not accept', conn.last_rotation_error)

    def test_peer_rotation_accepted_only_with_endorsement(self):
        pconn, conn = self.pair_inbound()
        self.assertTrue(self.peer.rotate(pconn.id))
        self.assertEqual(self.peer.call(pconn.id, 'POST', f'{CS_BASE}/connect/v1/test').status, 200)
        rogue = sdk_keys.generate_private_key()
        with self.assertRaises(ConnectError):
            self.peer.get_token(pconn.id, key=rogue)


class KillSwitchAndDisconnect(ConnectTestCase):
    def test_kill_switch(self):
        from django.core.management import call_command
        from connect import events
        from connect.models import Connection, OutboundEvent
        pconn, conn = self.pair_inbound()
        ev = events.enqueue(conn, 'alert.raised', {}, grant=conn.tenant_grants.get())
        call_command('connect_kill_switch', stdout=open(os.devnull, 'w'))
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.SUSPENDED)
        with self.assertRaises(ConnectError):
            self.peer.get_token(pconn.id)
        tok_headers = {'Agit8or-Connection': str(conn.pk)}
        self.assertEqual(self.net.request('POST', f'{CS_BASE}/connect/v1/events', tok_headers, b'{}').status, 503)
        self.assertEqual(events.deliver_due()['delivered'], 0)
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboundEvent.QUEUED)
        r = self.ui.post('/settings/integrations/connected-apps/kill-switch/', {'op': 'release'}, secure=True,
                         HTTP_HOST='clientst0r.test')
        self.assertEqual(r.status_code, 302)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.SUSPENDED)  # stays suspended until resumed

    def test_disconnect_preserves_records(self):
        from core.models import Organization
        from connect import lifecycle
        from connect.models import ConnectionKey, InboundEvent, TenantGrant
        pconn, conn = self.pair_inbound()
        self.peer.send_event(pconn.id, 'alert.raised', 'cust-1', {})
        orgs = Organization.objects.count()
        lifecycle.disconnect(conn, self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'revoked')
        self.assertEqual(Organization.objects.count(), orgs)
        self.assertEqual(TenantGrant.objects.filter(connection=conn, active=False).count(), 1)
        self.assertEqual(InboundEvent.objects.filter(connection=conn).count(), 1)
        self.assertFalse(ConnectionKey.objects.filter(connection=conn).exclude(private_key='').exists())
        self.assertEqual(pconn.state, 'revoked')          # the peer was told (signed connection event)
        pconn.state = 'active'
        with self.assertRaises(ConnectError):
            self.peer.get_token(pconn.id)


class AuditChain(ConnectTestCase):
    def test_tamper_detection(self):
        from django.core.management import call_command
        from connect import audit_log
        from connect.models import AppendOnlyError, ConnectAuditEvent
        self.pair_inbound()
        self.assertIsNone(audit_log.verify())
        ev = ConnectAuditEvent.objects.order_by('seq')[2]
        with self.assertRaises(AppendOnlyError):
            ev.save()
        with self.assertRaises(AppendOnlyError):
            ev.delete()
        with self.assertRaises(AppendOnlyError):
            ConnectAuditEvent.objects.filter(pk=ev.pk).update(result='denied')
        with self.assertRaises(AppendOnlyError):
            ConnectAuditEvent.objects.all().delete()
        with db.cursor() as c:
            c.execute('UPDATE connect_audit SET result = %s WHERE id = %s', ['denied', ev.pk])
        self.assertEqual(audit_log.verify(), ev.seq)
        with self.assertRaises(SystemExit):
            call_command('connect_verify_audit_chain', stdout=open(os.devnull, 'w'), stderr=open(os.devnull, 'w'))

    def test_deleted_row_detected(self):
        from connect import audit_log
        from connect.models import ConnectAuditEvent
        self.pair_inbound()
        victim = ConnectAuditEvent.objects.order_by('seq')[1]
        with db.cursor() as c:
            c.execute('DELETE FROM connect_audit WHERE id = %s', [victim.pk])
        self.assertIsNotNone(audit_log.verify())

    def test_audit_has_no_secrets(self):
        from connect.models import ConnectAuditEvent
        pconn, conn = self.pair_inbound()
        self.peer.call(pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1')
        dump = json.dumps([e.record() for e in ConnectAuditEvent.objects.all()])
        self.assertNotIn('PRIVATE KEY', dump)
        self.assertNotIn('eyJ', dump)  # no JWS / token


class SsrfAndTls(ConnectTestCase):
    def transport(self, **kw):
        from agit8or_connect.adapters.safe_http import SafeHttpTransport
        return SafeHttpTransport(**kw)

    def test_metadata_and_private_addresses_blocked(self):
        for url in ('https://169.254.169.254/latest/meta-data', 'https://10.0.0.5/', 'https://127.0.0.1/',
                    'https://[::1]/', 'https://192.168.1.10/.well-known/agit8or-connect', 'https://localhost/'):
            with self.assertRaises(ConnectError) as e:
                self.transport().request('GET', url)
            self.assertEqual(e.exception.code, 'blocked_destination', url)
        with self.assertRaises(ConnectError):
            self.transport(allow_private=True).request('GET', 'https://169.254.169.254/latest/meta-data')
        with self.assertRaises(ConnectError):
            self.transport().request('GET', 'http://example.com/')

    def test_dns_rebinding_blocked_at_connect_time(self):
        def rebinding(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.9.8.7', port))]
        with mock.patch('core.safe_http.socket.getaddrinfo', rebinding):
            with self.assertRaises(ConnectError) as e:
                self.transport().request('GET', 'https://looks-public.example.com/.well-known/agit8or-connect')
        self.assertEqual(e.exception.code, 'blocked_destination')

    def test_redirect_not_followed(self):
        from agit8or_connect.http import Response
        from connect import pairing
        calls = []

        class Redirector:
            def request(self, method, url, headers=None, body=None):
                calls.append(url)
                return Response(302, {'Location': 'https://169.254.169.254/'}, b'')
        with mock.patch('connect.transport.factory', lambda **kw: Redirector()):
            with self.assertRaises(pairing.PairingFailed):
                pairing.discover('https://redirector.example.com')
        self.assertEqual(len(calls), 1)

    def test_discovery_endpoint_on_other_origin_refused(self):
        from connect import pairing
        orig = self.peer.document
        self.peer.document = lambda: dict(orig(), endpoints=dict(orig()['endpoints'],
                                                                 token='https://169.254.169.254/token'))
        with self.assertRaises(pairing.PairingFailed):
            pairing.discover(PEER_BASE)

    def test_tls_verification_never_disabled(self):
        bad = re.compile(r'verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False|_create_unverified_context')
        offenders = []
        for top in ('connect', 'agit8or_connect'):
            for root, _, files in os.walk(os.path.join(REPO, top)):
                for f in files:
                    if f.endswith('.py') and not f.startswith('test_'):
                        with open(os.path.join(root, f), encoding='utf-8') as fh:
                            if bad.search(fh.read()):
                                offenders.append(os.path.join(root, f))
        self.assertEqual(offenders, [])


class SecretLeakage(ConnectTestCase):
    def test_logs_and_responses_carry_no_secrets(self):
        from connect import pairing
        from connect.models import ConnectionKey
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))
        handler = Grab(level=logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            inv, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
            pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=self.SCOPES,
                                            proposed_tenants=[{'id': 'cust-1'}])
            from connect.models import PairingRequest
            preq = PairingRequest.objects.get(pk=pconn.request_id)
            pairing.approve_inbound(preq, destination_addresses=['93.184.216.40'], scopes=self.SCOPES, grants=[(self.org_a.pk, 'cust-1', self.SCOPES)],
                                    user=self.admin)
            self.peer.poll(pconn.id)
            self.peer.accept(pconn.id)
            tok = self.peer.get_token(pconn.id)['access_token']
            responses = [self.peer.call(pconn.id, 'GET', CUSTOMER_URL, tenant='cust-1'),
                         self.peer.call(pconn.id, 'GET', CUSTOMER_URL, tenant='cust-9'),
                         self.net.request('GET', f'{CS_BASE}/.well-known/agit8or-connect'),
                         self.net.request('GET', f'{CS_BASE}/connect/v1/connections/{preq.connection.pk}/jwks'),
                         self.net.request('POST', f'{CS_BASE}/connect/v1/token', {}, b'grant_type=x')]
            pages = [self.ui.get(u, secure=True, HTTP_HOST='clientst0r.test').content for u in (
                '/settings/integrations/connected-apps/',
                f'/settings/integrations/connected-apps/{preq.connection.pk}/')]
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        secrets = [code, code.replace('-', ''), tok]
        for row in ConnectionKey.objects.all():
            secrets.append(row.private_pem().split('\n')[1])
        blob = '\n'.join(records)
        for s in secrets:
            self.assertNotIn(s, blob)
        for body in [r.body for r in responses] + pages:
            text = body.decode('utf-8', 'replace')
            self.assertNotIn('PRIVATE KEY', text)
            self.assertNotIn('"d":', text.replace(' ', ''))
            for s in secrets[:2] + secrets[3:]:
                self.assertNotIn(s, text)

    def test_private_key_bound_to_row(self):
        from connect.models import ConnectionKey
        from vault.secret_fields import SecretFieldError
        pconn, conn = self.pair_inbound()
        other_conn, _ = self.pair_outbound(peer=ReferencePeer('https://rmm3.test', self.net))
        a = conn.keys.get(state='active')
        b = other_conn.keys.get(state='active')
        self.assertTrue(a.private_key.startswith('enc2$'))
        b.private_key = a.private_key  # ciphertext copied to another row
        with self.assertRaises(SecretFieldError):
            b.private_pem()
        self.assertTrue(a.private_pem().startswith('-----BEGIN PRIVATE KEY-----'))


@override_settings(AGIT8OR_CONNECT_ENABLED=False)
class DisabledByDefault(ConnectTestCase):
    def test_all_endpoints_404(self):
        cid = uuid.uuid4()
        for method, path in [('GET', '/.well-known/agit8or-connect'), ('GET', '/connect/v1/health'),
                             ('POST', '/connect/v1/pairing/requests'),
                             ('POST', f'/connect/v1/pairing/requests/{cid}/status'), ('POST', '/connect/v1/token'),
                             ('GET', f'/connect/v1/connections/{cid}/jwks'), ('GET', '/connect/v1/capabilities'),
                             ('POST', '/connect/v1/test'), ('GET', '/connect/v1/customers'),
                             ('GET', '/connect/v1/customers/current'), ('POST', '/connect/v1/events')]:
            self.assertEqual(self.net.request(method, CS_BASE + path, {}, b'').status, 404, path)
        for path in ('/settings/integrations/connected-apps/', '/settings/integrations/connected-apps/invite/',
                     '/settings/integrations/connected-apps/new/rem0te/',
                     f'/settings/integrations/connected-apps/{cid}/'):
            self.assertEqual(self.ui.get(path, secure=True, HTTP_HOST='clientst0r.test').status_code, 404, path)

    def test_default_setting_is_off(self):
        from config import settings as project_settings
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AGIT8OR_CONNECT_ENABLED', None)
            self.assertFalse(os.getenv('AGIT8OR_CONNECT_ENABLED', 'False').lower() == 'true')
        self.assertIn("os.getenv('AGIT8OR_CONNECT_ENABLED', 'False')", open(project_settings.__file__).read())


class TicketRmmV1Untouched(ConnectTestCase):
    def test_rem0te_routes_still_resolve(self):
        from django.urls import reverse
        self.assertEqual(reverse('integration_api:inference'), '/api/integration/v1/inference')
        self.assertEqual(reverse('integration_api:events'), '/api/integration/v1/events')
