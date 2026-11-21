"""Quick Connect increment E (roadmap 79.19 connection alerts, 79.20 connection
diagnostics, audit anchoring C-05; docs/plans/quick-connect/INCREMENTS.md §E,
DESIGN.md §8.2, §9, §10, §12). Time and transport are mocked: the in-memory
reference peer over a Network and a fixed DNS/TLS preview."""
import json
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection as db
from django.test import Client, override_settings
from django.utils import timezone

from agit8or_connect.http import Response

from .base import CS_BASE, PEER_DEST_IP
from .test_increment_d import DTestCase

UI = '/settings/integrations/connected-apps/'
H = {'secure': True, 'HTTP_HOST': 'clientst0r.test'}
SECRET_RES = (r'eyJ[A-Za-z0-9_-]{10,}', r'BEGIN [A-Z ]*PRIVATE', r'PRIVATE KEY', r'access_token', r'client_assertion',
              r'DPoP [A-Za-z0-9]', r'Bearer [A-Za-z0-9]', r'code_verifier', r'"d"\s*:')


def _ok():
    from connect import health
    return health.CheckResult(True, 'ok', '', '', {d: (True, '') for d in health.DIMS})


def _down():
    from connect import health
    return health.CheckResult.fail('transport', 'tcp_refused', 'refused')


def _psa_defaults():
    from psa.models import Queue, TicketPriority, TicketStatus, TicketType
    if not Queue.objects.filter(is_active=True).exists():
        Queue.objects.create(name='Monitoring', slug='monitoring')
    for code, order in (('P1', 1), ('P2', 2), ('P3', 3), ('P4', 4)):
        if not TicketPriority.objects.filter(code=code).exists():
            TicketPriority.objects.create(code=code, name=f'Priority {code}', sort_order=order)
    if not TicketStatus.objects.filter(slug='new').exists():
        TicketStatus.objects.create(slug='new', name='New (test)', sort_order=1)
    if not TicketStatus.objects.filter(slug='resolved').exists():
        TicketStatus.objects.create(slug='resolved', name='Resolved (test)', sort_order=9, is_terminal=True)
    if not TicketType.objects.filter(is_active=True).exists():
        TicketType.objects.create(slug='monitoring-alert', name='Monitoring alert (test)')


class ETestCase(DTestCase):
    def markers(self, conn, key):
        from core.models import SystemWarningNotification
        return SystemWarningNotification.objects.filter(warning_id__startswith=f'connect:{conn.pk}:{key}:').count()

    def go_offline(self, conn, now):
        from connect import health
        for _ in range(3):
            conn.refresh_from_db()
            health.apply(conn, _down(), now, self.rng)
            now += timedelta(seconds=30)
        conn.refresh_from_db()
        self.assertEqual(conn.health, 'offline')
        return now

    def recover(self, conn, now):
        from connect import health
        for _ in range(2):
            conn.refresh_from_db()
            health.apply(conn, _ok(), now, self.rng)
            now += timedelta(seconds=30)
        conn.refresh_from_db()
        self.assertEqual(conn.health, 'connected')
        return now

    def opt_in_tickets(self, conn):
        from connect import alerts
        _psa_defaults()
        alerts.set_ticket_option(conn, True, self.org_a, self.admin)
        conn.refresh_from_db()

    def project(self):
        from events import projection
        from events.models import ProjectionQueueItem
        from connect.models import ConnectIncident
        for inc in ConnectIncident.objects.all():
            projection.project('connect', inc.pk)
        ProjectionQueueItem.objects.all().delete()


# --- alerts: dedupe, incidents, one ticket per incident ----------------------------------------

class AlertsAndIncidents(ETestCase):
    def test_flapping_two_hours_one_alert_per_status_and_one_recovery(self):
        from connect.models import ConnectIncident
        from psa.models import Ticket
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        now = conn.next_check_at
        now = self.go_offline(conn, now)
        # Flapping for two hours: two passes (Connected), three failures (Offline), ...
        end = now + timedelta(hours=2)
        while now < end:
            now = self.recover(conn, now)
            now = self.go_offline(conn, now)
        self.assertEqual(self.markers(conn, 'offline'), 1)
        self.assertEqual(self.markers(conn, 'connected'), 1)          # the recovery notice, once
        # One incident (reopened while flapping), one ticket.
        self.assertEqual(ConnectIncident.objects.filter(connection=conn).count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)
        inc = ConnectIncident.objects.get(connection=conn)
        self.assertGreater(inc.transition_count, 20)

    def test_thousand_heartbeats_while_offline_one_ticket(self):
        from connect import health
        from connect.models import ConnectIncident
        from psa.models import Ticket, TicketComment
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        now = self.go_offline(conn, conn.next_check_at)
        self.assertEqual(Ticket.objects.count(), 1)
        comments = TicketComment.objects.count()
        for _ in range(1000):
            conn.refresh_from_db(fields=['health', 'consecutive_fail', 'retry_step', 'circuit', 'health_dims',
                                         'consecutive_ok', 'status_key', 'alerted_status'])
            health.apply(conn, _down(), now, self.rng)
            now += timedelta(seconds=10)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketComment.objects.count(), comments)
        self.assertEqual(ConnectIncident.objects.get().transition_count, 2)     # degraded, offline
        t = Ticket.objects.get()
        self.assertEqual(t.organization, self.org_a)
        self.assertEqual(t.visibility, 'staff')
        self.assertEqual(t.priority.code, 'P2')
        for pattern in SECRET_RES:
            self.assertIsNone(re.search(pattern, t.subject + t.description), pattern)
        self.assertNotIn(PEER_DEST_IP, t.description)

    def test_no_ticket_without_opt_in(self):
        from psa.models import Ticket
        conn, _ = self.outbound()
        _psa_defaults()
        self.go_offline(conn, conn.next_check_at)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_ticket_notes_on_transitions_and_resolved_after_recovery_settles(self):
        from connect import incidents
        from connect.models import ConnectIncident
        from psa.models import Ticket, TicketComment
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        now = self.go_offline(conn, conn.next_check_at)
        t = Ticket.objects.get()
        now = self.recover(conn, now)
        self.assertTrue(TicketComment.objects.filter(ticket=t, body__icontains='connected again').exists())
        t.refresh_from_db()
        self.assertFalse(t.status.is_terminal)                      # not before the reopen window passed
        self.assertEqual(incidents.settle(), 0)
        inc = ConnectIncident.objects.get()
        later = inc.resolved_at + incidents.REOPEN_WINDOW + timedelta(seconds=1)
        self.assertEqual(incidents.settle(later), 1)
        t.refresh_from_db()
        self.assertTrue(t.status.is_terminal)
        self.assertEqual(incidents.settle(later), 0)                # once

    def test_worked_ticket_stays_open_on_recovery(self):
        from connect import incidents
        from connect.models import ConnectIncident
        from psa.models import Ticket, TicketComment
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        now = self.go_offline(conn, conn.next_check_at)
        t = Ticket.objects.get()
        TicketComment.objects.create(ticket=t, author=self.admin, body='Looking at it', is_internal=True)
        self.recover(conn, now)
        inc = ConnectIncident.objects.get()
        incidents.settle(inc.resolved_at + incidents.REOPEN_WINDOW + timedelta(seconds=1))
        t.refresh_from_db()
        self.assertFalse(t.status.is_terminal)
        self.assertTrue(TicketComment.objects.filter(ticket=t, body__icontains='stays open').exists())

    def test_security_block_after_offline_is_noted_on_the_same_ticket(self):
        from connect import health
        from psa.models import Ticket, TicketComment
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        self.go_offline(conn, conn.next_check_at)
        conn.refresh_from_db()
        health.security_failure(conn, 'spki_mismatch', {})
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertTrue(TicketComment.objects.filter(body__icontains='Security Blocked').exists())


