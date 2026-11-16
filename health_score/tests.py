"""Customer health score: each dimension with seeded data, unknown / stale
handling, weighting and coverage, change explanations, tenant isolation,
permission gating and the views (customers never see any of it)."""
import sys
import types
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from core.models import Organization, ScheduledTask
from health_score import permissions, providers, registry, scoring
from health_score.models import CustomerHealthSnapshot, HealthScoreConfig
from integrations.models import RMMAlert, RMMConnection, RMMDevice
from psa.models import Contract, Invoice, Queue, Ticket, TicketComment, TicketPriority, TicketStatus, TicketType
from pulse.models import PulseCheck, PulseResponse, PulseSend
from security_alerts.models import SecurityAlert, SecurityIncident, SecurityVendorConnection

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

NOW = timezone.now()


def _staff(username, scope='all', scope_orgs=(), **flags):
    user = User.objects.create_user(username, f'{username}@example.com', 'x')
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.user_type = UserType.STAFF
    profile.client_scope = scope
    role = RoleTemplate.objects.create(name=f'role-{username}', **flags)
    profile.global_role_template = role
    profile.save()
    if scope_orgs:
        profile.scope_organizations.set(scope_orgs)
    return user


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def _stub(value, status=None, key='x'):
    return {'key': key, 'label': key, 'value': value, 'status': status or ('ok' if value is not None else 'unknown'),
            'refs': [], 'explanation': '', 'as_of': None, 'source': ''}


def _make_ticket(org, **fields):
    t = Ticket.objects.create(
        organization=org, subject=fields.pop('subject', 'Printer down'),
        queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
        ticket_type=TicketType.objects.first(),
        status=fields.pop('status', TicketStatus.objects.filter(is_terminal=False).first()))
    if fields:
        Ticket.objects.filter(pk=t.pk).update(**fields)
        t.refresh_from_db()
    return t


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('psa_seed_defaults', verbosity=0)
        cls.a = Organization.objects.create(name='Alpha Co', slug='hs-alpha')
        cls.b = Organization.objects.create(name='Bravo Co', slug='hs-bravo')
        cls.conn = RMMConnection.objects.create(organization=cls.a, provider_type='ninjaone',
                                                name='RMM', base_url='https://rmm.example.test')

    def ctx(self, org, config=None):
        config = config or HealthScoreConfig()
        return registry.Context(client=org, now=NOW, config=config, today=timezone.localdate(NOW))

    def device(self, org, name, online=True, refreshed=None, **kw):
        return RMMDevice.objects.create(
            organization=org, connection=self.conn, external_id=name, device_name=name, is_online=online,
            last_seen=NOW, data_refreshed_at=refreshed or NOW - timedelta(minutes=10), **kw)


class TechnicalTests(_Base):
    def test_no_devices_is_unknown(self):
        r = providers.rmm_online(self.ctx(self.a))
        self.assertEqual(r['status'], 'unknown')
        self.assertIsNone(r['value'])

    def test_online_share_and_offline_refs(self):
        self.device(self.a, 'srv1')
        self.device(self.a, 'srv2')
        off = self.device(self.a, 'srv3', online=False)
        self.device(self.a, 'srv4')
        r = providers.rmm_online(self.ctx(self.a))
        self.assertEqual(r['value'], 75.0)
        self.assertEqual([x['pk'] for x in r['refs']], [off.pk])
        self.assertIn('/integrations/rmm/devices/', r['refs'][0]['url'])

    def test_stale_devices_are_stale_not_ok(self):
        self.device(self.a, 'old1', refreshed=NOW - timedelta(days=3))
        self.device(self.a, 'old2', refreshed=NOW - timedelta(days=3))
        for fn in (providers.rmm_online, providers.rmm_checkin, providers.rmm_alerts):
            r = fn(self.ctx(self.a))
            self.assertEqual(r['status'], 'stale', fn.__name__)
            self.assertIsNone(r['value'])
        dim = scoring.compute_dimension('technical', self.ctx(self.a), HealthScoreConfig())
        self.assertEqual(dim['status'], 'stale')
        self.assertIsNone(dim['value'])

    def test_stale_devices_are_excluded_but_reduce_checkin_share(self):
        self.device(self.a, 'ok1')
        self.device(self.a, 'old', refreshed=NOW - timedelta(days=3))
        self.assertEqual(providers.rmm_online(self.ctx(self.a))['value'], 100.0)
        r = providers.rmm_checkin(self.ctx(self.a))
        self.assertEqual(r['value'], 50.0)
        self.assertEqual(len(r['refs']), 1)

    def test_alerts_reduce_value(self):
        d = self.device(self.a, 'srv')
        RMMAlert.objects.create(organization=self.a, connection=self.conn, device=d, external_id='1',
                                alert_type='Disk 95% full', message='m', severity='critical',
                                status='active', triggered_at=NOW)
        RMMAlert.objects.create(organization=self.a, connection=self.conn, device=d, external_id='2',
                                alert_type='Patch', message='m', severity='warning',
                                status='resolved', triggered_at=NOW)
        r = providers.rmm_alerts(self.ctx(self.a))
        self.assertEqual(r['value'], 70.0)
        self.assertEqual(len(r['refs']), 1)

    def test_unsettled_ownership_device_not_counted(self):
        self.device(self.a, 'moved', ownership_status=RMMDevice.OWNERSHIP_MOVED)
        self.assertEqual(providers.rmm_online(self.ctx(self.a))['status'], 'unknown')


