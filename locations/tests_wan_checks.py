"""Scheduled WAN connection checks and down / recovery alerts (v3.17.617).

WAN connections were only checked when someone clicked Check Status, though
the form offered an interval and said the target would be pinged on it.
"""
import io
import json
import subprocess
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.mail import get_connection
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership
from core.models import Organization, SystemSetting, Webhook
from locations import wan_checks
from locations.models import WAN, Location, WANCheck
from locations.wan_checks import PingResult

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

UP = PingResult('up', response_time_ms=12)
DOWN = PingResult('down', error='No answer to ping.')
ERROR = PingResult('error', error='The ping command is not installed on the server.')


def locmem(_settings=None):
    return get_connection(backend='django.core.mail.backends.locmem.EmailBackend')


def _completed(rc, out='', err=''):
    return subprocess.CompletedProcess([], rc, out.encode(), err.encode())


class PingTargetTests(TestCase):

    def run_ping(self, completed=None, side_effect=None):
        with mock.patch.object(wan_checks, '_ping_binary', return_value='/usr/bin/ping'), \
             mock.patch('locations.wan_checks.subprocess.run',
                        return_value=completed, side_effect=side_effect) as run:
            return wan_checks.ping_target('203.0.113.1'), run

    def test_answer_reports_average_round_trip(self):
        out = ('3 packets transmitted, 3 received, 0% packet loss, time 402ms\n'
               'rtt min/avg/max/mdev = 9.871/14.302/20.110/4.1 ms\n')
        result, run = self.run_ping(_completed(0, out))
        self.assertEqual(result, PingResult('up', 14, ''))
        args = run.call_args.args[0]
        self.assertEqual(args[0], '/usr/bin/ping')  # absolute: the unit's PATH is the venv only
        self.assertEqual(args[-1], '203.0.113.1')

    def test_no_answer_is_down(self):
        result, _ = self.run_ping(_completed(1, '3 packets transmitted, 0 received'))
        self.assertEqual(result.result, 'down')

    def test_timeout_is_down(self):
        result, _ = self.run_ping(side_effect=subprocess.TimeoutExpired('ping', 15))
        self.assertEqual(result.result, 'down')

    def test_unresolvable_name_is_down(self):
        result, _ = self.run_ping(_completed(2, err='ping: gw.example: Name or service not known'))
        self.assertEqual(result.result, 'down')

    def test_other_ping_failure_is_a_check_error(self):
        result, _ = self.run_ping(_completed(2, err='ping: socket: Operation not permitted'))
        self.assertEqual(result.result, 'error')
        self.assertIn('Operation not permitted', result.error)

    def test_missing_binary_is_a_check_error(self):
        with mock.patch.object(wan_checks, '_ping_binary', return_value=None), \
             mock.patch('locations.wan_checks.subprocess.run') as run:
            result = wan_checks.ping_target('203.0.113.1')
        self.assertEqual(result.result, 'error')
        run.assert_not_called()

    def test_option_like_target_is_never_run(self):
        with mock.patch('locations.wan_checks.subprocess.run') as run:
            result = wan_checks.ping_target('-fc100000')
        self.assertEqual(result.result, 'error')
        run.assert_not_called()