class SharedEventLayer(ETestCase):
    def test_event_per_status_change_and_ticket_link(self):
        from events.models import EventLink, OperationalEvent
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        now = conn.next_check_at
        from connect import health
        for _ in range(2):
            conn.refresh_from_db()
            health.apply(conn, _down(), now, self.rng)
        self.project()
        ev = OperationalEvent.objects.get(source='connect')
        self.assertEqual((ev.status, ev.severity, ev.occurrences), ('open', 'medium', 1))     # degraded
        self.assertIsNone(ev.organization_id)                                                # MSP-wide
        conn.refresh_from_db()
        health.apply(conn, _down(), now, self.rng)
        self.project()
        ev.refresh_from_db()
        self.assertEqual((ev.status, ev.severity, ev.occurrences), ('open', 'high', 2))       # offline
        self.assertIn('Offline', ev.title)
        self.assertTrue(EventLink.objects.filter(event=ev, ticket__isnull=False).exists())
        self.recover(conn, now)
        self.project()
        ev.refresh_from_db()
        self.assertEqual(ev.status, 'resolved')
        self.assertEqual(ev.occurrences, 3)
        self.assertEqual(OperationalEvent.objects.filter(source='connect').count(), 1)
        blob = json.dumps(ev.raw)
        self.assertNotIn(PEER_DEST_IP, blob)
        for pattern in SECRET_RES:
            self.assertIsNone(re.search(pattern, blob), pattern)

    def test_saving_an_incident_queues_it_for_projection(self):
        from events.models import ProjectionQueueItem
        conn, _ = self.outbound()
        with self.captureOnCommitCallbacks(execute=True):
            self.go_offline(conn, conn.next_check_at)
        self.assertTrue(ProjectionQueueItem.objects.filter(source='connect').exists())
        from events import projection
        projection.run(budget_seconds=10)
        from events.models import OperationalEvent
        self.assertEqual(OperationalEvent.objects.filter(source='connect', status='open').count(), 1)

    def test_events_page_links_back_to_the_connection(self):
        from events.models import OperationalEvent
        from events.views import source_url
        conn, _ = self.outbound()
        self.go_offline(conn, conn.next_check_at)
        self.project()
        self.assertEqual(source_url(OperationalEvent.objects.get(source='connect')), f'{UI}{conn.pk}/')

    @override_settings(WEBHOOK_DELIVERY_ASYNC=False)
    def test_status_change_consumed_by_an_existing_webhook_subscription(self):
        from core.models import SystemSetting, Webhook
        from connect import alerts
        settings = SystemSetting.get_settings()
        settings.webhooks_enabled = True
        settings.save()
        calls = []

        class Session:
            trust_env = True

            def post(self, url, data=None, headers=None, timeout=None):
                calls.append(json.loads(data))

                class R:
                    status_code, text = 200, 'ok'
                return R()
        p = mock.patch('core.webhook_sender.guard_session', side_effect=lambda s, pol: Session())
        p.start()
        self.addCleanup(p.stop)
        conn, _ = self.outbound()
        Webhook.objects.create(organization=self.org_a, name='ops', url='https://hooks.example.test/in',
                               events=['connected_app.status_changed'])
        Webhook.objects.create(organization=self.org_b, name='other', url='https://hooks.example.test/b',
                               events=['connected_app.status_changed'])
        alerts.set_ticket_option(conn, False, self.org_a, self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.go_offline(conn, conn.next_check_at)
        events = [c for c in calls if c['event'] == 'connected_app.status_changed']
        self.assertEqual([e['data']['status'] for e in events], ['degraded', 'offline'])
        self.assertEqual(events[-1]['data']['previous_status'], 'degraded')
        self.assertEqual(events[-1]['data']['connection_id'], str(conn.pk))
        self.assertEqual(len(calls), 2)                      # only the alert organization's webhook
        blob = json.dumps(calls)
        self.assertNotIn(PEER_DEST_IP, blob)
        for pattern in SECRET_RES:
            self.assertIsNone(re.search(pattern, blob), pattern)

    def test_webhook_form_offers_the_event(self):
        from core.webhook_forms import WebhookForm
        self.assertIn('connected_app.status_changed', {v for v, _ in WebhookForm().fields['events'].choices})


# --- mute ----------------------------------------------------------------------------------------

class Mute(ETestCase):
    def test_muted_offline_is_silent_and_security_blocked_still_warns(self):
        from connect import alerts, health
        from connect.models import ConnectAuditEvent
        from audit.models import AuditLog
        from core import system_warnings
        conn, _ = self.outbound()
        self.opt_in_tickets(conn)
        alerts.mute(conn, 4, self.admin, 'maintenance')
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='alerts.mute', connection_id=str(conn.pk))
                        .exists())
        self.assertTrue(AuditLog.objects.filter(object_type='connect_source_policy',
                                                description__icontains='muted until').exists())
        self.go_offline(conn, conn.next_check_at)
        self.assertEqual(self.markers(conn, 'offline'), 0)
        self.assertEqual(self.markers(conn, 'degraded'), 0)
        from psa.models import Ticket
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(alerts.bell_count(self.admin, {}), 0)
        self.assertFalse([w for w in system_warnings.collect_system_warnings('info') if w['category'] == 'connect'])
        # The incident is still recorded (marked muted) and the page shows the mute.
        self.assertTrue(conn.incidents.get().muted)
        page = self.ui.get(UI + f'{conn.pk}/', **H)
        self.assertContains(page, 'data-connect-muted')
        self.assertContains(page, 'Security Blocked is never muted')
        # Security Blocked while muted: system warning, bell, e-mail marker, ticket.
        conn.refresh_from_db()
        health.security_failure(conn, 'identity_changed', {})
        self.assertEqual(self.markers(conn, 'security_blocked'), 1)
        w = [x for x in system_warnings.collect_system_warnings('info') if x['category'] == 'connect']
        self.assertEqual([x['severity'] for x in w], ['critical'])
        self.assertEqual(alerts.bell_count(self.admin, {}), 1)
        self.assertEqual(Ticket.objects.count(), 1)
        page = self.ui.get(UI + f'{conn.pk}/', **H)
        self.assertContains(page, 'data-connect-muted-security')

    def test_mute_is_time_limited(self):
        from connect import alerts, status
        conn, _ = self.outbound()
        with self.assertRaises(alerts.MuteRefused):
            alerts.mute(conn, 24 * 30, self.admin)            # more than 7 days: refused
        with self.assertRaises(alerts.MuteRefused):
            alerts.mute(conn, 'x', self.admin)
        until = alerts.mute(conn, 168, self.admin)
        self.assertLessEqual(until, timezone.now() + timedelta(days=7, seconds=5))
        conn.refresh_from_db()
        self.assertTrue(alerts.is_muted(conn, status.OFFLINE))
        self.assertFalse(alerts.is_muted(conn, status.SECURITY_BLOCKED))
        self.assertFalse(alerts.is_muted(conn, status.OFFLINE, now=until + timedelta(seconds=1)))
        later = until + timedelta(minutes=1)
        with mock.patch('django.utils.timezone.now', return_value=later):
            self.go_offline(conn, later)
        self.assertEqual(self.markers(conn, 'offline'), 1)       # the mute expired by itself

    def test_mute_through_the_ui_needs_manage_and_is_audited(self):
        from connect.models import ConnectAuditEvent
        conn, _ = self.outbound()
        viewer = User.objects.create_user('viewer-e', 've@example.test', 'pw-Viewer-e!x')
        with mock.patch('connect.views_ui.user_has_perm', side_effect=lambda u, p: p == 'view_app_connections'):
            c = Client()
            c.force_login(viewer)
            self.assertEqual(c.get(UI + f'{conn.pk}/', **H).status_code, 200)
            self.assertEqual(c.post(UI + f'{conn.pk}/', {'op': 'mute', 'hours': '1'}, **H).status_code, 403)
        conn.refresh_from_db()
        self.assertIsNone(conn.alert_mute_until)
        r = self.ui.post(UI + f'{conn.pk}/', {'op': 'mute', 'hours': '1', 'reason': 'patching'}, **H)
        self.assertEqual(r.status_code, 302)
        conn.refresh_from_db()
        self.assertIsNotNone(conn.alert_mute_until)
        self.assertEqual(conn.alert_mute_reason, 'patching')
        self.ui.post(UI + f'{conn.pk}/', {'op': 'unmute'}, **H)
        conn.refresh_from_db()
        self.assertIsNone(conn.alert_mute_until)
        self.assertEqual(ConnectAuditEvent.objects.filter(operation__in=('alerts.mute', 'alerts.unmute')).count(), 2)
        r = self.ui.post(UI + f'{conn.pk}/', {'op': 'alert_ticket', 'enabled': 'on', 'organization': self.org_b.pk},
                         **H)
        conn.refresh_from_db()
        self.assertEqual((conn.alert_ticket, conn.alert_organization_id), (True, self.org_b.pk))
        self.ui.post(UI + f'{conn.pk}/', {'op': 'alert_ticket', 'enabled': 'on', 'organization': ''}, **H)
        conn.refresh_from_db()
        self.assertEqual(conn.alert_organization_id, self.org_b.pk)    # refused: a ticket needs a customer record


