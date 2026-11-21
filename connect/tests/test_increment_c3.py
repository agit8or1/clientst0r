"""Quick Connect increment C3 (roadmap 79.13, rest of 79.14, 79.25): two-sided
authorisation, network approval of the other side's addresses, the commit
gate (active only after a passing test) and staged permission changes
(docs/plans/quick-connect/INCREMENTS.md §C3, DESIGN.md §4.1, §6.7, §11)."""
import json
import time
from datetime import timedelta
from unittest import mock

from django.db import DatabaseError
from django.utils import timezone

from agit8or_connect.errors import ConnectError

from .base import CS_BASE, PEER_DEST_IP, PEER_IP, ConnectTestCase
from .test_increment_c2 import OTHER_IP, UI, QcTestCase


class _Req:
    def __init__(self, user):
        from tech_access import protected
        self.user, self.session = user, {protected.SESSION_KEY: int(time.time())}
        self.META, self.path = {}, '/'


def _active_rules(conn):
    from connect.models import SourceRule
    return sorted(SourceRule.objects.filter(connection=conn, status='active').values_list('network', 'purpose'))


class C3Mixin:
    # Responder (Clientst0r = B): the 1.1 reference peer is A.
    def responder_until_approved(self, *, accept=True):
        """Quick Connect to Clientst0r, exchange, B approves permissions and
        customers; the peer learns the result (and accepts). Returns (pconn, conn)."""
        from connect import pairing
        from connect.models import PairingRequest
        location, _ = self.peer_authorises_here()
        pconn = self.qpeer.qc_callback(location)
        conn = self.grant().connection
        preq = PairingRequest.objects.get(connection=conn)
        self.assertIsNone(pairing.approve_inbound(
            preq, destination_addresses=[PEER_DEST_IP], scopes=self.SCOPES,
            grants=[(self.org_a.pk, 'cust-1', ['customers:read', 'events:publish'])],
            requested_scopes=self.PEER_SCOPES, user=self.admin))
        conn.refresh_from_db()
        if accept:
            self.assertEqual(self.qpeer.poll(pconn.id), 'approved')
            self.qpeer.accept(pconn.id, scopes=self.PEER_SCOPES,
                              tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-1',
                                              'scopes': ['customers:read', 'events:publish']}])
        return pconn, conn

    def approve_peer(self, conn, nets=(PEER_IP,), purpose='all', user=None):
        from connect import activation
        change = activation.propose_peer_sources(conn, list(nets), user or self.admin, purpose=purpose)
        pc = activation.approve_change(change, _Req(user or self.admin))
        conn.refresh_from_db()
        return change, pc

    def peer_tests_us(self, conn):
        """The other side runs its own connection test against this one
        (its qc-diagnostics probe), which is what lets this side's
        diagnostics step 14 (reverse connectivity) pass (increment E)."""
        pconn = self.qpeer.connections[self.qpeer.requests[conn.pairing_request_id]]
        pconn.remote_endpoints.setdefault('api_base', CS_BASE + '/connect/v1')
        self.qpeer.qc_probe(pconn.id)

    def commit(self, conn):
        from connect import activation, diagnostics
        conn.refresh_from_db()
        if conn.qc_revision == '1.1' and conn.direction == 'outbound':
            if conn.state == 'awaiting_network':
                activation.maybe_start_testing(conn, self.admin)     # re-open the test window first
                conn.refresh_from_db()
            if conn.state == 'testing' and 'reverse' in diagnostics.required_steps(conn):
                self.peer_tests_us(conn)
        return super().commit(conn)

    # Initiator (Clientst0r = A): the 1.1 reference peer is B.
    def initiator_until_approved(self, scopes=None):
        from connect import pairing
        conn, link = self.start_here()
        self.browser_get(self.peer_approves(link))
        self.browser_post(UI + f'quick-connect/{conn.pk}/', {'op': 'confirm', 'approve_peer': 'on'})
        conn.refresh_from_db()
        self.qpeer.approve(conn.pairing_request_id, scopes=self.PEER_SCOPES,
                           tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-1',
                                           'scopes': ['customers:read', 'events:publish']}],
                           requested_scopes=self.SCOPES)
        self.assertEqual(pairing.poll(conn), 'approved')
        conn.refresh_from_db()
        pairing.approve_local(conn, scopes=scopes or self.SCOPES,
                              grants=[(self.org_a.pk, 'cust-1', ['customers:read'])], user=self.admin)
        conn.refresh_from_db()
        return conn


