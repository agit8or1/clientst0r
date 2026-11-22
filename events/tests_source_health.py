"""Monitoring health contract 1.0.0 (roadmap 82.7–82.12).

Acceptance tests A–J from the Phase 82 community feedback (GitHub
Discussion #161) and the conformance cases C1–C15 of
docs/standards/MONITORING_HEALTH_STANDARD.md §9. Deterministic fixtures:
no network, fixed clocks where time matters.
"""
import json
import random
from datetime import datetime, timedelta, timezone as dt_tz
from pathlib import Path
from unittest import mock

from django.conf import settings as dj_settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization, SystemWarningNotification
from integrations.models import IntegrationSyncHealth
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from security_alerts.adapters.base import SecurityProvider
from security_alerts.models import SecurityAlert, SecurityIncident, SecurityVendorConnection

from . import source_health as sh
from . import source_health_store as store

STANDARD_DIR = Path(dj_settings.BASE_DIR) / 'docs' / 'standards' / 'monitoring-health'
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=dt_tz.utc)


class HTTPError(Exception):
    """A requests-like HTTP error with a response."""

    def __init__(self, status, headers=None):
        super().__init__(f'HTTP {status}')
        self.response = mock.Mock(status_code=status, headers=headers or {})


class FakeProvider(SecurityProvider):
    """Deterministic vendor: ``alerts`` is returned, or ``error`` raised;
    ``probe`` is True / an exception / None (no probe support)."""
    slug = 'security_fake_contract'

    def __init__(self, alerts=None, error=None, probe=None, ordered=False):
        self.alerts, self.error, self.probe = alerts or [], error, probe
        self.supports_empty_window_probe = probe is not None
        self.ordering_guaranteed = ordered
        self.probe_calls = []

    def test_connection(self, connection):
        return {'ok': True}

    def poll_alerts(self, connection, since=None):
        if self.error is not None:
            raise self.error
        return list(self.alerts)

    def probe_empty_window(self, connection, start, end):
        self.probe_calls.append((start, end))
        if isinstance(self.probe, BaseException):
            raise self.probe
        return self.probe


def alert(ext, when=None, **kw):
    return dict({'external_id': ext, 'severity': 'high', 'title': f'alert {ext}', 'asset_hint': 'PC-1',
                 'occurred_at': when}, **kw)


class _Base(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='SH Customer A', slug='sh-a')
        self.b = Organization.objects.create(name='SH Customer B', slug='sh-b')
        self.conn_a = SecurityVendorConnection.objects.create(organization=self.a, name='Defender A',
                                                              provider='defender', category='edr')
        self.conn_b = SecurityVendorConnection.objects.create(organization=self.b, name='Defender B',
                                                              provider='defender', category='edr')

    def run_sync(self, provider, conn=None):
        conn = conn or self.conn_a
        with self.captureOnCommitCallbacks(execute=False):
            return provider.sync(conn)

    def row(self, conn=None):
        conn = conn or self.conn_a
        return IntegrationSyncHealth.objects.get(content_type=ContentType.objects.get_for_model(conn),
                                                 object_id=conn.pk, kind='security')

    def eff(self, conn=None, now=None):
        r = self.row(conn)
        return sh.effective(store.fields_of(r, r.kind), now or timezone.now())

    def disp(self, conn=None, now=None):
        return sh.display(self.eff(conn, now)).key


# --- Acceptance tests A–J (Discussion #161) ---------------------------------------------------

