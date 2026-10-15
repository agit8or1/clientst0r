"""Website down / recovery alerts are sent on transitions, not every check.

`notify_on_down` was on the monitor form, defaulted to on, and read by nothing.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.mail import get_connection
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership
from core.models import Organization, SystemSetting
from monitoring.down_notifications import process_check_result
from monitoring.models import WebsiteMonitor


def locmem(_settings=None):
    return get_connection(backend='django.core.mail.backends.locmem.EmailBackend')


class DownNotificationTests(TestCase):

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
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Shop', url='https://shop.acme.test')
        patcher = patch('monitoring.down_notifications.get_smtp_connection', locmem)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, status, code=None, error=''):
        m = self.monitor
        m.status = status
        m.last_status_code = code
        m.last_error = error
        m.last_checked_at = timezone.now()
        m.save()
        process_check_result(m)
        m.refresh_from_db()

    def test_single_failure_is_debounced(self):
        self.check('down', 503, 'HTTP 503')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.monitor.consecutive_failures, 1)
        self.assertEqual(self.monitor.alert_state, 'up')

    def test_transition_sends_once_and_repeats_do_not_spam(self):
        for _ in range(5):
            self.check('down', 503, 'HTTP 503')
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn('Shop is DOWN', msg.subject)
        self.assertIn('HTTP 503', msg.body)
        self.assertEqual(msg.to, ['admin@acme.test'])
        self.assertEqual(self.monitor.alert_state, 'down')
        self.assertEqual(self.monitor.consecutive_failures, 5)

    def test_recovery_sends_once(self):
        self.check('down')
        self.check('down')
        self.check('active', 200)
        self.check('active', 200)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('RECOVERED', mail.outbox[1].subject)
        self.assertEqual(self.monitor.alert_state, 'up')
        self.assertEqual(self.monitor.consecutive_failures, 0)

    def test_blip_then_recovery_sends_nothing(self):
        self.check('down')
        self.check('active', 200)
        self.check('down')
        self.assertEqual(len(mail.outbox), 0)

    def test_warning_counts_as_up_and_error_is_ignored(self):
        self.check('down')
        self.check('error', error='Security: refused')
        self.assertEqual(self.monitor.consecutive_failures, 1)
        self.check('warning', 301)
        self.assertEqual(self.monitor.consecutive_failures, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_on_down_false_sends_nothing(self):
        self.monitor.notify_on_down = False
        self.monitor.save()
        for _ in range(3):
            self.check('down')
        self.check('active', 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_disabled_does_not_crash_or_resend_later(self):
        from core import mailer
        s = SystemSetting.get_settings()
        s.smtp_enabled = False
        s.save()
        # The real helper, which returns None when SMTP is off.
        with patch('monitoring.down_notifications.get_smtp_connection',
                   mailer.get_smtp_connection):
            self.check('down')
            self.check('down')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.monitor.alert_state, 'down')
        self.check('down')
        self.assertEqual(len(mail.outbox), 0)  # no stale "is DOWN" later

    @override_settings(WEBSITE_DOWN_ALERT_THRESHOLD=3)
    def test_threshold_is_configurable(self):
        self.check('down')
        self.check('down')
        self.assertEqual(len(mail.outbox), 0)
        self.check('down')
        self.assertEqual(len(mail.outbox), 1)

    def test_check_status_runs_the_alerting(self):
        """The real check path calls the notifier (no network: the URL guard
        refuses or the request fails, either way nothing raises)."""
        with patch('monitoring.down_notifications._process') as proc:
            with patch('requests.Session.get', side_effect=Exception('down')), \
                 patch('core.safe_http.validate_url'):
                self.monitor.check_status()
        proc.assert_called_once()


@override_settings(WEBHOOK_DELIVERY_ASYNC=False)
class DownWebhookTests(TestCase):

    def setUp(self):
        from core.models import Webhook
        self.org = Organization.objects.create(name='Acme', slug='acme')
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Shop', url='https://shop.acme.test',
            notify_on_down=False)
        Webhook.objects.create(organization=self.org, name='h', url='https://h.test/',
                               events=['monitor.down', 'monitor.up', 'monitor.check_failed'])
        self.sent = []
        patcher = patch('core.webhook_sender.deliver_webhook',
                        side_effect=lambda w, e, d: self.sent.append((e, d)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, status):
        m = self.monitor
        m.status = status
        m.last_checked_at = timezone.now()
        m.save()
        with self.captureOnCommitCallbacks(execute=True):
            process_check_result(m)

    def test_webhooks_follow_transitions(self):
        self.check('down')
        self.check('down')
        self.check('down')
        self.check('active')
        self.assertEqual([e for e, _ in self.sent], [
            'monitor.check_failed', 'monitor.check_failed', 'monitor.down',
            'monitor.check_failed', 'monitor.up',
        ])
        self.assertEqual(self.sent[2][1]['monitor_id'], self.monitor.pk)