# --- diagnostics: the fifteen steps, pass / fail / skipped ---------------------------------------

class DiagnosticStepMatrix(ETestCase):
    def run_diag(self, conn):
        from connect import client, diagnostics
        from connect.models import DiagnosticRun
        from django.core.cache import cache
        DiagnosticRun.objects.all().delete()
        cache.clear()
        client.clear_cache()
        row = diagnostics.run(conn, self.admin)
        return {s['id']: s for s in row.steps}

    def test_every_step_passes_against_the_reference_peer(self):
        conn, _ = self.outbound()
        steps = self.run_diag(conn)
        for sid in ('dns', 'destination', 'tcp', 'tls', 'certificate', 'protocol', 'identity', 'source', 'token',
                    'permissions', 'tenants', 'operation', 'event', 'last_success'):
            self.assertEqual(steps[sid]['status'], 'pass', (sid, steps[sid]))
        self.assertEqual(steps['reverse']['status'], 'not_tested')       # a v1 peer, no inbound test event

    def test_each_step_fails_on_its_own(self):
        from connect import diagnostics
        from connect.models import Connection
        conn, pconn = self.outbound()
        inner = self.net.handlers['https://rmm.test:443']
        cases = []

        def case(sid, code, setup, teardown):
            setup()
            steps = self.run_diag(conn)
            teardown()
            cases.append(sid)
            self.assertEqual((steps[sid]['status'], steps[sid]['code']), ('fail', code), (sid, steps[sid]))
            # Every step before the failing one still passed.
            order = [x for _, x, _ in diagnostics.STEPS]
            for before in order[:order.index(sid)]:
                if (sid, before) != ('operation', 'tenants'):      # 11 needs 12's answer
                    self.assertIn(steps[before]['status'], ('pass', 'not_tested'), (sid, before, steps[before]))

        def probe(**kw):
            def s():
                for k, v in kw.items():
                    setattr(self.probe, k, v)
            return s

        def reset():
            self.probe.code = self.probe.error = self.probe.spki = self.probe.not_after = ''
            self.probe.addresses = [PEER_DEST_IP]
            self.net.handlers['https://rmm.test:443'] = inner

        def handler(match, status, code='x'):
            def s():
                self.net.handlers['https://rmm.test:443'] = lambda m, u, h, b: Response(
                    status, {}, json.dumps({'error': {'code': code, 'message': 'no'}}).encode()) \
                    if match(m, u) else inner(m, u, h, b)
            return s

        case('dns', 'dns_nxdomain', probe(code='dns_nxdomain', error='did not resolve'), reset)
        case('destination', 'destination_changed', probe(addresses=['93.184.216.99']), reset)
        case('tcp', 'tcp_refused', probe(code='tcp_refused', error='refused'), reset)
        case('tls', 'tls_handshake', probe(code='tls_handshake', error='handshake'), reset)
        case('certificate', 'certificate_invalid', probe(code='certificate_invalid', error='expired'), reset)
        case('protocol', 'http_500', handler(lambda m, u: u.endswith('/.well-known/agit8or-connect'), 500), reset)

        def other_installation():
            self.peer.installation_id = self.peer.app['installation_id'] = 'b' * 8 + '-0000-4000-8000-' + '0' * 12
        real_id = self.peer.installation_id

        def back():
            self.peer.installation_id = self.peer.app['installation_id'] = real_id
        case('identity', 'identity_changed', other_installation, back)

        def foreign_source():
            Connection.objects.filter(pk=conn.pk).update(last_source_ip='198.51.100.7')
            conn.refresh_from_db()

        def own_source():
            Connection.objects.filter(pk=conn.pk).update(last_source_ip=None)
            conn.refresh_from_db()
        case('source', 'source_not_authorised_here', foreign_source, own_source)
        case('token', 'invalid_client', handler(lambda m, u: u.endswith('/token'), 400, 'invalid_client'), reset)
        # Step 10 alone: the token is issued, without a committed permission.
        from connect import client as cclient
        real_get_token = cclient.get_token

        def narrower(*a, **kw):
            tok = dict(real_get_token(*a, **kw))
            tok['scope'] = ' '.join(x for x in str(tok.get('scope', '')).split() if x != 'customers:read')
            return tok
        with mock.patch('connect.client.get_token', narrower):
            steps = self.run_diag(conn)
        self.assertEqual(steps['token']['status'], 'pass')
        self.assertEqual((steps['permissions']['status'], steps['permissions']['code']), ('fail', 'scope_withdrawn'))
        cases.append('permissions')
        grants = conn.remote_tenant_grants

        def mismatch():
            Connection.objects.filter(pk=conn.pk).update(
                remote_tenant_grants=[{'remote_tenant': 'org-x', 'local_tenant': 'cust-9', 'scopes': []}])
            conn.refresh_from_db()

        def unmatch():
            Connection.objects.filter(pk=conn.pk).update(remote_tenant_grants=grants)
            conn.refresh_from_db()
        case('tenants', 'tenant_mismatch', mismatch, unmatch)
        case('operation', 'insufficient_scope', handler(lambda m, u: u.endswith('/capabilities'), 403,
                                                         'insufficient_scope'), reset)
        case('event', 'event_rejected', handler(lambda m, u: u.endswith('/events'), 422), reset)
        self.assertEqual(len(cases), 13)

    def test_every_later_step_is_skipped_when_a_prerequisite_fails(self):
        conn, _ = self.outbound()
        self.probe.code, self.probe.error = 'dns_nxdomain', 'did not resolve'
        steps = self.run_diag(conn)
        self.assertEqual(steps['dns']['status'], 'fail')
        for sid in ('destination', 'tcp', 'tls', 'certificate', 'protocol', 'identity', 'source', 'token',
                    'permissions', 'tenants', 'operation', 'event', 'reverse'):
            self.assertEqual(steps[sid]['status'], 'skipped', sid)
            self.assertIn('Skipped because step 1', steps[sid]['explanation'])
        self.probe.code = self.probe.error = ''
        # A failure at the token step skips 10-13 and leaves 1-8 passing.
        inner = self.net.handlers['https://rmm.test:443']
        self.net.handlers['https://rmm.test:443'] = lambda m, u, h, b: Response(400, {}, json.dumps(
            {'error': {'code': 'invalid_client', 'message': 'no'}}).encode()) if u.endswith('/token') \
            else inner(m, u, h, b)
        steps = self.run_diag(conn)
        for sid in ('permissions', 'tenants', 'operation', 'event'):
            self.assertEqual(steps[sid]['status'], 'skipped', sid)
        self.assertEqual(steps['reverse']['status'], 'not_tested')
        # Step 15 is informational: never skipped; "stale" when old.
        self.assertIn(steps['last_success']['status'], ('pass', 'not_tested'))

    def test_last_success_not_tested_and_stale(self):
        from connect.models import Connection
        conn, _ = self.outbound()
        Connection.objects.filter(pk=conn.pk).update(last_outbound_ok_at=None, last_source_at=None)
        self.probe.code, self.probe.error = 'dns_nxdomain', 'x'
        steps = self.run_diag(conn)
        self.assertEqual(steps['last_success']['status'], 'not_tested')
        Connection.objects.filter(pk=conn.pk).update(last_outbound_ok_at=timezone.now() - timedelta(hours=1))
        steps = self.run_diag(conn)
        self.assertEqual((steps['last_success']['status'], steps['last_success']['code']), ('pass', 'stale'))

    def test_reverse_pass_fail_and_not_tested(self):
        """14: not_tested against a v1 peer, fail and pass against a 1.1 peer."""
        from agit8or_connect.reference_peer import ReferencePeer
        from connect import identity
        from connect.models import InstallationIdentity
        conn, _ = self.outbound()
        self.assertEqual(self.run_diag(conn)['reverse']['status'], 'not_tested')
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=True)
        qpeer = ReferencePeer('https://qc.test', self.net, app_type='rem0te', display_name='QC peer',
                              tenants={'cust-1': 'One'}, quick_connect=True)
        qconn, qpconn = self.pair_outbound(qpeer)
        self.commit(qconn)
        self.assertEqual(self.run_diag(qconn)['reverse']['code'], 'reverse_failed')
        qpconn.remote_endpoints['api_base'] = CS_BASE + '/connect/v1'
        qpeer.qc_probe(qpconn.id)
        self.assertEqual(self.run_diag(qconn)['reverse']['status'], 'pass')