class AcceptanceTests(_Base):
    def test_A_verified_quiet_window(self):
        """A working endpoint returns zero events and the bounded probe
        passes: healthy / quiet. Without a probe the same window is unknown."""
        p = FakeProvider(alerts=[], probe=True)
        self.assertTrue(self.run_sync(p)['ok'])
        self.assertEqual(len(p.probe_calls), 1)            # one bounded probe, no retries
        r = self.row()
        self.assertEqual((r.health, r.collection_outcome, r.alert_status, r.completeness, r.verification),
                         ('healthy', 'success', 'no_alerts', 'complete', 'probe_passed'))
        self.assertEqual(self.disp(), sh.D_HEALTHY_QUIET)
        # Same window, no way to verify: never healthy / quiet.
        self.run_sync(FakeProvider(alerts=[], probe=None), self.conn_b)
        rb = self.row(self.conn_b)
        self.assertEqual((rb.health, rb.alert_status, rb.completeness), ('unknown', 'unknown', 'unverified'))
        self.assertEqual(self.disp(self.conn_b), sh.D_UNKNOWN)

    def test_B_missing_permission(self):
        """Same window, the endpoint answers 403: permission denied."""
        self.assertFalse(self.run_sync(FakeProvider(error=HTTPError(403)))['ok'])
        r = self.row()
        self.assertEqual((r.health, r.collection_outcome, r.failure_reason, r.alert_status),
                         ('failed', 'failed', 'permission_denied', 'unknown'))
        self.assertEqual(self.disp(), sh.D_PERMISSION)
        # A forbidden probe after an empty window fails the read too.
        self.run_sync(FakeProvider(alerts=[], probe=HTTPError(403)), self.conn_b)
        self.assertEqual(self.disp(self.conn_b), sh.D_PERMISSION)
        self.assertNotEqual(self.row(self.conn_b).alert_status, 'no_alerts')

    def test_C_failed_ingestion(self):
        """Events retrieved, every store fails: ingestion failed."""
        with mock.patch('security_alerts.ingest.upsert_alert', side_effect=RuntimeError('db locked')):
            out = self.run_sync(FakeProvider(alerts=[alert('1', T0), alert('2', T0)]))
        self.assertFalse(out['ok'])
        r = self.row()
        self.assertEqual((r.health, r.collection_outcome, r.failure_reason, r.retrieved_count, r.committed_count,
                          r.rejected_count), ('failed', 'failed', 'ingestion_failed', 2, 0, 2))
        self.assertEqual(self.disp(), sh.D_INGESTION)
        self.assertIsNone(r.window_end_complete)       # the window will be asked for again

    def test_D_endpoint_unavailable(self):
        import requests
        self.run_sync(FakeProvider(error=requests.ConnectionError('Connection refused')))
        self.assertEqual(self.row().failure_reason, 'endpoint_unavailable')
        self.assertEqual(self.disp(), sh.D_UNAVAILABLE)
        self.run_sync(FakeProvider(error=requests.ReadTimeout('read timed out')), self.conn_b)
        self.assertEqual(self.row(self.conn_b).failure_reason, 'timeout')
        self.assertEqual(self.disp(self.conn_b), sh.D_UNAVAILABLE)

    def test_E_stale_after_threshold(self):
        """Collection stops: the sweep marks it stale once the threshold
        passes, and a critical source notifies once."""
        self.run_sync(FakeProvider(alerts=[], probe=True))
        r = self.row()
        r.stale_after_minutes = 30
        r.save()
        self.assertEqual(self.disp(now=r.last_success_at + timedelta(minutes=29)), sh.D_HEALTHY_QUIET)
        later = r.last_success_at + timedelta(minutes=31)
        f = self.eff(now=later)
        self.assertEqual((f['health'], f['reason'], f['alert_status'], f['freshness']),
                         ('unknown', 'stale_data', 'unknown', 'stale'))
        with self.captureOnCommitCallbacks(execute=False):
            self.assertEqual(store.sweep(now=later), 1)
            self.assertEqual(store.sweep(now=later + timedelta(minutes=1)), 0)
        self.assertEqual(self.row().display_state, sh.D_STALE)
        self.assertEqual(SystemWarningNotification.objects.filter(warning_id__startswith='srchealth:').count(), 1)

    def test_E_repeated_failures_go_failed(self):
        """Transient failures are Degraded until they persist."""
        import requests
        self.run_sync(FakeProvider(alerts=[], probe=True))
        for expected in ('degraded', 'degraded', 'failed'):
            self.run_sync(FakeProvider(error=requests.ConnectionError('refused')))
            self.assertEqual(self.row().health, expected)
        self.assertEqual(self.row().consecutive_failures, 3)
        self.assertIsNotNone(self.row().next_attempt_at)

    def test_F_unordered_results(self):
        """Out-of-order results: newest is the max validated timestamp, not the
        first record; no valid timestamp → unknown."""
        times = ['2026-11-20T10:00:00Z', '2026-11-20T11:30:00Z', '2026-11-20T09:00:00Z']
        p = FakeProvider(alerts=[alert(str(i), t) for i, t in enumerate(times)])
        self.run_sync(p)
        r = self.row()
        self.assertEqual(r.newest_event_at, datetime(2026, 11, 20, 11, 30, tzinfo=dt_tz.utc))
        self.assertEqual(r.newest_event_basis, 'validated_timestamps')
        self.run_sync(FakeProvider(alerts=[alert('x', None), alert('y', 'not a time'),
                                           alert('z', '2026-11-20T10:00:00')]), self.conn_b)   # naive
        rb = self.row(self.conn_b)
        self.assertIsNone(rb.newest_event_at)
        self.assertEqual(rb.newest_event_basis, 'unknown')

    def test_G_partial_ingestion(self):
        from security_alerts import ingest
        real = ingest.upsert_alert

        def flaky(lookup, values):
            if lookup['external_id'] == 'bad':
                raise RuntimeError('constraint')
            return real(lookup, values)
        with mock.patch('security_alerts.ingest.upsert_alert', side_effect=flaky):
            self.run_sync(FakeProvider(alerts=[alert('ok1', T0), alert('bad', T0), alert('ok2', T0)]))
        r = self.row()
        self.assertEqual((r.retrieved_count, r.committed_count, r.rejected_count), (3, 2, 1))
        self.assertEqual((r.health, r.collection_outcome, r.completeness, r.failure_reason, r.alert_status),
                         ('degraded', 'partial', 'partial', 'ingestion_failed', 'active_alerts'))
        self.assertEqual(self.disp(), sh.D_DEGRADED)
        self.assertEqual(SecurityAlert.objects.filter(connection=self.conn_a).count(), 2)
        self.assertEqual(self.conn_a.last_sync_status, 'partial')

    def test_H_ai_cannot_report_healthy(self):
        """One critical source unavailable, the other quiet: the AI output
        always carries the deterministic visibility statement."""
        import requests
        from security_alerts import ai_summarizer
        self.run_sync(FakeProvider(error=requests.ConnectionError('refused')))
        conn2 = SecurityVendorConnection.objects.create(organization=self.a, name='Firewall A',
                                                        provider='defender', category='firewall')
        self.run_sync(FakeProvider(alerts=[], probe=True), conn2)
        incident = SecurityIncident.objects.create(organization=self.a, title='Probe', severity='low')
        seen = {}

        def model(incident, *, requested_by=None, visibility=None):
            seen['visibility'] = visibility
            return {'summary': 'No threats detected. The environment is healthy.', 'next_steps': []}
        ai_summarizer.set_provider(model)
        try:
            with mock.patch.object(ai_summarizer, 'is_ai_enabled', return_value=True):
                out = ai_summarizer.summarize_incident(incident)
        finally:
            ai_summarizer.set_provider(None)
        self.assertTrue(out['ok'])
        self.assertFalse(out['monitoring_verified'])
        self.assertTrue(out['summary'].startswith('Zero threats detected in the successfully monitored sources.'))
        self.assertIn('Defender A', out['summary'])
        self.assertIn('cannot be verified', out['summary'])
        # The model received facts, not secrets or internals.
        self.assertFalse(seen['visibility']['monitoring_verified'])
        self.assertNotIn('_summary', seen['visibility'])
        self.assertNotIn('diagnostic', json.dumps(seen['visibility'], default=str))

    def test_I_multi_tenant_isolation(self):
        import requests
        self.run_sync(FakeProvider(alerts=[], probe=True), self.conn_b)
        before = (self.row(self.conn_b).health, self.row(self.conn_b).display_state)
        self.run_sync(FakeProvider(error=HTTPError(401)))
        self.run_sync(FakeProvider(error=requests.ConnectionError('x')))
        self.assertEqual((self.row(self.conn_b).health, self.row(self.conn_b).display_state), before)
        self.assertEqual(self.row().organization_id, self.a.pk)
        self.assertTrue(store.summary_for({self.b.pk}, kinds=('security',))['verified'])
        self.assertFalse(store.summary_for({self.a.pk}, kinds=('security',))['verified'])
        # B's roll-up never names A's source.
        b_names = [g['name'] for g in store.summary_for({self.b.pk})['gaps']]
        self.assertNotIn('Defender A', b_names)

    def test_J_recovery(self):
        self.run_sync(FakeProvider(error=HTTPError(403)))
        self.assertEqual(self.row().alerted_state, sh.D_PERMISSION)
        with self.captureOnCommitCallbacks(execute=False):
            FakeProvider(alerts=[], probe=True).sync(self.conn_a)
        r = self.row()
        self.assertEqual((r.health, r.consecutive_failures, r.alerted_state, r.display_state, r.next_attempt_at),
                         ('healthy', 0, '', sh.D_HEALTHY_QUIET, None))
        markers = SystemWarningNotification.objects.filter(warning_id__startswith=f'srchealth:{r.pk}:')
        self.assertEqual(sorted(m.warning_id.split(':')[2] for m in markers),
                         sorted([sh.D_PERMISSION, sh.D_HEALTHY_QUIET]))
        from audit.models import AuditLog
        moves = list(AuditLog.objects.filter(object_type='monitoring_source_health', object_id=r.pk)
                     .order_by('pk').values_list('extra_data', flat=True))
        self.assertEqual([m['to'] for m in moves], [sh.D_PERMISSION, sh.D_HEALTHY_QUIET])