class WanAlertTests(TestCase):

    def setUp(self):
        mail.outbox = []
        self.org = Organization.objects.create(name='Acme', slug='acme')
        admin = User.objects.create_user('orgadmin', email='admin@acme.test', password='x')
        Membership.objects.create(user=admin, organization=self.org, role='admin')
        s = SystemSetting.get_settings()
        s.smtp_enabled = True
        s.smtp_host = 'smtp.test'
        s.smtp_from_email = 'mailer@acme.test'
        s.site_url = 'https://example.test'
        s.save()
        self.location = Location.objects.create(organization=self.org, name='HQ')
        self.wan = WAN.objects.create(
            organization=self.org, location=self.location, name='Fiber',
            isp_name='FastNet', isp_support_phone='555-0100', circuit_id='CKT-9',
            monitoring_enabled=True, monitor_target='203.0.113.1')
        patcher = mock.patch('locations.wan_checks.get_smtp_connection', locmem)
        patcher.start()
        self.addCleanup(patcher.stop)
        fire = mock.patch('core.webhook_events.fire')
        self.fire = fire.start()
        self.addCleanup(fire.stop)

    def check(self, ping):
        wan_checks.apply_result(self.wan, ping)
        self.wan.refresh_from_db()

    def events(self):
        return [c.args[0] for c in self.fire.call_args_list]

    def test_single_failure_is_debounced(self):
        self.check(DOWN)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.wan.status, 'active')
        self.assertEqual(self.wan.consecutive_failures, 1)
        self.assertEqual(self.events(), ['wan.check_failed'])

    def test_outage_alerts_once_and_recovery_once(self):
        for _ in range(4):
            self.check(DOWN)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn('HQ - Fiber is DOWN', msg.subject)
        self.assertIn('555-0100', msg.body)
        self.assertIn('CKT-9', msg.body)
        self.assertIn('https://example.test/locations/', msg.body)
        self.assertEqual(msg.to, ['admin@acme.test'])
        self.assertEqual(self.wan.status, 'down')
        self.assertEqual(self.wan.alert_state, 'down')
        self.assertIsNotNone(self.wan.last_down_at)

        self.check(UP)
        self.check(UP)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('RECOVERED', mail.outbox[1].subject)
        self.assertEqual(self.wan.status, 'active')
        self.assertEqual(self.wan.consecutive_failures, 0)
        self.assertEqual(self.wan.last_response_time_ms, 12)
        self.assertEqual(self.events().count('wan.down'), 1)
        self.assertEqual(self.events().count('wan.up'), 1)
        self.assertEqual(self.events().count('wan.check_failed'), 4)

    def test_blip_then_answer_sends_nothing(self):
        self.check(DOWN)
        self.check(UP)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn('wan.up', self.events())

    def test_check_error_neither_counts_nor_clears(self):
        self.check(DOWN)
        self.check(ERROR)
        self.assertEqual(self.wan.consecutive_failures, 1)
        self.assertEqual(self.wan.last_check_result, 'error')
        self.check(DOWN)
        self.assertEqual(self.wan.alert_state, 'down')

    def test_notify_off_still_fires_webhooks(self):
        self.wan.notify_on_down = False
        self.wan.save()
        self.check(DOWN)
        self.check(DOWN)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('wan.down', self.events())

    def test_hand_set_status_is_left_alone(self):
        self.wan.status = 'maintenance'
        self.wan.save()
        for _ in range(3):
            self.check(DOWN)
        self.assertEqual(self.wan.status, 'maintenance')
        self.assertEqual(self.wan.alert_state, 'up')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.wan.checks.count(), 3)

    @override_settings(WAN_DOWN_ALERT_THRESHOLD=3)
    def test_threshold_setting(self):
        self.check(DOWN)
        self.check(DOWN)
        self.assertEqual(self.wan.alert_state, 'up')
        self.check(DOWN)
        self.assertEqual(self.wan.alert_state, 'down')

    def test_history_and_uptime(self):
        for ping in (UP, UP, DOWN, ERROR):
            self.check(ping)
        self.assertEqual(self.wan.checks.count(), 4)
        u = self.wan.uptime(30)
        self.assertEqual((u['checks'], u['down']), (3, 1))  # errors not counted
        self.assertAlmostEqual(float(self.wan.uptime_percentage), 66.67, places=2)

    def test_uptime_is_none_without_checks(self):
        self.assertIsNone(self.wan.uptime(30)['percent'])


class DueAndCommandTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Acme', slug='acme')
        loc = Location.objects.create(organization=self.org, name='HQ')
        now = timezone.now()

        def wan(name, **kw):
            kw.setdefault('monitoring_enabled', True)
            kw.setdefault('monitor_target', '203.0.113.1')
            return WAN.objects.create(organization=self.org, location=loc, name=name, **kw)

        self.never = wan('never')
        self.due = wan('due', monitor_interval_minutes=5, last_checked_at=now - timedelta(minutes=5))
        self.fresh = wan('fresh', monitor_interval_minutes=5, last_checked_at=now - timedelta(minutes=2))
        self.off = wan('off', monitoring_enabled=False)
        self.no_target = wan('no-target', monitor_target='')
        self.paused = wan('paused', status='maintenance')
        self.planned = wan('planned', status='planned')
        self.was_down = wan('was-down', status='down')

    def test_due_selection(self):
        names = {w.name for w in wan_checks.due_wans()}
        self.assertEqual(names, {'never', 'due', 'was-down'})

    def test_command_checks_due_wans_in_parallel_safe_way(self):
        with mock.patch.object(wan_checks, 'ping_target', return_value=UP) as ping, \
             mock.patch('core.webhook_events.fire'):
            out = io.StringIO()
            call_command('check_wans', stdout=out)
        self.assertEqual(ping.call_count, 3)
        self.assertIn('Checked 3 WAN connection(s): 3 answered', out.getvalue())
        self.was_down.refresh_from_db()
        self.assertEqual(self.was_down.status, 'active')
        self.fresh.refresh_from_db()
        self.assertEqual(self.fresh.checks.count(), 0)

    def test_force_ignores_intervals_but_not_paused(self):
        with mock.patch.object(wan_checks, 'ping_target', return_value=UP) as ping, \
             mock.patch('core.webhook_events.fire'):
            call_command('check_wans', '--force', stdout=io.StringIO())
        self.assertEqual(ping.call_count, 4)

    def test_scheduler_owns_the_command(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['check_wans'], ('check_wans', []))
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='check_wans')
        self.assertTrue(task.enabled)
        self.assertEqual(task.interval_minutes, 1)

    def test_prune_includes_wan_history(self):
        old = timezone.now() - timedelta(days=500)
        WANCheck.objects.create(wan=self.due, checked_at=old, result='up')
        WANCheck.objects.create(wan=self.due, checked_at=timezone.now(), result='up')
        call_command('prune_monitor_checks', stdout=io.StringIO())
        self.assertEqual(WANCheck.objects.count(), 1)


