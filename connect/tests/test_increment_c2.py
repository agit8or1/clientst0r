"""Quick Connect increment C2 (roadmap 79.9): browser-mediated bootstrap in
Clientst0r, both roles, against the 1.1 reference peer
(docs/plans/quick-connect/INCREMENTS.md §C2, PROTOCOL-1.1.md §5–§7)."""
import html
import json
import re
import time
from datetime import timedelta
from unittest import mock
from urllib.parse import urlsplit

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from agit8or_connect import discovery as sdk_discovery
from agit8or_connect import keys as sdk_keys
from agit8or_connect import quick_connect as qc
from agit8or_connect import tokens as sdk_tokens
from agit8or_connect.errors import ConnectError
from agit8or_connect.jws import unverified_payload
from agit8or_connect.reference_peer import ReferencePeer

from .base import CS_BASE, PEER_BASE, PEER_DEST_IP, PEER_IP, ConnectTestCase

UI = '/settings/integrations/connected-apps/'
AUTHORIZE = '/agit8or-connect/qc-authorize'
CS_EGRESS = '198.51.100.7'
BROWSER_IP = '203.0.113.200'      # the administrators' browsers: never used for any rule
OTHER_IP = '93.184.216.99'


class QcTestCase(ConnectTestCase):
    def setUp(self):
        super().setUp()
        from connect import identity, source_policy
        from connect.models import InstallationIdentity
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(
            qc_enabled=True, egress_addresses=[{'net': f'{CS_EGRESS}/32', 'note': ''}])
        # Clientst0r's outbound requests arrive at the peers from its egress.
        self.net.default_source = CS_EGRESS
        self.qpeer = ReferencePeer(PEER_BASE.replace('rmm', 'qc'), self.net, app_type='reference-peer',
                                   display_name='QC peer', quick_connect=True, egress=[PEER_IP],
                                   source_address=PEER_IP)
        source_policy.reset_cache()
        # Every request body Clientst0r sends to a peer, and every body a peer sends here.
        self.sent = []
        real = self.net.request

        def capture(method, url, headers=None, body=None, source=None):
            self.sent.append((url, bytes(body or b'')))
            return real(method, url, headers, body, source)
        p = mock.patch.object(self.net, 'request', capture)
        p.start()
        self.addCleanup(p.stop)

    # --- helpers ---------------------------------------------------------------------
    def fresh(self, client=None):
        from tech_access.protected import SESSION_KEY
        s = (client or self.ui).session
        s[SESSION_KEY] = int(time.time())
        s.save()

    def browser_get(self, url, client=None):
        p = urlsplit(url)
        return (client or self.ui).get(p.path + (f'?{p.query}' if p.query else ''), REMOTE_ADDR=BROWSER_IP,
                                       secure=True)

    def browser_post(self, path, data, client=None):
        return (client or self.ui).post(path, data, REMOTE_ADDR=BROWSER_IP, secure=True)

    def rules(self, conn, status=None):
        from connect.models import SourceRule
        qs = SourceRule.objects.filter(connection=conn)
        if status:
            qs = qs.filter(status__in=status)
        return sorted(qs.values_list('network', flat=True))

    def assert_no_password_field(self, response):
        self.assertNotIn('type="password"', response.content.decode())

    # Responder (Clientst0r = B) -------------------------------------------------------
    def peer_authorises_here(self, peer=None, approve=True):
        """The peer starts; this installation's admin reviews and approves in
        its own UI. Returns (redirect URL to the peer, review response)."""
        peer = peer or self.qpeer
        url = peer.qc_start(CS_BASE, requested_scopes=self.SCOPES)
        self.assertTrue(url.startswith(CS_BASE + AUTHORIZE + '?invitation='), url)
        review = self.browser_get(url)
        self.assertEqual(review.status_code, 200, review.content[:500])
        self.assert_no_password_field(review)
        q = qc.parse_query(url)
        self.fresh()
        r = self.browser_post(AUTHORIZE, {'invitation': q['invitation'], 'state': q['state'],
                                          'op': 'approve' if approve else 'deny'})
        self.assertEqual(r.status_code, 303, r.content[:500])
        return r['Location'], review

    def grant(self):
        from connect.models import QuickConnectGrant
        return QuickConnectGrant.objects.select_related('connection').get()

    def craft_exchange(self, location, *, key=None, verifier=None, peer=None, code=None):
        """An exchange as the peer (A) would send it, with optional faults."""
        peer = peer or self.qpeer
        q = qc.parse_query(location)
        att = peer.qc_attempts[q['state']]
        conn = peer.connections[att['conn']]
        _, ka = conn.active_key()
        key = key or ka
        url = CS_BASE + qc.EXCHANGE_PATH
        exch, _ = qc.build_exchange(key, invitation=att['claims'], accept=unverified_payload(q['accept']),
                                    accept_jws=q['accept'], code=code or q['code'],
                                    code_verifier=verifier or att['verifier'], initiator_app=peer.app,
                                    discovery_url=peer.url(sdk_discovery.WELL_KNOWN),
                                    requested_scopes=att['scopes'])
        return url, exch, key

    def post_exchange(self, url, exch, key):
        r = self.net.request('POST', url, {'Content-Type': 'application/json',
                                           'DPoP': sdk_tokens.build_dpop_proof(key, 'POST', url)},
                             json.dumps({'exchange': exch}).encode())
        return r.status, json.loads(r.body or b'{}')

    # Initiator (Clientst0r = A) ---------------------------------------------------------
    def start_here(self, peer=None, scopes='connection:read customers:read events:publish'):
        """Screens 1-3 of the wizard. Returns (connection, authorise link)."""
        from connect.models import Connection
        peer = peer or self.qpeer
        r = self.browser_post(UI + 'quick-connect/', {'url': peer.base, 'op': 'check'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-qc-screen="network"')
        self.assert_no_password_field(r)
        r = self.browser_post(UI + 'quick-connect/', {
            'url': peer.base, 'op': 'authorize', 'own_egress': f'{CS_EGRESS}/32', 'egress_confirmed': 'on',
            'requested_scopes': scopes, 'destination_addresses': PEER_DEST_IP, 'orgs': [self.org_a.pk]})
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000])
        conn = Connection.objects.get(qc_revision='1.1', direction=Connection.OUTBOUND,
                                      state=Connection.PENDING_PAIRING)
        r = self.browser_get(UI + f'quick-connect/{conn.pk}/')
        self.assertContains(r, 'data-qc-authorize-link')
        self.assert_no_password_field(r)
        link = html.unescape(re.search(r'href="([^"]+)"[^>]*data-qc-authorize-link', r.content.decode()).group(1))
        return conn, link

    def peer_approves(self, link, peer=None, approve=True):
        peer = peer or self.qpeer
        rid = peer.qc_review(link)
        return peer.qc_authorize(rid, approve=approve)