# --- Conformance cases not covered by A–J (standard §9) -----------------------------------------

class ConformanceTests(_Base):
    def test_C2_active_alerts_with_healthy_collector(self):
        self.run_sync(FakeProvider(alerts=[alert('1', T0)]))
        r = self.row()
        self.assertEqual((r.health, r.alert_status), ('healthy', 'active_alerts'))
        self.assertEqual(self.disp(), sh.D_HEALTHY_ACTIVE)

    def test_C4_authentication_failure(self):
        self.run_sync(FakeProvider(error=HTTPError(401)))
        self.assertEqual(self.row().failure_reason, 'authentication_failure')
        self.assertEqual(sh.display(self.eff()).label, 'Authentication failed')

    def test_C6_rate_limited_respects_retry_after(self):
        self.run_sync(FakeProvider(alerts=[], probe=True))
        self.run_sync(FakeProvider(error=HTTPError(429, {'Retry-After': '900'})))
        r = self.row()
        self.assertEqual((r.failure_reason, r.health), ('rate_limited', 'degraded'))
        self.assertGreaterEqual((r.next_attempt_at - r.last_attempt_at).total_seconds(), 900)
        self.assertFalse(store.due(self.conn_a, 'security', r.last_attempt_at + timedelta(seconds=600)))
        self.assertTrue(store.due(self.conn_a, 'security', r.last_attempt_at + timedelta(seconds=3700)))

    def test_C6_malformed_response_is_not_empty(self):
        class Broken(FakeProvider):
            def poll_alerts(self, connection, since=None):
                return None
        self.run_sync(Broken())
        self.assertEqual((self.row().failure_reason, self.row().alert_status), ('invalid_response', 'unknown'))

    def test_C13_duplicate_attempt_is_idempotent(self):
        result = sh.CollectionResult(attempted_at=T0, retrieved=1, processed=1, committed=1, collection_id='run-1',
                                     verification=sh.V_PROBE)
        store.record_collection(self.conn_a, 'security', result)
        failed = sh.CollectionResult(attempted_at=T0, error=HTTPError(500), collection_id='run-1')
        store.record_collection(self.conn_a, 'security', failed)
        self.assertEqual((self.row().health, self.row().consecutive_failures), ('healthy', 0))
        # Re-delivered alerts are deduplicated by external id.
        self.run_sync(FakeProvider(alerts=[alert('dup', T0)]))
        self.run_sync(FakeProvider(alerts=[alert('dup', T0)]))
        self.assertEqual(SecurityAlert.objects.filter(connection=self.conn_a, external_id='dup').count(), 1)

    def test_failed_window_is_requested_again(self):
        """A failed attempt never advances the collection cursor."""
        p = FakeProvider(alerts=[], probe=True)
        self.run_sync(p)
        cur = self.row().window_end_complete
        self.run_sync(FakeProvider(error=HTTPError(503)))
        self.assertEqual(self.row().window_end_complete, cur)
        seen = {}

        class Spy(FakeProvider):
            def poll_alerts(self, connection, since=None):
                seen['since'] = since
                return []
        self.run_sync(Spy(probe=True))
        self.assertEqual(seen['since'], cur)

    def test_push_source_cannot_claim_quiet(self):
        """Webhook-only connections are unknown until something arrives."""
        recs = store.gather({self.a.pk}, kinds=('push',))
        self.assertEqual({r['name'] for r in recs}, {'Defender A'})
        self.assertEqual(recs[0]['health'], 'unknown')
        self.assertNotEqual(recs[0]['alert_status'], 'no_alerts')

    def test_customer_digest_all_clear_needs_verified_monitoring(self):
        from security_alerts import digest
        self.assertFalse(digest._monitoring_verified(self.a))
        subject, body = digest.render_unverified(self.a, brand='MSP', unsubscribe='u')
        self.assertIn('not fully verified', subject)
        self.assertNotIn('all clear', subject)