@override_settings(WEBHOOK_DELIVERY_ASYNC=False)
class WanWebhookDeliveryTests(TestCase):

    def test_wan_down_is_delivered_to_subscribed_hook(self):
        org = Organization.objects.create(name='Acme', slug='acme')
        s = SystemSetting.get_settings()
        s.webhooks_enabled = True
        s.save()
        Webhook.objects.create(organization=org, name='h', url='https://hooks.example.test/in',
                               events=['wan.down'])
        loc = Location.objects.create(organization=org, name='HQ')
        wan = WAN.objects.create(organization=org, location=loc, name='Fiber',
                                 monitoring_enabled=True, monitor_target='203.0.113.1',
                                 notify_on_down=False)
        calls = []

        class Session:
            trust_env = True

            def post(self, url, data=None, headers=None, timeout=None):
                calls.append(json.loads(data))
                return mock.Mock(status_code=200, text='ok')

        with mock.patch('core.webhook_sender.guard_session', side_effect=lambda s, p: Session()):
            with self.captureOnCommitCallbacks(execute=True):
                wan_checks.apply_result(wan, DOWN)
                wan_checks.apply_result(wan, DOWN)
        self.assertEqual([c['event'] for c in calls], ['wan.down'])
        self.assertEqual(calls[0]['data']['name'], 'Fiber')
        self.assertEqual(calls[0]['data']['location'], 'HQ')
        self.assertEqual(calls[0]['data']['consecutive_failures'], 2)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WanPagesTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Acme', slug='acme')
        self.user = User.objects.create_user('admin', email='a@acme.test', password='x')
        Membership.objects.create(user=self.user, organization=self.org, role='admin')
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()
        self.loc = Location.objects.create(organization=self.org, name='HQ')
        self.wan = WAN.objects.create(organization=self.org, location=self.loc, name='Fiber',
                                      monitoring_enabled=True, monitor_target='203.0.113.1')

    def test_manual_check_reports_the_streak(self):
        with mock.patch.object(wan_checks, 'ping_target', return_value=DOWN), \
             mock.patch('core.webhook_events.fire'):
            r = self.client.get(f'/locations/{self.loc.pk}/wan/{self.wan.pk}/check-status/', follow=True)
        self.assertContains(r, '1 failed check(s) in a row')
        self.wan.refresh_from_db()
        self.assertEqual(self.wan.status, 'active')

    def test_detail_shows_uptime_and_last_result(self):
        WANCheck.objects.create(wan=self.wan, checked_at=timezone.now(), result='up')
        self.wan.last_check_result = 'up'
        self.wan.uptime_percentage = 100
        self.wan.save()
        r = self.client.get(f'/locations/{self.loc.pk}/wan/{self.wan.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Answered')
        self.assertContains(r, '100')
        self.assertNotContains(r, 'not used yet')

    def test_monitoring_list_status_filter_and_badge(self):
        self.wan.status = 'down'
        self.wan.last_checked_at = timezone.now() - timedelta(minutes=3)
        self.wan.save()
        r = self.client.get('/monitoring/wans/?status=down')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'fa-times-circle')
        self.assertContains(r, '3\xa0minutes ago')
        self.assertNotContains(r, 'value="None"')

    def test_form_rejects_option_like_target_and_requires_one(self):
        from locations.forms import WANForm
        base = {'name': 'Backup', 'wan_type': 'internet', 'status': 'active',
                'monitoring_enabled': 'on', 'monitor_interval_minutes': 5}
        form = WANForm(data={**base, 'monitor_target': '-f'}, organization=self.org, location=self.loc)
        self.assertFalse(form.is_valid())
        self.assertIn('monitor_target', form.errors)
        form = WANForm(data={**base, 'monitor_target': ''}, organization=self.org, location=self.loc)
        self.assertFalse(form.is_valid())
        self.assertIn('monitor_target', form.errors)