class ResponderHappyPath(QcTestCase):
    """The reference peer (A) connects to Clientst0r (B)."""

    def test_flow_ends_awaiting_approval_with_equal_sas_and_nothing_granted(self):
        from connect.models import Connection, PairingRequest
        location, review = self.peer_authorises_here()
        self.assertContains(review, 'data-qc-temporary')
        self.assertIn(PEER_IP, review.content.decode())
        g = self.grant()
        conn = g.connection
        self.assertEqual(conn.state, Connection.PENDING_PAIRING)
        # Browser-address independence: the authorise requests came from
        # BROWSER_IP; the only rule is the peer's declared egress.
        self.assertEqual(self.rules(conn), [f'{PEER_IP}/32'])
        pconn = self.qpeer.qc_callback(location)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_LOCAL)
        self.assertEqual(pconn.state, 'awaiting_remote_approval')
        self.assertTrue(conn.sas)
        self.assertEqual(conn.sas, pconn.sas)
        self.assertEqual(conn.qc_revision, '1.1')
        g.refresh_from_db()
        self.assertIsNotNone(g.used_at)
        self.assertEqual(g.observed_source, PEER_IP)
        # Nothing auto-approved.
        self.assertEqual(conn.inbound_scopes, [])
        self.assertFalse(conn.tenant_grants.exists())
        self.assertEqual(self.rules(conn, status=['active']), [])
        preq = PairingRequest.objects.get(connection=conn)
        self.assertEqual(preq.status, PairingRequest.PENDING)
        # SAS on this side's review page too.
        r = self.browser_get(UI + f'requests/{preq.pk}/')
        self.assertContains(r, f'data-connect-sas>{conn.sas}<')
        self.assertContains(r, 'data-qc-attempt')
        # The peer polls (v1) from its egress: pending.
        self.assertEqual(self.qpeer.poll(pconn.id), 'pending')
        # No password went anywhere.
        for url, body in self.sent:
            self.assertNotIn(b'password', body.lower(), url)
            self.assertNotIn(b'pw-Admin', body)
        from connect import audit_log
        self.assertIsNone(audit_log.verify())

    def test_then_v1_approval_and_tenant_isolation(self):
        from connect import pairing
        from connect.models import PairingRequest
        location, _ = self.peer_authorises_here()
        pconn = self.qpeer.qc_callback(location)
        conn = self.grant().connection
        preq = PairingRequest.objects.get(connection=conn)
        pairing.approve_inbound(preq, destination_addresses=[PEER_DEST_IP], scopes=self.SCOPES,
                                grants=[(self.org_a.pk, 'cust-1', ['customers:read', 'events:publish'])],
                                requested_scopes=self.PEER_SCOPES, user=self.admin)
        self.assertEqual(self.qpeer.poll(pconn.id), 'approved')
        self.qpeer.accept(pconn.id, scopes=self.PEER_SCOPES,
                          tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-1',
                                          'scopes': ['customers:read', 'events:publish']}])
        conn.refresh_from_db()
        # C3: the other side's address is approved separately, and the
        # connection is active only after a passing test.
        self.assertEqual(conn.state, 'awaiting_network')
        from connect import activation
        from tech_access import protected
        req = type('Req', (), {})()
        req.user, req.session, req.META, req.path = self.admin, {protected.SESSION_KEY: int(time.time())}, {}, '/'
        activation.approve_change(activation.propose_peer_sources(conn, [PEER_IP], self.admin), req)
        self.commit(conn)
        r = self.qpeer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(json.loads(r.body), {'tenant': 'cust-1', 'name': 'Acme Customer'})
        # Cross-organization isolation: a customer that was not granted is unreachable.
        r = self.qpeer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-2')
        self.assertIn(r.status, (403, 404), r.body)
        self.assertNotIn(b'Beta Customer', r.body)
        r = self.qpeer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers')
        self.assertEqual([t['name'] for t in json.loads(r.body)['tenants']], ['Acme Customer'])
        self.assertNotIn(b'Beta Customer', r.body)