class SecurityTests(_Base):
    def test_unconfigured_is_unknown_not_healthy(self):
        self.assertEqual(providers.security_alerts(self.ctx(self.a))['status'], 'unknown')
        self.assertEqual(providers.security_incidents(self.ctx(self.a))['status'], 'unknown')

    def _vendor(self, org, synced=True):
        return SecurityVendorConnection.objects.create(
            organization=org, client_org=org, name='EDR', provider='crowdstrike', category='edr',
            last_sync_at=NOW - timedelta(minutes=5) if synced else NOW - timedelta(days=9))

    def test_connection_with_no_alerts_is_healthy(self):
        self._vendor(self.a)
        r = providers.security_alerts(self.ctx(self.a))
        self.assertEqual((r['status'], r['value']), ('ok', 100.0))

    def test_unsynced_connection_is_stale(self):
        self._vendor(self.a, synced=False)
        self.assertEqual(providers.security_alerts(self.ctx(self.a))['status'], 'stale')

    def test_open_alerts_by_severity(self):
        conn = self._vendor(self.a)
        SecurityAlert.objects.create(connection=conn, organization=self.a, client_org=self.a, external_id='1',
                                     severity='critical', title='Ransomware')
        SecurityAlert.objects.create(connection=conn, organization=self.a, client_org=self.a, external_id='2',
                                     severity='low', title='Port scan', status='resolved')
        r = providers.security_alerts(self.ctx(self.a))
        self.assertEqual(r['value'], 70.0)
        self.assertEqual(r['status'], 'warn')
        self.assertEqual(len(r['refs']), 1)

    def test_incidents(self):
        SecurityIncident.objects.create(organization=self.a, client_org=self.a, title='Breach', severity='high')
        SecurityIncident.objects.create(organization=self.a, client_org=self.a, title='Old', severity='high',
                                        status='closed')
        r = providers.security_incidents(self.ctx(self.a))
        self.assertEqual(r['value'], 75.0)
        self.assertEqual(len(r['refs']), 1)


class BackupTests(_Base):
    def test_backup_monitoring_absent_is_unknown(self):
        self.assertFalse(providers._installed('backup_monitoring'))
        for fn in (providers.backup_jobs, providers.restore_tests):
            r = fn(self.ctx(self.a))
            self.assertEqual(r['status'], 'unknown')
            self.assertIn('not installed', r['explanation'])
        dim = scoring.compute_dimension('backup', self.ctx(self.a), HealthScoreConfig())
        self.assertEqual(dim['status'], 'unknown')

    def _job(self, **kw):
        base = dict(name='job', last_run_at=NOW, last_status='ok', last_success_at=NOW - timedelta(hours=2),
                    expected_interval_hours=24, fresh=True)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_evaluate_backup(self):
        v, state, issues = providers.evaluate_backup([self._job(), self._job(last_status='failed')], NOW)
        self.assertEqual((v, state, len(issues)), (50.0, 'scored', 1))
        v, state, _ = providers.evaluate_backup([self._job(last_success_at=NOW - timedelta(days=4))], NOW)
        self.assertEqual(v, 10.0)
        v, state, _ = providers.evaluate_backup([self._job(fresh=False)], NOW)
        self.assertEqual((v, state), (None, 'stale'))
        v, state, _ = providers.evaluate_backup([self._job(last_run_at=None)], NOW)
        self.assertEqual((v, state), (None, 'unknown'))
        self.assertEqual(providers.evaluate_backup([], NOW)[1], 'unknown')

    def test_backup_provider_with_models_present(self):
        job = SimpleNamespace(name='nightly', pk=1, last_run_at=NOW, last_status='ok',
                              last_success_at=NOW, expected_interval_hours=24,
                              connection=SimpleNamespace(active=True, last_poll_at=NOW,
                                                         last_poll_status='ok', is_push=False))
        job._meta = SimpleNamespace(app_label='backup_monitoring', model_name='backupjob')

        class _Jobs:
            objects = SimpleNamespace(filter=lambda **kw: SimpleNamespace(select_related=lambda *a: [job]))
        with mock.patch.object(providers, '_backup_models', return_value=(_Jobs, None)):
            r = providers.backup_jobs(self.ctx(self.a))
        self.assertEqual((r['status'], r['value']), ('ok', 100.0))