class ContractUnitTests(SimpleTestCase):
    def test_states_are_independent(self):
        ok_alerts = sh.evaluate(sh.CollectionResult(attempted_at=T0, retrieved=3, processed=3, committed=3))
        self.assertEqual((ok_alerts['health'], ok_alerts['alert_status']), ('healthy', 'active_alerts'))
        broken = sh.evaluate(sh.CollectionResult(attempted_at=T0, error=HTTPError(403)))
        self.assertEqual((broken['health'], broken['alert_status']), ('failed', 'unknown'))

    def test_http_classification(self):
        cases = {401: 'authentication_failure', 403: 'permission_denied', 404: 'configuration_error',
                 408: 'timeout', 429: 'rate_limited', 500: 'endpoint_unavailable', 503: 'endpoint_unavailable',
                 422: 'invalid_response'}
        for status, reason in cases.items():
            self.assertEqual(sh.classify_exception(HTTPError(status))[0], reason, status)
        self.assertEqual(sh.classify_exception(ValueError('Expecting value: line 1'))[0], 'invalid_response')

    def test_retry_backoff_grows_with_jitter_and_cap(self):
        rng = random.Random(7)
        delays = [sh.next_retry_delay(n, rng=rng) for n in range(1, 10)]
        self.assertTrue(all(sh.RETRY_BASE_SECONDS / 2 <= d <= sh.RETRY_CAP_SECONDS for d in delays))
        self.assertLess(delays[0], delays[4])
        self.assertEqual(sh.next_retry_delay(1, retry_after=1200, rng=rng) >= 1200, True)
        self.assertEqual(sh.next_retry_delay(0), 0)

    def test_ordering_guarantee_uses_first_record_only_when_documented(self):
        times = ['2026-11-20T09:00:00Z', '2026-11-20T11:00:00Z']
        self.assertEqual(sh.newest_event_time(times, T0)[0].hour, 11)
        self.assertEqual(sh.newest_event_time(times, T0, ordering_guaranteed=True),
                         (datetime(2026, 11, 20, 9, tzinfo=dt_tz.utc), 'source_order'))
        future = ['2027-01-01T00:00:00Z']
        self.assertEqual(sh.newest_event_time(future, T0), (None, 'unknown'))

    def test_summary_and_ai_guard(self):
        quiet = sh.effective({'name': 'EDR', 'kind': 'security', 'health': 'healthy', 'outcome': 'success',
                              'alert_status': 'no_alerts', 'completeness': 'complete', 'last_success_at': T0,
                              'stale_after_minutes': 60, 'critical': True}, T0)
        down = sh.effective({'name': 'Microsoft Defender', 'kind': 'security', 'health': 'failed',
                             'outcome': 'failed', 'alert_status': 'unknown', 'reason': 'endpoint_unavailable',
                             'completeness': 'unverified', 'last_success_at': T0 - timedelta(hours=1),
                             'stale_after_minutes': 60, 'critical': True}, T0)
        s = sh.summarize([quiet, down])
        self.assertFalse(s['verified'])
        self.assertEqual(s['alert_status'], 'unknown')
        statement = sh.visibility_statement(s)
        self.assertTrue(statement.startswith('Zero threats detected in the successfully monitored sources.'))
        self.assertIn('Microsoft Defender (source unavailable)', statement)
        text, changed = sh.guard_ai_text('All clear, everything is healthy.', s)
        self.assertTrue(changed and text.startswith(statement))
        self.assertTrue(sh.summarize([quiet])['verified'])
        self.assertFalse(sh.summarize([])['verified'])


