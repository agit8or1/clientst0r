"""Quick Connect increment D (roadmap 79.16 health states, 79.17 automatic
reconnection, 79.18 event queue recovery) plus the qc-diagnostics probe and
the fifteen diagnostic steps (docs/plans/quick-connect/INCREMENTS.md §D,
DESIGN.md §4.2, §4.3, §7.3, §8, §9, §10). Time and transport are mocked:
the in-memory reference peer over a Network, a fixed DNS/TLS preview."""
import json
import random
import time
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from agit8or_connect import quick_connect as qc
from agit8or_connect.errors import ConnectError
from agit8or_connect.http import Response

from .base import CS_BASE, PEER_BASE, PEER_DEST_IP, PEER_IP, ConnectTestCase

UI = '/settings/integrations/connected-apps/'
LADDER = (10, 30, 60, 120, 300, 600, 900, 900)


class Probe:
    """Controllable DNS + TLS preview (connect.transport.probe)."""

    def __init__(self):
        self.calls = 0
        self.addresses = [PEER_DEST_IP]
        self.code = ''
        self.error = ''
        self.spki = ''
        self.not_after = ''

    def __call__(self, url, **kw):
        from connect import destinations
        self.calls += 1
        host, port = destinations.host_port(url)
        return destinations.Preview(host=host, port=port, addresses=list(self.addresses) if self.code not in
                                    ('dns_nxdomain', 'blocked_destination') else [], cert_names=[host],
                                    spki=self.spki, error=self.error, code=self.code, not_after=self.not_after)


class DTestCase(ConnectTestCase):
    def setUp(self):
        super().setUp()
        self.probe = Probe()
        p = mock.patch('connect.transport.probe', self.probe)
        p.start()
        self.addCleanup(p.stop)
        self.rng = random.Random(20261121)

    def outbound(self):
        conn, pconn = self.pair_outbound()
        conn.refresh_from_db()
        if conn.state == 'testing':
            self.commit(conn)
            conn.refresh_from_db()
        self.assertEqual(conn.state, 'active', conn.last_error)
        return conn, pconn

    def commit(self, conn):
        """pair_outbound already commits when the reference peer answers;
        commit only what is still under test."""
        conn.refresh_from_db()
        if conn.state == 'testing':
            return super().commit(conn)
        self.assertEqual(conn.state, 'active', conn.last_error)
        return None

    def check(self, conn, now):
        from connect import health
        conn.refresh_from_db()
        health.check_one(conn, now, self.rng)
        conn.refresh_from_db()
        return conn

    def peer_down(self):
        self.net.down.add('https://rmm.test:443')

    def peer_up(self):
        self.net.down.clear()


# --- displayed status ---------------------------------------------------------------------

class DisplayedStatus(ConnectTestCase):
    def test_state_table(self):
        from connect import status
        from connect.models import Connection as C
        table = [
            (C.PENDING_PAIRING, '', 'pending_setup', 'Pending Setup'),
            (C.AWAITING_REMOTE, '', 'awaiting_approval', 'Awaiting Approval'),
            (C.AWAITING_LOCAL, '', 'awaiting_approval', 'Awaiting Approval'),
            (C.AWAITING_SECOND, '', 'awaiting_approval', 'Awaiting Approval'),
            (C.AWAITING_NETWORK, '', 'awaiting_network', 'Awaiting Network Authorization'),
            (C.TESTING, '', 'testing', 'Testing'),
            (C.ACTIVE, '', 'connected', 'Connected'),
            (C.ACTIVE, C.HEALTH_CONNECTED, 'connected', 'Connected'),
            (C.ACTIVE, C.HEALTH_DEGRADED, 'degraded', 'Degraded'),
            (C.ACTIVE, C.HEALTH_OFFLINE, 'offline', 'Offline'),
            (C.SECURITY_BLOCKED, C.HEALTH_CONNECTED, 'security_blocked', 'Security Blocked'),
            (C.SUSPENDED, C.HEALTH_OFFLINE, 'suspended', 'Suspended'),
            (C.REVOKED, '', 'revoked', 'Revoked'),
            (C.FAILED, '', 'setup_failed', 'Setup failed'),
        ]
        for state, health, key, label in table:
            d = status.display(C(state=state, health=health))
            self.assertEqual((d.key, d.label), (key, label), state)

    def test_connected_only_after_commit(self):
        """A pairing under test never displays Connected; commit sets it."""
        from connect import status
        from connect import pairing
        from connect.models import PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=self.SCOPES,
                                        proposed_tenants=[{'id': 'cust-1', 'label': 'x'}])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        self.assertEqual(status.display(preq.connection).key, 'awaiting_approval')
        pairing.approve_inbound(preq, destination_addresses=[PEER_DEST_IP], scopes=self.SCOPES,
                                grants=[(self.org_a.pk, 'cust-1', ['customers:read'])],
                                requested_scopes=self.PEER_SCOPES, user=self.admin)
        self.assertEqual(self.peer.poll(pconn.id), 'approved')
        self.peer.accept(pconn.id, scopes=self.PEER_SCOPES)
        conn = preq.connection
        conn.refresh_from_db()
        self.assertEqual(status.display(conn).key, 'testing')
        self.commit(conn)
        conn.refresh_from_db()
        self.assertEqual((status.display(conn).key, conn.health, conn.circuit), ('connected', 'connected', 'closed'))
        self.assertIsNotNone(conn.next_check_at)
        r = self.ui.get(UI, secure=True, HTTP_HOST='clientst0r.test')
        self.assertContains(r, 'data-connect-status="connected"')


# --- health, hysteresis, ladder ---------------------------------------------------------------

