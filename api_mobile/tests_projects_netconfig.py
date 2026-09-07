"""
Mobile API — projects and network configs (v3.17.558).

The recurring question in both: what does a technician in a van need, and what
should stay on the desk. Profitability, billing and device credentials are all
deliberately absent from these payloads, and there are tests that say so.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset
from core.models import Organization
from netconfig.models import BackupTarget, ConfigBackup
from psa.models import (
    Contract, Project, ProjectTask, Queue, Ticket, TicketPriority,
    TicketStatus, TicketTimeEntry, TicketType,
)
from psa.tests._base import _setup_seed

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# Same shape as api_mobile/tests.py: cumulative logins across test classes
# sharing one IP otherwise trip the 10/hour login throttle and setUp gets a 429.
# `DEFAULT_THROTTLE_RATES: {}` does not disable it — the classes have to go.
NO_THROTTLE_REST = dict(django_settings.REST_FRAMEWORK,
                        DEFAULT_THROTTLE_CLASSES=[])


def _clear_throttle_cache():
    from django.core.cache import cache
    try:
        cache.clear()
    except Exception:
        pass


def _login(client, username, password):
    resp = client.post('/api/mobile/v1/auth/login/',
                       data={'username': username, 'password': password},
                       content_type='application/json')
    return resp.json()['token']


def _get(client, url, token):
    return client.get(url, HTTP_AUTHORIZATION=f'Token {token}')


def _patch(client, url, token, payload):
    import json
    return client.patch(url, data=json.dumps(payload),
                        content_type='application/json',
                        HTTP_AUTHORIZATION=f'Token {token}')


def _post(client, url, token, payload=None):
    import json
    return client.post(url, data=json.dumps(payload or {}),
                       content_type='application/json',
                       HTTP_AUTHORIZATION=f'Token {token}')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileProjectTests(TestCase):
    def setUp(self):
        _clear_throttle_cache()
        _setup_seed()
        self.org = Organization.objects.create(name='MPCo', slug='mp-co')
        self.other_org = Organization.objects.create(name='MPOther', slug='mp-other')
        self.user = User.objects.create_user('mpuser', password='hunter2')
        Membership.objects.create(user=self.user, organization=self.org,
                                  role=Role.OWNER, is_active=True)

        self.project = Project.objects.create(
            organization=self.org, name='Server migration', client_org=self.org,
            due_date=date.today() + timedelta(days=30))
        self.task = ProjectTask.objects.create(
            project=self.project, title='Provision tenant')
        self.foreign_project = Project.objects.create(
            organization=self.other_org, name='Not ours')

        self.client = Client()
        self.token = _login(self.client, 'mpuser', 'hunter2')

    def test_list_is_scoped_to_my_orgs(self):
        body = _get(self.client, '/api/mobile/v1/projects/', self.token).json()
        names = [p['name'] for p in body['results']]
        self.assertIn('Server migration', names)
        self.assertNotIn('Not ours', names)

    def test_list_counts_open_tasks(self):
        ProjectTask.objects.create(project=self.project, title='Done bit',
                                   status='done')
        row = _get(self.client, '/api/mobile/v1/projects/',
                   self.token).json()['results'][0]
        self.assertEqual(row['task_count'], 2)
        self.assertEqual(row['open_task_count'], 1)

    def test_mine_filter_narrows_to_my_work(self):
        unassigned = Project.objects.create(
            organization=self.org, name='Nobody on it')
        self.task.assigned_to = self.user
        self.task.save(update_fields=['assigned_to'])
        body = _get(self.client, '/api/mobile/v1/projects/?mine=true',
                    self.token).json()
        names = [p['name'] for p in body['results']]
        self.assertIn('Server migration', names)
        self.assertNotIn('Nobody on it', names)
        self.assertTrue(unassigned.pk)

    def test_mine_is_not_the_default(self):
        """A project with nothing assigned yet would otherwise be invisible to
        the person about to be assigned it."""
        Project.objects.create(organization=self.org, name='Nobody on it')
        body = _get(self.client, '/api/mobile/v1/projects/', self.token).json()
        self.assertIn('Nobody on it', [p['name'] for p in body['results']])

    def test_open_filter_excludes_finished_projects(self):
        self.project.status = 'completed'
        self.project.save(update_fields=['status'])
        body = _get(self.client, '/api/mobile/v1/projects/?status=open',
                    self.token).json()
        self.assertEqual(body['results'], [])

    def test_detail_returns_tasks(self):
        body = _get(self.client, f'/api/mobile/v1/projects/{self.project.pk}/',
                    self.token).json()
        self.assertEqual([t['title'] for t in body['tasks']],
                         ['Provision tenant'])

    def test_detail_reports_hours_budget(self):
        self.project.budget_hours = Decimal('10')
        self.project.save(update_fields=['budget_hours'])
        body = _get(self.client, f'/api/mobile/v1/projects/{self.project.pk}/',
                    self.token).json()
        self.assertEqual(body['budget']['hours_budget'], '10.00')
        self.assertEqual(body['budget']['state'], 'ok')

    def test_detail_never_exposes_money(self):
        """Margin is not a number to hand somebody standing in a client's
        server room."""
        Contract.objects.create(
            organization=self.org, client_org=self.org, name='MSA',
            status='active', start_date=date.today() - timedelta(days=30),
            hourly_rate=Decimal('150.00'))
        self.project.budget_amount = Decimal('9999.00')
        self.project.save(update_fields=['budget_amount'])
        ticket = Ticket.objects.create(
            organization=self.org, subject='Work', project=self.project,
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())
        TicketTimeEntry.objects.create(
            ticket=ticket, user=self.user,
            started_at=timezone.now() - timedelta(hours=1),
            ended_at=timezone.now(), duration_minutes=60, is_billable=True)

        import json as _json
        raw = _json.dumps(
            _get(self.client, f'/api/mobile/v1/projects/{self.project.pk}/',
                 self.token).json())
        for forbidden in ('margin', 'revenue', 'amount', '150.00', '9999'):
            self.assertNotIn(forbidden, raw, forbidden)

    def test_a_blocked_task_says_what_it_waits_for(self):
        blocker = ProjectTask.objects.create(
            project=self.project, title='Order hardware')
        self.task.add_dependency(blocker)
        body = _get(self.client, f'/api/mobile/v1/projects/{self.project.pk}/',
                    self.token).json()
        task = next(t for t in body['tasks'] if t['title'] == 'Provision tenant')
        self.assertTrue(task['is_blocked'])
        self.assertEqual(task['blocked_by'], ['Order hardware'])

    def test_cross_org_project_is_404(self):
        resp = _get(self.client,
                    f'/api/mobile/v1/projects/{self.foreign_project.pk}/',
                    self.token)
        self.assertEqual(resp.status_code, 404)

    def test_task_status_can_be_updated(self):
        resp = _patch(self.client,
                      f'/api/mobile/v1/project-tasks/{self.task.pk}/',
                      self.token, {'status': 'done'})
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'done')
        self.assertIsNotNone(self.task.completed_at)

    def test_a_bogus_status_is_refused(self):
        resp = _patch(self.client,
                      f'/api/mobile/v1/project-tasks/{self.task.pk}/',
                      self.token, {'status': 'whenever'})
        self.assertEqual(resp.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'todo')

    def test_a_blocked_task_can_still_be_marked_done(self):
        """The dependency may have been finished by somebody who has not
        updated it; refusing would leave a tech unable to record real work."""
        blocker = ProjectTask.objects.create(
            project=self.project, title='Order hardware')
        self.task.add_dependency(blocker)
        resp = _patch(self.client,
                      f'/api/mobile/v1/project-tasks/{self.task.pk}/',
                      self.token, {'status': 'done'})
        self.assertEqual(resp.status_code, 200)

    def test_cross_org_task_is_404(self):
        foreign_task = ProjectTask.objects.create(
            project=self.foreign_project, title='Theirs')
        resp = _patch(self.client,
                      f'/api/mobile/v1/project-tasks/{foreign_task.pk}/',
                      self.token, {'status': 'done'})
        self.assertEqual(resp.status_code, 404)

    def test_requires_auth(self):
        self.assertIn(Client().get('/api/mobile/v1/projects/').status_code,
                      (401, 403))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileNetconfigTests(TestCase):
    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='MNCo', slug='mn-co')
        self.other_org = Organization.objects.create(name='MNOther', slug='mn-other')
        self.user = User.objects.create_user('mnuser', password='hunter2')
        Membership.objects.create(user=self.user, organization=self.org,
                                  role=Role.OWNER, is_active=True)

        self.switch = Asset.objects.create(
            organization=self.org, name='core-sw-01', asset_type='switch')
        self.laptop = Asset.objects.create(
            organization=self.org, name='a-laptop', asset_type='laptop')
        self.foreign = Asset.objects.create(
            organization=self.other_org, name='their-sw', asset_type='switch')

        self.client = Client()
        self.token = _login(self.client, 'mnuser', 'hunter2')

    def _backup(self, body='hostname core-sw-01\nend'):
        backup, _ = ConfigBackup.record_for_asset(self.switch, body)
        return backup

    def test_device_list_shows_network_gear_only(self):
        body = _get(self.client, '/api/mobile/v1/netconfig/devices/',
                    self.token).json()
        names = [d['name'] for d in body['results']]
        self.assertIn('core-sw-01', names)
        self.assertNotIn('a-laptop', names)

    def test_device_list_is_org_scoped(self):
        body = _get(self.client, '/api/mobile/v1/netconfig/devices/',
                    self.token).json()
        self.assertNotIn('their-sw', [d['name'] for d in body['results']])

    def test_device_list_counts_snapshots(self):
        self._backup()
        row = _get(self.client, '/api/mobile/v1/netconfig/devices/',
                   self.token).json()['results'][0]
        self.assertEqual(row['backup_count'], 1)
        self.assertIsNotNone(row['latest_capture'])

    def test_search_narrows_the_list(self):
        Asset.objects.create(organization=self.org, name='edge-fw',
                             asset_type='firewall')
        body = _get(self.client,
                    '/api/mobile/v1/netconfig/devices/?search=edge',
                    self.token).json()
        self.assertEqual([d['name'] for d in body['results']], ['edge-fw'])

    def test_device_detail_lists_snapshots(self):
        self._backup()
        body = _get(self.client,
                    f'/api/mobile/v1/netconfig/devices/{self.switch.pk}/',
                    self.token).json()
        self.assertEqual(len(body['backups']), 1)

    def test_a_non_network_asset_is_404(self):
        resp = _get(self.client,
                    f'/api/mobile/v1/netconfig/devices/{self.laptop.pk}/',
                    self.token)
        self.assertEqual(resp.status_code, 404)

    def test_a_cross_org_device_is_404(self):
        resp = _get(self.client,
                    f'/api/mobile/v1/netconfig/devices/{self.foreign.pk}/',
                    self.token)
        self.assertEqual(resp.status_code, 404)

    def test_detail_says_why_collection_is_unavailable(self):
        """A greyed-out button with no explanation generates the support
        call."""
        body = _get(self.client,
                    f'/api/mobile/v1/netconfig/devices/{self.switch.pk}/',
                    self.token).json()
        self.assertFalse(body['can_collect'])
        self.assertIn('No SSH connection', body['collect_blocked_reason'])

    def test_backup_detail_returns_the_config_text(self):
        backup = self._backup()
        body = _get(self.client,
                    f'/api/mobile/v1/netconfig/backups/{backup.pk}/',
                    self.token).json()
        self.assertIn('hostname core-sw-01', body['body'])
        self.assertFalse(body['truncated'])

    def test_a_huge_config_is_truncated_and_says_so(self):
        backup = self._backup('x' * 250_000)
        body = _get(self.client,
                    f'/api/mobile/v1/netconfig/backups/{backup.pk}/',
                    self.token).json()
        self.assertTrue(body['truncated'])
        self.assertEqual(len(body['body']), 200_000)

    def test_a_cross_org_backup_is_404(self):
        foreign_backup, _ = ConfigBackup.record_for_asset(self.foreign, 'theirs')
        resp = _get(self.client,
                    f'/api/mobile/v1/netconfig/backups/{foreign_backup.pk}/',
                    self.token)
        self.assertEqual(resp.status_code, 404)

    def test_no_device_credential_ever_reaches_the_phone(self):
        """The server runs the SSH session. The phone holds nothing."""
        from vault.models import Password
        cred = Password.objects.create(
            organization=self.org, title='switch admin', username='admin')
        cred.set_password('super-secret-pw')
        cred.save()
        BackupTarget.objects.create(
            asset=self.switch, host='10.0.0.2', username='admin',
            credential=cred)

        import json as _json
        raw = _json.dumps(
            _get(self.client,
                 f'/api/mobile/v1/netconfig/devices/{self.switch.pk}/',
                 self.token).json())
        self.assertNotIn('super-secret-pw', raw)
        self.assertNotIn('10.0.0.2', raw)

    def test_collect_without_a_target_is_refused(self):
        resp = _post(self.client,
                     f'/api/mobile/v1/netconfig/devices/{self.switch.pk}/collect/',
                     self.token)
        self.assertEqual(resp.status_code, 400)

    def test_collect_runs_the_server_side_collector(self):
        from unittest.mock import patch
        from vault.models import Password
        cred = Password.objects.create(
            organization=self.org, title='switch admin', username='admin')
        cred.set_password('pw')
        cred.save()
        BackupTarget.objects.create(
            asset=self.switch, host='10.0.0.2', username='admin',
            credential=cred)

        with patch('netconfig.collector.collect_over_ssh',
                   return_value=('hostname core-sw-01\nend', '15.2')):
            resp = _post(
                self.client,
                f'/api/mobile/v1/netconfig/devices/{self.switch.pk}/collect/',
                self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(ConfigBackup.objects.filter(asset=self.switch).count(), 1)

    def test_requires_auth(self):
        self.assertIn(
            Client().get('/api/mobile/v1/netconfig/devices/').status_code,
            (401, 403))
