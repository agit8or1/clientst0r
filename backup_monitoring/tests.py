"""Backup monitoring: providers, ingest, alert rules, restore tests,
tenant isolation, permissions and views."""
import json
import time
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleTemplate
from assets.models import Asset
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech

from . import ingest as ingest_mod
from .alerts import evaluate_connection
from .health import connection_freshness, job_rows, restore_test_summary
from .models import (BackupAlert, BackupAlertPolicy, BackupConnection, BackupJob, BackupRepository, BackupRun,
                     ProtectedSystem, RestoreTest)
from .providers import BACKUP_PROVIDER_REGISTRY, ProviderError, get_backup_provider
from .providers.pbs import ProxmoxBackupServerProvider
from .recording import ensure_job, poll_connection, record_repository, record_run
from .summary import asset_backup_panel

ROLE_VIEW = dict(view_backup_status=True)
ROLE_MANAGE = dict(view_backup_status=True, manage_backup_integrations=True)


def make_staff(username, role_name, scope_orgs=None, **flags):
    user = _make_msp_tech(User.objects.create_user(username, f'{username}@x.com', 'pw'))
    role = RoleTemplate.objects.create(name=role_name, **flags)
    profile = user.profile
    profile.global_role_template = role
    if scope_orgs is not None:
        profile.client_scope = 'selected'
    profile.save()
    if scope_orgs is not None:
        profile.scope_organizations.set(scope_orgs)
    return user


def make_pbs(org, name='pbs-1', **kw):
    conn = BackupConnection(organization=org, provider='pbs', name=name,
                            base_url='https://pbs.example.com:8007', **kw)
    conn.set_credentials({'api_token': 'root@pam!mon:s3cret'})
    conn.save()
    return conn


def make_push(org, provider='restic', name='restic-1'):
    conn = BackupConnection(organization=org, provider=provider, name=name)
    secret = conn.issue_ingest_secret()
    conn.save()
    return conn, secret


def make_job(conn, ext='job-1', success_ago_h=1, status='success', runs=1, org=None, name=None):
    now = timezone.now()
    job = ensure_job(conn, ext, name or ext, system_external_id=f'sys-{ext}', system_name=f'sys-{ext}')
    if org is not None:
        job.organization = org
        job.save()
    for i in range(runs):
        started = now - timedelta(hours=success_ago_h + (runs - 1 - i))
        record_run(job, f'{ext}-run-{i}', started, status, started + timedelta(minutes=5))
    job.refresh_from_db()
    return job


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='Cust A', slug='bm-a')
        cls.org_b = Organization.objects.create(name='Cust B', slug='bm-b')


# ---------------------------------------------------------------- providers

