"""
Baseline test coverage for the scheduling/ app.

Cron-driven scheduled tasks with sign-off support. Bug = silent
task-execution failure: a recurrence that never spawns the next
instance, an `is_overdue` that returns wrong, a `check_completion`
that doesn't fire when the last sign-off arrives.

Coverage areas:
  * `ScheduledTask.is_overdue` — true past due, false when completed,
    false when no due date.
  * `get_next_due_date` for each recurrence cadence.
  * `check_completion` — `require_all_signoffs` vs any.
  * `spawn_next_occurrence` — recurrence chain + tag/assignment copy.
  * `TaskAssignment` unique-together (task, user).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import Organization, Tag
from scheduling.models import ScheduledTask, TaskAssignment, TaskComment


class ScheduledTaskOverdueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SchedCo', slug='sched-co')

    def _task(self, **overrides):
        defaults = dict(organization=self.org, title='task',
                        due_date=timezone.now() + timedelta(days=1),
                        status='pending')
        defaults.update(overrides)
        return ScheduledTask.objects.create(**defaults)

    def test_is_overdue_true_when_past_due_and_pending(self):
        t = self._task(due_date=timezone.now() - timedelta(hours=1))
        self.assertTrue(t.is_overdue)

    def test_is_overdue_false_when_completed_even_past_due(self):
        t = self._task(due_date=timezone.now() - timedelta(hours=1),
                       status='completed')
        self.assertFalse(t.is_overdue)

    def test_is_overdue_false_when_cancelled_even_past_due(self):
        t = self._task(due_date=timezone.now() - timedelta(hours=1),
                       status='cancelled')
        self.assertFalse(t.is_overdue)

    def test_is_overdue_false_when_no_due_date(self):
        t = self._task(due_date=None)
        self.assertFalse(t.is_overdue)


class ScheduledTaskRecurrenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='RecCo', slug='rec-co')
        cls.base_due = timezone.now() + timedelta(days=10)

    def _task(self, recurrence, interval=None):
        return ScheduledTask.objects.create(
            organization=self.org, title=f'rec-{recurrence}',
            due_date=self.base_due, recurrence=recurrence,
            recurrence_interval_days=interval,
        )

    def test_none_returns_none(self):
        t = self._task('none')
        self.assertIsNone(t.get_next_due_date())

    def test_daily_adds_one_day(self):
        t = self._task('daily')
        self.assertEqual(t.get_next_due_date(), self.base_due + timedelta(days=1))

    def test_weekly_adds_seven_days(self):
        t = self._task('weekly')
        self.assertEqual(t.get_next_due_date(), self.base_due + timedelta(days=7))

    def test_biweekly_adds_fourteen_days(self):
        t = self._task('biweekly')
        self.assertEqual(t.get_next_due_date(), self.base_due + timedelta(days=14))

    def test_monthly_adds_thirty_days(self):
        # Implementation uses 30 days as the monthly approximation —
        # not calendar-aware. This test pins that contract; if the
        # behavior changes to month-aware, this test should update.
        t = self._task('monthly')
        self.assertEqual(t.get_next_due_date(), self.base_due + timedelta(days=30))

    def test_quarterly_adds_ninety_one_days(self):
        t = self._task('quarterly')
        self.assertEqual(t.get_next_due_date(), self.base_due + timedelta(days=91))

    def test_custom_uses_recurrence_interval_days(self):
        t = self._task('custom', interval=42)
        self.assertEqual(t.get_next_due_date(), self.base_due + timedelta(days=42))

    def test_custom_with_no_interval_returns_none(self):
        t = self._task('custom', interval=None)
        self.assertIsNone(t.get_next_due_date())

    def test_no_due_date_returns_none(self):
        t = ScheduledTask.objects.create(
            organization=self.org, title='no-due', recurrence='daily',
        )
        self.assertIsNone(t.get_next_due_date())


class ScheduledTaskCompletionTests(TestCase):
    """`check_completion` is the load-bearing piece of the sign-off flow.
    `require_all_signoffs` flips it from any-of to all-of."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='CompCo-sched', slug='comp-sched')
        cls.alice = User.objects.create_user('alice', email='a@x.com', password='pw')
        cls.bob = User.objects.create_user('bob', email='b@x.com', password='pw')

    def _task_with_two_assignees(self, *, require_all):
        t = ScheduledTask.objects.create(
            organization=self.org, title='two-assignees',
            due_date=timezone.now() + timedelta(days=5),
            require_all_signoffs=require_all,
        )
        TaskAssignment.objects.create(task=t, user=self.alice)
        TaskAssignment.objects.create(task=t, user=self.bob)
        return t

    def test_any_signoff_completes_task_when_not_require_all(self):
        t = self._task_with_two_assignees(require_all=False)
        # Alice signs off — that's enough.
        a = t.task_assignments.get(user=self.alice)
        a.sign_off()
        t.refresh_from_db()
        self.assertEqual(t.status, 'completed')
        self.assertIsNotNone(t.completed_at)

    def test_partial_signoff_does_not_complete_when_require_all(self):
        t = self._task_with_two_assignees(require_all=True)
        a = t.task_assignments.get(user=self.alice)
        a.sign_off()
        t.refresh_from_db()
        # Bob still hasn't acknowledged — task stays pending.
        self.assertEqual(t.status, 'pending')

    def test_all_signoffs_completes_task_when_require_all(self):
        t = self._task_with_two_assignees(require_all=True)
        for assn in t.task_assignments.all():
            assn.sign_off()
        t.refresh_from_db()
        self.assertEqual(t.status, 'completed')

    def test_completion_with_no_assignments_is_noop(self):
        t = ScheduledTask.objects.create(
            organization=self.org, title='no-assignees',
            due_date=timezone.now() + timedelta(days=1),
        )
        # No assignments — check_completion should NOT raise or change status.
        t.check_completion()
        t.refresh_from_db()
        self.assertEqual(t.status, 'pending')