class ResponderFullFlow(C3Mixin, QcTestCase):
    def test_active_only_after_reverse_approval_and_a_passing_test(self):
        from connect import activation
        from connect.models import Connection, SourceRule
        location, _ = self.peer_authorises_here()
        pconn = self.qpeer.qc_callback(location)
        conn = self.grant().connection
        # After the exchange only the status poll stays, until the attempt deadline.
        rule = SourceRule.objects.get(connection=conn, status='temporary')
        self.assertEqual((rule.purpose, rule.expires_at), ('poll', conn.qc_attempt_expires_at))
        from connect import pairing
        from connect.models import PairingRequest
        preq = PairingRequest.objects.get(connection=conn)
        pairing.approve_inbound(preq, destination_addresses=[PEER_DEST_IP], scopes=self.SCOPES,
                                grants=[(self.org_a.pk, 'cust-1', ['customers:read', 'events:publish'])],
                                requested_scopes=self.PEER_SCOPES, user=self.admin)
        conn.refresh_from_db()
        # Quick Connect: approving permissions does not approve the other side's address.
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        self.assertEqual(_active_rules(conn), [])
        # Its approval is still learnt through the narrow poll rule.
        self.assertEqual(self.qpeer.poll(pconn.id), 'approved')
        self.qpeer.accept(pconn.id, scopes=self.PEER_SCOPES,
                          tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-1',
                                          'scopes': ['customers:read', 'events:publish']}])
        # Reverse direction not approved: the peer cannot reach the token endpoint here.
        with self.assertRaises(ConnectError) as e:
            self.qpeer.get_token(pconn.id)
        self.assertEqual(e.exception.status, 403)
        r = self.browser_get(UI + f'{conn.pk}/')
        self.assertContains(r, 'data-connect-approve-network')
        self.assertNotContains(r, 'CONNECTED')
        # Proposing alone changes nothing.
        change = activation.propose_peer_sources(conn, [PEER_IP], self.admin)
        self.assertFalse(change.widening)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        with self.assertRaises(ConnectError):
            self.qpeer.get_token(pconn.id)
        self.assertIsNone(activation.approve_change(change, _Req(self.admin)))
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        test_rule = SourceRule.objects.get(connection=conn, change=change)
        self.assertEqual((test_rule.status, test_rule.purpose), ('temporary', 'all'))
        self.assertLessEqual(test_rule.expires_at, timezone.now() + activation.TEST_WINDOW)
        # Testing: the peer may test (token, capabilities) but reaches no customer data.
        self.assertEqual(self.qpeer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities').status, 200)
        r = self.qpeer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(r.status, 401)
        self.assertNotIn(b'Acme', r.body)
        self.assertNotContains(self.browser_get(UI + f'{conn.pk}/'), 'CONNECTED')
        report = activation.run_commit_test(conn, self.admin)
        self.assertTrue(report['ok'], report)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.ACTIVE)
        ids = [c['id'] for c in report['checks']]
        for step in ('dns', 'destination', 'tcp', 'tls', 'certificate', 'identity', 'protocol', 'source', 'token',
                     'permissions', 'tenants', 'event'):
            self.assertIn(step, ids)
        # Commit: the approved rule is active; the poll rule is gone.
        self.assertEqual(_active_rules(conn), [(f'{PEER_IP}/32', 'all')])
        self.assertFalse(SourceRule.objects.filter(connection=conn, status='temporary').exists())
        r = self.qpeer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(json.loads(r.body)['name'], 'Acme Customer')
        self.assertContains(self.browser_get(UI + f'{conn.pk}/'), 'CONNECTED')
        from connect import audit_log
        from connect.models import ConnectAuditEvent
        ev = ConnectAuditEvent.objects.get(operation='connection.committed', connection_id=str(conn.pk))
        self.assertEqual(ev.detail['run_id'], report['run_id'])
        self.assertIsNone(audit_log.verify())

    def test_responder_checks_initiator_identity_at_commit(self):
        """The initiator's discovery is re-read at commit time: another
        installation behind its address fails the attempt."""
        from connect.models import Connection
        pconn, conn = self.responder_until_approved()
        real = self.qpeer.document

        def other():
            d = real()
            d['installation_id'] = '00000000-0000-4000-8000-000000000001'
            d['app'] = {**d.get('app', {}), 'installation_id': d['installation_id']}
            return d
        self.approve_peer(conn)
        with mock.patch.object(self.qpeer, 'document', other):
            from connect import activation
            report = activation.run_commit_test(conn, self.admin)
        self.assertFalse(report['ok'])
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.FAILED)
        self.assertEqual(self.rules(conn, status=['temporary', 'active', 'staged']), [])

    def test_failed_test_stays_testing_with_time_limited_rule(self):
        """The other side has not finished (no accept yet): the test fails at
        authentication, nothing is active, the test rule is time-limited."""
        from connect import activation
        from connect.models import Connection, SourceRule
        pconn, conn = self.responder_until_approved(accept=False)
        self.approve_peer(conn)
        report = activation.run_commit_test(conn, self.admin)
        self.assertFalse(report['ok'])
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.assertIn('Authentication', conn.last_error)
        self.assertEqual(_active_rules(conn), [])
        for r in SourceRule.objects.filter(connection=conn, status='temporary'):
            self.assertIsNotNone(r.expires_at)
            self.assertLessEqual(r.expires_at, max(timezone.now() + activation.TEST_WINDOW,
                                                   conn.qc_attempt_expires_at))
        r = self.browser_get(UI + f'{conn.pk}/')
        self.assertContains(r, 'data-connect-commit-test')
        self.assertContains(r, 'data-connect-check="token"')
        self.assertNotContains(r, 'CONNECTED')
        # The other side completes; the retest commits.
        self.assertEqual(self.qpeer.poll(pconn.id), 'approved')
        self.qpeer.accept(pconn.id, scopes=self.PEER_SCOPES, tenant_grants=[])
        self.commit(conn)