class InitiatorHappyPath(QcTestCase):
    """Clientst0r (A) connects to the reference peer (B)."""

    def test_flow_ends_awaiting_remote_with_equal_sas(self):
        from connect import pairing
        from connect.models import Connection
        conn, link = self.start_here()
        self.assertTrue(link.startswith(self.qpeer.base + qc.AUTHORIZE_ENTRY_PATH + '?invitation='))
        inv = unverified_payload(qc.parse_query(link)['invitation'])
        self.assertEqual(inv['egress'], [{'net': f'{CS_EGRESS}/32', 'note': ''}])
        self.assertEqual(inv['base'], CS_BASE)
        self.assertEqual(inv['responder_installation'], self.qpeer.installation_id)
        back = self.peer_approves(link)
        r = self.browser_get(back)
        self.assertEqual(r.status_code, 302, r.content[:500])
        r = self.browser_get(UI + f'quick-connect/{conn.pk}/')
        self.assertContains(r, 'data-qc-screen="confirm"')
        self.assertContains(r, f'{PEER_IP}/32')
        self.assert_no_password_field(r)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.PENDING_PAIRING)
        self.assertEqual(self.rules(conn), [])       # nothing before the administrator approves
        # Not ticking the approval does nothing.
        self.browser_post(UI + f'quick-connect/{conn.pk}/', {'op': 'confirm'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.PENDING_PAIRING)
        self.assertEqual(self.rules(conn), [])
        r = self.browser_post(UI + f'quick-connect/{conn.pk}/', {'op': 'confirm', 'approve_peer': 'on'})
        self.assertEqual(r.status_code, 302)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_REMOTE, conn.last_error)
        pconn = self.qpeer.connections[self.qpeer.requests[conn.pairing_request_id]]
        self.assertEqual(pconn.state, 'awaiting_local_approval')
        self.assertEqual(conn.sas, pconn.sas)
        # The rules contain only the peer's signed egress, never a browser address.
        self.assertEqual(self.rules(conn), [f'{PEER_IP}/32'])
        r = self.browser_get(UI + f'quick-connect/{conn.pk}/')
        self.assertContains(r, f'data-connect-sas>{conn.sas}<')
        self.assert_no_password_field(r)
        # Single use: the code and verifier are wiped after the exchange.
        conn.qc_invitation.refresh_from_db()
        self.assertEqual((conn.qc_invitation.pending_code, conn.qc_invitation.code_verifier), ('', ''))
        for url, body in self.sent:
            self.assertNotIn(b'password', body.lower(), url)
        # Then v1, unchanged: the peer approves, Clientst0r polls and approves.
        self.qpeer.approve(conn.pairing_request_id, scopes=self.PEER_SCOPES,
                           tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-1',
                                           'scopes': ['customers:read', 'events:publish']}],
                           requested_scopes=self.SCOPES)
        self.assertEqual(pairing.poll(conn), 'approved')
        conn.refresh_from_db()
        pairing.approve_local(conn, scopes=self.SCOPES, grants=[(self.org_a.pk, 'cust-1', ['customers:read'])],
                              user=self.admin)
        conn.refresh_from_db()
        # C3: next, this side approves the other side's address; active only
        # after the connection test (test_increment_c3).
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)

    def test_callback_state_must_match_session_and_runs_once(self):
        from connect.models import Connection
        conn, link = self.start_here()
        back = self.peer_approves(link)
        # Another administrator's browser cannot use the answer.
        other = self.client_class()
        other.force_login(self.admin2)
        r = self.browser_get(back, client=other)
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, 'data-qc-error="state_mismatch"', status_code=400)
        # A forged state is refused too.
        r = self.browser_get(back.replace('state=', 'state=AAAA'), client=self.ui)
        self.assertContains(r, 'state_mismatch', status_code=400)
        self.assertEqual(self.browser_get(back).status_code, 302)
        r = self.browser_get(back)
        self.assertContains(r, 'data-qc-error="callback_used"', status_code=400)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.PENDING_PAIRING)

    def test_denied_at_the_peer_rolls_back(self):
        conn, link = self.start_here()
        back = self.peer_approves(link, approve=False)
        r = self.browser_get(back)
        self.assertContains(r, 'data-qc-error="access_denied"', status_code=400)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'failed')
        self.assertEqual(self.rules(conn, status=['temporary', 'active', 'staged']), [])