class HealthAndBackoff(DTestCase):
    def test_interval_is_60s_with_10_percent_jitter(self):
        from connect import health
        conn, _ = self.outbound()
        now = timezone.now()
        for i in range(20):
            now = conn.next_check_at
            conn = self.check(conn, now)
            gap = (conn.next_check_at - now).total_seconds()
            self.assertGreaterEqual(gap, 54)
            self.assertLessEqual(gap, 66)
            self.assertEqual(conn.health, 'connected')
        self.assertEqual(health.interval_delay(type(conn)(monitor_interval_s=5)) // 1 >= 27, True)

    def test_hysteresis_and_ladder(self):
        """Two failures -> Degraded, three transport failures -> Offline (circuit
        open); the ladder 10, 30, 60, 120, 300, 600, 900, 900 s ± 20 %; two
        passes -> Connected."""
        conn, _ = self.outbound()
        self.peer_down()
        now = conn.next_check_at
        seen, healths = [], []
        for expected in LADDER:
            conn = self.check(conn, now)
            gap = (conn.next_check_at - now).total_seconds()
            self.assertGreaterEqual(gap, expected * 0.8 - 0.001, (expected, gap))
            self.assertLessEqual(gap, expected * 1.2 + 0.001, (expected, gap))
            seen.append(gap)
            healths.append(conn.health)
            now = conn.next_check_at
        self.assertEqual(healths[:3], ['connected', 'degraded', 'offline'])
        self.assertEqual(conn.circuit, 'open')
        self.assertEqual(conn.consecutive_fail, len(LADDER))
        self.assertEqual(conn.retry_step, 6)               # capped at 15 minutes
        self.assertEqual(conn.health_dims['transport']['ok'], False)
        # Recovery: the half-open probe passes (circuit closed, still Offline),
        # the second pass makes it Connected; then the normal interval again.
        self.peer_up()
        conn = self.check(conn, now)
        self.assertEqual((conn.health, conn.circuit, conn.retry_step), ('offline', 'closed', 0))
        self.assertLessEqual((conn.next_check_at - now).total_seconds(), 12)
        now = conn.next_check_at
        conn = self.check(conn, now)
        self.assertEqual(conn.health, 'connected')
        self.assertGreaterEqual((conn.next_check_at - now).total_seconds(), 54)

    def test_seeded_jitter_is_deterministic_and_bounded(self):
        from connect import health
        a = [health.backoff_delay(i, random.Random(7)) for i in range(9)]
        b = [health.backoff_delay(i, random.Random(7)) for i in range(9)]
        self.assertEqual(a, b)

        class Edge:
            def __init__(self, v):
                self.v = v

            def uniform(self, lo, hi):
                return hi if self.v else lo
        for step, base in enumerate(LADDER):
            self.assertAlmostEqual(health.backoff_delay(step, Edge(1)), base * 1.2)
            self.assertAlmostEqual(health.backoff_delay(step, Edge(0)), base * 0.8)
        self.assertEqual(health.backoff_delay(99, Edge(1)), 900 * 1.2)

    def test_non_transport_failure_degrades_but_never_offline(self):
        from connect import health
        conn, _ = self.outbound()
        now = conn.next_check_at
        res = health.CheckResult.fail('authenticated', 'invalid_dpop_proof', 'refused')
        for _ in range(5):
            conn.refresh_from_db()
            health.apply(conn, res, now, self.rng)
            now = now + timedelta(seconds=1)
        conn.refresh_from_db()
        self.assertEqual((conn.health, conn.circuit, conn.state), ('degraded', 'closed', 'active'))

    def test_restart_resumes_schedule(self):
        """The ladder position and the next check live in the database: a new
        process neither restarts at 10 s nor checks before the due time."""
        from connect import monitor
        conn, _ = self.outbound()
        self.peer_down()
        now = conn.next_check_at
        for _ in range(4):
            conn = self.check(conn, now)
            now = conn.next_check_at
        from connect.models import Connection
        fresh = Connection.objects.get(pk=conn.pk)      # "after a restart"
        self.assertEqual((fresh.retry_step, fresh.circuit, fresh.health), (4, 'open', 'offline'))
        calls = self.probe.calls
        res = monitor.run_pass(now=fresh.next_check_at - timedelta(seconds=5))
        self.assertEqual(res['checked'], 0)
        self.assertEqual(self.probe.calls, calls)
        res = monitor.run_pass(now=fresh.next_check_at)
        self.assertEqual(res['checked'], 1)
        fresh.refresh_from_db()
        self.assertEqual(fresh.retry_step, 5)

    def test_crash_in_a_check_is_isolated_and_resumed(self):
        """Raise inside a check: the run returns, the connection is rescheduled
        on the ladder, no connection is checked twice in one pass, and the
        next run checks it."""
        from connect import health, monitor
        conn, _ = self.outbound()
        conn2, _ = self.pair_outbound(self._second_peer(), tenant='cust-1', org=self.org_b)
        self.commit(conn2)
        from connect.models import Connection
        now = timezone.now() + timedelta(minutes=5)
        Connection.objects.filter(pk__in=[conn.pk, conn2.pk]).update(next_check_at=now - timedelta(seconds=1))
        seen = []
        real = health.check_one

        def boom(c, *a, **k):
            seen.append(c.pk)
            if c.pk == conn.pk:
                raise RuntimeError('defect')
            return real(c, *a, **k)
        with mock.patch('connect.health.check_one', boom):
            res = monitor.run_pass(now=now)
        self.assertEqual(sorted(seen), sorted([conn.pk, conn2.pk]))
        self.assertEqual((res['errors'], res['checked']), (1, 1))
        conn.refresh_from_db()
        self.assertGreater(conn.next_check_at, now)
        self.assertLessEqual(conn.next_check_at, now + timedelta(seconds=13))
        # Claimed rows are not checked again in the same pass.
        with mock.patch('connect.health.check_one', boom):
            seen.clear()
            monitor.run_pass(now=now)
        self.assertEqual(seen, [])
        res = monitor.run_pass(now=conn.next_check_at)
        self.assertEqual(res['checked'], 1)

    def _second_peer(self):
        from agit8or_connect.reference_peer import ReferencePeer
        p = ReferencePeer('https://rmm2.test', self.net, app_type='rem0te', display_name='Second',
                          tenants={'cust-1': 'One'})
        return p

    def test_compare_and_set_claim(self):
        from connect import health
        conn, _ = self.outbound()
        stale = type(conn).objects.get(pk=conn.pk)
        self.assertTrue(health.claim(conn))
        self.assertFalse(health.claim(stale))          # a second runner with the old value loses

    def test_monitor_run_loops_within_budget(self):
        """50 s budget: the 10 s and 30 s steps happen inside one run."""
        from connect import monitor
        conn, _ = self.outbound()
        type(conn).objects.filter(pk=conn.pk).update(next_check_at=timezone.now())
        self.peer_down()
        clock = [0.0]

        def sleep(s):
            clock[0] += s
            # advance the database schedule as if the time had passed
            type(conn).objects.filter(pk=conn.pk).update(next_check_at=timezone.now())
        t = monitor.run(budget=50, clock=lambda: clock[0], sleep=sleep)
        self.assertGreaterEqual(t['passes'], 2)
        self.assertLessEqual(clock[0], 50)
        conn.refresh_from_db()
        self.assertGreaterEqual(conn.consecutive_fail, 2)


# --- no reconnect after a security failure --------------------------------------------------

class SecurityFailures(DTestCase):
    def assertBlocked(self, conn, code):
        from connect.models import ConnectAuditEvent
        conn.refresh_from_db()
        self.assertEqual((conn.state, conn.security_block_code), ('security_blocked', code))
        self.assertIsNone(conn.next_check_at)
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='connection.security_blocked',
                                                         result=code).exists())
        # Never retried: the monitor makes zero calls, even when "due".
        from connect import monitor
        type(conn).objects.filter(pk=conn.pk).update(next_check_at=timezone.now() - timedelta(hours=1))
        probes, log = self.probe.calls, len(self.net.log)
        for _ in range(3):
            monitor.run_pass(now=timezone.now() + timedelta(hours=2))
        self.assertEqual((self.probe.calls, len(self.net.log)), (probes, log))

    def _check(self, conn):
        return self.check(conn, conn.next_check_at)

    def test_destination_changed(self):
        conn, _ = self.outbound()
        self.probe.addresses = ['93.184.216.99']
        self._check(conn)
        self.assertBlocked(conn, 'destination_changed')
        self.assertEqual(conn.security_block_detail['addresses'], ['93.184.216.99'])

    def test_certificate_invalid(self):
        conn, _ = self.outbound()
        self.probe.code, self.probe.error = 'certificate_invalid', 'TLS certificate not accepted (expired).'
        self._check(conn)
        self.assertBlocked(conn, 'certificate_invalid')

    def test_certificate_name_mismatch(self):
        conn, _ = self.outbound()
        self.probe.code = 'certificate_name_mismatch'
        self._check(conn)
        self.assertBlocked(conn, 'certificate_name_mismatch')

    def test_spki_mismatch(self):
        from connect.models import ApprovedDestination
        conn, _ = self.outbound()
        ApprovedDestination.objects.filter(connection=conn).update(spki_pins=['pinned-key-hash'])
        self.probe.spki = 'another-key-hash'
        self._check(conn)
        self.assertBlocked(conn, 'spki_mismatch')

    def test_peer_revoked(self):
        conn, pconn = self.outbound()
        self.peer.revoke(pconn.id)
        from connect import client
        client.clear_cache()
        self._check(conn)
        self.assertBlocked(conn, 'peer_revoked')

    def test_key_revoked(self):
        conn, _ = self.outbound()
        with mock.patch('connect.client.get_token', side_effect=ConnectError('key_revoked', 'key refused', 401)):
            self._check(conn)
        self.assertBlocked(conn, 'key_revoked')

    def test_source_not_authorised_by_peer(self):
        conn, _ = self.outbound()
        inner = self.net.handlers['https://rmm.test:443']

        def refusing(method, url, headers, body):
            if url.endswith('/token'):
                return Response(403, {}, json.dumps({'error': {'code': 'source_not_authorised',
                                                               'message': 'no'}}).encode())
            return inner(method, url, headers, body)
        self.net.handlers['https://rmm.test:443'] = refusing
        from connect import client
        client.clear_cache()
        self._check(conn)
        self.assertBlocked(conn, 'source_not_authorised')

    def test_scope_withdrawn(self):
        conn, pconn = self.outbound()
        before = list(conn.outbound_scopes)
        pconn.inbound_scopes = [s for s in pconn.inbound_scopes if s != 'customers:read']
        from connect import client
        client.clear_cache()
        self._check(conn)
        self.assertBlocked(conn, 'scope_withdrawn')
        conn.refresh_from_db()
        self.assertEqual(sorted(conn.outbound_scopes), sorted(before))     # never narrowed silently
        self.assertEqual(conn.security_block_detail['missing_scopes'], ['customers:read'])

    def test_invalid_signature(self):
        conn, _ = self.outbound()
        with mock.patch('connect.health.light_check', return_value=__import__(
                'connect.health', fromlist=['x']).CheckResult.fail('authorised', 'invalid_signature', 'bad')):
            self._check(conn)
        self.assertBlocked(conn, 'invalid_signature')

    def test_identity_changed_on_retest_blocks_a_committed_connection(self):
        """Resume runs the commit-gate test; a different installation at the
        address blocks the connection (never rolled back, never retried)."""
        from connect import lifecycle
        conn, _ = self.outbound()
        lifecycle.suspend(conn, self.admin)
        self.peer.installation_id = self.peer.app['installation_id'] = 'f' * 8 + '-0000-4000-8000-' + '0' * 12
        lifecycle.resume(conn, self.admin)
        self.assertBlocked(conn, 'identity_changed')
        conn.refresh_from_db()
        self.assertTrue(conn.keys.filter(state='active').exists())          # not rolled back like a pairing

    def test_evidence_kept_after_successful_retest(self):
        """An administrator approves the new address, the retest goes through
        testing and the commit gate, and the block evidence stays."""
        from connect import destinations
        from connect.models import ConnectAuditEvent
        from .test_increment_c3 import _Req
        conn, _ = self.outbound()
        self.probe.addresses = ['93.184.216.99']
        self._check(conn)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'security_blocked')
        self.assertFalse(destinations.retest(conn, self.admin))         # nothing approved since the block
        self.assertEqual(type(conn).objects.get(pk=conn.pk).state, 'security_blocked')
        ch = destinations.propose_change(conn, ['93.184.216.99'], self.admin)
        destinations.approve(ch, _Req(self.admin))
        mark = ConnectAuditEvent.objects.order_by('-seq').first().seq
        self.assertTrue(destinations.retest(conn, self.admin))
        conn.refresh_from_db()
        self.assertEqual((conn.state, conn.health), ('active', 'connected'))
        self.assertEqual(conn.security_block_code, 'destination_changed')
        self.assertEqual(conn.security_block_detail['addresses'], ['93.184.216.99'])
        ops = list(ConnectAuditEvent.objects.filter(seq__gt=mark).order_by('seq').values_list('operation', 'result'))
        self.assertIn(('connection.retest', 'testing'), ops)
        self.assertIn(('connection.committed', 'ok'), ops)
        self.assertLess(ops.index(('connection.retest', 'testing')), ops.index(('connection.committed', 'ok')))

    def test_no_checks_while_suspended_revoked_or_kill_switch(self):
        from connect import lifecycle, monitor
        conn, _ = self.outbound()
        lifecycle.suspend(conn, self.admin)
        conn2, _ = self.pair_outbound(HealthAndBackoff._second_peer(self), org=self.org_b)
        self.commit(conn2)
        lifecycle.revoke(conn2, self.admin)
        type(conn).objects.update(next_check_at=timezone.now() - timedelta(hours=1))
        probes, log = self.probe.calls, len(self.net.log)
        self.assertEqual(monitor.run_pass(now=timezone.now())['checked'], 0)
        conn3, _ = self.pair_outbound(self._third_peer(), org=self.org_b)
        self.commit(conn3)
        lifecycle.engage_kill_switch(self.admin)
        probes, log = self.probe.calls, len(self.net.log)
        type(conn).objects.update(next_check_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(monitor.run_pass(now=timezone.now())['checked'], 0)
        t = monitor.run(budget=5, clock=lambda: 0.0, sleep=lambda s: None)
        self.assertTrue(t.get('kill_switch'))
        self.assertEqual((self.probe.calls, len(self.net.log)), (probes, log))

    def _third_peer(self):
        from agit8or_connect.reference_peer import ReferencePeer
        return ReferencePeer('https://rmm3.test', self.net, app_type='rem0te', display_name='Third',
                             tenants={'cust-1': 'One'})


# --- event queue recovery (QC-06) ------------------------------------------------------------

class QueueRecovery(DTestCase):
    def go_offline(self, conn):
        self.peer_down()
        now = conn.next_check_at
        for _ in range(3):
            conn = self.check(conn, now)
            now = conn.next_check_at
        self.assertEqual((conn.health, conn.circuit), ('offline', 'open'))
        return conn

    def test_offline_keeps_attempts_and_drains_in_order_after_nine_hours(self):
        from connect import events, monitor
        from connect.models import DeliveryAttempt, OutboundEvent
        conn, pconn = self.outbound()
        grant = conn.tenant_grants.get()
        conn = self.go_offline(conn)
        evs = [events.enqueue(conn, 'alert.raised', {'n': i}, grant=grant) for i in range(5)]
        nine_hours_ago = timezone.now() - timedelta(hours=9)
        for i, ev in enumerate(evs):
            OutboundEvent.objects.filter(pk=ev.pk).update(created_at=nine_hours_ago + timedelta(seconds=i),
                                                          next_attempt_at=nine_hours_ago)
        log = len(self.net.log)
        for _ in range(30):          # 9 h of scheduler runs while Offline
            events.deliver_due()
            monitor.upkeep()
        self.assertEqual(len(self.net.log), log)              # short-circuited: nothing sent
        self.assertEqual(set(OutboundEvent.objects.filter(pk__in=[e.pk for e in evs])
                             .values_list('status', 'attempts')), {('queued', 0)})
        self.assertFalse(DeliveryAttempt.objects.filter(event__in=evs).exists())
        # Recovery: half-open probe passes, the circuit closes, the queue drains.
        self.peer_up()
        conn = self.check(conn, conn.next_check_at)
        self.assertEqual(conn.circuit, 'closed')
        OutboundEvent.objects.filter(pk__in=[e.pk for e in evs]).update(next_attempt_at=timezone.now())
        self.assertEqual(events.deliver_due()['delivered'], 5)
        got = [e['data']['n'] for e in pconn.received_events if e['type'] == 'alert.raised']
        self.assertEqual(got, [0, 1, 2, 3, 4])                # in order, once each
        self.assertEqual(set(OutboundEvent.objects.filter(pk__in=[e.pk for e in evs])
                             .values_list('status', 'attempts')), {('delivered', 1)})
        self.assertEqual(events.deliver_due()['delivered'], 0)

    def test_ordered_drain_blocks_behind_the_oldest(self):
        from connect import events
        from connect.models import OutboundEvent
        conn, pconn = self.outbound()
        grant = conn.tenant_grants.get()
        first = events.enqueue(conn, 'alert.raised', {'n': 1}, grant=grant)
        second = events.enqueue(conn, 'alert.raised', {'n': 2}, grant=grant)
        OutboundEvent.objects.filter(pk=first.pk).update(next_attempt_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(events.deliver_due()['delivered'], 0)    # the newer one waits for the older
        OutboundEvent.objects.filter(pk=first.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(events.deliver_due()['delivered'], 2)
        self.assertEqual([e['data']['n'] for e in pconn.received_events if e['type'] == 'alert.raised'], [1, 2])

    def test_age_dead_letter_and_requeue(self):
        from connect import events
        from connect.models import ConnectAuditEvent, OutboundEvent
        conn, pconn = self.outbound()
        ev = events.enqueue(conn, 'alert.raised', {'n': 1}, grant=conn.tenant_grants.get())
        OutboundEvent.objects.filter(pk=ev.pk).update(created_at=timezone.now() - timedelta(days=8))
        self.assertEqual(events.expire_aged(), 1)
        ev.refresh_from_db()
        self.assertEqual(ev.status, 'dead')
        self.assertIn('Expired', ev.last_error)
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='event.expired').exists())
        # The failed list offers Requeue (same id); delivered once.
        page = self.ui.get(UI + f'{conn.pk}/', secure=True, HTTP_HOST='clientst0r.test')
        self.assertContains(page, 'data-connect-dead-letters')
        r = self.ui.post(UI + f'{conn.pk}/', {'op': 'requeue', 'event': str(ev.pk)}, secure=True,
                         HTTP_HOST='clientst0r.test')
        self.assertEqual(r.status_code, 302)
        ev.refresh_from_db()
        self.assertEqual((ev.status, ev.attempts), ('queued', 0))
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='event.requeued').exists())
        self.assertEqual(events.deliver_due()['delivered'], 1)
        self.assertEqual([e['id'] for e in pconn.received_events if e['type'] == 'alert.raised'], [str(ev.pk)])
        self.assertEqual(events.expire_aged(), 0)     # the age counts from the requeue

    def test_requeue_needs_manage_permission(self):
        from django.contrib.auth.models import User
        from django.test import Client
        from connect import events
        from connect.models import OutboundEvent
        conn, _ = self.outbound()
        ev = events.enqueue(conn, 'alert.raised', {}, grant=conn.tenant_grants.get())
        OutboundEvent.objects.filter(pk=ev.pk).update(status='dead')
        viewer = User.objects.create_user('viewer', 'v@example.test', 'pw-Viewer-1!x')
        c = Client()
        c.force_login(viewer)
        r = c.post(UI + f'{conn.pk}/', {'op': 'requeue', 'event': str(ev.pk)}, secure=True,
                   HTTP_HOST='clientst0r.test')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(OutboundEvent.objects.get(pk=ev.pk).status, 'dead')

    def test_prune_delivered_only(self):
        from connect import events
        from connect.models import OutboundEvent
        conn, _ = self.outbound()
        old = events.enqueue(conn, 'alert.raised', {}, grant=conn.tenant_grants.get())
        dead = events.enqueue(conn, 'alert.raised', {}, grant=conn.tenant_grants.get())
        OutboundEvent.objects.filter(pk=old.pk).update(status='delivered',
                                                       delivered_at=timezone.now() - timedelta(days=91))
        OutboundEvent.objects.filter(pk=dead.pk).update(status='dead', created_at=timezone.now() - timedelta(days=200))
        events.prune_delivered()
        self.assertFalse(OutboundEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(OutboundEvent.objects.filter(pk=dead.pk).exists())

    def test_deliver_events_command_still_works_alone(self):
        import io
        from django.core.management import call_command
        from connect import events
        conn, pconn = self.outbound()
        events.enqueue(conn, 'alert.raised', {'n': 7}, grant=conn.tenant_grants.get())
        out = io.StringIO()
        call_command('connect_deliver_events', stdout=out)
        self.assertIn('delivered 1', out.getvalue())
        self.assertEqual([e['data']['n'] for e in pconn.received_events if e['type'] == 'alert.raised'], [7])

    def test_monitor_command(self):
        import io
        from django.core.management import call_command
        conn, _ = self.outbound()
        type(conn).objects.filter(pk=conn.pk).update(next_check_at=timezone.now())
        out = io.StringIO()
        call_command('connect_monitor', '--budget', '0', stdout=out)
        self.assertIn('checked 1 connection', out.getvalue())

    @override_settings(AGIT8OR_CONNECT_ENABLED=False)
    def test_monitor_command_off_by_default(self):
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('connect_monitor', stdout=out)
        self.assertIn('is off', out.getvalue())

    def test_scheduler_registration(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['connect_monitor'], ('connect_monitor', []))
        self.assertIn('connect_monitor', dict(ScheduledTask.TASK_TYPES))
        self.assertIn('connect_deliver_events', COMMAND_TASKS)


# --- resume through testing; v1 (Rem0te-style) connection ------------------------------------

class ResumeAndV1(DTestCase):
    def test_resume_goes_through_testing_and_the_monitor_retests(self):
        from connect import lifecycle, monitor
        from connect.models import ConnectAuditEvent
        conn, _ = self.outbound()
        lifecycle.suspend(conn, self.admin)
        self.peer_down()
        lifecycle.resume(conn, self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'testing')              # not active before a passing test
        self.assertIsNotNone(conn.retest_until)
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='connection.resumed', result='testing').exists())
        r = self.ui.get(UI + f'{conn.pk}/', secure=True, HTTP_HOST='clientst0r.test')
        self.assertNotContains(r, 'CONNECTED')
        self.peer_up()
        monitor.run_pass(now=conn.next_check_at)
        conn.refresh_from_db()
        self.assertEqual((conn.state, conn.health), ('active', 'connected'))

    def test_auto_retest_stops_after_its_window(self):
        from connect import monitor
        conn, _ = self.outbound()
        from connect import lifecycle
        lifecycle.suspend(conn, self.admin)
        self.peer_down()
        lifecycle.resume(conn, self.admin)
        conn.refresh_from_db()
        later = conn.retest_until + timedelta(seconds=1)
        type(conn).objects.filter(pk=conn.pk).update(next_check_at=later)
        log = len(self.net.log)
        monitor.run_pass(now=later)
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'testing')
        self.assertIsNone(conn.next_check_at)
        self.assertEqual(len(self.net.log), log)

    def test_v1_inbound_connection_transient_failure_reconnects(self):
        """An already-active v1 connection (the Rem0te shape: code flow, no
        1.1) gets health states and reconnection for transient failures."""
        pconn, conn = self.pair_inbound()
        self.assertEqual(conn.qc_revision, '')
        conn.refresh_from_db()
        self.peer_down()
        now = conn.next_check_at
        for _ in range(3):
            conn = self.check(conn, now)
            now = conn.next_check_at
        self.assertEqual((conn.state, conn.health), ('active', 'offline'))
        self.peer_up()
        conn = self.check(conn, now)
        conn = self.check(conn, conn.next_check_at)
        self.assertEqual((conn.state, conn.health), ('active', 'connected'))
        # The other side still reaches customer data as before.
        r = self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(r.status, 200)

    def test_v1_inbound_connection_security_failure_stays_blocked(self):
        from connect import monitor
        pconn, conn = self.pair_inbound()
        conn.refresh_from_db()
        self.probe.addresses = ['93.184.216.99']
        conn = self.check(conn, conn.next_check_at)
        self.assertEqual(conn.state, 'security_blocked')
        self.probe.addresses = [PEER_DEST_IP]            # even if it "comes back"
        type(conn).objects.filter(pk=conn.pk).update(next_check_at=timezone.now())
        monitor.run_pass(now=timezone.now() + timedelta(hours=1))
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'security_blocked')
        with self.assertRaises(ConnectError):
            self.peer.get_token(pconn.id)