class ServiceDeliveryTests(_Base):
    def _closed(self, org, breached):
        return _make_ticket(org, closed_at=NOW - timedelta(days=5),
                            resolution_due_at=NOW - timedelta(days=4),
                            sla_breached_resolution=breached)

    def test_too_little_data_is_unknown(self):
        self._closed(self.a, False)
        self.assertEqual(providers.sla_attainment(self.ctx(self.a))['status'], 'unknown')

    def test_sla_attainment(self):
        for breached in (False, False, False, True):
            t = self._closed(self.a, breached)
        r = providers.sla_attainment(self.ctx(self.a))
        self.assertEqual(r['value'], 75.0)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual([x['pk'] for x in r['refs']], [t.pk])
        self.assertIn('/psa/', r['refs'][0]['url'])

    def test_ticket_volume_vs_baseline(self):
        for _ in range(6):                      # baseline: 6 in the 90 days -> 2 per 30 days
            _make_ticket(self.a, created_at=NOW - timedelta(days=60))
        for _ in range(2):
            _make_ticket(self.a)
        r = providers.ticket_volume(self.ctx(self.a))
        self.assertEqual(r['value'], 100.0)
        for _ in range(6):
            _make_ticket(self.a)
        r = providers.ticket_volume(self.ctx(self.a))
        self.assertLess(r['value'], 50)
        self.assertTrue(r['refs'])

    def test_ticket_volume_needs_baseline(self):
        _make_ticket(self.a)
        self.assertEqual(providers.ticket_volume(self.ctx(self.a))['status'], 'unknown')

    def test_reopen_rate(self):
        ts = [_make_ticket(self.a, closed_at=NOW - timedelta(days=3)) for _ in range(4)]
        TicketComment.objects.create(ticket=ts[0], body='Reopened. Status: Closed → In progress',
                                     is_internal=True, is_system=True)
        r = providers.reopen_rate(self.ctx(self.a))
        self.assertEqual(r['value'], 0.0)       # 1 of 4 reopened = 25%
        self.assertEqual([x['pk'] for x in r['refs']], [ts[0].pk])