class InvitationRefusals(QcTestCase):
    """Clientst0r as B refuses bad invitations, each with its own code and an
    audit record, before anything is recorded or fetched."""

    def invitation(self, **kw):
        key = sdk_keys.generate_private_key()
        args = dict(initiator_app=self.qpeer.app, responder_origin=CS_BASE, attempt=str(__import__('uuid').uuid4()),
                    base=self.qpeer.base, redirect_uri=self.qpeer.base + '/agit8or-connect/qc-callback',
                    egress=[PEER_IP], requested_scopes=self.SCOPES,
                    code_challenge=qc.pkce_challenge(qc.generate_pkce_verifier()), nonce=qc.generate_nonce())
        claims_override = kw.pop('claims', None)
        args.update(kw)
        jws, claims = qc.build_invitation(key, **args)
        if claims_override:      # validly signed, but with claims a builder would refuse
            from agit8or_connect.jws import sign_compact, unverified_header
            jws = sign_compact(key, unverified_header(jws), {**claims, **claims_override})
        return jws

    def refused(self, jws, code):
        from connect.models import ConnectAuditEvent
        before = self.net.log[:]
        r = self.ui.get(AUTHORIZE, {'invitation': jws, 'state': qc.generate_state()}, REMOTE_ADDR=BROWSER_IP)
        self.assertEqual(r.status_code, 400, (code, r.content[:300]))
        self.assertContains(r, f'data-qc-error="{code}"', status_code=400)
        self.assertNotIn('type="password"', r.content.decode())
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='qc.invitation_refused', result=code).exists(),
                        code)
        self.assertEqual(self.net.log, before)      # nothing fetched

    def test_each_refusal_has_its_own_code(self):
        self.refused(self.invitation(now=int(time.time()) - 2000), 'invitation_expired')
        good = self.invitation()
        head, payload, sig = good.split('.')
        claims = json.loads(sdk_keys.b64url_decode(payload) if hasattr(sdk_keys, 'b64url_decode') else
                            __import__('base64').urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        claims['requested_scopes'] = ['connection:admin']
        from agit8or_connect.canonical import b64url, canonical_json
        self.refused('.'.join([head, b64url(canonical_json(claims).encode()), sig]), 'invalid_signature')
        self.refused(self.invitation(redirect_uri='https://evil.test/agit8or-connect/qc-callback'),
                     'invalid_redirect_uri')
        self.refused(self.invitation(base='https://127.0.0.1', redirect_uri='https://127.0.0.1/cb'), 'invalid_base')
        self.refused(self.invitation(base='https://169.254.169.254', redirect_uri='https://169.254.169.254/cb'),
                     'invalid_base')
        self.refused(self.invitation(responder_origin='https://another.test'), 'wrong_audience')
        self.refused(self.invitation(responder_installation='00000000-0000-4000-8000-000000000000'),
                     'wrong_audience')
        self.refused(self.invitation(claims={'egress': [{'net': '10.0.0.0/8', 'note': ''}]}), 'invalid_egress')
        self.refused(self.invitation(claims={'egress': [{'net': '127.0.0.1/32', 'note': ''}]}), 'invalid_egress')

    def test_reused_invitation(self):
        from connect.models import QuickConnectGrant
        url = self.qpeer.qc_start(CS_BASE, requested_scopes=self.SCOPES)
        # Viewing does not consume it; deciding does.
        self.assertEqual(self.browser_get(url).status_code, 200)
        self.assertEqual(self.browser_get(url).status_code, 200)
        q = qc.parse_query(url)
        self.fresh()
        self.assertEqual(self.browser_post(AUTHORIZE, {**q, 'op': 'approve'}).status_code, 303)
        r = self.browser_get(url)
        self.assertContains(r, 'data-qc-error="invitation_used"', status_code=400)
        r = self.browser_post(AUTHORIZE, {**q, 'op': 'approve'})
        self.assertContains(r, 'invitation_used', status_code=400)
        self.assertEqual(QuickConnectGrant.objects.count(), 1)

    def test_approve_needs_fresh_reauth_and_the_permission(self):
        from connect.models import Connection
        url = self.qpeer.qc_start(CS_BASE, requested_scopes=self.SCOPES)
        q = qc.parse_query(url)
        r = self.browser_get(url)
        self.assertContains(r, 'data-qc-reauth')
        r = self.browser_post(AUTHORIZE, {**q, 'op': 'approve'})
        self.assertContains(r, 'data-qc-error="reauth_required"', status_code=200)
        self.assertFalse(Connection.objects.exists())
        # The re-authentication page is this installation's own sign-in.
        r = self.ui.post(UI + 'confirm/', {'password': 'pw-Admin-1!x', 'next': AUTHORIZE + '?x=1'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], AUTHORIZE + '?x=1')
        r = self.ui.post(UI + 'confirm/', {'password': 'pw-Admin-1!x', 'next': 'https://evil.test/'})
        self.assertEqual(r['Location'], UI)
        # Somebody without manage_app_connections cannot even review.
        plain = User.objects.create_user('tech', 't@example.test', 'pw-Tech-1!x')
        c = self.client_class()
        c.force_login(plain)
        self.assertEqual(c.get(AUTHORIZE, {'invitation': q['invitation'], 'state': q['state']}).status_code, 403)
        # Not signed in: the login page, nothing else.
        r = self.client_class().get(AUTHORIZE, {'invitation': q['invitation'], 'state': q['state']})
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_duplicate_installation_warned(self):
        from connect.models import Connection
        Connection.objects.create(direction='inbound', state=Connection.SECURITY_BLOCKED, remote_app_type='x',
                                  remote_installation_id=self.qpeer.installation_id, base_url='https://x.test')
        url = self.qpeer.qc_start(CS_BASE, requested_scopes=self.SCOPES)
        self.assertContains(self.browser_get(url), 'data-connect-duplicate')


class ExchangeRefusals(QcTestCase):
    def approved(self):
        location, _ = self.peer_authorises_here()
        return location

    def test_wrong_source_refused_before_verification_and_shown(self):
        from connect import source_policy
        from connect.models import ConnectAuditEvent, SourceRule
        source_policy.apply_direct([{'layer': 'installation', 'network': OTHER_IP}], via='test')
        location = self.approved()
        g = self.grant()
        rules_before = SourceRule.objects.count()
        url, exch, key = self.craft_exchange(location)
        self.peer_ip = OTHER_IP
        # Even a garbage signature is never looked at: the source layer answers first.
        status, body = self.post_exchange(url, exch[:-4] + 'AAAA', key)
        self.assertEqual((status, body['error']['code']), (403, 'source_not_authorised'))
        status, body = self.post_exchange(url, exch, key)
        self.assertEqual((status, body['error']['code']), (403, 'source_not_authorised'))
        g.refresh_from_db()
        self.assertIsNone(g.used_at)
        self.assertEqual(g.refused_source, OTHER_IP)
        self.assertEqual(SourceRule.objects.count(), rules_before)
        self.assertEqual(self.rules(g.connection), [f'{PEER_IP}/32'])
        self.assertFalse(ConnectAuditEvent.objects.filter(operation='qc.exchange_accepted').exists())
        r = self.browser_get(UI + f'{g.connection.pk}/')
        self.assertContains(r, 'data-qc-refused-source')
        self.assertContains(r, OTHER_IP)
        # From the approved address the same exchange works.
        self.peer_ip = PEER_IP
        status, body = self.post_exchange(url, exch, key)
        self.assertEqual(status, 202, body)

    def test_wrong_verifier_other_key_expired_and_reused_code(self):
        from connect.models import Connection
        location = self.approved()
        url, exch, key = self.craft_exchange(location, verifier=qc.generate_pkce_verifier())
        self.assertEqual(self.post_exchange(url, exch, key)[1]['error']['code'], 'pkce_mismatch')
        other = sdk_keys.generate_private_key()
        url, exch, key = self.craft_exchange(location, key=other)
        self.assertEqual(self.post_exchange(url, exch, key)[1]['error']['code'], 'key_mismatch')
        url, exch, key = self.craft_exchange(location, code=qc.generate_code())
        # An unknown code names no attempt: refused by the source layer.
        self.assertEqual(self.post_exchange(url, exch, key), (403, mock.ANY))
        g = self.grant()
        self.assertEqual(g.connection.state, Connection.PENDING_PAIRING)
        # Valid now.
        url, exch, key = self.craft_exchange(location)
        self.assertEqual(self.post_exchange(url, exch, key)[0], 202)
        # The same code again (new exchange, new jti), or the same exchange
        # again: after the exchange the attempt keeps only a status-poll rule
        # (C3), so the source layer refuses both before any verification.
        url, exch2, key = self.craft_exchange(location)
        self.assertEqual(self.post_exchange(url, exch2, key)[1]['error']['code'], 'source_not_authorised')
        self.assertEqual(self.post_exchange(url, exch, key)[1]['error']['code'], 'source_not_authorised')
        from connect.models import QuickConnectGrant
        g = QuickConnectGrant.objects.get()
        g.refresh_from_db()
        self.assertIsNotNone(g.used_at)

    def test_code_expired(self):
        from connect.models import QuickConnectGrant
        location = self.approved()
        QuickConnectGrant.objects.update(code_expires_at=timezone.now() - timedelta(seconds=1))
        url, exch, key = self.craft_exchange(location)
        status, body = self.post_exchange(url, exch, key)
        self.assertEqual((status, body['error']['code']), (400, 'code_expired'))
        self.assertIsNone(self.grant().used_at)


class AttemptDeadline(QcTestCase):
    def test_abandoned_initiator_attempt_rolled_back(self):
        from connect import identity
        from connect.models import ConnectionKey
        conn, link = self.start_here()
        self.browser_get(self.peer_approves(link))
        conn.refresh_from_db()
        from connect import source_policy
        source_policy.pairing_rules_for_connection(conn, [f'{PEER_IP}/32'], self.admin,
                                                   expires_at=conn.qc_attempt_expires_at)
        type(conn).objects.filter(pk=conn.pk).update(qc_attempt_expires_at=timezone.now() - timedelta(seconds=1))
        v = identity.get().connect_policy_version
        call_command('connect_deliver_events', stdout=__import__('io').StringIO())
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'failed')
        self.assertEqual(self.rules(conn, status=['temporary', 'active', 'staged']), [])
        self.assertTrue(self.rules(conn, status=['removed']))
        self.assertFalse(conn.keys.exclude(state=ConnectionKey.RETIRED).exists())
        self.assertFalse(conn.keys.exclude(private_key='').exists())
        self.assertGreater(identity.get().connect_policy_version, v)
        from connect.models import ApprovedDestination
        self.assertFalse(ApprovedDestination.objects.filter(connection=conn).exists())

    def test_abandoned_responder_attempt_rolled_back(self):
        from connect import identity
        self.peer_authorises_here()
        conn = self.grant().connection
        self.assertEqual(self.rules(conn, status=['temporary']), [f'{PEER_IP}/32'])
        type(conn).objects.filter(pk=conn.pk).update(qc_attempt_expires_at=timezone.now() - timedelta(seconds=1))
        v = identity.get().connect_policy_version
        call_command('connect_deliver_events', stdout=__import__('io').StringIO())
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'failed')
        self.assertEqual(self.rules(conn, status=['temporary', 'active']), [])
        self.assertGreater(identity.get().connect_policy_version, v)


