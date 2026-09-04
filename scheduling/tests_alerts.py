"""
Task warning windows (v3.17.535).

`alert_before_hours` and the alert-sending command already existed. What was
missing: the lead time could only be expressed in hours (a week meant typing
168), and nothing showed the warning anywhere — it was email-only, so a task
creeping up on you was invisible on the very screens you look at.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Organization
from scheduling.forms import ScheduledTaskForm
from scheduling.models import ScheduledTask

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class AlertLeadTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='AlertCo', slug='alert-co')

    def task(self, **kw):
        defaults = dict(organization=self.org, title='Job', status='pending',
                        due_date=timezone.now() + timedelta(hours=48))
        defaults.update(kw)
        return ScheduledTask.objects.create(**defaults)

    def test_days_are_stored_as_hours(self):
        """Hours stay canonical so the existing alert command is untouched."""
        t = self.task()
        t.set_alert_lead(7, 'days')
        self.assertEqual(t.alert_before_hours, 168)
        self.assertEqual(t.alert_before_unit, 'days')

    def test_the_lead_time_reads_back_in_the_unit_it_was_set_in(self):
        """168 hours is a correct but useless thing to show someone who typed 7."""
        t = self.task()
        t.set_alert_lead(7, 'days')
        self.assertEqual(t.alert_lead_display, '7 days')
        t.set_alert_lead(4, 'hours')
        self.assertEqual(t.alert_lead_display, '4 hours')

    def test_singular_reads_correctly(self):
        t = self.task()
        t.set_alert_lead(1, 'days')
        self.assertEqual(t.alert_lead_display, '1 day')

    def test_a_nonsense_unit_falls_back_to_hours(self):
        t = self.task()
        t.set_alert_lead(3, 'fortnights')
        self.assertEqual(t.alert_before_unit, 'hours')
        self.assertEqual(t.alert_before_hours, 3)

    def test_a_negative_lead_is_clamped(self):
        t = self.task()
        t.set_alert_lead(-5, 'hours')
        self.assertEqual(t.alert_before_hours, 0)


class AlertWindowTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='WindowCo', slug='window-co')

    def task(self, hours_until_due, lead_hours=24, status='pending'):
        return ScheduledTask.objects.create(
            organization=self.org, title='Job', status=status,
            due_date=timezone.now() + timedelta(hours=hours_until_due),
            alert_before_hours=lead_hours)

    def test_outside_the_window_is_quiet(self):
        self.assertFalse(self.task(48, lead_hours=24).is_alerting)

    def test_inside_the_window_warns(self):
        self.assertTrue(self.task(12, lead_hours=24).is_alerting)

    def test_overdue_is_not_also_alerting(self):
        """Overdue is the louder state. Both at once would put two badges
        saying different things on the same row."""
        overdue = self.task(-2, lead_hours=24)
        self.assertTrue(overdue.is_overdue)
        self.assertFalse(overdue.is_alerting)

    def test_completed_and_cancelled_tasks_never_warn(self):
        for status in ('completed', 'cancelled'):
            self.assertFalse(self.task(1, status=status).is_alerting, status)

    def test_a_task_with_no_due_date_never_warns(self):
        t = ScheduledTask.objects.create(
            organization=self.org, title='Someday', status='pending')
        self.assertFalse(t.is_alerting)
        self.assertIsNone(t.alert_at)

    def test_a_zero_lead_disables_the_warning(self):
        """0 means "don't warn me", not "warn me always"."""
        self.assertFalse(self.task(12, lead_hours=0).is_alerting)

    def test_alert_at_is_the_due_date_minus_the_lead(self):
        t = self.task(48, lead_hours=24)
        self.assertAlmostEqual(
            (t.due_date - t.alert_at).total_seconds(), 24 * 3600, delta=1)


class AlertFormTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='FormCo', slug='form-co')

    def _data(self, **kw):
        data = {
            'title': 'Quarterly check', 'priority': 'normal',
            'recurrence': 'none',
            'due_date': (timezone.now() + timedelta(days=10)
                         ).strftime('%Y-%m-%dT%H:%M'),
            'alert_before_value': '3', 'alert_before_unit': 'days',
        }
        data.update(kw)
        return data

    def test_days_entered_on_the_form_are_stored_as_hours(self):
        form = ScheduledTaskForm(self._data(), org=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        task = form.save(commit=False)
        task.organization = self.org
        task.save()
        self.assertEqual(task.alert_before_hours, 72)
        self.assertEqual(task.alert_before_unit, 'days')

    def test_hours_entered_on_the_form_are_stored_verbatim(self):
        form = ScheduledTaskForm(
            self._data(alert_before_value='6', alert_before_unit='hours'),
            org=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        task = form.save(commit=False)
        task.organization = self.org
        task.save()
        self.assertEqual(task.alert_before_hours, 6)

    def test_editing_shows_the_lead_back_in_its_own_unit(self):
        task = ScheduledTask.objects.create(
            organization=self.org, title='Job', status='pending',
            alert_before_hours=168, alert_before_unit='days')
        form = ScheduledTaskForm(instance=task, org=self.org)
        self.assertEqual(form.fields['alert_before_value'].initial, 7)
        self.assertEqual(form.fields['alert_before_unit'].initial, 'days')


class AlertRecurrenceTests(TestCase):

    def test_a_recurring_task_keeps_its_unit(self):
        """Otherwise next quarter's copy reads "168 hours" for a 7-day lead."""
        org = Organization.objects.create(name='RecurCo', slug='recur-co')
        task = ScheduledTask.objects.create(
            organization=org, title='Quarterly', status='pending',
            recurrence='quarterly',
            due_date=timezone.now() + timedelta(days=1),
            alert_before_hours=168, alert_before_unit='days')
        nxt = task.spawn_next_occurrence()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.alert_before_unit, 'days')
        self.assertEqual(nxt.alert_lead_display, '7 days')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AlertDisplayTests(TestCase):
    """The warning has to appear where people actually look."""

    def setUp(self):
        self.org = Organization.objects.create(name='ShowCo', slug='show-co')
        self.admin = User.objects.create_superuser('showadmin', 's@x.com', 'pw')
        self.client.force_login(self.admin)
        session = self.client.session
        session['2fa_prompted'] = True
        session['current_organization_id'] = self.org.id
        session.save()
        self.task = ScheduledTask.objects.create(
            organization=self.org, title='Firewall swap', status='pending',
            due_date=timezone.now() + timedelta(hours=6),
            alert_before_hours=24)

    def test_the_calendar_shows_the_warning(self):
        r = self.client.get(reverse('scheduling:task_calendar'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Due soon')

    def test_the_calendar_is_quiet_outside_the_window(self):
        self.task.due_date = timezone.now() + timedelta(days=30)
        self.task.save()
        r = self.client.get(reverse('scheduling:task_calendar'))
        self.assertNotContains(r, 'Due soon')

    def test_the_task_list_marks_it(self):
        r = self.client.get(reverse('scheduling:task_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'fa-bell')