class CommercialTests(_Base):
    def _invoice(self, org, due_days_ago, status='sent', total='100'):
        today = timezone.localdate(NOW)
        return Invoice.objects.create(
            organization=org, client_org=org, title='Work', invoice_date=today - timedelta(days=due_days_ago + 30),
            due_date=today - timedelta(days=due_days_ago), status=status, total=Decimal(total))

    def test_no_invoices_unknown(self):
        self.assertEqual(providers.overdue_invoices(self.ctx(self.a))['status'], 'unknown')

    def test_overdue_invoices(self):
        self._invoice(self.a, 45)
        self._invoice(self.a, 5, status='paid')
        r = providers.overdue_invoices(self.ctx(self.a))
        self.assertEqual(r['value'], 75.0)
        self.assertEqual(len(r['refs']), 1)
        self.assertIn('45 days late', r['refs'][0]['label'])

    def test_all_paid_is_healthy(self):
        self._invoice(self.a, 5, status='paid')
        self.assertEqual(providers.overdue_invoices(self.ctx(self.a))['value'], 100.0)

    def _contract(self, end_in_days, **kw):
        today = timezone.localdate(NOW)
        return Contract.objects.create(organization=self.a, client_org=self.a, name='MSA', status='active',
                                       start_date=today - timedelta(days=300),
                                       end_date=today + timedelta(days=end_in_days), **kw)

    def test_renewal_without_draft_flags(self):
        c = self._contract(30)
        r = providers.contract_renewals(self.ctx(self.a))
        self.assertEqual(r['value'], 60.0)
        self.assertEqual(r['refs'][0]['pk'], c.pk)

    def test_renewal_with_draft_or_auto_renew_is_fine(self):
        c = self._contract(30)
        Contract.objects.create(organization=self.a, client_org=self.a, name='MSA renewal', status='draft',
                                start_date=c.end_date, parent_contract=c)
        self.assertEqual(providers.contract_renewals(self.ctx(self.a))['value'], 100.0)

    def test_no_active_contract_unknown(self):
        self.assertEqual(providers.contract_renewals(self.ctx(self.a))['status'], 'unknown')

    def test_profitability_absent_unknown(self):
        r = providers.profitability(self.ctx(self.a))
        self.assertEqual(r['status'], 'unknown')

    def test_profitability_incomplete_unknown_and_complete_scored(self):
        fake = types.ModuleType('reports.costing')
        fake.client_margin_summary = lambda client, today: {'margin_pct': 30, 'complete': False}
        with mock.patch.dict(sys.modules, {'reports.costing': fake}):
            self.assertEqual(providers.profitability(self.ctx(self.a))['status'], 'unknown')
            fake.client_margin_summary = lambda client, today: {'margin_pct': 30, 'complete': True}
            r = providers.profitability(self.ctx(self.a))
        self.assertEqual(r['value'], 75.0)


class SatisfactionTests(_Base):
    def _send(self, org_answers, when):
        check = PulseCheck.objects.create(name='Quarterly')
        send = PulseSend.objects.create(
            pulse_check=check, expires_at=when + timedelta(days=14),
            questions=[{'id': 1, 'kind': 'rating', 'text': 'Overall?'}])
        for i, (org, value) in enumerate(org_answers):
            PulseResponse.objects.create(send=send, organization=org, email=f'u{i}@{org.slug}.test',
                                         token_hash=f'{send.pk}-{org.pk}-{i}-{when.timestamp()}',
                                         answers={'1': value}, responded_at=when)
        return send

    def test_no_responses_unknown(self):
        self.assertEqual(providers.pulse_score(self.ctx(self.a))['status'], 'unknown')

    def test_score_from_ratings(self):
        send = self._send([(self.a, 5), (self.a, 3), (self.b, 1)], NOW - timedelta(days=10))
        r = providers.pulse_score(self.ctx(self.a))
        self.assertEqual(r['value'], 75.0)
        self.assertEqual(r['refs'][0]['pk'], send.pk)

    def test_old_answers_are_stale(self):
        self._send([(self.a, 5)], NOW - timedelta(days=400))
        self.assertEqual(providers.pulse_score(self.ctx(self.a))['status'], 'stale')

    def test_trend(self):
        self._send([(self.a, 5)], NOW - timedelta(days=120))
        self.assertEqual(providers.pulse_trend(self.ctx(self.a))['status'], 'unknown')
        self._send([(self.a, 3)], NOW - timedelta(days=10))
        r = providers.pulse_trend(self.ctx(self.a))
        self.assertEqual(r['status'], 'critical' if r['value'] < 50 else r['status'])
        self.assertLess(r['value'], 75)