class SchemaTests(SimpleTestCase):
    """The published JSON Schema, its examples and the Python validator agree."""

    def test_examples_validate(self):
        examples = sorted((STANDARD_DIR / 'examples').glob('*.json'))
        self.assertGreaterEqual(len(examples), 4)
        for path in examples:
            payload = json.loads(path.read_text())
            self.assertEqual(sh.validate(payload), [], path.name)

    def test_schema_enums_match_the_implementation(self):
        schema = json.loads((STANDARD_DIR / 'schema-1.0.0.json').read_text())
        props = schema['properties']
        self.assertEqual(schema['properties']['schema_version']['pattern'], r'^1\.[0-9]+\.[0-9]+$')
        self.assertEqual(tuple(props['health']['enum']), sh.HEALTH_VALUES)
        self.assertEqual(tuple(props['collection_outcome']['enum']), sh.OUTCOME_VALUES)
        self.assertEqual(tuple(props['alert_status']['enum']), sh.ALERT_VALUES)
        self.assertEqual(tuple(v for v in props['failure_reason']['enum'] if v), sh.REASON_VALUES)
        self.assertEqual(tuple(props['completeness']['enum']), sh.COMPLETENESS_VALUES)
        self.assertEqual(set(schema['required']), set(sh.REQUIRED))

    def test_validator_rejects_contradictions(self):
        good = json.loads((STANDARD_DIR / 'examples' / 'healthy-quiet.json').read_text())
        bad = dict(good, alert_status='no_alerts', health='unknown', completeness='unverified')
        self.assertIn('no_alerts requires verified healthy collection', sh.validate(bad))
        bad = dict(good, health='healthy', freshness='stale')
        self.assertIn('healthy requires freshness fresh', sh.validate(bad))
        bad = dict(good, collection_outcome='failed', health='failed', failure_reason=None, alert_status='unknown')
        self.assertIn('a failed collection needs a failure_reason', sh.validate(bad))
        self.assertTrue(sh.validate(dict(good, schema_version='2.0.0')))

    def test_contract_output_validates(self):
        f = sh.evaluate(sh.CollectionResult(attempted_at=T0, window_start=T0 - timedelta(minutes=5), window_end=T0,
                                            verification=sh.V_PROBE))
        payload = sh.to_contract(sh.effective(f, T0), tenant_id=7, source_id='security:1:2', source_type='security')
        self.assertEqual(sh.validate(payload), [])
        self.assertEqual(payload['display_state'], 'healthy_quiet')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(_Base):
    def setUp(self):
        super().setUp()
        FakeProvider(error=HTTPError(403)).sync(self.conn_a)
        FakeProvider(alerts=[], probe=True).sync(self.conn_b)
        self.admin = User.objects.create_superuser('sh-admin', 'a@example.test', 'pw')
        role = RoleTemplate.objects.create(name='sh scoped', events_view=True)
        self.tech = _make_msp_tech(User.objects.create_user('sh-tech', password='pw'))
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

    def test_admin_sees_every_customer_and_the_failure(self):
        r = self.client_for(self.admin, self.a).get('/security/events/sources/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'SH Customer A')
        self.assertContains(r, 'SH Customer B')
        self.assertContains(r, 'data-state="permission_denied"')
        self.assertContains(r, 'cannot be verified')

    def test_scoped_tech_sees_only_their_customer(self):
        c = self.client_for(self.tech, self.b)
        r = c.get('/security/events/sources/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Defender A')
        # (The site-wide client switcher lists every client for MSP staff;
        # the reliability tables must not.)
        self.assertNotContains(r, f'?customer={self.a.pk}"')
        self.assertContains(r, f'?customer={self.b.pk}"')
        self.assertEqual(c.get(f'/security/events/sources/?customer={self.a.pk}').status_code, 403)
        data = c.get('/security/events/sources.json').json()
        self.assertEqual(data['schema_version'], '1.0.0')
        self.assertEqual({p['tenant_id'] for p in data['sources']}, {str(self.b.pk)})
        for p in data['sources']:
            self.assertEqual(sh.validate(p), [], p)

    def test_json_never_includes_credentials(self):
        self.conn_a.last_error = ''
        data = self.client_for(self.admin, self.a).get('/security/events/sources.json').json()
        text = json.dumps(data)
        self.assertNotIn('webhook_token', text)
        self.assertNotIn('password', text.lower())