class ScheduledTaskRecurrenceSpawnTests(TestCase):
    """When a recurring task completes, the next occurrence must spawn
    with the same configuration + assignments + tags."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SpawnCo', slug='spawn-co')
        cls.user = User.objects.create_user('spawn-user', email='sp@x.com', password='pw')

    def test_completing_recurring_task_spawns_next_occurrence(self):
        original_due = timezone.now() + timedelta(days=1)
        t = ScheduledTask.objects.create(
            organization=self.org, title='weekly thing',
            due_date=original_due, recurrence='weekly',
        )
        TaskAssignment.objects.create(task=t, user=self.user)
        tag = Tag.objects.create(name='cron-tag', organization=self.org)
        t.tags.add(tag)

        # Sign off — completes + spawns next.
        t.task_assignments.first().sign_off()

        children = ScheduledTask.objects.filter(parent_task=t)
        self.assertEqual(children.count(), 1)
        nxt = children.first()
        self.assertEqual(nxt.due_date, original_due + timedelta(days=7))
        self.assertEqual(nxt.recurrence, 'weekly')
        self.assertEqual(nxt.status, 'pending')
        # Assignments + tags carry over.
        self.assertEqual(nxt.task_assignments.count(), 1)
        self.assertEqual(nxt.task_assignments.first().user, self.user)
        self.assertEqual(list(nxt.tags.values_list('name', flat=True)), ['cron-tag'])

    def test_one_time_task_completion_does_not_spawn(self):
        t = ScheduledTask.objects.create(
            organization=self.org, title='one-shot',
            due_date=timezone.now() + timedelta(days=1),
            recurrence='none',
        )
        TaskAssignment.objects.create(task=t, user=self.user)
        t.task_assignments.first().sign_off()
        self.assertFalse(ScheduledTask.objects.filter(parent_task=t).exists())


class TaskAssignmentConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='AssnCo', slug='assn-co')
        cls.user = User.objects.create_user('assn-user', email='ax@x.com', password='pw')
        cls.task = ScheduledTask.objects.create(
            organization=cls.org, title='t',
            due_date=timezone.now() + timedelta(days=1),
        )

    def test_same_user_cannot_be_assigned_twice(self):
        TaskAssignment.objects.create(task=self.task, user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskAssignment.objects.create(task=self.task, user=self.user)


class TaskCalendarLocalDayTests(TestCase):
    """The task calendar groups by the installation's local day. A task due
    at 23:30 Eastern is already the next day in UTC, so it used to be filed
    under tomorrow."""

    def test_late_task_is_grouped_under_its_local_day(self):
        from datetime import date, datetime
        from unittest import mock
        from zoneinfo import ZoneInfo
        from django.conf import settings as django_settings
        from django.test import override_settings
        from accounts.models import Membership, Role
        middleware = [m for m in django_settings.MIDDLEWARE
                      if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]
        eastern = ZoneInfo('America/New_York')
        org = Organization.objects.create(name='Cal Eve', slug='cal-eve')
        user = User.objects.create_user('cal-eve', password='pw')
        Membership.objects.create(user=user, organization=org, role=Role.OWNER, is_active=True)
        ScheduledTask.objects.create(organization=org, title='Late', status='pending',
                                     due_date=datetime(2026, 11, 11, 23, 30, tzinfo=eastern))
        self.client.force_login(user)
        s = self.client.session
        s['current_organization_id'] = org.id
        s.save()
        noon = datetime(2026, 11, 11, 12, 0, tzinfo=eastern).astimezone(ZoneInfo('UTC'))
        with override_settings(TIME_ZONE='America/New_York', MIDDLEWARE=middleware,
                               SECURE_SSL_REDIRECT=False), \
                mock.patch('django.utils.timezone.now', return_value=noon):
            resp = self.client.get('/scheduling/calendar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([d for d, _ in resp.context['calendar_data']], [date(2026, 11, 11)])