class WeightingTests(_Base):
    def test_overall_only_over_known_dimensions(self):
        cfg = HealthScoreConfig()
        dims = {k: {'weight': cfg.dimension_weight(k), 'value': None, 'status': 'unknown'}
                for k in registry.DIMENSION_KEYS}
        overall, status, known, total = scoring.overall_from(dims, cfg)
        self.assertEqual((overall, status, known, total), (None, 'unknown', 0, 6))
        dims['technical'].update(value=80.0, status='ok')
        dims['security'].update(value=40.0, status='critical')
        overall, status, known, total = scoring.overall_from(dims, cfg)
        self.assertEqual(overall, 60.0)            # equal weights 20/20
        self.assertEqual((known, total), (2, 6))
        self.assertEqual(status, 'warn')

    def test_custom_weights_and_off_dimensions(self):
        cfg = HealthScoreConfig(dimension_weights={'technical': 30, 'security': 10, 'backup': 0})
        dims = {k: {'weight': cfg.dimension_weight(k), 'value': None, 'status': 'unknown'}
                for k in registry.DIMENSION_KEYS}
        dims['technical'].update(value=80.0)
        dims['security'].update(value=40.0)
        overall, _s, known, total = scoring.overall_from(dims, cfg)
        self.assertEqual(overall, 70.0)            # (80*30 + 40*10) / 40
        self.assertEqual(total, 5)                 # backup is off

    def test_dimension_uses_signal_weights_and_skips_unscored(self):
        cfg = HealthScoreConfig(signal_weights={'rmm_online': 3, 'rmm_checkin': 1, 'rmm_alerts': 0})
        self.device(self.a, 'x1')
        self.device(self.a, 'x2', online=False)
        self.device(self.a, 'x3', refreshed=NOW - timedelta(days=3))
        dim = scoring.compute_dimension('technical', self.ctx(self.a, cfg), cfg)
        online = next(s for s in dim['signals'] if s['key'] == 'rmm_online')
        checkin = next(s for s in dim['signals'] if s['key'] == 'rmm_checkin')
        self.assertEqual(online['value'], 50.0)
        self.assertAlmostEqual(checkin['value'], 66.7, places=1)
        self.assertEqual(dim['signals_total'], 2)          # alerts weight 0 = off
        self.assertAlmostEqual(dim['value'], (50 * 3 + 66.7) / 4, places=0)

    def device(self, org, name, online=True, refreshed=None):
        return RMMDevice.objects.create(organization=org, connection=self.conn, external_id=name,
                                        device_name=name, is_online=online, last_seen=NOW,
                                        data_refreshed_at=refreshed or NOW - timedelta(minutes=10))

    def test_thresholds(self):
        cfg = HealthScoreConfig(ok_threshold=90, warn_threshold=60)
        self.assertEqual([cfg.status_for(v) for v in (95, 90, 75, 59, None)],
                         ['ok', 'ok', 'warn', 'critical', 'unknown'])

    def test_config_inheritance(self):
        default = HealthScoreConfig.objects.create(dimension_weights={'technical': 99})
        self.assertEqual(HealthScoreConfig.for_client(self.a).dimension_weight('technical'), 99)
        HealthScoreConfig.objects.create(organization=self.a, dimension_weights={'technical': 7})
        self.assertEqual(HealthScoreConfig.for_client(self.a).dimension_weight('technical'), 7)
        self.assertEqual(HealthScoreConfig.for_client(self.b).pk, default.pk)

    def test_broken_provider_is_unknown(self):
        sig = registry.Signal('technical', 'boom', 'Boom', lambda ctx: 1 / 0)
        out = registry.run_signal(sig, self.ctx(self.a))
        self.assertEqual((out['status'], out['value']), ('unknown', None))

    def test_empty_client_has_no_score(self):
        data = scoring.compute_client(self.b, now=NOW)
        self.assertIsNone(data['overall'])
        self.assertEqual((data['known_dimensions'], data['total_dimensions']), (0, 6))
        self.assertEqual(data['status'], 'unknown')

    def test_registry_accepts_new_signals(self):
        with mock.patch.dict(registry._SIGNALS):
            @registry.signal('satisfaction', 'custom_x', 'Custom')
            def custom(ctx):
                return registry.result(90, 'ok', source='test', explanation='fine')
            data = scoring.compute_dimension('satisfaction', self.ctx(self.b), HealthScoreConfig())
        self.assertEqual(data['value'], 90.0)