class FakeResp:
    def __init__(self, data=None, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return {'data': self._data}


class PBSProviderTests(Fixture):
    def setUp(self):
        self.conn = make_pbs(self.org_a)
        self.calls = []
        start = int(time.time()) - 3600
        self.routes = {
            '/version': {'version': '3.2.1', 'release': '1'},
            '/status/datastore-usage': [
                {'store': 'main', 'total': 1000, 'used': 900, 'avail': 100},
                {'store': 'broken', 'total': 0, 'used': 0, 'avail': 0, 'error': 'datastore is not mounted'}],
            '/config/prune': [{'store': 'main', 'keep-daily': 7, 'keep-weekly': 4}],
            '/admin/datastore/main/groups': [
                {'backup-type': 'vm', 'backup-id': '100', 'comment': 'web01', 'last-backup': start,
                 'backup-count': 3}],
            '/admin/datastore/main/snapshots': [
                {'backup-type': 'vm', 'backup-id': '100', 'backup-time': start, 'size': 5000,
                 'verification': {'state': 'ok'}},
                {'backup-type': 'vm', 'backup-id': '100', 'backup-time': start + 900, 'size': 6000,
                 'verification': {'state': 'failed'}}],
            '/nodes/localhost/tasks': [
                {'upid': 'UPID:ok', 'worker_type': 'backup', 'worker_id': 'main:vm/100',
                 'starttime': start, 'endtime': start + 60, 'status': 'OK'},
                {'upid': 'UPID:verifyfail', 'worker_type': 'backup', 'worker_id': 'main:vm/100',
                 'starttime': start + 900, 'endtime': start + 960, 'status': 'OK'},
                {'upid': 'UPID:warn', 'worker_type': 'backup', 'worker_id': 'main:vm/100',
                 'starttime': start + 2000, 'endtime': start + 2060, 'status': 'WARNINGS: 2'},
                {'upid': 'UPID:fail', 'worker_type': 'backup', 'worker_id': 'main:vm/100',
                 'starttime': start + 3000, 'endtime': start + 3030, 'status': 'unable to open chunk store'},
                {'upid': 'UPID:run', 'worker_type': 'backup', 'worker_id': 'main:vm/100',
                 'starttime': start + 3500},
                {'upid': 'UPID:gc', 'worker_type': 'garbage_collection', 'worker_id': 'main',
                 'starttime': start, 'endtime': start + 5, 'status': 'OK'}],
        }
        self.start = start

    def _get(self, url, headers=None, params=None, timeout=None, verify=None):
        path = url.split('/api2/json', 1)[1]
        self.calls.append((path, headers, params, verify))
        return FakeResp(self.routes[path])

    def _patch(self):
        return mock.patch('backup_monitoring.providers.pbs.requests.get', side_effect=self._get)

    def test_registry_has_only_real_providers(self):
        self.assertEqual(set(BACKUP_PROVIDER_REGISTRY), {'pbs', 'restic', 'borg', 'kopia'})
        self.assertIsInstance(get_backup_provider(self.conn), ProxmoxBackupServerProvider)

    def test_auth_header_and_test_connection(self):
        with self._patch():
            result = ProxmoxBackupServerProvider(self.conn).test_connection()
        self.assertTrue(result['ok'])
        self.assertIn('3.2.1', result['message'])
        self.assertEqual(self.calls[0][1]['Authorization'], 'PBSAPIToken=root@pam!mon:s3cret')
        self.assertIs(self.calls[0][3], True)

    def test_repositories_capacity_and_unavailable(self):
        with self._patch():
            repos = {r.external_id: r for r in ProxmoxBackupServerProvider(self.conn).list_repositories()}
        self.assertEqual((repos['main'].total_bytes, repos['main'].used_bytes), (1000, 900))
        self.assertTrue(repos['main'].available)
        self.assertFalse(repos['broken'].available)
        self.assertIn('not mounted', repos['broken'].message)

    def test_jobs_have_retention_and_system(self):
        with self._patch():
            jobs = ProxmoxBackupServerProvider(self.conn).list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].external_id, 'main:vm/100')
        self.assertEqual(jobs[0].system_name, 'web01')
        self.assertIn('daily 7', jobs[0].retention)

    def test_runs_status_mapping_and_sizes(self):
        with self._patch():
            runs = {r.external_id: r for r in ProxmoxBackupServerProvider(self.conn).list_runs(
                timezone.now() - timedelta(days=1))}
        self.assertNotIn('UPID:gc', runs)
        self.assertEqual(runs['UPID:ok'].status, 'success')
        self.assertEqual(runs['UPID:ok'].bytes_processed, 5000)
        self.assertEqual(runs['UPID:verifyfail'].status, 'warning')   # snapshot verification failed
        self.assertEqual(runs['UPID:warn'].status, 'warning')
        self.assertEqual(runs['UPID:fail'].status, 'failed')
        self.assertIn('chunk store', runs['UPID:fail'].message)
        self.assertEqual(runs['UPID:run'].status, 'running')
        params = [c for c in self.calls if c[0] == '/nodes/localhost/tasks'][0][2]
        self.assertEqual(params['typefilter'], 'backup')

    def test_auth_failure_is_provider_error(self):
        with mock.patch('backup_monitoring.providers.pbs.requests.get', return_value=FakeResp(None, 401)):
            result = ProxmoxBackupServerProvider(self.conn).test_connection()
            self.assertFalse(result['ok'])
            with self.assertRaises(ProviderError):
                ProxmoxBackupServerProvider(self.conn).list_repositories()

    def test_poll_records_everything_and_is_idempotent(self):
        with self._patch():
            r1 = poll_connection(self.conn)
            r2 = poll_connection(self.conn)
        self.assertTrue(r1['ok'])
        self.assertEqual(r1['runs'], 5)
        self.assertEqual(r2['runs'], 0)
        self.assertEqual(BackupRun.objects.count(), 5)
        job = BackupJob.objects.get()
        self.assertEqual(job.last_status, 'running')
        self.assertIsNotNone(job.last_success_at)
        self.assertEqual(BackupRepository.objects.count(), 2)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_poll_status, 'ok')
        self.assertIsNotNone(self.conn.last_poll_at)

    def test_failed_poll_does_not_advance_last_poll_at(self):
        with self._patch():
            poll_connection(self.conn)
        self.conn.refresh_from_db()
        good = self.conn.last_poll_at
        with mock.patch('backup_monitoring.providers.pbs.requests.get', return_value=FakeResp(None, 500)):
            result = poll_connection(self.conn)
        self.assertFalse(result['ok'])
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_poll_status, 'error')
        self.assertEqual(self.conn.last_poll_at, good)
        self.assertIn('HTTP 500', self.conn.last_poll_error)

    def test_credentials_are_sealed_at_rest(self):
        raw = BackupConnection.objects.filter(pk=self.conn.pk).values_list('credentials', flat=True)[0]
        self.assertTrue(raw.startswith('enc2$'))
        self.assertNotIn('s3cret', raw)
        self.assertEqual(self.conn.get_credentials()['api_token'], 'root@pam!mon:s3cret')


# ------------------------------------------------------------------- ingest