# --- alerts -----------------------------------------------------------------------------------

class Alerts(DTestCase):
    def markers(self, conn, key):
        from core.models import SystemWarningNotification
        return SystemWarningNotification.objects.filter(warning_id__startswith=f'connect:{conn.pk}:{key}:').count()

    def test_flapping_is_deduplicated_and_recovery_sent_once(self):
        from connect import health
        conn, _ = self.outbound()
        fail = health.CheckResult.fail('authorised', 'http_500', 'boom', kind='transport')
        ok = health.CheckResult(True, 'ok', '', '', {d: (True, '') for d in health.DIMS})
        now = conn.next_check_at
        for i in range(120):          # two hours: fail, fail, pass, pass, ...
            conn.refresh_from_db()
            health.apply(conn, fail if (i // 2) % 2 == 0 else ok, now, self.rng)
            now += timedelta(minutes=1)
        self.assertEqual(self.markers(conn, 'degraded'), 1)
        self.assertEqual(self.markers(conn, 'connected'), 1)
        from connect.models import ConnectAuditEvent
        self.assertGreater(ConnectAuditEvent.objects.filter(operation='connection.status').count(), 50)

    def test_new_alert_allowed_after_thirty_minutes(self):
        from connect import alerts, status
        conn, _ = self.outbound()
        self.assertTrue(alerts.notify(conn, status.OFFLINE))
        self.assertFalse(alerts.notify(conn, status.OFFLINE))
        later = timezone.now() + timedelta(minutes=31)
        with mock.patch('django.utils.timezone.now', return_value=later):
            self.assertTrue(alerts.notify(conn, status.OFFLINE))

    def test_security_block_raises_system_warning_and_bell(self):
        from connect import alerts
        from core import system_warnings
        conn, _ = self.outbound()
        self.probe.addresses = ['93.184.216.99']
        self.check(conn, conn.next_check_at)
        self.assertEqual(self.markers(conn, 'security_blocked'), 1)
        w = [x for x in system_warnings.collect_system_warnings('info') if x['category'] == 'connect']
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]['severity'], 'critical')
        self.assertNotIn('93.184.216.99', json.dumps(w, default=str))     # code and name only
        self.assertEqual(alerts.bell_count(self.admin, {}), 1)

    def test_alert_text_has_no_secrets(self):
        from connect import alerts, status
        conn, _ = self.outbound()
        body = alerts._body(conn, status.SECURITY_BLOCKED, 'destination_changed', '')
        for bad in ('eyJ', 'BEGIN', 'access_token', 'DPoP '):
            self.assertNotIn(bad, body)


