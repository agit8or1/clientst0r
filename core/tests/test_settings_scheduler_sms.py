"""Administration -> Automation -> Task Scheduler and Communications -> SMS Provider.

* The scheduler form used to int() whatever was typed, so one blank or
  non-numeric interval was a 500 and nothing was saved; out-of-range values
  were stored. It now keeps the old interval for that task and says so.
  A shorter interval also moves the next run up instead of waiting out the old one.
* The status box said "Scheduler is installed and running!" whatever was
  true; it now reports whether any task has started recently.
* The SMS provider list offered Sinch and AWS SNS, which core/sms.py cannot
  send through, so every later send failed. They are no longer accepted.
"""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ScheduledTask, SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SchedulerPageTests(TestCase):

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('sched-admin', 'a@example.com', 'x')
        self.client.force_login(self.admin)
        ScheduledTask.get_or_create_defaults()
        self.task = ScheduledTask.objects.get(task_type='website_monitoring')

    def _post(self, **fields):
        data = {}
        for t in ScheduledTask.objects.all():
            data[f'task_{t.id}_interval'] = str(t.interval_minutes)
            if t.enabled:
                data[f'task_{t.id}_enabled'] = 'on'
        data.update(fields)
        return self.client.post(reverse('core:settings_scheduler'), data)

    def test_bad_interval_keeps_old_value_and_does_not_500(self):
        before = self.task.interval_minutes
        for bad in ('', 'abc', '0', '99999', '-3'):
            r = self._post(**{f'task_{self.task.id}_interval': bad})
            self.assertEqual(r.status_code, 302, bad)
            self.task.refresh_from_db()
            self.assertEqual(self.task.interval_minutes, before, bad)

    def test_valid_interval_and_disable_are_saved_and_next_run_moves_up(self):
        ScheduledTask.objects.filter(pk=self.task.pk).update(
            interval_minutes=1440, last_run_at=timezone.now(),
            next_run_at=timezone.now() + timedelta(days=1))
        data = {f'task_{self.task.id}_interval': '5'}  # enabled box left out: disabled
        data.update({f'task_{t.id}_interval': str(t.interval_minutes)
                     for t in ScheduledTask.objects.exclude(pk=self.task.pk)})
        self.client.post(reverse('core:settings_scheduler'), data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.interval_minutes, 5)
        self.assertFalse(self.task.enabled)
        self.assertLess(self.task.next_run_at, timezone.now() + timedelta(minutes=6))

    def test_status_box_does_not_claim_running_without_evidence(self):
        ScheduledTask.objects.update(last_run_at=None)
        html = self.client.get(reverse('core:settings_scheduler')).content.decode()
        self.assertNotIn('installed and running', html)
        self.assertIn('No task has started in the last 15 minutes', html)
        ScheduledTask.objects.filter(pk=self.task.pk).update(last_run_at=timezone.now())
        html = self.client.get(reverse('core:settings_scheduler')).content.decode()
        self.assertIn('Tasks are being started', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SmsProviderTests(TestCase):

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('sms-admin', 'b@example.com', 'x')
        self.client.force_login(self.admin)

    def test_unsendable_providers_are_refused(self):
        for provider in ('sinch', 'aws_sns', 'nonsense'):
            r = self.client.post(reverse('core:settings_sms'), {'sms_provider': provider})
            self.assertEqual(r.status_code, 302)
            self.assertNotEqual(SystemSetting.get_settings().sms_provider, provider)

    def test_supported_provider_is_saved_and_list_hides_the_others(self):
        self.client.post(reverse('core:settings_sms'), {'sms_provider': 'telnyx'})
        self.assertEqual(SystemSetting.get_settings().sms_provider, 'telnyx')
        html = self.client.get(reverse('core:settings_sms')).content.decode()
        self.assertNotIn('value="sinch"', html)
        self.assertNotIn('value="aws_sns"', html)