class OffSwitchesAndFallback(QcTestCase):
    def test_qc_disabled(self):
        from connect import identity
        from connect.models import InstallationIdentity
        url = self.qpeer.qc_start(CS_BASE, requested_scopes=self.SCOPES)
        self.assertContains(self.ui.get(UI), 'data-qc-start')
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=False)
        self.assertNotContains(self.ui.get(UI), 'data-qc-start')
        self.assertEqual(self.browser_get(url).status_code, 404)
        self.assertEqual(self.ui.get(UI + 'quick-connect/').status_code, 404)
        r = self.net.request('POST', CS_BASE + qc.EXCHANGE_PATH, {'Content-Type': 'application/json'},
                             b'{"exchange": "x.y.z"}')
        self.assertEqual(r.status, 404)
        doc = identity.document()
        self.assertNotIn('extensions', doc)
        self.assertNotIn('qc_exchange', doc['endpoints'])

    def test_discovery_advertises_only_what_is_served(self):
        from connect import identity
        doc = identity.document()
        self.assertEqual(doc['versions'], ['1'])
        self.assertEqual(doc['extensions'], {'qc-bootstrap': 1, 'qc-source-binding': 1})
        self.assertEqual(doc['endpoints']['qc_authorize'], CS_BASE + AUTHORIZE)
        self.assertEqual(qc.pairing_flow(qc.negotiate_extensions(
            qc.advertised_extensions(doc, CS_BASE + sdk_discovery.WELL_KNOWN))), qc.BOOTSTRAP_ID)

    @override_settings(AGIT8OR_CONNECT_PUBLIC_URL='https://Clientst0r.test/')
    def test_public_url_must_be_canonical(self):
        r = self.ui.get(UI + 'quick-connect/')
        self.assertContains(r, 'data-connect-not-configured')
        from connect import identity
        doc = identity.document()
        self.assertNotIn('extensions', doc)

    def test_fallback_to_code_flow_with_v1_peer(self):
        from connect.models import Connection
        # self.peer is a v1-only reference peer (discovery readable, no 1.1).
        r = self.browser_post(UI + 'quick-connect/', {'url': self.peer.base, 'op': 'authorize',
                                                      'own_egress': f'{CS_EGRESS}/32', 'egress_confirmed': 'on',
                                                      'requested_scopes': 'customers:read',
                                                      'destination_addresses': PEER_DEST_IP})
        self.assertContains(r, 'data-qc-fallback')
        self.assertContains(r, 'data-qc-code-flow')
        self.assertFalse(Connection.objects.exists())
        # The v1 code flow still works against it.
        conn, _ = self.pair_outbound()
        self.assertEqual(conn.state, 'active')

    def test_kill_switch(self):
        from connect import lifecycle
        from connect.models import Connection
        location, _ = self.peer_authorises_here()       # before the switch
        url2 = self.qpeer.qc_start(CS_BASE, requested_scopes=self.SCOPES)
        lifecycle.engage_kill_switch(self.admin)
        q = qc.parse_query(url2)
        self.fresh()
        r = self.browser_post(AUTHORIZE, {**q, 'op': 'approve'})
        self.assertContains(r, 'data-qc-error="kill_switch"', status_code=400)
        url, exch, key = self.craft_exchange(location)
        self.assertEqual(self.post_exchange(url, exch, key)[0], 503)
        r = self.browser_post(UI + 'quick-connect/', {
            'url': self.qpeer.base, 'op': 'authorize', 'own_egress': f'{CS_EGRESS}/32', 'egress_confirmed': 'on',
            'requested_scopes': 'customers:read', 'destination_addresses': PEER_DEST_IP})
        self.assertContains(r, 'kill switch')
        self.assertEqual(Connection.objects.filter(direction='outbound').count(), 0)

    def test_security_blocked_peer_and_destination_change(self):
        from connect.models import Connection
        conn, link = self.start_here()
        blocked = Connection.objects.create(direction='outbound', state=Connection.SECURITY_BLOCKED,
                                            remote_app_type='x', remote_installation_id=self.qpeer.installation_id,
                                            base_url='https://x.test')
        r = self.browser_get(self.peer_approves(link))
        self.assertContains(r, 'data-qc-error="duplicate"', status_code=400)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'failed')
        blocked.delete()
        # A destination change during the exchange fails the attempt; nothing is sent.
        conn, link = self.start_here()
        self.browser_get(self.peer_approves(link))
        origin = sdk_discovery.origin(self.qpeer.base)
        real = self.net.request

        def changed(method, url, headers=None, body=None, source=None):
            if sdk_discovery.origin(url) == origin:
                raise ConnectError('destination_changed', 'resolved outside the pin', 502)
            return real(method, url, headers, body, source)
        with mock.patch.object(self.net, 'request', changed):
            self.browser_post(UI + f'quick-connect/{conn.pk}/', {'op': 'confirm', 'approve_peer': 'on'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'failed')
        self.assertEqual(self.rules(conn, status=['temporary', 'active']), [])
        self.assertFalse(any(u.startswith(self.qpeer.base + qc.EXCHANGE_PATH) for u, _ in self.sent))