# --- qc-diagnostics/1 probe (served) -----------------------------------------------------------

class ProbeEndpoint(DTestCase):
    def setUp(self):
        super().setUp()
        from connect import identity
        from connect.models import InstallationIdentity
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=True)

    def test_probe_requires_token_and_source_and_returns_observed_address(self):
        from connect import identity
        pconn, conn = self.pair_inbound()
        doc = identity.document()
        self.assertIn('qc-diagnostics', doc['extensions'])
        self.assertEqual(doc['endpoints']['qc_probe'], CS_BASE + qc.PROBE_PATH)
        # No token: refused like any v1 resource request.
        r = self.net.request('POST', CS_BASE + qc.PROBE_PATH, {'Content-Type': 'application/json'}, b'{}')
        self.assertIn(r.status, (401, 403))
        self.assertNotIn(b'observed_source', r.body)
        pconn.remote_endpoints['api_base'] = CS_BASE + '/connect/v1'
        out = self.peer.qc_probe(pconn.id, nonce=qc.generate_nonce())
        self.assertEqual(out['observed_source'], PEER_IP)
        self.assertEqual(out['checks'], {'source': 'ok', 'token': 'ok'})
        self.assertEqual(out['connection_state'], 'active')
        # From an address outside the rules: refused before authentication.
        self.peer_ip = '93.184.216.200'
        with self.assertRaises(ConnectError) as e:
            self.peer.qc_probe(pconn.id)
        self.assertEqual(e.exception.status, 403)

    def test_probe_404_while_quick_connect_off(self):
        from connect import identity
        from connect.models import InstallationIdentity
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=False)
        pconn, conn = self.pair_inbound()
        from agit8or_connect import tokens
        url = CS_BASE + qc.PROBE_PATH
        token = self.peer.get_token(pconn.id)['access_token']
        _, key = pconn.active_key()
        r = self.net.request('POST', url, {'Authorization': f'DPoP {token}', 'Content-Type': 'application/json',
                                           'DPoP': tokens.build_dpop_proof(key, 'POST', url, access_token=token)},
                             b'{}')
        self.assertEqual(r.status, 404)
        self.assertNotIn('qc_probe', identity.document()['endpoints'])