class InitiatorFullFlow(C3Mixin, QcTestCase):
    def test_wizard_to_connected_through_the_ui(self):
        from connect.models import Connection, SourceRule
        conn = self.initiator_until_approved()
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        self.assertEqual(_active_rules(conn), [])
        r = self.browser_get(UI + f'quick-connect/{conn.pk}/')
        self.assertNotContains(r, 'data-qc-connected')
        r = self.browser_get(UI + f'{conn.pk}/')
        self.assertContains(r, 'data-connect-activation="awaiting_network"')
        self.assertContains(r, f'{PEER_IP}/32')       # the peer's signed egress, approved for the pairing
        # Without the password nothing is approved.
        self.browser_post(UI + f'{conn.pk}/', {'op': 'approve_network', 'networks': f'{PEER_IP}/32',
                                               'purpose': 'all'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        self.assertFalse(SourceRule.objects.filter(connection=conn, change__status='approved').exists())
        self.assertFalse(conn.network_changes.filter(kind='source_rules').exists())
        r = self.browser_post(UI + f'{conn.pk}/', {'op': 'approve_network', 'networks': f'{PEER_IP}/32',
                                                   'purpose': 'all', 'password': 'pw-Admin-1!x'})
        self.assertEqual(r.status_code, 302)
        conn.refresh_from_db()
        # E: a Quick Connect connection also needs diagnostics step 14 -- the
        # other side has to have reached this one -- so it keeps testing
        # until the other side ran its own test, then the retest commits.
        self.assertEqual(conn.state, Connection.TESTING, conn.last_error)
        self.assertIn('Reverse connectivity', conn.last_error)
        self.peer_tests_us(conn)
        self.browser_post(UI + f'{conn.pk}/', {'op': 'commit_test'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.ACTIVE, conn.last_error)
        self.assertTrue(conn.last_test['ok'])
        self.assertEqual(_active_rules(conn), [(f'{PEER_IP}/32', 'all')])
        self.assertContains(self.browser_get(UI + f'quick-connect/{conn.pk}/'), 'data-qc-connected')

    def test_network_failure_returns_to_awaiting_network_without_exposure(self):
        from connect import activation, destinations
        from connect.models import Connection, SourceRule
        conn = self.initiator_until_approved()

        def refused(url, **kw):
            host, port = destinations.host_port(url)
            return destinations.Preview(host=host, port=port, addresses=[PEER_DEST_IP], cert_names=[host],
                                        error='The connection to port 443 was refused.', code='tcp_refused')
        with mock.patch('connect.transport.probe', refused):
            self.approve_peer(conn)
            report = activation.run_commit_test(conn, self.admin)
        self.assertFalse(report['ok'])
        steps = {c['id']: c['status'] for c in report['checks']}
        self.assertEqual((steps['dns'], steps['tcp'], steps['token']), ('pass', 'fail', 'skipped'))
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        self.assertIn('TCP', conn.last_error)
        self.assertEqual(_active_rules(conn), [])
        # The approval stays (staged, not evaluated); the pairing rule stays time-limited.
        self.assertTrue(SourceRule.objects.filter(connection=conn, status='staged').exists())
        for r in SourceRule.objects.filter(connection=conn, status='temporary'):
            self.assertIsNotNone(r.expires_at)
        # Fixed on the other side: the retest re-opens the window and commits.
        self.commit(conn)

    def test_destination_outside_approved_addresses_fails(self):
        from connect import activation, destinations
        conn = self.initiator_until_approved()

        def moved(url, **kw):
            host, port = destinations.host_port(url)
            return destinations.Preview(host=host, port=port, addresses=['93.184.216.77'], cert_names=[host])
        with mock.patch('connect.transport.probe', moved):
            self.approve_peer(conn)
            self.assertFalse(activation.run_commit_test(conn, self.admin)['ok'])
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'awaiting_network')
        self.assertEqual(next(c for c in conn.last_test['checks'] if c['status'] == 'fail')['code'],
                         'destination_changed')

    def test_one_directional_allows_only_discovery(self):
        from connect import activation
        conn = self.initiator_until_approved()
        self.approve_peer(conn, purpose='discovery')
        self.assertEqual(conn.state, 'testing')
        self.commit(conn)
        self.assertEqual(_active_rules(conn), [(f'{PEER_IP}/32', 'discovery')])
        pconn = self.qpeer.connections[self.qpeer.requests[conn.pairing_request_id]]
        self.assertEqual(self.net.request('GET', CS_BASE + '/.well-known/agit8or-connect', source=PEER_IP).status,
                         200)
        with self.assertRaises(ConnectError) as e:
            self.qpeer.get_token(pconn.id)
        self.assertEqual(e.exception.status, 403)
        self.assertIsNotNone(activation)

    def test_commit_is_atomic(self):
        from connect import activation
        from connect.models import ApprovedDestination, Connection
        conn = self.initiator_until_approved()
        with mock.patch('connect.activation.run_commit_test'):
            self.approve_peer(conn)          # testing, test not run yet
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.peer_tests_us(conn)
        with mock.patch('connect.destinations.activate', side_effect=DatabaseError('disk full')):
            with self.assertRaises(DatabaseError):
                activation.run_commit_test(conn, self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.assertEqual(_active_rules(conn), [])
        self.assertEqual(ApprovedDestination.objects.get(connection=conn).status, 'staged')
        # A commit needs the id of the latest passing run.
        with self.assertRaises(activation.ActivationRefused):
            activation.commit_connection(conn, 'not-a-run', self.admin)
        conn.refresh_from_db()
        self.assertNotEqual(conn.state, Connection.ACTIVE)

    def test_kill_switch_closes_the_test_window(self):
        from connect import activation, lifecycle
        from connect.models import Connection
        conn = self.initiator_until_approved()
        with mock.patch('connect.activation.run_commit_test'):
            self.approve_peer(conn)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        lifecycle.engage_kill_switch(self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        self.assertFalse(self.rules(conn, status=['active']))
        with self.assertRaises(activation.ActivationRefused):
            activation.run_commit_test(conn, self.admin)
        lifecycle.release_kill_switch(self.admin)
        self.commit(conn)


class ReverseRuleApproval(C3Mixin, QcTestCase):
    def test_widening_needs_a_second_administrator_and_a_current_fingerprint(self):
        from connect import activation, source_policy
        from connect.models import ConnectChange, Connection
        from tech_access import protected
        source_policy.apply_direct([{'layer': 'installation', 'network': OTHER_IP}], via='test')
        pconn, conn = self.responder_until_approved()
        # Another address than the one approved for the pairing widens access.
        change = activation.propose_peer_sources(conn, [OTHER_IP], self.admin)
        self.assertTrue(change.widening)
        pc = activation.approve_change(change, _Req(self.admin))
        self.assertIsNotNone(pc)
        change.refresh_from_db()
        self.assertEqual(change.status, ConnectChange.AWAITING_SECOND)
        protected.confirm(pc, _Req(self.admin))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(pc, _Req(self.admin))          # never by the proposer
        # The rules change after the proposal: refused.
        source_policy.pairing_rules_for_connection(conn, ['93.184.216.55/32'], self.admin,
                                                   expires_at=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(pc, _Req(self.admin2))
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_NETWORK)
        # Proposed again, approved by a second administrator: testing (not active).
        change = activation.propose_peer_sources(conn, [OTHER_IP], self.admin)
        pc = activation.approve_change(change, _Req(self.admin))
        protected.confirm(pc, _Req(self.admin))
        protected.approve(pc, _Req(self.admin2))
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.assertEqual(_active_rules(conn), [])

    def test_private_and_range_widen(self):
        from connect import activation
        pconn, conn = self.responder_until_approved()
        self.assertTrue(activation.propose_peer_sources(conn, ['93.184.216.0/24'], self.admin).widening)
        self.assertTrue(activation.propose_peer_sources(conn, ['10.0.0.5'], self.admin, private=True).widening)
        self.assertFalse(activation.propose_peer_sources(conn, [PEER_IP], self.admin).widening)

    def test_needs_fresh_reauth_and_the_right_state(self):
        from connect import activation, source_policy
        pconn, conn = self.responder_until_approved()
        change = activation.propose_peer_sources(conn, [PEER_IP], self.admin)
        req = _Req(self.admin)
        req.session = {}
        with self.assertRaises(source_policy.ChangeRefused):
            activation.approve_change(change, req)
        self.approve_peer(conn)
        with self.assertRaises(activation.ActivationRefused):     # testing now
            activation.propose_peer_sources(conn, [PEER_IP], self.admin)


class V1CodeFlow(ConnectTestCase):
    """Fixes QC-07 for the v1 code flow too; the Rem0te ticket-rmm-v1 link
    and already-active connections are unaffected."""

    def test_outbound_runs_the_test_before_active(self):
        from connect import pairing
        from connect.models import Connection, ConnectAuditEvent
        code = self.peer.create_invitation()
        conn = pairing.start_outbound(pairing.discover(self.peer.base), code, destination_addresses=[PEER_DEST_IP],
                                      requested_scopes=self.PEER_SCOPES, organizations=[self.org_a],
                                      user=self.admin, peer_sources=[self.peer_ip])
        self.peer.approve(conn.pairing_request_id, scopes=self.PEER_SCOPES, tenant_grants=[],
                          requested_scopes=self.SCOPES)
        pairing.poll(conn)
        conn.refresh_from_db()
        # The peer's token endpoint is broken: approval leaves the connection testing.
        pconn = self.peer.connections[self.peer.requests[conn.pairing_request_id]]
        pconn.state = 'awaiting_local_approval'
        pairing.approve_local(conn, scopes=self.SCOPES, grants=[], user=self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.assertFalse(conn.last_test['ok'])
        self.assertEqual(_active_rules(conn), [])
        self.assertFalse(ConnectAuditEvent.objects.filter(operation='connection.committed').exists())
        pconn.state = 'active'
        self.commit(conn)
        self.assertEqual(_active_rules(conn), [(f'{PEER_IP}/32', 'all')])

    def test_inbound_passes_straight_through_network_approval(self):
        pconn, conn = self.pair_inbound()       # asserts testing after approval, then commits
        self.assertEqual(_active_rules(conn), [(f'{PEER_IP}/32', 'all')])
        from connect.models import ConnectChange
        ch = ConnectChange.objects.get(connection=conn, kind='source_rules')
        self.assertEqual((ch.status, ch.widening, ch.approved_by), ('applied', False, self.admin))

    def test_existing_active_connection_is_unaffected(self):
        """A connection that was active before this release: no new state, no
        retest, tokens and calls work exactly as before."""
        import importlib
        from connect import lifecycle, source_policy
        from connect.models import Connection
        pconn, conn = self.pair_inbound()
        # As a pre-C3 row: active, an active rule, no committed-test record.
        Connection.objects.filter(pk=conn.pk).update(last_test={})
        conn.refresh_from_db()
        mig = importlib.import_module('connect.migrations.0005_c3_activation_states')
        self.assertTrue(all(type(op).__name__ == 'AlterField' for op in mig.Migration.operations))
        r = self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(json.loads(r.body)['name'], 'Acme Customer')
        lifecycle.suspend(conn, self.admin)
        lifecycle.resume(conn, self.admin)       # D: through testing and the commit gate, which passes here
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.ACTIVE)
        # Tokens issued in the same second as the suspension stay refused
        # (whole-second iat); a later token works as before.
        Connection.objects.filter(pk=conn.pk).update(tokens_not_before=timezone.now() - timedelta(seconds=5))
        r = self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(r.status, 200)
        self.assertTrue(source_policy.test_address(PEER_IP, str(conn.pk))['allowed'])


class TwoSidedAuthorisation(ConnectTestCase):
    def test_a_scope_granted_one_way_never_implies_the_reverse(self):
        """The peer grants us events:publish; we grant it only customers:read.
        It cannot obtain events:publish here, and nothing it grants or asks
        changes what it may do here."""
        from connect import pairing
        code = self.peer.create_invitation()
        conn = pairing.start_outbound(pairing.discover(self.peer.base), code, destination_addresses=[PEER_DEST_IP],
                                      requested_scopes=self.PEER_SCOPES, organizations=[self.org_a],
                                      user=self.admin, peer_sources=[self.peer_ip])
        self.peer.approve(conn.pairing_request_id, scopes=self.PEER_SCOPES, tenant_grants=[],
                          requested_scopes=self.SCOPES)
        pairing.poll(conn)
        conn.refresh_from_db()
        pairing.approve_local(conn, scopes=['connection:read', 'customers:read'], grants=[], user=self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active', conn.last_error)
        self.assertIn('events:publish', conn.outbound_scopes)
        self.assertNotIn('events:publish', conn.inbound_scopes)
        pconn = self.peer.connections[self.peer.requests[conn.pairing_request_id]]
        with self.assertRaises(ConnectError):
            self.peer.get_token(pconn.id, scopes=['events:publish'])
        tok = self.peer.get_token(pconn.id)
        self.assertEqual(sorted(tok['scope'].split()), ['connection:read', 'customers:read'])

    def test_no_transitive_trust_between_connections(self):
        """Peer 1's connection grants nothing on peer 2's connection, even with
        its own valid token."""
        from agit8or_connect.reference_peer import ReferencePeer
        p1, c1 = self.pair_inbound()
        peer2 = ReferencePeer('https://rmm2.test', self.net, app_type='rem0te', display_name='Second')
        p2, c2 = self.pair_inbound(peer2, tenant='cust-2', org=self.org_b)
        r = self.peer.call(p1.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-2')
        self.assertIn(r.status, (403, 404))
        self.assertNotIn(b'Beta Customer', r.body)
        r = self.peer.call(p1.id, 'GET', f'{CS_BASE}/connect/v1/customers')
        self.assertEqual([t['name'] for t in json.loads(r.body)['tenants']], ['Acme Customer'])


class StagedPermissionChanges(ConnectTestCase):
    def test_preview_approve_and_narrowing_only_rollback(self):
        from connect import permissions
        from connect.models import ConnectChange
        conn, pconn = self.pair_outbound()
        self.assertEqual(conn.inbound_scopes, sorted(self.SCOPES))
        # 1. narrow: drop events:publish.
        ch1 = permissions.propose(conn, scopes=['connection:read', 'customers:read'],
                                  grants=[(self.org_a.pk, 'cust-1', ['customers:read'])], user=self.admin)
        self.assertIn('permission events:publish', ch1.preview['loses'])
        self.assertFalse(ch1.preview['gains'])
        conn.refresh_from_db()
        self.assertIn('events:publish', conn.inbound_scopes)      # staged: nothing changed yet
        self.assertIsNone(permissions.approve(ch1, _Req(self.admin)))
        conn.refresh_from_db()
        self.assertEqual(conn.inbound_scopes, ['connection:read', 'customers:read'])
        # 2. add events:publish back and drop customers:read.
        ch2 = permissions.propose(conn, scopes=['connection:read', 'events:publish'],
                                  grants=[(self.org_a.pk, 'cust-1', ['events:publish'])], user=self.admin)
        self.assertIn('permission events:publish', ch2.preview['gains'])
        self.assertIn('permission customers:read', ch2.preview['loses'])
        permissions.approve(ch2, _Req(self.admin))
        conn.refresh_from_db()
        self.assertEqual(conn.inbound_scopes, ['connection:read', 'events:publish'])
        # Rollback of 2 never restores customers:read: only the intersection.
        rb = permissions.rollback(ConnectChange.objects.get(pk=ch2.pk), _Req(self.admin))
        conn.refresh_from_db()
        self.assertEqual(conn.inbound_scopes, ['connection:read'])
        self.assertEqual(rb.rollback_of_id, ch2.pk)
        self.assertFalse(rb.preview['gains'])
        g = conn.tenant_grants.get(organization=self.org_a)
        self.assertEqual(g.scopes, [])
        # Tokens already issued lose the permission at once.
        r = self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(r.status, 403)

    def test_stale_fingerprint_and_reauth(self):
        from connect import permissions, source_policy
        conn, _ = self.pair_outbound()
        ch = permissions.propose(conn, scopes=['connection:read'], grants=[], user=self.admin)
        req = _Req(self.admin)
        req.session = {}
        with self.assertRaises(source_policy.ChangeRefused):
            permissions.approve(ch, req)
        other = permissions.propose(conn, scopes=['connection:read', 'customers:read'], grants=[], user=self.admin)
        permissions.approve(other, _Req(self.admin))
        with self.assertRaises(source_policy.ChangeRefused):
            permissions.approve(ch, _Req(self.admin))
        with self.assertRaises(permissions.PermissionChangeRefused):     # never asked for by the peer
            permissions.propose(conn, scopes=['assets:read'], grants=[], user=self.admin)

    def test_elevated_scope_needs_second_admin(self):
        from agit8or_connect.scopes import Catalog, Scope
        from connect import catalog, permissions
        from connect.models import Connection
        from tech_access import protected
        cat = Catalog(list(catalog.CATALOG.scopes) + [Scope('lab_actions:execute', 'Lab action', 'high_risk')])
        conn, _ = self.pair_outbound()
        Connection.objects.filter(pk=conn.pk).update(
            peer_requested_scopes=list(conn.peer_requested_scopes) + ['lab_actions:execute'])
        conn.refresh_from_db()
        with mock.patch.object(catalog, 'CATALOG', cat):
            ch = permissions.propose(conn, scopes=list(conn.inbound_scopes) + ['lab_actions:execute'],
                                     grants=[(self.org_a.pk, 'cust-1', ['customers:read'])], user=self.admin)
            self.assertTrue(ch.preview['second_admin'])
            pc = permissions.approve(ch, _Req(self.admin))
            self.assertIsNotNone(pc)
            conn.refresh_from_db()
            self.assertNotIn('lab_actions:execute', conn.inbound_scopes)
            protected.confirm(pc, _Req(self.admin))
            with self.assertRaises(protected.ProtectedChangeError):
                protected.approve(pc, _Req(self.admin))
            protected.approve(pc, _Req(self.admin2))
        conn.refresh_from_db()
        self.assertIn('lab_actions:execute', conn.inbound_scopes)

    def test_ui_add_customer_is_staged(self):
        conn, _ = self.pair_outbound()
        n = conn.tenant_grants.count()
        r = self.ui.post(UI + f'{conn.pk}/', {'op': 'add_grant', 'grant_rows': '1', 'org_0': str(self.org_b.pk),
                                              'tenant_0': 'cust-2', 'scope_0': ['customers:read']},
                         secure=True, HTTP_HOST='clientst0r.test')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(conn.tenant_grants.count(), n)
        from connect.models import ConnectChange
        ch = ConnectChange.objects.get(connection=conn, kind='permissions', status='staged')
        self.assertTrue(any('customer' in g for g in ch.preview['gains']))
        self.assertContains(self.ui.get(UI + f'{conn.pk}/', secure=True, HTTP_HOST='clientst0r.test'),
                            f'data-connect-change="{ch.pk}"')