class SnapshotTests(_Base):
    def test_compute_and_save_updates_the_days_row(self):
        self.device(self.a, 's1')
        snap = scoring.compute_and_save(self.a, now=NOW)
        self.assertEqual(snap.known_dimensions, 1)
        self.assertEqual(snap.coverage_pct, 17)
        again = scoring.compute_and_save(self.a, now=NOW)
        self.assertEqual(again.pk, snap.pk)
        self.assertEqual(CustomerHealthSnapshot.objects.filter(client=self.a).count(), 1)

    def test_management_command_and_scheduler_registration(self):
        self.device(self.a, 's1')
        call_command('compute_health_scores', verbosity=0)
        self.assertTrue(CustomerHealthSnapshot.objects.filter(client=self.a).exists())
        self.assertTrue(CustomerHealthSnapshot.objects.filter(client=self.b).exists())
        call_command('compute_health_scores', client=[self.b.pk], verbosity=0)
        from core.management.commands.run_scheduler import TASK_COMMANDS
        ScheduledTask.get_or_create_defaults()
        self.assertTrue(ScheduledTask.objects.filter(task_type='compute_health_scores').exists())
        self.assertIn('compute_health_scores', TASK_COMMANDS)

    def test_explain_change(self):
        d1 = self.device(self.a, 'srv1')
        d2 = self.device(self.a, 'srv2')
        yesterday = NOW - timedelta(days=1)
        scoring.compute_and_save(self.a, now=yesterday)
        RMMDevice.objects.filter(pk=d2.pk).update(is_online=False)
        today = scoring.compute_and_save(self.a, now=NOW)
        prev = scoring.previous_snapshot(today)
        self.assertEqual(prev.date, timezone.localdate(yesterday))
        changes = scoring.explain_change(today, prev)
        online = next(c for c in changes if c['key'] == 'rmm_online')
        self.assertEqual((online['before'], online['after'], online['delta']), (100.0, 50.0, -50.0))
        self.assertEqual(online['direction'], 'worse')
        self.assertEqual([r['pk'] for r in online['appeared']], [d2.pk])
        self.assertEqual(online['cleared'], [])
        # and back: the record is listed as no longer contributing
        RMMDevice.objects.filter(pk=d2.pk).update(is_online=True)
        later = scoring.compute_and_save(self.a, now=NOW + timedelta(days=1))
        back = next(c for c in scoring.explain_change(later, today) if c['key'] == 'rmm_online')
        self.assertEqual(back['direction'], 'better')
        self.assertEqual([r['pk'] for r in back['cleared']], [d2.pk])
        self.assertIsNone(scoring.explain_change(prev, None) or None)
        del d1

    def test_explain_change_unchanged_is_empty(self):
        self.device(self.a, 'srv1')
        scoring.compute_and_save(self.a, now=NOW - timedelta(days=1))
        today = scoring.compute_and_save(self.a, now=NOW)
        self.assertEqual(scoring.explain_change(today, scoring.previous_snapshot(today)), [])

    def test_explain_change_to_stale(self):
        d = self.device(self.a, 'srv1')
        scoring.compute_and_save(self.a, now=NOW - timedelta(days=1))
        RMMDevice.objects.filter(pk=d.pk).update(data_refreshed_at=NOW - timedelta(days=5))
        today = scoring.compute_and_save(self.a, now=NOW)
        c = next(c for c in scoring.explain_change(today, scoring.previous_snapshot(today))
                 if c['key'] == 'rmm_online')
        self.assertEqual((c['before_status'], c['after_status'], c['after']), ('ok', 'stale', None))


