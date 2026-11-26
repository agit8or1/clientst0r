"""Monitoring coverage: gaps, recovery, backfill and delivered-late alerts
(roadmap 82.15–82.20, community feedback in GitHub Discussion #161).

Deterministic: no network, a fixed clock (django.utils.timezone.now is
patched), fake providers that declare their history capability.
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, SimpleTestCase, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from audit.models import AuditLog
from core.models import Organization, SystemWarningNotification
from integrations.models import IntegrationSyncHealth
from psa.models import Ticket
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from security_alerts.models import (RemediationPlaybook, SecurityAlert, SecurityAlertRule, SecurityIncident,
                                    SecurityVendorConnection)
from security_alerts.tests import _seed_psa

from . import coverage as cov
from . import projection
from . import source_health as sh
from . import source_health_store as store
from .models import CoverageWindow, EventSettings, OperationalEvent
from .tests_source_health import T0, FakeProvider, HTTPError, alert

CAP = cov.HistoryCapability(supports_history=True, max_lookback=timedelta(days=7), ordering=cov.ORDER_UNORDERED,
                            pagination=cov.PAGE_CURSOR, page_size=2)
M = timedelta(minutes=1)


class Crash(BaseException):
    """A process dying mid-backfill (not an ordinary error)."""


class HistoryProvider(FakeProvider):
    """A vendor that pages through past alerts. ``pages`` are HistoryPage,
    exceptions to raise, or callables returning either."""
    slug = 'security_fake_history'

    def __init__(self, pages=(), cap=CAP, **kw):
        super().__init__(**kw)
        self.pages = list(pages)
        self.history_capability = cap
        self.calls = []

    def fetch_history(self, connection, start, end, page_token=None, limit=100):
        self.calls.append((start, end, page_token, limit))
        item = self.pages[int(page_token or 0)]
        if callable(item) and not isinstance(item, BaseException):
            item = item()
        if isinstance(item, BaseException):
            raise item
        return item


def page(*alerts, nxt='', end=None):
    return cov.HistoryPage(records=list(alerts), next_token=nxt, exhausted=(not nxt) if end is None else end)


def iso(t):
    return t.isoformat().replace('+00:00', 'Z')


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class _Base(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='CV Customer A', slug='cv-a')
        self.b = Organization.objects.create(name='CV Customer B', slug='cv-b')
        self.conn_a = SecurityVendorConnection.objects.create(organization=self.a, name='EDR A', provider='defender',
                                                              category='edr')
        self.conn_b = SecurityVendorConnection.objects.create(organization=self.b, name='EDR B', provider='defender',
                                                              category='edr')
        self.clock = Clock(T0)
        p = mock.patch('django.utils.timezone.now', self.clock)
        p.start()
        self.addCleanup(p.stop)
        # The vendor adapter the backfill finds for a connection (None = the
        # connection has no API adapter, as the shipped Defender stub).
        self.history = None
        q = mock.patch('security_alerts.capabilities.api_adapter', side_effect=lambda provider: self.history)
        q.start()
        self.addCleanup(q.stop)

    # helpers ------------------------------------------------------------------------------
    def at(self, delta):
        self.clock.t = T0 + delta
        return self.clock.t

    def sync(self, provider, conn=None, delta=None):
        if delta is not None:
            self.at(delta)
        with self.captureOnCommitCallbacks(execute=False):
            return provider.sync(conn or self.conn_a)

    def outage(self, conn=None, failures=2, recovery=None):
        """T0 verified success, failures every 10 min, recovery at +30 min."""
        conn = conn or self.conn_a
        self.sync(FakeProvider(alerts=[], probe=True), conn, timedelta(0))
        for i in range(failures):
            self.sync(FakeProvider(error=HTTPError(503)), conn, (i + 1) * 10 * M)
        if recovery is not None:
            self.sync(recovery, conn, 30 * M)

    def backfill(self, provider=None, delta=31 * M):
        if provider is not None:
            self.history = provider
        self.at(delta)
        with self.captureOnCommitCallbacks(execute=False):
            return cov.backfill_tick()

    def window(self, conn=None, **kw):
        conn = conn or self.conn_a
        ct = ContentType.objects.get_for_model(conn)
        return CoverageWindow.objects.filter(source_key=f'security:{ct.pk}:{conn.pk}', **kw).order_by('pk')

    def record(self, conn=None, org=None):
        conn = conn or self.conn_a
        recs = store.gather({(org or self.a).pk}, kinds=('security',))
        return next(r for r in recs if r['name'] == conn.name)

    def row(self, conn=None):
        conn = conn or self.conn_a
        return IntegrationSyncHealth.objects.get(content_type=ContentType.objects.get_for_model(conn),
                                                 object_id=conn.pk, kind='security')

    def contract(self, r, tenant):
        p = sh.to_contract(r, tenant_id=tenant, source_id=r['source_id'], source_type=r['kind'])
        self.assertEqual(sh.validate(p), [], p)
        return p


class CoverageAcceptanceTests(_Base):
    def test_01_healthy_no_alerts(self):
        self.sync(FakeProvider(alerts=[], probe=True), delta=timedelta(0))
        r = self.record()
        self.assertEqual(r['coverage_state'], cov.VERIFIED_QUIET)
        self.assertFalse(self.window().exists())
        self.assertEqual(sh.display(r).key, sh.D_HEALTHY_QUIET)
        self.assertEqual(self.contract(r, self.a.pk)['coverage']['state'], 'verified_quiet')

    def test_02_single_failed_read(self):
        self.sync(FakeProvider(alerts=[], probe=True), delta=timedelta(0))
        self.sync(FakeProvider(error=HTTPError(503)), delta=10 * M)
        w = self.window().get()
        self.assertEqual((w.state, w.failed_reads, w.coverage_lost_at, w.first_failure_at, w.recovered_at),
                         (cov.COVERAGE_GAP, 1, T0, T0 + 10 * M, None))
        r = self.record()
        self.assertEqual(r['coverage_state'], cov.COVERAGE_GAP)
        self.assertNotEqual(r['alert_status'], sh.NO_ALERTS)        # never verified quiet
        self.assertFalse(sh.summarize([r])['verified'])
        p = self.contract(r, self.a.pk)
        self.assertEqual((p['coverage']['gap']['state'], p['coverage']['gap']['failed_reads']), ('coverage_gap', 1))
        self.assertEqual(p['coverage']['last_verified_coverage_at'], iso(T0))
        self.assertEqual(p['last_success_at'], iso(T0))

    def test_03_multiple_consecutive_failures(self):
        self.outage(failures=4)
        w = self.window().get()
        self.assertEqual((w.failed_reads, w.first_failure_at, w.last_failure_at), (4, T0 + 10 * M, T0 + 40 * M))
        self.assertEqual(self.row().consecutive_failures, 4)
        self.assertEqual(CoverageWindow.objects.count(), 1)             # one gap, not one per read

    def test_04_recovery_and_complete_backfill(self):
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        w = self.window().get()
        self.assertEqual((w.state, w.recovered_at, w.backfill_state), (cov.COVERAGE_GAP, T0 + 30 * M, 'pending'))
        # Collection works again, but the missed window is not recovered: not quiet.
        r = self.record()
        self.assertEqual(sh.display(r).key, sh.D_RECOVERING)
        self.assertFalse(sh.summarize([r])['verified'])
        p = HistoryProvider(pages=[page(alert('g1', iso(T0 + 5 * M)), alert('g2', iso(T0 + 15 * M)), nxt='1'),
                                   page(alert('g3', iso(T0 + 25 * M)))])
        out = self.backfill(p)
        self.assertEqual(out['resolved'], 1)
        w.refresh_from_db()
        self.assertEqual((w.state, w.backfill_state, w.recovered_count, w.pages_fetched, w.checkpoint_cursor),
                         (cov.RECOVERED_LATE, 'complete', 3, 2, ''))
        self.assertEqual(w.max_delay_seconds, 26 * 60)                  # g1: occurred +5, stored +31
        self.assertEqual(p.calls[0][:3], (T0, T0 + 30 * M, None))       # from the last verified coverage
        g1 = SecurityAlert.objects.get(external_id='g1')
        self.assertEqual((g1.occurred_at, g1.seen_at, g1.delivered_late, g1.delivery_delay_seconds,
                          g1.coverage_window_id), (T0 + 5 * M, T0 + 31 * M, True, 26 * 60, w.pk))
        r = self.record()
        self.assertEqual(r['coverage_state'], cov.ACTIVE_MONITORING)    # the gap is resolved
        self.assertEqual(cov.coverage_display(w.state, recovered=3).label, 'Recovered – Delivered Late')
        gap = self.contract(r, self.a.pk)['coverage']['gap']
        self.assertEqual((gap['state'], gap['complete'], gap['events_delivered_late']), ('recovered_late', True, 3))

    def test_05_recovery_with_no_missed_events(self):
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        self.backfill(HistoryProvider(pages=[page()]))
        w = self.window().get()
        self.assertEqual((w.state, w.recovered_count), (cov.RECOVERED_LATE, 0))
        self.assertEqual(cov.coverage_display(w.state, recovered=0).label, 'Recovered – None Missed')
        r = self.record()
        self.assertEqual(r['coverage_state'], cov.VERIFIED_QUIET)       # now; the gap stays on record
        self.assertEqual(r['coverage_window'].pk, w.pk)
        self.assertEqual(self.contract(r, self.a.pk)['coverage']['gap']['state'], 'recovered_late')

    def test_06_partial_backfill_lookback_cap(self):
        short = cov.HistoryCapability(True, timedelta(minutes=20), cov.ORDER_UNORDERED, cov.PAGE_CURSOR, 50)
        self.history = HistoryProvider(cap=short)
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        p = HistoryProvider(pages=[page(alert('late-1', iso(T0 + 20 * M)))], cap=short)
        self.backfill(p)
        w = self.window().get()
        self.assertEqual((w.state, w.backfill_state, w.lookback_truncated, w.recovered_count),
                         (cov.PARTIAL_RECOVERY, 'incomplete', True, 1))
        self.assertEqual(p.calls[0][0], T0 + 11 * M)                     # never further back than allowed
        self.assertEqual(sh.validate(self.contract(self.record(), self.a.pk)), [])

    def test_07_source_without_history_capability(self):
        # The first read after recovery returns two alerts from the gap.
        self.outage(recovery=FakeProvider(alerts=[alert('r1', iso(T0 + 12 * M)), alert('r2', None)]))
        w = self.window().get()
        self.assertEqual((w.state, w.backfill_state, w.recovered_count), (cov.PARTIAL_RECOVERY, 'unsupported', 2))
        self.assertTrue(SecurityAlert.objects.get(external_id='r2').delivered_late)  # no time: first read
        self.assertIsNone(SecurityAlert.objects.get(external_id='r2').occurred_at)
        # Nothing at all: unrecoverable, never recovered.
        self.outage(conn=self.conn_b, recovery=FakeProvider(alerts=[], probe=True))
        self.assertEqual(self.window(self.conn_b).get().state, cov.UNRECOVERABLE_GAP)
        # A history adapter whose capability is not fully declared is never
        # complete, even though every page answered (a 200 alone is not proof).
        c = SecurityVendorConnection.objects.create(organization=self.a, name='EDR C', provider='defender',
                                                    category='edr')
        undeclared = cov.HistoryCapability(supports_history=True, pagination=cov.PAGE_CURSOR)
        self.history = HistoryProvider(pages=[page(alert('u1', iso(T0 + 12 * M)))], cap=undeclared)
        self.outage(conn=c, recovery=FakeProvider(alerts=[], probe=True))
        self.backfill()
        self.assertEqual(self.window(c).get().state, cov.PARTIAL_RECOVERY)
        self.assertFalse(undeclared.can_prove_complete())

    def test_08_backfill_pagination_failure(self):
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        p = HistoryProvider(pages=[page(alert('p1', iso(T0 + 5 * M)), nxt='1'), HTTPError(503)])
        self.backfill(p)
        w = self.window().get()
        self.assertEqual((w.state, w.backfill_state, w.checkpoint_cursor, w.backfill_attempts),
                         (cov.COVERAGE_GAP, 'running', '1', 1))
        self.assertGreater(w.backfill_next_at, T0 + 31 * M)              # backoff, not a tight loop
        self.assertIn('endpoint_unavailable', w.backfill_error)
        # Not due yet: nothing is fetched.
        calls = len(p.calls)
        self.backfill(p, 31 * M)
        self.assertEqual(len(p.calls), calls)
        delta = 31 * M
        for _ in range(cov.MAX_ATTEMPTS):
            delta += timedelta(hours=2)
            self.backfill(p, delta)
        w.refresh_from_db()
        self.assertEqual((w.state, w.backfill_state, w.recovered_count, w.checkpoint_cursor),
                         (cov.PARTIAL_RECOVERY, 'failed', 1, '1'))
        self.assertTrue(all(c[2] == '1' for c in p.calls[1:]))           # always resumed at page 2

    def test_09_duplicates_during_recovery(self):
        _seed_psa()
        SecurityAlertRule.objects.create(organization=self.a, name='all', match_severity_min='info')
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[alert('d1', iso(T0 + 5 * M), title='One'),
                                                  alert('d2', iso(T0 + 15 * M), title='Two')]))
        tickets, incidents = Ticket.objects.count(), SecurityIncident.objects.count()
        p = HistoryProvider(pages=[page(alert('d1', iso(T0 + 5 * M), title='One'),
                                        alert('d2', iso(T0 + 15 * M), title='Two'), nxt='1'),
                                   page(alert('d3', iso(T0 + 20 * M), title='Three'),
                                        alert('d1', iso(T0 + 5 * M), title='One'))])
        self.backfill(p)
        w = self.window().get()
        self.assertEqual((w.state, w.recovered_count, w.duplicate_count), (cov.RECOVERED_LATE, 3, 3))
        self.assertEqual(SecurityAlert.objects.filter(connection=self.conn_a).count(), 3)
        self.assertEqual(Ticket.objects.count(), tickets + 1)            # only d3 is new
        self.assertEqual(SecurityIncident.objects.count(), incidents)   # d3 joins the open incident
        # Running everything again changes nothing.
        self.backfill(p, 40 * M)
        self.sync(FakeProvider(alerts=[alert('d1', iso(T0 + 5 * M), title='One')]), delta=41 * M)
        self.assertEqual(SecurityAlert.objects.filter(connection=self.conn_a).count(), 3)
        self.assertEqual(Ticket.objects.count(), tickets + 1)
        self.assertEqual(SystemWarningNotification.objects.filter(warning_id__startswith='coverage:').count(), 0)

    def test_10_out_of_order_events(self):
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        p = HistoryProvider(pages=[page(alert('o3', iso(T0 + 25 * M)), alert('o1', 'not a time'), nxt='1'),
                                   page(alert('o2', iso(T0 + 5 * M)), alert('o0', iso(T0 - 5 * M)))])
        self.backfill(p)
        w = self.window().get()
        self.assertEqual(w.state, cov.RECOVERED_LATE)
        late = dict(SecurityAlert.objects.values_list('external_id', 'delivered_late'))
        # Inside the gap or without a trustworthy time: late. Before the gap: not.
        self.assertEqual(late, {'o3': True, 'o1': True, 'o2': True, 'o0': False})
        self.assertEqual(w.max_delay_seconds, 26 * 60)                   # o2, not o3 (unordered)

    def test_11_repeated_outages(self):
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        self.backfill(HistoryProvider(pages=[page(alert('x1', iso(T0 + 5 * M)))]))
        # A second outage opens a second gap; the first stays on record.
        self.sync(FakeProvider(error=HTTPError(503)), delta=60 * M)
        self.sync(FakeProvider(alerts=[], probe=True), delta=70 * M)
        # It fails again before its window is recovered: the same gap grows.
        self.sync(FakeProvider(error=HTTPError(503)), delta=75 * M)
        w2 = self.window(state=cov.COVERAGE_GAP).get()
        self.assertEqual((w2.failed_reads, w2.recovered_at, w2.backfill_state), (2, None, ''))
        self.history = HistoryProvider(pages=[page()])
        self.sync(FakeProvider(alerts=[], probe=True), delta=80 * M)
        self.backfill(delta=81 * M)
        states = list(self.window().values_list('state', 'coverage_lost_at', 'recovered_count'))
        self.assertEqual(states, [(cov.RECOVERED_LATE, T0, 1), (cov.RECOVERED_LATE, T0 + 30 * M, 0)])
        self.assertEqual(self.record()['coverage_windows_30d'], 2)

    def test_12_restart_during_recovery(self):
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        first = HistoryProvider(pages=[page(alert('s1', iso(T0 + 5 * M)), nxt='1'), Crash('killed')])
        with self.assertRaises(Crash):
            self.backfill(first)
        w = self.window().get()                                          # what the database kept
        self.assertEqual((w.checkpoint_cursor, w.recovered_count, w.state), ('1', 1, cov.COVERAGE_GAP))
        # A new process, a new adapter instance: resumes at the checkpoint.
        second = HistoryProvider(pages=[page(alert('s1', iso(T0 + 5 * M)), nxt='1'),
                                        page(alert('s2', iso(T0 + 15 * M)))])
        self.backfill(second, 35 * M)
        self.assertEqual(second.calls[0][2], '1')
        w.refresh_from_db()
        self.assertEqual((w.state, w.recovered_count, w.duplicate_count), (cov.RECOVERED_LATE, 2, 0))
        self.assertEqual(SecurityAlert.objects.filter(external_id='s1').count(), 1)

    def test_13_tenant_isolation(self):
        self.outage(recovery=FakeProvider(alerts=[alert('iso-a', iso(T0 + 5 * M))]))
        self.sync(FakeProvider(alerts=[], probe=True), self.conn_b, 30 * M)
        self.assertFalse(self.window(self.conn_b).exists())
        self.assertEqual(self.window().get().organization_id, self.a.pk)
        self.assertEqual(self.record(self.conn_b, self.b)['coverage_state'], cov.VERIFIED_QUIET)
        b_keys = {r['source_id'] for r in store.gather({self.b.pk})}
        self.assertNotIn(self.window().get().source_key, b_keys)
        self.assertFalse(SecurityAlert.objects.filter(organization=self.b, external_id='iso-a').exists())
        projection.project('security_alert', SecurityAlert.objects.get(external_id='iso-a').pk)
        from reports.widget_sources import get_widget_data
        viewer = {'user_id': None, 'org_ids': [self.b.pk], 'perms': {'events_view'},
                  'perm_orgs': {'events_view': [self.b.pk]}}
        for cat in ('current', 'gaps', 'delayed'):
            text = json.dumps(get_widget_data('monitoring_coverage', {'category': cat}, viewer))
            self.assertNotIn('EDR A', text, cat)
            self.assertNotIn('iso-a', text, cat)
            self.assertNotIn('CV Customer A', text, cat)

    def test_14_delayed_high_severity_alert_goes_through_workflow(self):
        _seed_psa()
        SecurityAlertRule.objects.create(organization=self.a, name='high+', match_severity_min='high')
        RemediationPlaybook.objects.create(organization=self.a, name='Isolate', match_severity_min='high')
        self.history = HistoryProvider()
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        self.backfill(HistoryProvider(pages=[page(alert('crit', iso(T0 + 5 * M), severity='critical',
                                                        title='Ransomware'))]))
        a = SecurityAlert.objects.get(external_id='crit')
        self.assertTrue(a.delivered_late)
        self.assertIsNotNone(a.auto_ticket)                               # the normal alert-to-ticket rule
        self.assertTrue(a.auto_ticket.subject.startswith('[Security][Delivered late] '))
        self.assertIn('not seen in real time', a.auto_ticket.description)
        incident = a.incidents.get()
        kinds = list(incident.events.values_list('kind', flat=True))
        self.assertIn('delivered_late', kinds)
        self.assertIn('playbook_suggested', kinds)                         # approval still required
        self.assertNotIn('playbook_action', kinds)                         # nothing ran on its own
        event = projection.project('security_alert', a.pk)
        self.assertEqual((event.delivered_late, event.occurred_at, event.first_seen_at),
                         (True, T0 + 5 * M, T0 + 31 * M))

    def test_15_historical_wallboard_accuracy_after_recovery(self):
        self.history = HistoryProvider()
        from reports.widget_sources import get_widget_data, msp_wide_viewer
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        self.backfill(HistoryProvider(pages=[page(alert('w1', iso(T0 + 5 * M)), alert('w2', iso(T0 + 20 * M)))]))
        projection.project('security_alert', SecurityAlert.objects.get(external_id='w1').pk)
        gaps = get_widget_data('monitoring_coverage', {'category': 'gaps'}, msp_wide_viewer())
        row = next(r for r in gaps['rich_rows'] if r[0]['text'] == 'EDR A')
        self.assertEqual(row[2]['key'], cov.RECOVERED_LATE)
        self.assertEqual((row[2]['text'], row[3]['text'], row[4]['text'], row[5]['text'], row[6]['text']),
                         ('Recovered – Delivered Late', '2026-11-20 12:10', '20 min', '2', '26 min'))
        self.assertTrue(row[2]['icon'] and row[2]['title'])             # icon + text + tooltip
        now = get_widget_data('monitoring_coverage', {'category': 'current'}, msp_wide_viewer())
        cur = next(r for r in now['rich_rows'] if r[0]['text'] == 'EDR A')
        # Current health and coverage are separate from the historical gap.
        self.assertEqual((cur[2]['key'], cur[3]['key'], cur[4]['key']),
                         (sh.D_HEALTHY_ACTIVE, cov.ACTIVE_MONITORING, cov.RECOVERED_LATE))
        late = get_widget_data('monitoring_coverage', {'category': 'delayed'}, msp_wide_viewer())
        self.assertEqual(late['rich_rows'][0][4]['text'], 'Delivered late · 26 min')
        self.assertEqual(late['rows'][0][0], 'alert w1')                  # plain-text fallback

    def test_16_multiple_sources_with_different_states(self):
        c = SecurityVendorConnection.objects.create(organization=self.a, name='EDR C', provider='defender',
                                                    category='edr')
        d = SecurityVendorConnection.objects.create(organization=self.a, name='EDR D', provider='defender',
                                                    category='edr')
        self.history = HistoryProvider(pages=[page(alert('m1', iso(T0 + 5 * M)))])
        self.outage(recovery=FakeProvider(alerts=[], probe=True))                      # A: recovered
        self.backfill()
        self.history = None
        self.outage(conn=self.conn_b, recovery=FakeProvider(alerts=[], probe=True))     # B: unrecoverable
        self.outage(conn=c)                                                             # C: still down
        self.sync(FakeProvider(alerts=[], probe=True), d, 32 * M)                       # D: quiet
        self.at(33 * M)
        states = {r['name']: r['coverage_state'] for r in store.gather(None, kinds=('security',))}
        # Current coverage: B collects again (quiet now), its gap is history.
        self.assertEqual(states, {'EDR A': cov.ACTIVE_MONITORING, 'EDR B': cov.VERIFIED_QUIET,
                                  'EDR C': cov.COVERAGE_GAP, 'EDR D': cov.VERIFIED_QUIET})
        windows = {w.source_name: w.state for w in CoverageWindow.objects.all()}
        self.assertEqual(windows, {'EDR A': cov.RECOVERED_LATE, 'EDR B': cov.UNRECOVERABLE_GAP,
                                   'EDR C': cov.COVERAGE_GAP})
        s = sh.summarize(store.gather({self.a.pk, self.b.pk}, kinds=('security',)))
        self.assertFalse(s['verified'])                                  # C is down
        statement = sh.visibility_statement(s)
        self.assertIn('EDR B', statement)                                # alerts may be missing
        self.assertIn('may be missing', statement)


class CoverageListingTests(_Base):
    def test_connection_with_a_polled_row_is_listed_once(self):
        """A connection that has a polled health row is not listed again as a
        webhook-only source (its adapter may be missing, as here)."""
        self.outage(failures=1, recovery=FakeProvider(alerts=[], probe=True))
        names = [r['name'] for r in store.gather({self.a.pk})]
        self.assertEqual(names.count('EDR A'), 1, names)

    def test_gap_sentence_uses_the_install_time_zone(self):
        from django.test import override_settings
        summary = {'missing_windows': [{'name': 'EDR A', 'from': T0, 'to': T0 + 30 * M}]}
        with override_settings(TIME_ZONE='America/New_York'):
            from django.utils import timezone as dj_tz
            dj_tz.activate('America/New_York')
            try:
                text = sh._missing_sentence(summary)
            finally:
                dj_tz.deactivate()
        self.assertNotIn('UTC', text)
        self.assertRegex(text, r'E[SD]T')


class CoverageNotificationTests(_Base):
    def test_prolonged_gap_notifies_once(self):
        self.outage(failures=1)
        self.at(30 * M)
        self.assertEqual(cov.notify_tick(), 0)                            # 20 min < 60 min threshold
        self.at(80 * M)
        with self.captureOnCommitCallbacks(execute=False):
            self.assertEqual(cov.notify_tick(), 1)
            self.assertEqual(cov.notify_tick(), 0)                        # once per gap
        w = self.window().get()
        self.assertTrue(SystemWarningNotification.objects.filter(warning_id=f'coverage:{w.pk}:prolonged').exists())
        EventSettings.objects.filter(pk=1).update(coverage_gap_notify_minutes=0)
        self.sync(FakeProvider(error=HTTPError(503)), self.conn_b, 0 * M)
        self.at(500 * M)
        self.assertEqual(cov.notify_tick(), 0)                            # switched off

    def test_unsuccessful_recovery_notifies_once(self):
        self.outage(recovery=FakeProvider(alerts=[], probe=True))       # no history: unrecoverable
        with self.captureOnCommitCallbacks(execute=False):
            self.assertEqual(cov.notify_tick(), 1)
            self.assertEqual(cov.notify_tick(), 0)
        w = self.window().get()
        self.assertIsNotNone(w.notified_unrecovered_at)
        self.assertTrue(AuditLog.objects.filter(object_type='monitoring_coverage_window', object_id=w.pk).exists())

    def test_non_critical_source_is_not_notified(self):
        self.outage(failures=1)
        IntegrationSyncHealth.objects.update(critical=False)
        self.at(500 * M)
        self.assertEqual(cov.notify_tick(), 0)

    def test_stale_collector_opens_a_gap(self):
        self.sync(FakeProvider(alerts=[], probe=True), delta=timedelta(0))
        self.at(timedelta(hours=6))
        store.sweep(now=self.clock.t)
        w = self.window().get()
        self.assertEqual((w.cause, w.coverage_lost_at, w.state), ('stale_data', T0, cov.COVERAGE_GAP))
        self.sync(FakeProvider(alerts=[], probe=True), delta=timedelta(hours=6, minutes=1))
        w.refresh_from_db()
        self.assertEqual(w.state, cov.UNRECOVERABLE_GAP)                  # no history capability

    def test_backfill_switched_off(self):
        EventSettings.objects.update_or_create(pk=1, defaults={'backfill_enabled': False})
        self.history = HistoryProvider(pages=[page()])
        self.outage(recovery=FakeProvider(alerts=[], probe=True))
        w = self.window().get()
        self.assertEqual((w.state, w.backfill_state), (cov.UNRECOVERABLE_GAP, 'disabled'))
        self.assertEqual(self.history.calls, [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CoverageViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.outage(recovery=FakeProvider(alerts=[alert('v1', iso(T0 + 5 * M), title='Late one')]))
        self.sync(FakeProvider(error=HTTPError(503)), self.conn_b, 31 * M)
        projection.project('security_alert', SecurityAlert.objects.get(external_id='v1').pk)
        self.admin = User.objects.create_superuser('cv-admin', 'a@example.test', 'pw')
        role = RoleTemplate.objects.create(name='cv scoped', events_view=True)
        self.tech = _make_msp_tech(User.objects.create_user('cv-tech', password='pw'))
        self.tech.profile.global_role_template = role
        self.tech.profile.client_scope = 'selected'
        self.tech.profile.save()
        self.tech.profile.scope_organizations.add(self.b)
        Membership.objects.create(user=self.tech, organization=self.b, role=Role.EDITOR)

    def client_for(self, user, org):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = org.pk
        s.save()
        return c

    def test_reliability_page_shows_coverage_and_history(self):
        c = self.client_for(self.admin, self.a)
        r = c.get('/security/events/sources/')
        self.assertContains(r, 'data-coverage="partial_recovery"')
        self.assertContains(r, 'data-coverage="coverage_gap"')
        self.assertContains(r, 'Coverage history')
        r = c.get('/security/events/sources/?coverage=delayed')
        self.assertContains(r, 'Late one')
        self.assertContains(r, 'data-delivered-late="1"')
        data = c.get('/security/events/sources.json').json()
        self.assertEqual(data['schema_version'], '1.1.0')
        for p in data['sources']:
            self.assertEqual(sh.validate(p), [], p)
        states = {p['coverage']['state'] for p in data['sources'] if p['source_type'] == 'security'}
        self.assertEqual(states, {'active_monitoring', 'coverage_gap'})

    def test_scoped_tech_sees_only_their_gaps(self):
        c = self.client_for(self.tech, self.b)
        r = c.get('/security/events/sources/?coverage=delayed')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Late one')
        self.assertNotContains(r, 'EDR A')
        r = c.get('/security/events/sources/')
        self.assertContains(r, 'EDR B')
        data = c.get('/security/events/sources.json').json()
        self.assertEqual({p['tenant_id'] for p in data['sources']}, {str(self.b.pk)})

    def test_delayed_alert_marked_in_siem_and_timeline(self):
        c = self.client_for(self.admin, self.a)
        a = SecurityAlert.objects.get(external_id='v1')
        self.assertContains(c.get(f'/security/alerts/{a.pk}/'), 'data-delivered-late="1"')
        lst = c.get('/security/alerts/?late=1')
        self.assertContains(lst, 'Late one')
        event = OperationalEvent.objects.get(source='security_alert', source_id=a.pk)
        self.assertContains(c.get(f'/security/events/{event.pk}/'), 'data-delivered-late="1"')
        self.assertContains(c.get('/security/events/?late=1&status=all'), 'Late one')

    def test_coverage_settings_need_admin_and_are_audited(self):
        url = '/security/events/ingestion/'
        body = {'action': 'coverage', 'backfill_enabled': '1', 'backfill_max_lookback_hours': '48',
                'coverage_gap_notify_minutes': '30', 'coverage_recovery_notify': '1'}
        self.assertEqual(self.client_for(self.tech, self.b).post(url, body).status_code, 403)
        self.assertEqual(self.client_for(self.admin, self.a).post(url, body).status_code, 302)
        s = EventSettings.get()
        self.assertEqual((s.backfill_max_lookback_hours, s.coverage_gap_notify_minutes), (48, 30))
        log = AuditLog.objects.filter(description='Changed monitoring coverage settings').get()
        self.assertEqual(log.extra_data['before']['coverage_gap_notify_minutes'], 60)
        self.assertEqual(log.extra_data['after']['coverage_gap_notify_minutes'], 30)


class CoverageUnitTests(SimpleTestCase):
    def test_complete_needs_declared_capability_and_proof(self):
        self.assertFalse(cov.UNDECLARED.can_prove_complete())
        self.assertFalse(cov.NO_HISTORY.can_prove_complete())
        self.assertTrue(CAP.can_prove_complete())
        none_signal = cov.HistoryCapability(True, timedelta(days=1), cov.ORDER_ASCENDING, cov.PAGE_NONE)
        self.assertFalse(none_signal.can_prove_complete())
        self.assertEqual(cov.resolve(CAP, proven_end=False, truncated=False, rejected=0, recovered=0,
                                     covered_any=True)[0], cov.PARTIAL_RECOVERY)
        self.assertEqual(cov.resolve(CAP, proven_end=True, truncated=False, rejected=1, recovered=3,
                                     covered_any=True)[0], cov.PARTIAL_RECOVERY)
        self.assertEqual(cov.resolve(CAP, proven_end=True, truncated=False, rejected=0, recovered=0,
                                     covered_any=True), (cov.RECOVERED_LATE, 'complete'))

    def test_page_end_signals(self):
        short = cov.HistoryCapability(True, timedelta(days=1), cov.ORDER_UNORDERED, cov.PAGE_SHORT)
        self.assertEqual(cov.page_end(short, cov.HistoryPage(records=[1]), 1, 2), ('end', True))
        self.assertEqual(cov.page_end(short, cov.HistoryPage(records=[1, 2], next_token='2'), 2, 2), ('more', '2'))
        self.assertEqual(cov.page_end(short, cov.HistoryPage(records=[1, 2]), 2, 2), ('end', False))
        self.assertEqual(cov.page_end(CAP, cov.HistoryPage(records=[1]), 1, 2), ('end', False))   # no explicit end
        self.assertEqual(cov.page_end(CAP, cov.HistoryPage(records=[1], exhausted=True), 1, 2), ('end', True))
        total = cov.HistoryCapability(True, timedelta(days=1), cov.ORDER_UNORDERED, cov.PAGE_TOTAL)
        self.assertEqual(cov.page_end(total, cov.HistoryPage(records=[1], total=3, next_token='x'), 1, 2),
                         ('more', 'x'))
        self.assertEqual(cov.page_end(total, cov.HistoryPage(records=[1], total=3), 3, 2), ('end', True))

    def test_every_state_has_icon_text_and_tooltip(self):
        for key in cov.COVERAGE_VALUES:
            d = cov.coverage_display(key)
            self.assertTrue(d.label and d.icon.startswith('fa-') and d.tooltip and d.badge, key)
        self.assertEqual(len({cov.coverage_display(k).icon for k in cov.COVERAGE_VALUES}), len(cov.COVERAGE_VALUES))

    def test_validator_rules_for_coverage(self):
        base = json.loads((sh_dir() / 'examples' / 'healthy-quiet.json').read_text())
        bad = dict(base, coverage={'state': 'verified_quiet', 'last_verified_coverage_at': None,
                                   'gap': {'state': 'coverage_gap', 'complete': False}, 'history_capability': None})
        errors = sh.validate(bad)
        self.assertIn('coverage verified_quiet cannot have an open gap', errors)
        self.assertIn('an open coverage gap cannot report no_alerts', errors)
        bad = dict(base, coverage={'state': 'verified_quiet', 'gap': {'state': 'recovered_late', 'complete': True},
                                   'history_capability': {'supports_history': True}})
        self.assertIn('a recovered_late gap needs a fully declared history capability', sh.validate(bad))
        self.assertEqual(sh.validate(dict(base, coverage=None)), [])     # 1.0.0 producers stay valid


class CoverageSchemaTests(SimpleTestCase):
    def test_schema_1_1_matches_the_implementation(self):
        schema = json.loads((sh_dir() / 'schema-1.1.0.json').read_text())
        props = schema['properties']
        self.assertEqual(sh.SCHEMA_VERSION, '1.1.0')
        self.assertEqual(set(props['display_state']['enum']), set(sh.DISPLAY))
        self.assertEqual(tuple(props['coverage']['properties']['state']['enum']), cov.COVERAGE_VALUES)
        self.assertEqual(tuple(props['coverage']['properties']['state']['enum']), sh.COVERAGE_STATES)
        gap = props['coverage']['properties']['gap']['properties']
        self.assertEqual(tuple(gap['state']['enum']), cov.WINDOW_VALUES)
        cap = props['coverage']['properties']['history_capability']['properties']
        self.assertEqual(tuple(v for v in cap['ordering']['enum'] if v), cov.ORDERINGS)
        self.assertEqual(tuple(v for v in cap['pagination']['enum'] if v), cov.PAGINATION_SIGNALS)
        self.assertEqual(set(schema['required']), set(sh.REQUIRED))      # nothing new is required

    def test_coverage_examples_validate(self):
        for name in ('recovered-delivered-late', 'coverage-gap-recovering', 'unrecoverable-gap'):
            payload = json.loads((sh_dir() / 'examples' / f'{name}.json').read_text())
            self.assertEqual(sh.validate(payload), [], name)
            self.assertIsNotNone(payload['coverage'])


def sh_dir():
    from .tests_source_health import STANDARD_DIR
    return STANDARD_DIR


class PBSHistoryTests(TestCase):
    def test_pbs_pages_with_short_page_signal(self):
        from backup_monitoring.providers.pbs import ProxmoxBackupServerProvider
        from backup_monitoring.tests import make_pbs
        org = Organization.objects.create(name='CV PBS', slug='cv-pbs')
        provider = ProxmoxBackupServerProvider(make_pbs(org))
        start = int(T0.timestamp())
        tasks = [{'worker_type': 'backup', 'worker_id': 'store1:vm/100', 'upid': f'U{i}', 'starttime': start + i * 60,
                  'endtime': start + i * 60 + 30, 'status': 'OK'} for i in range(3)]
        seen = []

        def fake_get(path, params=None):
            seen.append(params)
            return tasks[params['start']:params['start'] + params['limit']]
        with mock.patch.object(provider, '_get', side_effect=fake_get), \
                mock.patch.object(provider, '_snapshot_sizes', return_value={}):
            p1 = provider.fetch_history(T0, T0 + timedelta(hours=1), None, 2)
            p2 = provider.fetch_history(T0, T0 + timedelta(hours=1), p1.next_token, 2)
        self.assertEqual(([r.external_id for r in p1.records], p1.next_token), (['U0', 'U1'], '2'))
        self.assertEqual(([r.external_id for r in p2.records], p2.next_token, p2.exhausted), (['U2'], '', True))
        self.assertEqual((seen[0]['since'], seen[0]['until'], seen[1]['start']), (start, start + 3600, 2))
        cap = provider.history_capability
        self.assertTrue(cap.can_prove_complete())
        self.assertEqual(cov.page_end(cap, p2, 3, 2), ('end', True))