# --- the fifteen diagnostic steps -------------------------------------------------------------

class Diagnostics(DTestCase):
    def run_diag(self, conn, user=None):
        from connect import diagnostics
        row = diagnostics.run(conn, user or self.admin)
        return row, {s['id']: s for s in row.steps}

    def test_fifteen_steps_pass_against_the_reference_peer(self):
        from connect.models import ConnectAuditEvent
        conn, _ = self.outbound()
        row, steps = self.run_diag(conn)
        self.assertEqual([s['n'] for s in row.steps], list(range(1, 16)))
        bad = {k: (v['status'], v['code'], v['explanation']) for k, v in steps.items()
               if v['status'] not in ('pass', 'not_tested')}
        self.assertEqual(bad, {})
        self.assertEqual(row.result, 'pass')
        self.assertEqual(steps['reverse']['status'], 'not_tested')     # a v1 peer without inbound test event
        for s in row.steps:
            for k in ('n', 'id', 'name', 'status', 'code', 'explanation', 'next_action', 'at', 'duration_ms', 'data'):
                self.assertIn(k, s)
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='diagnostics.run', result='pass').exists())
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_quick_connect_peer_reverse_step_via_probe(self):
        """A 1.1 peer offering qc-diagnostics: step 8 uses its probe, step 14
        passes once the peer reports it reached this installation."""
        from agit8or_connect.reference_peer import ReferencePeer
        from connect import identity
        from connect.models import InstallationIdentity
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=True)
        qpeer = ReferencePeer('https://qc.test', self.net, app_type='rem0te', display_name='QC peer',
                              tenants={'cust-1': 'One'}, quick_connect=True)
        conn, pconn = self.pair_outbound(qpeer)
        self.commit(conn)
        row, steps = self.run_diag(conn)
        self.assertEqual(steps['source']['status'], 'pass', steps['source'])
        self.assertIn('observed_source', steps['source']['data'])
        self.assertEqual(steps['reverse']['status'], 'fail')
        self.assertEqual(steps['reverse']['code'], 'reverse_failed')
        pconn.remote_endpoints['api_base'] = CS_BASE + '/connect/v1'
        qpeer.qc_probe(pconn.id)            # the other side runs its diagnostics against us
        from django.core.cache import cache
        cache.clear()
        from connect.models import DiagnosticRun
        DiagnosticRun.objects.all().delete()
        row, steps = self.run_diag(conn)
        self.assertEqual(steps['reverse']['status'], 'pass', steps['reverse'])
        self.assertEqual(row.result, 'pass', [(s['id'], s['status'], s['explanation']) for s in row.steps
                                              if s['status'] == 'fail'])

    def _expect(self, conn, failing, code, *, skipped_from=None):
        row, steps = self.run_diag(conn)
        self.assertEqual((steps[failing]['status'], steps[failing]['code']), ('fail', code), steps[failing])
        self.assertTrue(steps[failing]['next_action'])
        self.assertEqual(row.result, 'fail')
        if skipped_from:
            for sid in skipped_from:
                self.assertEqual(steps[sid]['status'], 'skipped', (sid, steps[sid]))
                self.assertIn('Skipped because step', steps[sid]['explanation'])
        self.assertEqual(steps['last_success']['n'], 15)
        conn.refresh_from_db()
        return row, steps

    def test_dns_failure(self):
        conn, _ = self.outbound()
        self.probe.code, self.probe.error = 'dns_nxdomain', 'The host name did not resolve.'
        self._expect(conn, 'dns', 'dns_nxdomain', skipped_from=('destination', 'tcp', 'tls', 'token', 'event'))

    def test_destination_changed_is_reported_not_acted_on(self):
        conn, _ = self.outbound()
        self.probe.addresses = ['93.184.216.99']
        self._expect(conn, 'destination', 'destination_changed', skipped_from=('tcp', 'identity'))
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')              # read-only: the monitor acts, not diagnostics

    def test_tcp_refused(self):
        conn, _ = self.outbound()
        self.probe.code, self.probe.error = 'tcp_refused', 'The connection to port 443 was refused.'
        self._expect(conn, 'tcp', 'tcp_refused', skipped_from=('tls', 'certificate'))

    def test_tls_failure(self):
        conn, _ = self.outbound()
        self.probe.code, self.probe.error = 'tls_handshake', 'TLS handshake failed.'
        self._expect(conn, 'tls', 'tls_handshake', skipped_from=('certificate', 'protocol'))

    def test_certificate_invalid_and_expiring(self):
        conn, _ = self.outbound()
        self.probe.code, self.probe.error = 'certificate_invalid', 'TLS certificate not accepted (expired).'
        self._expect(conn, 'certificate', 'certificate_invalid', skipped_from=('protocol', 'identity'))
        self.probe.code = self.probe.error = ''
        self.probe.not_after = (timezone.now() + timedelta(days=3)).isoformat()
        from connect.models import DiagnosticRun
        DiagnosticRun.objects.all().delete()
        self._expect(conn, 'certificate', 'certificate_expiring')
        DiagnosticRun.objects.all().delete()
        self.probe.not_after = (timezone.now() + timedelta(days=15)).isoformat()
        row, steps = self.run_diag(conn)
        self.assertEqual((steps['certificate']['status'], steps['certificate']['code']), ('pass', 'certificate_expiring'))

    def test_pin_mismatch(self):
        from connect.models import ApprovedDestination
        conn, _ = self.outbound()
        ApprovedDestination.objects.filter(connection=conn).update(spki_pins=['pinned'])
        self.probe.spki = 'other'
        self._expect(conn, 'certificate', 'spki_mismatch')
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_identity_changed(self):
        conn, _ = self.outbound()
        self.peer.installation_id = self.peer.app['installation_id'] = 'a' * 8 + '-0000-4000-8000-' + '0' * 12
        self._expect(conn, 'identity', 'identity_changed', skipped_from=('token', 'permissions', 'event'))
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_source_refused_by_peer(self):
        conn, _ = self.outbound()
        inner = self.net.handlers['https://rmm.test:443']
        self.net.handlers['https://rmm.test:443'] = lambda m, u, h, b: Response(
            403, {}, json.dumps({'error': {'code': 'source_not_authorised', 'message': 'no'}}).encode()) \
            if u.endswith('/token') else inner(m, u, h, b)
        from connect import client
        client.clear_cache()
        self._expect(conn, 'source', 'source_not_authorised', skipped_from=('permissions', 'event'))
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_source_not_allowed_here(self):
        from connect.models import Connection
        conn, _ = self.outbound()
        Connection.objects.filter(pk=conn.pk).update(last_source_ip='198.51.100.7')
        self._expect(conn, 'source', 'source_not_authorised_here')

    def test_token_refused(self):
        conn, pconn = self.outbound()
        self.peer.revoke(pconn.id)
        from connect import client
        client.clear_cache()
        self._expect(conn, 'token', 'invalid_client', skipped_from=('permissions', 'tenants', 'operation', 'event'))
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_clock_skew(self):
        conn, _ = self.outbound()
        self.peer.clock = lambda: time.time() + 900
        self._expect(conn, 'token', 'clock_skew', skipped_from=('permissions', 'event'))

    def test_scope_withdrawn_reported(self):
        conn, pconn = self.outbound()
        pconn.inbound_scopes = [s for s in pconn.inbound_scopes if s != 'customers:read']
        from connect import client
        client.clear_cache()
        self._expect(conn, 'token', 'scope_withdrawn')
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_tenant_mismatch(self):
        """The customer grants the other application reports now differ
        from those it reported at pairing: step 11 fails, nothing changes."""
        conn, _ = self.outbound()
        type(conn).objects.filter(pk=conn.pk).update(
            remote_tenant_grants=[{'remote_tenant': 'org-elsewhere', 'local_tenant': 'cust-9', 'scopes': []}])
        conn.refresh_from_db()
        self._expect(conn, 'tenants', 'tenant_mismatch')
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'active')

    def test_event_rejected(self):
        conn, pconn = self.outbound()
        inner = self.net.handlers['https://rmm.test:443']
        self.net.handlers['https://rmm.test:443'] = lambda m, u, h, b: Response(422, {}, b'{}') \
            if u.endswith('/events') else inner(m, u, h, b)
        _, steps = self._expect(conn, 'event', 'event_rejected')
        from connect.models import OutboundEvent
        self.assertFalse(OutboundEvent.objects.filter(connection=conn, event_type='connect.test',
                                                      status='queued').exists())

    def test_security_blocked_connection_sends_no_credentials(self):
        from connect import destinations
        conn, _ = self.outbound()
        destinations.security_block(conn, 'peer_revoked', {})
        log = list(self.net.log)
        row, steps = self.run_diag(conn)
        sent = self.net.log[len(log):]
        self.assertFalse([u for m, u in sent if u.endswith('/token') or u.endswith('/events')])
        for sid in ('token', 'permissions', 'tenants', 'operation', 'event', 'reverse'):
            self.assertEqual(steps[sid]['status'], 'not_tested')
        conn.refresh_from_db()
        self.assertEqual(conn.state, 'security_blocked')

    def test_steps_carry_no_secrets(self):
        import re
        conn, _ = self.outbound()
        row, _ = self.run_diag(conn)
        blob = json.dumps(row.steps)
        for pattern in (r'eyJ[A-Za-z0-9_-]{10,}', r'BEGIN [A-Z ]*PRIVATE', r'access_token', r'client_assertion'):
            self.assertIsNone(re.search(pattern, blob), pattern)

    def test_permission_and_rate_limit(self):
        from django.contrib.auth.models import User
        from django.test import Client
        from connect.models import DiagnosticRun
        conn, _ = self.outbound()
        viewer = User.objects.create_user('viewer2', 'v2@example.test', 'pw-Viewer-2!x')
        c = Client()
        c.force_login(viewer)
        r = c.post(UI + f'{conn.pk}/', {'op': 'diagnose'}, secure=True, HTTP_HOST='clientst0r.test')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(DiagnosticRun.objects.exists())
        for _ in range(6):
            r = self.ui.post(UI + f'{conn.pk}/', {'op': 'diagnose'}, secure=True, HTTP_HOST='clientst0r.test')
            self.assertEqual(r.status_code, 302)
        self.assertEqual(DiagnosticRun.objects.count(), 6)
        r = self.ui.post(UI + f'{conn.pk}/', {'op': 'diagnose'}, secure=True, HTTP_HOST='clientst0r.test',
                         follow=True)
        self.assertContains(r, 'Try again later')
        self.assertEqual(DiagnosticRun.objects.count(), 6)
        page = self.ui.get(UI + f'{conn.pk}/', secure=True, HTTP_HOST='clientst0r.test')
        self.assertContains(page, 'data-connect-diagnostics')
        self.assertContains(page, 'data-diag-step="reverse"')

    def test_kill_switch_refuses(self):
        from connect import diagnostics, lifecycle
        conn, _ = self.outbound()
        lifecycle.engage_kill_switch(self.admin)
        with self.assertRaises(diagnostics.DiagnosticsRefused):
            diagnostics.run(conn, self.admin)