def signed_post(client, conn, secret, payload, ts=None, signature=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    ts = str(ts if ts is not None else int(time.time()))
    sig = signature if signature is not None else ingest_mod.sign(secret, ts, body)
    return client.post(reverse('backup_monitoring:ingest', args=[conn.ingest_id]), data=body,
                       content_type='application/json', HTTP_X_BACKUP_TIMESTAMP=ts, HTTP_X_BACKUP_SIGNATURE=sig)


def report(run_id='r1', status='success', **extra):
    started = timezone.now() - timedelta(minutes=10)
    data = {'job': {'id': 'nightly', 'name': 'Nightly home', 'schedule': 'daily 02:00',
                    'retention': 'keep-daily 7'},
            'system': {'id': 'host1', 'name': 'host1'},
            'run': {'id': run_id, 'status': status, 'started_at': started.isoformat(),
                    'finished_at': (started + timedelta(minutes=3)).isoformat(), 'bytes': 12345,
                    'message': ''}}
    data.update(extra)
    return data


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class IngestTests(Fixture):
    def setUp(self):
        self.conn, self.secret = make_push(self.org_a)
        self.client = Client()

    def test_valid_report_creates_job_system_and_run(self):
        r = signed_post(self.client, self.conn, self.secret, report())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['run'], 'created')
        run = BackupRun.objects.get()
        self.assertEqual((run.status, run.bytes_processed, run.duration_seconds), ('success', 12345, 180))
        job = BackupJob.objects.get()
        self.assertEqual(job.retention, 'keep-daily 7')
        self.assertEqual(job.system.name, 'host1')
        self.assertEqual(job.organization, self.org_a)
        self.conn.refresh_from_db()
        self.assertIsNotNone(self.conn.last_ingest_at)

    def test_bad_signature_rejected_and_nothing_stored(self):
        r = signed_post(self.client, self.conn, 'wrong-secret', report())
        self.assertEqual(r.status_code, 401)
        r = signed_post(self.client, self.conn, self.secret, report(), signature='sha256=' + '0' * 64)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(BackupRun.objects.count(), 0)

    def test_tampered_body_rejected(self):
        body = json.dumps(report()).encode()
        ts = str(int(time.time()))
        sig = ingest_mod.sign(self.secret, ts, body)
        r = signed_post(self.client, self.conn, self.secret, None, ts=ts, signature=sig,
                        raw=body.replace(b'success', b'failed'))
        self.assertEqual(r.status_code, 401)

    def test_missing_headers_and_old_timestamp_rejected(self):
        url = reverse('backup_monitoring:ingest', args=[self.conn.ingest_id])
        self.assertEqual(self.client.post(url, data='{}', content_type='application/json').status_code, 401)
        old = int(time.time()) - 3600
        self.assertEqual(signed_post(self.client, self.conn, self.secret, report(), ts=old).status_code, 401)

    def test_replay_is_deduplicated(self):
        body = report(run_id='same')
        ts = int(time.time())
        first = signed_post(self.client, self.conn, self.secret, body, ts=ts)
        second = signed_post(self.client, self.conn, self.secret, body, ts=ts)
        self.assertEqual(first.json()['status'], 'ok')
        self.assertEqual(second.json()['status'], 'duplicate')
        self.assertEqual(BackupRun.objects.count(), 1)

    def test_replayed_run_id_cannot_overwrite_a_final_result(self):
        signed_post(self.client, self.conn, self.secret, report(run_id='x', status='failed'))
        signed_post(self.client, self.conn, self.secret, report(run_id='x', status='success'))
        self.assertEqual(BackupRun.objects.get().status, 'failed')

    def test_running_run_is_finalised_by_second_report(self):
        signed_post(self.client, self.conn, self.secret, report(run_id='y', status='running'))
        r = signed_post(self.client, self.conn, self.secret, report(run_id='y', status='success'))
        self.assertEqual(r.json()['run'], 'updated')
        self.assertEqual(BackupRun.objects.get().status, 'success')

    def test_validation_errors(self):
        bad_status = report()
        bad_status['run']['status'] = 'great'
        for payload in (bad_status, {'job': {}, 'run': {'id': 'a'}}, {'unrelated': 1}, [1, 2]):
            r = signed_post(self.client, self.conn, self.secret, payload)
            self.assertEqual(r.status_code, 400, payload)
        r = signed_post(self.client, self.conn, self.secret, None, raw=b'not json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(BackupRun.objects.count(), 0)

    def test_repository_report(self):
        payload = {'repository': {'id': 'repo1', 'name': 'B2 bucket', 'total_bytes': 100, 'used_bytes': 40}}
        r = signed_post(self.client, self.conn, self.secret, payload)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(BackupRepository.objects.get().used_pct, 40.0)

    def test_unknown_inactive_and_non_push_connections_get_401(self):
        import uuid
        url = reverse('backup_monitoring:ingest', args=[uuid.uuid4()])
        self.assertEqual(self.client.post(url, data='{}', content_type='application/json').status_code, 401)
        self.conn.active = False
        self.conn.save()
        self.assertEqual(signed_post(self.client, self.conn, self.secret, report()).status_code, 401)
        pbs = make_pbs(self.org_a)
        self.assertEqual(signed_post(self.client, pbs, 'x', report()).status_code, 401)

    def test_get_not_allowed_and_oversize_rejected(self):
        url = reverse('backup_monitoring:ingest', args=[self.conn.ingest_id])
        self.assertEqual(self.client.get(url).status_code, 405)
        big = b'{"x": "' + b'a' * (ingest_mod.MAX_BODY_BYTES + 10) + b'"}'
        r = signed_post(self.client, self.conn, self.secret, None, raw=big)
        self.assertEqual(r.status_code, 413)

    def test_secret_is_sealed_and_rotation_invalidates_old(self):
        raw = BackupConnection.objects.filter(pk=self.conn.pk).values_list('ingest_secret', flat=True)[0]
        self.assertTrue(raw.startswith('enc2$'))
        self.conn.issue_ingest_secret()
        self.conn.save()
        self.assertEqual(signed_post(self.client, self.conn, self.secret, report()).status_code, 401)

    def test_ingest_evaluates_alerts(self):
        signed_post(self.client, self.conn, self.secret, report(run_id='f1', status='failed'))
        self.assertTrue(BackupAlert.objects.filter(kind='failed', status='open').exists())


# ------------------------------------------------------------- alert rules

class AlertRuleTests(Fixture):
    def setUp(self):
        self.conn, _ = make_push(self.org_a)
        self.now = timezone.now()

    def kinds(self):
        return set(BackupAlert.objects.filter(status__in=['open', 'acknowledged']).values_list('kind', flat=True))

    def test_healthy_job_raises_nothing(self):
        make_job(self.conn)
        evaluate_connection(self.conn)
        self.assertEqual(self.kinds(), set())

    def test_missed_after_threshold(self):
        make_job(self.conn, success_ago_h=30)
        evaluate_connection(self.conn)
        self.assertIn('missed', self.kinds())
        alert = BackupAlert.objects.get(kind='missed')
        self.assertEqual(alert.severity, 'critical')
        self.assertEqual(alert.organization, self.org_a)

    def test_missed_threshold_is_policy_driven(self):
        make_job(self.conn, success_ago_h=30)
        BackupAlertPolicy.objects.create(organization=self.org_a, missed_threshold_hours=48)
        evaluate_connection(self.conn)
        self.assertNotIn('missed', self.kinds())

    def test_job_interval_override(self):
        job = make_job(self.conn, success_ago_h=10)
        job.expected_interval_hours = 6
        job.save()
        evaluate_connection(self.conn)
        self.assertIn('missed', self.kinds())

    def test_failed_latest_run(self):
        job = make_job(self.conn, success_ago_h=3)
        record_run(job, 'bad', self.now - timedelta(hours=1), 'failed', self.now - timedelta(minutes=50),
                   message='disk full')
        evaluate_connection(self.conn)
        self.assertEqual(self.kinds(), {'failed'})
        self.assertIn('disk full', BackupAlert.objects.get().detail)

    def test_repeated_failures_default_two(self):
        job = make_job(self.conn, success_ago_h=5)
        for i in range(2):
            record_run(job, f'bad{i}', self.now - timedelta(hours=2 - i), 'failed')
        evaluate_connection(self.conn)
        self.assertEqual(self.kinds(), {'failed', 'repeated_failures'})

    def test_single_failure_is_not_repeated(self):
        job = make_job(self.conn, success_ago_h=5)
        record_run(job, 'bad', self.now - timedelta(hours=1), 'failed')
        evaluate_connection(self.conn)
        self.assertNotIn('repeated_failures', self.kinds())

    def test_capacity_threshold_and_severity(self):
        record_repository(self.conn, 'r1', 'Repo', 100, 86)
        record_repository(self.conn, 'r2', 'Full', 100, 97)
        record_repository(self.conn, 'r3', 'Fine', 100, 10)
        evaluate_connection(self.conn)
        alerts = {a.repository.name: a for a in BackupAlert.objects.filter(kind='capacity')}
        self.assertEqual(set(alerts), {'Repo', 'Full'})
        self.assertEqual(alerts['Repo'].severity, 'warning')
        self.assertEqual(alerts['Full'].severity, 'critical')

    def test_repository_unavailable(self):
        record_repository(self.conn, 'r1', 'Gone', None, None, available=False, message='not mounted')
        evaluate_connection(self.conn)
        self.assertIn('repo_unavailable', self.kinds())

    def test_protected_system_without_job(self):
        from .recording import ensure_system
        ensure_system(self.conn, 'lonely', 'lonely-host')
        evaluate_connection(self.conn)
        self.assertEqual(self.kinds(), {'no_job'})
        BackupAlertPolicy.objects.create(organization=self.org_a, alert_missing_protected_device=False)
        BackupAlert.objects.all().delete()
        evaluate_connection(self.conn)
        self.assertEqual(self.kinds(), set())

    def test_dedup_updates_one_live_alert(self):
        make_job(self.conn, success_ago_h=40)
        evaluate_connection(self.conn)
        evaluate_connection(self.conn)
        self.assertEqual(BackupAlert.objects.count(), 1)
        self.assertEqual(BackupAlert.objects.get().occurrences, 2)

    def test_auto_resolve_when_condition_clears_and_reopen_is_new_row(self):
        job = make_job(self.conn, success_ago_h=40)
        evaluate_connection(self.conn)
        record_run(job, 'fresh', self.now - timedelta(minutes=5), 'success', self.now)
        evaluate_connection(self.conn)
        self.assertEqual(BackupAlert.objects.get().status, 'resolved')
        self.assertIsNotNone(BackupAlert.objects.get().resolved_at)
        BackupRun.objects.filter(external_id='fresh').delete()
        refresh = BackupJob.objects.get()
        from .recording import refresh_job_summary
        refresh_job_summary(refresh)
        evaluate_connection(self.conn)
        self.assertEqual(BackupAlert.objects.count(), 2)

    def test_acknowledged_alert_stays_deduplicated(self):
        make_job(self.conn, success_ago_h=40)
        evaluate_connection(self.conn)
        BackupAlert.objects.update(status='acknowledged')
        evaluate_connection(self.conn)
        self.assertEqual(BackupAlert.objects.count(), 1)

    def test_stale_connection_raises_only_stale_and_keeps_others(self):
        pbs = make_pbs(self.org_a)
        job = make_job(pbs, success_ago_h=40)
        pbs.last_poll_at = self.now - timedelta(hours=1)
        pbs.last_poll_status = 'ok'
        pbs.save()
        evaluate_connection(pbs)
        self.assertEqual(self.kinds(), {'missed'})
        pbs.last_poll_at = self.now - timedelta(hours=5)
        pbs.save()
        evaluate_connection(pbs)
        self.assertEqual(self.kinds(), {'missed', 'stale'})   # missed not resolved on stale evidence
        self.assertEqual(BackupAlert.objects.get(kind='stale').organization, self.org_a)
        pbs.last_poll_at = self.now
        pbs.save()
        evaluate_connection(pbs)
        self.assertEqual(BackupAlert.objects.get(kind='stale').status, 'resolved')
        self.assertTrue(job)

    def test_stale_does_not_open_new_job_alerts(self):
        pbs = make_pbs(self.org_a)
        make_job(pbs, success_ago_h=40)
        pbs.last_poll_at = self.now - timedelta(hours=9)
        pbs.last_poll_status = 'ok'
        pbs.save()
        evaluate_connection(pbs)
        self.assertEqual(self.kinds(), {'stale'})

    def test_never_polled_connection_is_silent(self):
        pbs = make_pbs(self.org_a)
        evaluate_connection(pbs)
        self.assertEqual(BackupAlert.objects.count(), 0)

    def test_inactive_connection_not_evaluated(self):
        make_job(self.conn, success_ago_h=40)
        self.conn.active = False
        self.conn.save()
        evaluate_connection(self.conn)
        self.assertEqual(BackupAlert.objects.count(), 0)


class HealthTests(Fixture):
    def test_stale_and_unknown_are_never_ok(self):
        pbs = make_pbs(self.org_a)
        job = make_job(pbs, success_ago_h=1)
        self.assertEqual(job_rows([BackupJob.objects.select_related('connection', 'organization').get()])[0]['state'],
                         'stale')                       # never polled: no contact recorded -> not healthy
        pbs.last_poll_at, pbs.last_poll_status = timezone.now(), 'ok'
        pbs.save()
        job = BackupJob.objects.select_related('connection', 'organization').get()
        self.assertEqual(job_rows([job])[0]['state'], 'ok')
        pbs.last_poll_at = timezone.now() - timedelta(hours=6)
        pbs.save()
        job = BackupJob.objects.select_related('connection', 'organization').get()
        row = job_rows([job])[0]
        self.assertEqual(row['state'], 'stale')
        self.assertEqual(row['badge'], 'warning')
        self.assertIn('h ago', row['data_age'])

    def test_job_with_no_runs_is_unknown(self):
        conn, _ = make_push(self.org_a)
        conn.last_poll_at, conn.last_poll_status = timezone.now(), 'ok'
        conn.save()
        ensure_job(conn, 'empty', 'empty')
        job = BackupJob.objects.select_related('connection', 'organization').get()
        self.assertEqual(job_rows([job])[0]['state'], 'unknown')

    def test_warning_run_counts_as_completed_but_shows_warning(self):
        conn, _ = make_push(self.org_a)
        conn.last_poll_at = timezone.now()
        conn.save()
        make_job(conn, status='warning')
        job = BackupJob.objects.select_related('connection', 'organization').get()
        self.assertEqual(job_rows([job])[0]['state'], 'warning')

    def test_freshness_of_push_connection(self):
        conn, _ = make_push(self.org_a)
        self.assertEqual(connection_freshness(conn)[0], 'never')


class RestoreTestSeparationTests(Fixture):
    def test_successful_backups_do_not_count_as_restore_tests(self):
        conn, _ = make_push(self.org_a)
        conn.last_poll_at = timezone.now()
        conn.save()
        make_job(conn, runs=5)
        self.assertEqual(RestoreTest.objects.count(), 0)
        summary = restore_test_summary([], BackupAlertPolicy.for_org(self.org_a))
        self.assertEqual(summary['state'], 'none')
        self.assertEqual(summary['label'], 'Never tested')

    def test_restore_results_do_not_change_backup_health(self):
        conn, _ = make_push(self.org_a)
        conn.last_poll_at = timezone.now()
        conn.save()
        job = make_job(conn)
        RestoreTest.objects.create(organization=self.org_a, system_name='x', tested_on=timezone.now().date(),
                                   result='failed')
        job = BackupJob.objects.select_related('connection', 'organization').get(pk=job.pk)
        self.assertEqual(job_rows([job])[0]['state'], 'ok')
        evaluate_connection(conn)
        self.assertEqual(BackupAlert.objects.count(), 0)

    def test_restore_summary_states(self):
        policy = BackupAlertPolicy(restore_test_max_age_days=100)
        today = timezone.now().date()

        def t(days, result):
            return RestoreTest(organization=self.org_a, tested_on=today - timedelta(days=days), result=result)
        self.assertEqual(restore_test_summary([t(5, 'passed')], policy)['state'], 'ok')
        self.assertEqual(restore_test_summary([t(150, 'passed')], policy)['state'], 'overdue')
        self.assertEqual(restore_test_summary([t(5, 'failed')], policy)['state'], 'failed')
        self.assertEqual(restore_test_summary([t(5, 'partial')], policy)['badge'], 'warning')


# --------------------------------------------------------------------- views

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(Fixture):
    def setUp(self):
        self.staff_a = make_staff('bm-staff-a', 'bm manage A', scope_orgs=[self.org_a], **ROLE_MANAGE)
        self.viewer_a = make_staff('bm-viewer-a', 'bm view A', scope_orgs=[self.org_a], **ROLE_VIEW)
        self.nobody = make_staff('bm-none', 'bm none', scope_orgs=[self.org_a])
        self.admin = User.objects.create_superuser('bm-root', 'r@x.com', 'pw')
        self.conn_a = make_pbs(self.org_a, 'conn-a')
        self.conn_b = make_pbs(self.org_b, 'conn-b')
        for c in (self.conn_a, self.conn_b):
            c.last_poll_at, c.last_poll_status = timezone.now(), 'ok'
            c.save()
        self.job_a = make_job(self.conn_a, 'ja', name='JobA')
        self.job_b = make_job(self.conn_b, 'jb', name='JobB')
        record_repository(self.conn_a, 'ra', 'RepoA', 100, 50)
        record_repository(self.conn_b, 'rb', 'RepoB', 100, 50)
        self.alert_b = BackupAlert.objects.create(
            organization=self.org_b, connection=self.conn_b, kind='failed', title='B alert', dedup_key='k')
        self.alert_a = BackupAlert.objects.create(
            organization=self.org_a, connection=self.conn_a, kind='failed', title='A alert', dedup_key='k')

    def client_for(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()
        return c

    # permissions
    def test_user_without_flag_is_forbidden_everywhere(self):
        c = self.client_for(self.nobody)
        for name in ('dashboard', 'alert_list', 'restore_test_list', 'connection_list', 'connection_create',
                     'restore_test_create'):
            self.assertEqual(c.get(reverse(f'backup_monitoring:{name}')).status_code, 403, name)

    def test_viewer_can_read_but_not_manage(self):
        c = self.client_for(self.viewer_a)
        self.assertEqual(c.get(reverse('backup_monitoring:dashboard')).status_code, 200)
        self.assertEqual(c.get(reverse('backup_monitoring:alert_list')).status_code, 200)
        self.assertEqual(c.get(reverse('backup_monitoring:restore_test_list')).status_code, 200)
        self.assertEqual(c.get(reverse('backup_monitoring:connection_list')).status_code, 403)
        self.assertEqual(c.get(reverse('backup_monitoring:connection_create')).status_code, 403)
        self.assertEqual(c.get(reverse('backup_monitoring:restore_test_create')).status_code, 403)
        r = c.post(reverse('backup_monitoring:alert_decide', args=[self.alert_a.pk]), {'decision': 'acknowledge'})
        self.assertEqual(r.status_code, 403)
        self.alert_a.refresh_from_db()
        self.assertEqual(self.alert_a.status, 'open')

    def test_customer_portal_user_is_refused(self):
        from accounts.models import Membership, Role
        cust = User.objects.create_user('bm-cust', 'c@x.com', 'pw')
        role = RoleTemplate.objects.create(name='bm cust', **ROLE_MANAGE)
        Membership.objects.create(user=cust, organization=self.org_a, role=Role.OWNER, role_template=role)
        c = self.client_for(cust, self.org_a)
        self.assertEqual(c.get(reverse('backup_monitoring:dashboard')).status_code, 403)
        self.assertEqual(c.get(reverse('backup_monitoring:connection_list')).status_code, 403)

    def test_anonymous_is_redirected(self):
        r = Client().get(reverse('backup_monitoring:dashboard'))
        self.assertIn(r.status_code, (302, 401))

    # isolation
    def test_dashboard_shows_only_own_customer(self):
        r = self.client_for(self.staff_a).get(reverse('backup_monitoring:dashboard'))
        self.assertContains(r, 'Cust A')
        self.assertNotContains(r, 'Cust B')
        self.assertNotContains(r, 'RepoB')

    def test_superuser_sees_both(self):
        r = self.client_for(self.admin).get(reverse('backup_monitoring:dashboard') + '?customer=all')
        self.assertContains(r, 'Cust A')
        self.assertContains(r, 'Cust B')

    def test_other_customers_records_are_404(self):
        c = self.client_for(self.staff_a)
        self.assertEqual(c.get(reverse('backup_monitoring:customer_detail', args=[self.org_b.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('backup_monitoring:job_detail', args=[self.job_b.pk])).status_code, 404)
        self.assertEqual(c.get(reverse('backup_monitoring:job_detail', args=[self.job_a.pk])).status_code, 200)
        self.assertEqual(c.get(reverse('backup_monitoring:connection_edit', args=[self.conn_b.pk])).status_code, 404)
        for name in ('connection_test', 'connection_poll', 'connection_delete'):
            r = c.post(reverse(f'backup_monitoring:{name}', args=[self.conn_b.pk]))
            self.assertEqual(r.status_code, 404, name)
        self.assertTrue(BackupConnection.objects.filter(pk=self.conn_b.pk).exists())
        r = c.post(reverse('backup_monitoring:alert_decide', args=[self.alert_b.pk]), {'decision': 'resolve'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(c.get(reverse('backup_monitoring:policy_edit', args=[self.org_b.pk])).status_code, 404)

    def test_lists_exclude_other_customers(self):
        c = self.client_for(self.staff_a)
        self.assertContains(c.get(reverse('backup_monitoring:alert_list')), 'A alert')
        self.assertNotContains(c.get(reverse('backup_monitoring:alert_list')), 'B alert')
        r = c.get(reverse('backup_monitoring:connection_list'))
        self.assertContains(r, 'conn-a')
        self.assertNotContains(r, 'conn-b')

    def test_customer_scoping_within_one_owner(self):
        """A connection owned by org A that reports a system for customer B:
        B's data is visible to B's staff only."""
        system = ProtectedSystem.objects.get(connection=self.conn_a)
        system.customer = self.org_b
        system.save()
        self.job_a.organization = self.org_b
        self.job_a.save()
        staff_b = make_staff('bm-staff-b', 'bm manage B', scope_orgs=[self.org_b], **ROLE_MANAGE)
        self.assertEqual(self.client_for(staff_b).get(
            reverse('backup_monitoring:job_detail', args=[self.job_a.pk])).status_code, 200)
        self.assertEqual(self.client_for(self.staff_a).get(
            reverse('backup_monitoring:job_detail', args=[self.job_a.pk])).status_code, 404)

    # connection CRUD
    def test_create_pbs_connection_seals_token_and_never_echoes_it(self):
        c = self.client_for(self.staff_a)
        r = c.post(reverse('backup_monitoring:connection_create'), {
            'name': 'New PBS', 'provider': 'pbs', 'organization': self.org_a.pk,
            'base_url': 'https://pbs2.example.com:8007', 'verify_tls': 'on', 'active': 'on',
            'api_token': 'u@pbs!t:topsecret'})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        conn = BackupConnection.objects.get(name='New PBS')
        self.assertEqual(conn.get_credentials()['api_token'], 'u@pbs!t:topsecret')
        r = c.get(reverse('backup_monitoring:connection_edit', args=[conn.pk]))
        self.assertNotContains(r, 'topsecret')

    def test_pbs_requires_https_and_token(self):
        c = self.client_for(self.staff_a)
        r = c.post(reverse('backup_monitoring:connection_create'), {
            'name': 'bad', 'provider': 'pbs', 'organization': self.org_a.pk, 'base_url': 'http://x', 'active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(BackupConnection.objects.filter(name='bad').exists())

    def test_create_push_connection_shows_secret_once(self):
        c = self.client_for(self.staff_a)
        r = c.post(reverse('backup_monitoring:connection_create'), {
            'name': 'Borg box', 'provider': 'borg', 'organization': self.org_a.pk, 'active': 'on'})
        self.assertEqual(r.status_code, 200)
        conn = BackupConnection.objects.get(name='Borg box')
        self.assertContains(r, 'data-issued-secret')
        self.assertContains(r, str(conn.ingest_id))
        again = c.get(reverse('backup_monitoring:connection_edit', args=[conn.pk]))
        self.assertNotContains(again, 'data-issued-secret')

    def test_cannot_create_connection_for_unreachable_org(self):
        c = self.client_for(self.staff_a)
        r = c.post(reverse('backup_monitoring:connection_create'), {
            'name': 'sneaky', 'provider': 'borg', 'organization': self.org_b.pk, 'active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(BackupConnection.objects.filter(name='sneaky').exists())

    def test_delete_connection(self):
        c = self.client_for(self.staff_a)
        self.assertEqual(c.post(reverse('backup_monitoring:connection_delete', args=[self.conn_a.pk])).status_code, 302)
        self.assertFalse(BackupConnection.objects.filter(pk=self.conn_a.pk).exists())
        self.assertFalse(BackupJob.objects.filter(pk=self.job_a.pk).exists())

    # restore tests
    def test_record_restore_test(self):
        c = self.client_for(self.staff_a)
        system = ProtectedSystem.objects.get(connection=self.conn_a)
        r = c.post(reverse('backup_monitoring:restore_test_create'), {
            'organization': self.org_a.pk, 'system': system.pk, 'tested_on': timezone.now().date().isoformat(),
            'result': 'passed', 'notes': 'restored VM to lab'})
        self.assertEqual(r.status_code, 302, r.context['form'].errors if r.context else '')
        t = RestoreTest.objects.get()
        self.assertEqual((t.organization, t.verified_by, t.source), (self.org_a, self.staff_a, 'manual'))
        self.assertContains(c.get(reverse('backup_monitoring:restore_test_list')), 'restored VM to lab')

    def test_restore_test_rejects_cross_customer_system_and_future_date(self):
        c = self.client_for(self.staff_a)
        other = ProtectedSystem.objects.get(connection=self.conn_b)
        r = c.post(reverse('backup_monitoring:restore_test_create'), {
            'organization': self.org_a.pk, 'system': other.pk, 'tested_on': timezone.now().date().isoformat(),
            'result': 'passed'})
        self.assertEqual(r.status_code, 200)
        r = c.post(reverse('backup_monitoring:restore_test_create'), {
            'organization': self.org_a.pk, 'system_name': 'x',
            'tested_on': (timezone.now().date() + timedelta(days=3)).isoformat(), 'result': 'passed'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(RestoreTest.objects.count(), 0)

    def test_restore_tests_isolated(self):
        RestoreTest.objects.create(organization=self.org_b, system_name='b-secret-sys',
                                   tested_on=timezone.now().date(), result='passed')
        r = self.client_for(self.staff_a).get(reverse('backup_monitoring:restore_test_list'))
        self.assertNotContains(r, 'b-secret-sys')

    # alerts
    def test_acknowledge_resolve_and_ticket_dedup(self):
        c = self.client_for(self.staff_a)
        url = reverse('backup_monitoring:alert_decide', args=[self.alert_a.pk])
        c.post(url, {'decision': 'acknowledge'})
        self.alert_a.refresh_from_db()
        self.assertEqual((self.alert_a.status, self.alert_a.acknowledged_by), ('acknowledged', self.staff_a))
        from psa.models import Ticket
        c.post(url, {'decision': 'ticket'})
        c.post(url, {'decision': 'ticket'})
        self.alert_a.refresh_from_db()
        self.assertIsNotNone(self.alert_a.ticket)
        self.assertEqual(Ticket.objects.filter(subject__startswith='[Backup]').count(), 1)
        c.post(url, {'decision': 'resolve'})
        self.alert_a.refresh_from_db()
        self.assertEqual(self.alert_a.status, 'resolved')

    def test_auto_ticket_policy_creates_one_ticket_per_alert(self):
        from psa.models import Ticket
        BackupAlertPolicy.objects.create(organization=self.org_a, auto_ticket=True)
        conn, _ = make_push(self.org_a, name='ticketing')
        make_job(conn, 'old', success_ago_h=60)
        evaluate_connection(conn)
        evaluate_connection(conn)
        self.assertEqual(Ticket.objects.filter(subject__startswith='[Backup]').count(), 1)
        self.assertIsNotNone(BackupAlert.objects.get(connection=conn).ticket)

    def test_alert_unique_constraint_blocks_duplicate_live_rows(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            BackupAlert.objects.create(organization=self.org_a, connection=self.conn_a, kind='failed',
                                       title='dup', dedup_key='k')

    # job / customer pages
    def test_job_detail_shows_history_and_source(self):
        r = self.client_for(self.staff_a).get(reverse('backup_monitoring:job_detail', args=[self.job_a.pk]))
        self.assertContains(r, 'JobA')
        self.assertContains(r, 'conn-a')

    def test_customer_detail_shows_capacity_and_restore_status(self):
        r = self.client_for(self.staff_a).get(reverse('backup_monitoring:customer_detail', args=[self.org_a.pk]))
        self.assertContains(r, 'RepoA')
        self.assertContains(r, 'Never tested')
        self.assertContains(r, 'progress-bar')

    def test_stale_connection_page_never_shows_healthy(self):
        self.conn_a.last_poll_at = timezone.now() - timedelta(hours=8)
        self.conn_a.save()
        c = self.client_for(self.staff_a)
        dash = c.get(reverse('backup_monitoring:dashboard'))
        self.assertContains(dash, 'data-state="stale"')
        self.assertNotContains(dash, 'data-state="ok"')
        self.assertContains(dash, 'Stale')

    def test_policy_edit(self):
        c = self.client_for(self.staff_a)
        r = c.post(reverse('backup_monitoring:policy_edit', args=[self.org_a.pk]), {
            'missed_threshold_hours': 12, 'consecutive_failures': 3, 'capacity_pct': 80,
            'alert_missing_protected_device': 'on', 'restore_test_max_age_days': 90})
        self.assertEqual(r.status_code, 302)
        p = BackupAlertPolicy.objects.get(organization=self.org_a)
        self.assertEqual((p.missed_threshold_hours, p.capacity_pct, p.auto_ticket), (12, 80, False))

    def test_system_mapping_rejects_other_customers_asset(self):
        c = self.client_for(self.staff_a)
        system = ProtectedSystem.objects.get(connection=self.conn_a)
        foreign = Asset.objects.create(organization=self.org_b, name='b-box')
        r = c.post(reverse('backup_monitoring:system_edit', args=[system.pk]), {
            'name': system.name, 'customer': self.org_a.pk, 'asset': foreign.pk})
        self.assertEqual(r.status_code, 200)
        system.refresh_from_db()
        self.assertIsNone(system.asset)

    def test_navigation_has_one_entry_for_permitted_users_only(self):
        from core import navigation
        entries = [e for g in navigation.PRIMARY for e in g.entries if e.label == 'Backup Monitoring']
        self.assertEqual(len(entries), 1)
        self.assertEqual([g.key for g in navigation.PRIMARY if any(e.label == 'Backup Monitoring' for e in g.entries)],
                         ['assets'])
        ctx_ok = {'user': self.viewer_a}
        ctx_no = {'user': self.nobody}
        self.assertTrue(navigation.SECTIONS_BY_KEY['assets_backups'].gate(ctx_ok))
        self.assertFalse(navigation.SECTIONS_BY_KEY['assets_backups'].gate(ctx_no))


# ------------------------------------------------- workspace / compliance etc.

class IntegrationPointTests(Fixture):
    def test_device_workspace_panel(self):
        viewer = make_staff('bm-ws', 'bm ws', scope_orgs=[self.org_a], **ROLE_VIEW)
        nobody = make_staff('bm-ws-none', 'bm ws none', scope_orgs=[self.org_a])
        conn = make_pbs(self.org_a)
        conn.last_poll_at, conn.last_poll_status = timezone.now(), 'ok'
        conn.save()
        job = make_job(conn, 'wsjob')
        asset = Asset.objects.create(organization=self.org_a, name='web01')
        self.assertIsNone(asset_backup_panel(asset, viewer))        # nothing linked
        job.system.asset = asset
        job.system.save()
        panel = asset_backup_panel(asset, viewer)
        self.assertEqual(panel[0]['state'], 'ok')
        self.assertEqual(panel[0]['source'], 'Proxmox Backup Server')
        self.assertIsNone(asset_backup_panel(asset, nobody))        # no permission
        conn.last_poll_at = timezone.now() - timedelta(hours=9)
        conn.save()
        self.assertEqual(asset_backup_panel(asset, viewer)[0]['state'], 'stale')

    def test_panel_ignores_system_mapped_across_customers(self):
        viewer = make_staff('bm-ws2', 'bm ws2', **ROLE_VIEW)
        conn = make_pbs(self.org_b)
        job = make_job(conn, 'x')
        asset = Asset.objects.create(organization=self.org_a, name='a-box')
        job.system.asset = asset          # asset of A, system of B
        job.system.save()
        self.assertIsNone(asset_backup_panel(asset, viewer))

    def test_compliance_evidence_uses_real_data(self):
        from compliance.views import _section_backup_evidence
        empty = _section_backup_evidence(self.org_a)
        self.assertEqual(empty['summary']['backup_jobs_tracked'], 0)
        conn, _ = make_push(self.org_a)
        conn.last_poll_at = timezone.now()
        conn.save()
        make_job(conn, 'ev')
        make_job(make_push(self.org_b, name='other')[0], 'evb')
        RestoreTest.objects.create(organization=self.org_a, system_name='s', tested_on=timezone.now().date(),
                                   result='passed')
        section = _section_backup_evidence(self.org_a)
        self.assertEqual(section['summary']['backup_jobs_tracked'], 1)
        self.assertEqual(section['rows'][0]['state'], 'ok')
        self.assertEqual(section['summary']['restore_tests_recorded'], 1)

    def test_scheduler_registration(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['poll_backup_monitoring'][0], 'poll_backup_monitoring')
        self.assertIn('poll_backup_monitoring', dict(ScheduledTask.TASK_TYPES))
        self.assertIn('poll_backup_monitoring', [d['task_type'] for d in ScheduledTask.PERIODIC_COMMAND_DEFAULTS])

    def test_poll_command_polls_and_evaluates(self):
        conn = make_pbs(self.org_a)
        make_push(self.org_a)
        routes_ok = mock.MagicMock(side_effect=lambda url, **kw: FakeResp(
            [] if '/api2/json/status' in url or 'tasks' in url or 'prune' in url else {}))
        with mock.patch('backup_monitoring.providers.pbs.requests.get', routes_ok):
            call_command('poll_backup_monitoring', verbosity=0)
        conn.refresh_from_db()
        self.assertEqual(conn.last_poll_status, 'ok')

    def test_poll_command_reports_failed_connections(self):
        from django.core.management.base import CommandError
        make_pbs(self.org_a)
        with mock.patch('backup_monitoring.providers.pbs.requests.get', return_value=FakeResp(None, 500)):
            with self.assertRaises(CommandError):
                call_command('poll_backup_monitoring', verbosity=0)

    def test_permissions_registered_and_seeded(self):
        from accounts import permission_registry as reg
        for key in ('view_backup_status', 'manage_backup_integrations'):
            self.assertIn(key, reg.REGISTRY)
            self.assertTrue(hasattr(RoleTemplate, key))
            self.assertTrue(reg.REGISTRY[key].staff_only)
        from accounts.role_seeds import definitions
        by_key = {d.key: d.flags for d in definitions()}
        self.assertTrue(by_key['org_admin']['manage_backup_integrations'])
        self.assertTrue(by_key['tech_l1'].get('view_backup_status'))
        self.assertFalse(by_key['tech_l1'].get('manage_backup_integrations'))
        self.assertFalse(by_key['customer_admin'].get('view_backup_status'))