# --- commit gate ---------------------------------------------------------------------------------

class CommitGate(ETestCase):
    def test_commit_requires_a_passing_diagnostics_run(self):
        from connect import activation, diagnostics
        from connect.models import ConnectAuditEvent, Connection, DiagnosticRun
        conn, _ = self.pair_outbound()
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.ACTIVE)
        # The commit record names the diagnostics run, which passed the gate.
        ev = ConnectAuditEvent.objects.get(operation='connection.committed', connection_id=str(conn.pk))
        row = DiagnosticRun.objects.get(pk=ev.detail['diagnostic_run'])
        self.assertEqual(row.trigger, DiagnosticRun.RETEST)
        self.assertTrue(diagnostics.gate(row, conn)[0])

    def test_failing_diagnostics_keep_the_connection_testing(self):
        from connect import activation, lifecycle
        from connect.models import Connection
        conn, _ = self.outbound()
        lifecycle.suspend(conn, self.admin)
        inner = self.net.handlers['https://rmm.test:443']
        # The connection test passes, but the capabilities call (step 12) is refused.
        calls = {'n': 0}

        def h(m, u, hd, b):
            if u.endswith('/capabilities'):
                calls['n'] += 1
                if calls['n'] > 1:
                    return Response(403, {}, b'{"error": {"code": "insufficient_scope", "message": "no"}}')
            return inner(m, u, hd, b)
        self.net.handlers['https://rmm.test:443'] = h
        lifecycle.resume(conn, self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.assertFalse(conn.last_test['ok'])
        self.assertFalse(conn.last_test['diagnostics_ok'])
        self.assertIn('operation', [c['id'] for c in conn.last_test['checks'] if c['status'] == 'fail'])
        # A commit with the connection test's run id alone is refused.
        Connection.objects.filter(pk=conn.pk).update(last_test={**conn.last_test, 'ok': True})
        with self.assertRaises(activation.ActivationRefused):
            activation.commit_connection(conn, conn.last_test['run_id'], self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.net.handlers['https://rmm.test:443'] = inner
        self.commit(conn)

    def test_stale_diagnostics_run_is_refused(self):
        from connect import activation, lifecycle
        from connect.models import Connection, DiagnosticRun
        conn, _ = self.outbound()
        lifecycle.suspend(conn, self.admin)
        with mock.patch('connect.activation.commit_connection'):
            lifecycle.resume(conn, self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)
        self.assertTrue(conn.last_test['diagnostics_ok'])
        DiagnosticRun.objects.filter(pk=conn.last_test['diagnostic_run']).update(
            finished_at=timezone.now() - timedelta(minutes=20))
        with self.assertRaises(activation.ActivationRefused):
            activation.commit_connection(conn, conn.last_test['run_id'], self.admin)

    def test_quick_connect_needs_step_fourteen(self):
        from connect import diagnostics
        from connect.models import DiagnosticRun
        conn, _ = self.outbound()
        row = diagnostics.run(conn, self.admin)
        self.assertEqual({s['id']: s['status'] for s in row.steps}['reverse'], 'not_tested')
        self.assertTrue(diagnostics.gate(row, conn)[0])               # v1: steps 1-13
        conn.qc_revision = '1.1'
        ok, failing = diagnostics.gate(row, conn)
        self.assertFalse(ok)
        self.assertEqual([f['id'] for f in failing], ['reverse'])
        steps = [dict(s, status='pass') if s['id'] == 'reverse' else s for s in row.steps]
        DiagnosticRun.objects.filter(pk=row.pk).update(steps=steps)
        row.refresh_from_db()
        self.assertTrue(diagnostics.gate(row, conn)[0])
        # Skipped or failed required steps never pass the gate.
        steps = [dict(s, status='skipped') if s['id'] == 'event' else s for s in steps]
        DiagnosticRun.objects.filter(pk=row.pk).update(steps=steps)
        row.refresh_from_db()
        self.assertEqual([f['id'] for f in diagnostics.gate(row, conn)[1]], ['event'])


# --- periodic full run (monitor) -----------------------------------------------------------------

class PeriodicFullRun(ETestCase):
    def test_every_fifteen_minutes_bounded_per_pass(self):
        from agit8or_connect.reference_peer import ReferencePeer
        from connect import monitor
        from connect.models import DiagnosticRun
        conn, _ = self.outbound()
        other, _ = self.pair_outbound(ReferencePeer('https://rmm2.test', self.net, app_type='rem0te'))
        self.commit(other)
        DiagnosticRun.objects.all().delete()
        now = timezone.now()
        checked = [(conn, 'connected'), (other, 'connected')]
        self.assertEqual(monitor.full_diagnostics(checked, now), 1)          # FULL_PER_PASS
        self.assertEqual(monitor.full_diagnostics(checked, now), 1)          # the other one
        self.assertEqual(monitor.full_diagnostics(checked, now), 0)          # both done for 15 minutes
        self.assertEqual(DiagnosticRun.objects.filter(trigger='monitor').count(), 2)
        later = now + timedelta(minutes=16)
        with mock.patch('django.utils.timezone.now', return_value=later):
            self.assertEqual(monitor.full_diagnostics(checked, later), 1)

    def test_run_pass_only_adds_full_runs_with_budget_left(self):
        from connect import monitor
        from connect.models import DiagnosticRun
        conn, _ = self.outbound()
        DiagnosticRun.objects.all().delete()
        self.assertEqual(monitor.run_pass(conn.next_check_at, self.rng, remaining=lambda: 5)['full_runs'], 0)
        conn.refresh_from_db()
        self.assertEqual(monitor.run_pass(conn.next_check_at, self.rng, remaining=lambda: 40)['full_runs'], 1)
        self.assertEqual(DiagnosticRun.objects.filter(trigger='monitor').count(), 1)
        # Not for unhealthy or inactive connections, nor during the kill switch.
        from connect import lifecycle
        DiagnosticRun.objects.all().delete()
        lifecycle.engage_kill_switch(self.admin)
        self.assertEqual(monitor.full_diagnostics([(conn, 'connected')]), 0)
        self.assertFalse(DiagnosticRun.objects.exists())

    def test_full_run_on_recovery_and_security_failure_blocks(self):
        from connect import monitor
        from connect.models import DiagnosticRun
        conn, _ = self.outbound()
        ten_ago = timezone.now() - timedelta(minutes=10)
        DiagnosticRun.objects.all().delete()
        DiagnosticRun.objects.create(connection=conn, trigger='monitor', started_at=ten_ago, finished_at=ten_ago,
                                     result='pass')
        self.assertEqual(monitor.full_diagnostics([(conn, 'connected')]), 0)        # not due
        self.assertEqual(monitor.full_diagnostics([(conn, 'offline')]), 1)          # recovered: full run
        DiagnosticRun.objects.all().delete()
        self.peer.installation_id = self.peer.app['installation_id'] = 'c' * 8 + '-0000-4000-8000-' + '0' * 12
        self.assertEqual(monitor.full_diagnostics([(conn, 'connected')]), 1)
        conn.refresh_from_db()
        self.assertEqual((conn.state, conn.security_block_code), ('security_blocked', 'identity_changed'))


# --- the qc-diagnostics probe in the light check -------------------------------------------------

class ProbeInLightCheck(ETestCase):
    def setUp(self):
        super().setUp()
        from agit8or_connect.reference_peer import ReferencePeer
        from connect import identity
        from connect.models import InstallationIdentity
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=True)
        self.qpeer = ReferencePeer('https://qc.test', self.net, app_type='rem0te', display_name='QC peer',
                                   tenants={'cust-1': 'One'}, quick_connect=True)

    def sent(self, since):
        return [u for m, u in self.net.log[since:] if m == 'POST']

    def test_probe_used_when_advertised_else_v1_test(self):
        from connect import diagnostics
        from agit8or_connect import quick_connect as qc
        conn, _ = self.pair_outbound(self.qpeer)
        self.commit(conn)
        conn.refresh_from_db()
        diagnostics.run(conn, self.admin)
        conn.refresh_from_db()
        self.assertEqual(conn.remote_probe_url, 'https://qc.test' + qc.PROBE_PATH)
        n = len(self.net.log)
        self.check(conn, conn.next_check_at)
        posts = self.sent(n)
        self.assertIn('https://qc.test' + qc.PROBE_PATH, posts)
        self.assertNotIn('https://qc.test/connect/v1/test', posts)
        self.assertEqual(conn.health, 'connected')
        # A v1 peer: POST test.
        v1, _ = self.outbound()
        diagnostics.run(v1, self.admin)
        v1.refresh_from_db()
        self.assertEqual(v1.remote_probe_url, '')
        n = len(self.net.log)
        self.check(v1, v1.next_check_at)
        self.assertIn('https://rmm.test/connect/v1/test', self.sent(n))

    def test_probe_gone_falls_back_and_not_authorised_blocks(self):
        from connect import diagnostics
        from agit8or_connect import quick_connect as qc
        conn, _ = self.pair_outbound(self.qpeer)
        self.commit(conn)
        diagnostics.run(conn, self.admin)
        conn.refresh_from_db()
        self.qpeer.quick_connect = False                   # the other side stopped serving the probe
        n = len(self.net.log)
        self.check(conn, conn.next_check_at)
        self.assertIn('https://qc.test/connect/v1/test', self.sent(n))
        self.assertEqual(conn.remote_probe_url, '')
        self.assertEqual(conn.health, 'connected')
        # Probe back, saying it no longer authorises our address: Security Blocked.
        self.qpeer.quick_connect = True
        type(conn).objects.filter(pk=conn.pk).update(remote_probe_url='https://qc.test' + qc.PROBE_PATH)
        real = self.qpeer._qc_probe

        def refusing(method, url, headers, body):
            r = real(method, url, headers, body)
            data = json.loads(r.body)
            data['checks']['source'] = 'not_authorised'
            return Response(200, {'Content-Type': 'application/json'}, json.dumps(data).encode())
        self.qpeer._qc_probe = refusing
        conn.refresh_from_db()
        self.check(conn, conn.next_check_at)
        self.assertEqual((conn.state, conn.security_block_code), ('security_blocked', 'source_not_authorised'))


# --- diagnostics tab, history, export ------------------------------------------------------------

class DiagnosticsTabAndExport(ETestCase):
    def seeded_run(self, conn):
        """A run whose steps carry seeded secrets, as a peer error message might."""
        from connect import diagnostics
        from connect.models import ConnectionKey, DiagnosticRun
        row = diagnostics.run(conn, self.admin)
        key = ConnectionKey.objects.filter(connection=conn, state='active').first().private_pem()
        jwt = 'eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlLXNlZWQtMTIzNDU2Nzg5'
        self.seeded = [jwt, key.split('\n')[1], 'Z9Y8X7W6V5', 'pw-very-secret-1', 'sig-SEEDSEEDSEED']
        steps = list(row.steps)
        steps[8] = dict(steps[8], status='fail', code='invalid_client',
                        explanation=f'Token refused: access_token={jwt} DPoP {jwt} Authorization: Bearer {jwt}',
                        next_action=f'{key} pairing code Z9Y8X-7W6V5 password=pw-very-secret-1',
                        data={**steps[8]['data'], 'access_token': jwt, 'private_key': key,
                              'warning': 'signature=sig-SEEDSEEDSEED'})
        DiagnosticRun.objects.filter(pk=row.pk).update(steps=steps)
        row.refresh_from_db()
        return row

    def test_export_is_redacted_json_and_text_and_audited(self):
        from connect.models import ConnectAuditEvent
        conn, _ = self.outbound()
        row = self.seeded_run(conn)
        for fmt in ('', '?format=text'):
            r = self.ui.get(UI + f'{conn.pk}/diagnostics/{row.pk}/export/{fmt}', **H)
            self.assertEqual(r.status_code, 200)
            self.assertIn('attachment;', r['Content-Disposition'])
            self.assertEqual(r['Cache-Control'], 'no-store')
            text = r.content.decode()
            for s in self.seeded:
                self.assertNotIn(s, text)
            for pattern in SECRET_RES + (r'BEGIN', r'Z9Y8X-7W6V5', r'signature='):
                self.assertIsNone(re.search(pattern, text), (fmt, pattern))
            # Addresses and certificate names stay.
            self.assertIn(PEER_DEST_IP, text)
            self.assertIn('rmm.test', text)
        doc = json.loads(self.ui.get(UI + f'{conn.pk}/diagnostics/{row.pk}/export/', **H).content)
        self.assertEqual([s['n'] for s in doc['run']['steps']], list(range(1, 16)))
        self.assertNotIn('access_token', doc['run']['steps'][8]['data'])
        self.assertNotIn('private_key', doc['run']['steps'][8]['data'])
        self.assertEqual(ConnectAuditEvent.objects.filter(operation='diagnostics.export').count(), 3)

    def test_export_of_a_real_run_has_no_secret_patterns(self):
        from connect import diagnostics
        from agit8or_connect.reference_peer import ReferencePeer
        conn, _ = self.outbound()
        row = diagnostics.run(conn, self.admin)
        for fmt in ('json', 'text'):
            _, _, body = diagnostics.export(row, self.admin, fmt=fmt)
            text = body.decode()
            for pattern in SECRET_RES:
                self.assertIsNone(re.search(pattern, text), pattern)

    def test_tab_history_and_permissions(self):
        from connect import diagnostics
        conn, _ = self.outbound()
        first = diagnostics.run(conn, self.admin)
        self.probe.code, self.probe.error = 'tcp_refused', 'refused'
        second = diagnostics.run(conn, self.admin)
        page = self.ui.get(UI + f'{conn.pk}/diagnostics/', **H)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'data-connect-diagnostic-run="{second.pk}"')
        self.assertContains(page, 'data-connect-diagnostic-history')
        self.assertContains(page, f'?run={first.pk}')
        self.assertContains(page, 'data-diag-changed')             # tcp: was pass
        self.assertContains(page, 'data-connect-gate="fail"')
        self.assertContains(page, 'data-connect-export="json"')
        page = self.ui.get(UI + f'{conn.pk}/diagnostics/?run={first.pk}', **H)
        self.assertContains(page, f'data-connect-diagnostic-run="{first.pk}"')
        self.assertContains(self.ui.get(UI + f'{conn.pk}/', **H), 'data-connect-diagnostics-link')
        # View permission: history yes; run and export no.
        viewer = User.objects.create_user('viewer-d', 'vd@example.test', 'pw-Viewer-d!x')
        c = Client()
        c.force_login(viewer)
        with mock.patch('connect.views_ui.user_has_perm', side_effect=lambda u, p: p == 'view_app_connections'):
            r = c.get(UI + f'{conn.pk}/diagnostics/', **H)
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, 'data-connect-export')
            self.assertNotContains(r, 'data-connect-run-diagnostics')
            self.assertEqual(c.post(UI + f'{conn.pk}/diagnostics/', {'op': 'diagnose'}, **H).status_code, 403)
            self.assertEqual(c.get(UI + f'{conn.pk}/diagnostics/{first.pk}/export/', **H).status_code, 403)
        # No permission at all.
        self.assertEqual(c.get(UI + f'{conn.pk}/diagnostics/', **H).status_code, 403)
        # Another connection's run is not exported through this one.
        from agit8or_connect.reference_peer import ReferencePeer
        other, _ = self.pair_outbound(ReferencePeer('https://rmm2.test', self.net, app_type='rem0te'))
        self.assertEqual(self.ui.get(UI + f'{other.pk}/diagnostics/{first.pk}/export/', **H).status_code, 404)

    def test_run_now_from_the_tab(self):
        from connect.models import DiagnosticRun
        conn, _ = self.outbound()
        DiagnosticRun.objects.all().delete()
        r = self.ui.post(UI + f'{conn.pk}/diagnostics/', {'op': 'diagnose'}, **H)
        self.assertEqual(r.status_code, 302)
        row = DiagnosticRun.objects.get()
        self.assertIn(f'?run={row.pk}', r['Location'])
        self.assertEqual(row.trigger, 'manual')

    def test_tab_404_while_connect_is_off(self):
        conn, _ = self.outbound()
        with override_settings(AGIT8OR_CONNECT_ENABLED=False):
            self.assertEqual(self.ui.get(UI + f'{conn.pk}/diagnostics/', **H).status_code, 404)