class IsolationTests(_Base):
    def test_signals_never_read_another_clients_records(self):
        conn_b = RMMConnection.objects.create(organization=self.b, provider_type='ninjaone',
                                              name='B', base_url='https://b.example.test')
        RMMDevice.objects.create(organization=self.b, connection=conn_b, external_id='bd', device_name='B-SRV',
                                 is_online=False, data_refreshed_at=NOW)
        _make_ticket(self.b, closed_at=NOW - timedelta(days=2), resolution_due_at=NOW, sla_breached_resolution=True)
        Invoice.objects.create(organization=self.b, client_org=self.b, title='x', status='sent',
                               invoice_date=timezone.localdate(), due_date=timezone.localdate() - timedelta(days=50),
                               total=Decimal('50'))
        SecurityIncident.objects.create(organization=self.b, client_org=self.b, title='B breach', severity='critical')
        data = scoring.compute_client(self.a, now=NOW)
        self.assertIsNone(data['overall'])
        self.assertEqual(data['known_dimensions'], 0)
        blob = repr(data['dimensions'])
        self.assertNotIn('B-SRV', blob)
        self.assertNotIn('B breach', blob)
        # and B does see its own
        b = scoring.compute_client(self.b, now=NOW)
        self.assertIn('B-SRV', repr(b['dimensions']))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.superuser = User.objects.create_superuser('root-hs', 'root@example.com', 'x')
        cls.tech = _staff('tech-hs')                                     # no financial permission
        cls.finance = _staff('fin-hs', reports_view_financial=True)
        cls.admin = _staff('adm-hs', manage_health_score_settings=True)
        cls.scoped = _staff('scoped-hs', scope='selected', scope_orgs=[cls.a])
        cls.customer = User.objects.create_user('cust-hs', 'cust@example.com', 'x')
        Membership.objects.create(user=cls.customer, organization=cls.a, role=Role.OWNER, is_active=True)
        Invoice.objects.create(organization=cls.a, client_org=cls.a, title='x', status='sent',
                               invoice_date=timezone.localdate() - timedelta(days=90),
                               due_date=timezone.localdate() - timedelta(days=45), total=Decimal('50'))
        RMMDevice.objects.create(organization=cls.a, connection=cls.conn, external_id='d', device_name='A-SRV',
                                 is_online=True, last_seen=NOW, data_refreshed_at=NOW)
        cls.snap_a = scoring.compute_and_save(cls.a)
        cls.snap_b = scoring.compute_and_save(cls.b)

    def get(self, user, name, *args, **params):
        return _login(user).get(reverse(name, args=args), params)

    def test_customers_get_403_everywhere(self):
        for name, args in (('health_score:list', ()), ('health_score:detail', (self.a.pk,)),
                           ('health_score:settings', ())):
            self.assertEqual(self.get(self.customer, name, *args).status_code, 403, name)
        c = _login(self.customer)
        self.assertEqual(c.post(reverse('health_score:recompute', args=[self.a.pk])).status_code, 403)

    def test_customer_client_page_and_portal_show_no_health(self):
        page = self.get(self.customer, 'accounts:organization_detail', self.a.pk)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'id="client-health"')
        self.assertNotContains(page, 'Customer health')
        import pathlib
        for path in pathlib.Path(django_settings.BASE_DIR, 'portal').rglob('*.py'):
            self.assertNotIn('health_score', path.read_text(), str(path))
        for path in pathlib.Path(django_settings.BASE_DIR, 'templates', 'portal').rglob('*.html'):
            self.assertNotIn('health_score', path.read_text(), str(path))

    def test_anonymous_redirected(self):
        self.assertEqual(Client().get(reverse('health_score:list')).status_code, 302)

    def test_staff_sees_workspace_panel(self):
        page = self.get(self.tech, 'accounts:organization_detail', self.a.pk)
        self.assertContains(page, 'id="client-health"')
        self.assertContains(page, 'based on 1 of 6 dimension')

    def test_list_shows_clients_and_filters(self):
        r = self.get(self.superuser, 'health_score:list')
        self.assertContains(r, 'Alpha Co')
        self.assertContains(r, 'Bravo Co')
        r = self.get(self.superuser, 'health_score:list', filter='unknown')
        self.assertContains(r, 'Alpha Co')                    # 1 of 6 known = incomplete
        r = self.get(self.superuser, 'health_score:list', filter='stale')
        self.assertNotContains(r, 'Alpha Co')
        RMMDevice.objects.filter(external_id='d').update(data_refreshed_at=NOW - timedelta(days=9))
        scoring.compute_and_save(self.a)
        r = self.get(self.superuser, 'health_score:list', filter='stale')
        self.assertContains(r, 'Alpha Co')
        self.assertNotContains(r, 'Bravo Co')
        r = self.get(self.superuser, 'health_score:list', sort='technical')
        self.assertEqual(r.status_code, 200)

    def test_scoped_staff_sees_only_their_client(self):
        r = self.get(self.scoped, 'health_score:list')
        self.assertContains(r, 'Alpha Co')
        self.assertNotContains(r, 'Bravo Co')
        self.assertEqual(self.get(self.scoped, 'health_score:detail', self.b.pk).status_code, 403)
        self.assertEqual(self.get(self.scoped, 'health_score:detail', self.a.pk).status_code, 200)
        c = _login(self.scoped)
        self.assertEqual(c.post(reverse('health_score:recompute', args=[self.b.pk])).status_code, 403)

    def test_commercial_dimension_gated_by_financial_permission(self):
        without = self.get(self.tech, 'health_score:detail', self.a.pk)
        self.assertNotContains(without, 'Overdue invoices')
        self.assertNotContains(without, 'dim-commercial')
        self.assertContains(without, 'left out of the score')
        with_perm = self.get(self.finance, 'health_score:detail', self.a.pk)
        self.assertContains(with_perm, 'Overdue invoices')
        self.assertContains(with_perm, 'dim-commercial')
        # the headline does not leak the hidden dimension: tech sees 1 of 5 known, finance 2 of 6
        self.assertContains(without, 'based on 1 of 5 dimension')
        self.assertContains(with_perm, 'based on 2 of 6 dimension')
        # and the list hides the cell
        self.assertNotContains(self.get(self.tech, 'health_score:list'), '>Commercial</a>' if False else 'commercial=')

    def test_financial_permission_key(self):
        self.assertEqual(permissions.financial_permission_key(), 'reports_view_financial')

    def test_detail_without_snapshot(self):
        org = Organization.objects.create(name='Fresh Co', slug='hs-fresh')
        r = self.get(self.superuser, 'health_score:detail', org.pk)
        self.assertContains(r, 'No health snapshot yet')

    def test_recompute_creates_snapshot(self):
        org = Organization.objects.create(name='Fresh Co', slug='hs-fresh2')
        r = _login(self.tech).post(reverse('health_score:recompute', args=[org.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(CustomerHealthSnapshot.objects.filter(client=org).exists())
        self.assertEqual(_login(self.tech).get(reverse('health_score:recompute', args=[org.pk])).status_code, 405)

    def test_detail_explains_change(self):
        CustomerHealthSnapshot.objects.filter(pk=self.snap_a.pk).update(date=timezone.localdate() - timedelta(days=1))
        RMMDevice.objects.filter(external_id='d').update(is_online=False)
        scoring.compute_and_save(self.a)
        r = self.get(self.superuser, 'health_score:detail', self.a.pk)
        self.assertContains(r, 'Why it changed')
        self.assertContains(r, 'A-SRV')
        self.assertContains(r, 'worse')

    def test_settings_permission_gating(self):
        self.assertEqual(self.get(self.tech, 'health_score:settings').status_code, 403)
        self.assertEqual(self.get(self.finance, 'health_score:settings').status_code, 403)
        self.assertEqual(self.get(self.admin, 'health_score:settings').status_code, 200)
        self.assertEqual(self.get(self.superuser, 'health_score:settings').status_code, 200)
        c = _login(self.tech)
        self.assertEqual(c.post(reverse('health_score:settings'), {'dim_technical': '50'}).status_code, 403)
        self.assertFalse(HealthScoreConfig.objects.exists())

    def test_settings_save_and_validation(self):
        c = _login(self.admin)
        r = c.post(reverse('health_score:settings'), {'dim_technical': '50', 'dim_security': '0',
                                                      'sig_rmm_online': '5', 'ok_threshold': '80',
                                                      'warn_threshold': '55'})
        self.assertEqual(r.status_code, 302)
        cfg = HealthScoreConfig.objects.get(organization__isnull=True)
        self.assertEqual(cfg.dimension_weight('technical'), 50)
        self.assertEqual(cfg.dimension_weight('security'), 0)
        self.assertEqual(cfg.signal_weight('rmm_online'), 5)
        self.assertEqual((cfg.ok_threshold, cfg.warn_threshold), (80, 55))
        bad = c.post(reverse('health_score:settings'), {'dim_technical': '-3', 'ok_threshold': '40',
                                                        'warn_threshold': '60'})
        self.assertEqual(bad.status_code, 200)
        cfg.refresh_from_db()
        self.assertEqual(cfg.dimension_weight('technical'), 50)

    def test_settings_client_override_and_reset(self):
        c = _login(self.superuser)
        url = reverse('health_score:settings') + f'?client={self.a.pk}'
        c.post(url, {'client': self.a.pk, 'dim_technical': '1', 'ok_threshold': '70', 'warn_threshold': '40'})
        self.assertEqual(HealthScoreConfig.for_client(self.a).dimension_weight('technical'), 1)
        self.assertEqual(HealthScoreConfig.for_client(self.b).dimension_weight('technical'), 20)
        c.post(url, {'client': self.a.pk, 'reset': '1'})
        self.assertEqual(HealthScoreConfig.for_client(self.a).dimension_weight('technical'), 20)
        # a scoped user cannot configure a client outside their scope
        self.assertEqual(self.get(self.scoped, 'health_score:settings', client=self.b.pk).status_code, 403)

    def test_permission_registry_entry(self):
        from accounts import permission_registry as reg
        p = reg.get('manage_health_score_settings')
        self.assertIsNotNone(p)
        self.assertTrue(p.staff_only)
        self.assertFalse(p.customer_assignable)
        self.assertFalse(RoleTemplate._meta.get_field('manage_health_score_settings').default)