# --- audit anchoring (C-05) ----------------------------------------------------------------------

class AuditAnchoring(ETestCase):
    def command(self, *args):
        import io
        out, err = io.StringIO(), io.StringIO()
        try:
            call_command('connect_verify_audit_chain', *args, stdout=out, stderr=err)
            code = 0
        except SystemExit as e:
            code = e.code
        return code, out.getvalue() + err.getvalue()

    def test_anchor_rows_hourly(self):
        from audit.models import AuditLog
        from connect import audit_anchor, audit_log, monitor
        self.outbound()
        t0 = timezone.now()
        monitor.upkeep(t0)
        anchors = AuditLog.objects.filter(object_type='connect_audit_anchor')
        self.assertEqual(anchors.count(), 1)
        a = anchors.get()
        seq, h = audit_anchor.head()
        self.assertEqual((a.extra_data['seq'], a.extra_data['hash']), (seq, h))
        audit_log.record('test.op')
        monitor.upkeep(t0 + timedelta(minutes=30))
        self.assertEqual(anchors.count(), 1)                     # not within the hour
        with mock.patch('django.utils.timezone.now', return_value=t0 + timedelta(minutes=61)):
            monitor.upkeep(t0 + timedelta(minutes=61))
        self.assertEqual(anchors.count(), 2)
        # The head did not move: no new anchor for a day.
        with mock.patch('django.utils.timezone.now', return_value=t0 + timedelta(minutes=125)):
            monitor.upkeep(t0 + timedelta(minutes=125))
        self.assertLessEqual(anchors.count(), 3)

    def test_security_block_anchors_at_once(self):
        from audit.models import AuditLog
        from connect import health
        conn, _ = self.outbound()
        health.security_failure(conn, 'spki_mismatch', {})
        a = AuditLog.objects.filter(object_type='connect_audit_anchor').order_by('-pk').first()
        self.assertEqual(a.extra_data['reason'], 'security_block')
        self.assertEqual(a.extra_data['connection'], str(conn.pk))

    def test_verify_passes_and_detects_truncation(self):
        from connect import audit_anchor
        self.outbound()
        audit_anchor.anchor('test')
        code, out = self.command()
        self.assertEqual(code, 0, out)
        self.assertIn('anchor(s) match', out)
        self.assertIn('Main audit log chain intact', out)
        seq, _ = audit_anchor.head()
        with db.cursor() as c:                       # truncate the newest Connect rows behind the ORM
            c.execute('DELETE FROM connect_audit WHERE seq >= %s', [seq - 1])
        from connect import audit_log
        self.assertIsNone(audit_log.verify())        # the chain alone still looks intact
        code, out = self.command()
        self.assertEqual(code, 1)
        self.assertIn('truncated', out)

    def test_verify_detects_full_truncation_and_rewrite(self):
        from connect import audit_anchor
        self.outbound()
        audit_anchor.anchor('test')
        seq, h = audit_anchor.head()
        with db.cursor() as c:                       # rewrite the anchored row with a recomputed hash
            c.execute('UPDATE connect_audit SET hash = %s WHERE seq = %s', ['0' * 64, seq])
        code, out = self.command('--connect-only')
        self.assertEqual(code, 1)
        with db.cursor() as c:
            c.execute('DELETE FROM connect_audit')
        code, out = self.command('--connect-only')
        self.assertEqual(code, 1)
        self.assertIn('truncated', out)

    def test_main_chain_seals_the_anchors(self):
        from audit import chain
        from audit.models import AuditLog
        from connect import audit_anchor
        self.outbound()
        a = audit_anchor.anchor('test')
        chain.seal()
        self.assertEqual(self.command()[0], 0)
        AuditLog.objects.filter(pk=a.pk).update(extra_data={**a.extra_data, 'seq': 1})   # an edited anchor
        code, out = self.command()
        self.assertEqual(code, 1)
        self.assertIn('Main audit log chain BROKEN', out)
