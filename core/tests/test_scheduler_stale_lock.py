"""A scheduled task survives the process that was running it being killed.

`ScheduledTask` took its run lock by writing `last_status='running'` and cleared
it only after the work returned. Nothing else in the codebase ever cleared it —
no reaper, and no reset on Settings > Scheduler. So any death between those two
writes (a reboot, an OOM kill, `systemctl stop` during the nightly breach scan)
left the row at 'running' forever, and `should_run()` returned False forever
after. The task went off the schedule silently, with the only recovery being a
hand-edit of the database.

The lock is now taken with a conditional UPDATE, which both expires a claim
older than STALE_RUN_MINUTES and stops two overlapping scheduler processes from
running the same task twice.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import ScheduledTask


class StaleRunReclaimTests(TestCase):

    def setUp(self):
        # update_or_create, not create: some task types are seeded by data
        # migrations, so the row may already exist.
        self.task, _ = ScheduledTask.objects.update_or_create(
            task_type='website_monitoring',
            defaults={'interval_minutes': 5, 'enabled': True,
                      'last_status': 'pending', 'last_run_at': None,
                      'next_run_at': None},
        )

    def _interrupted(self, minutes_ago):
        """The exact row a killed scheduler process leaves behind."""
        started = timezone.now() - timedelta(minutes=minutes_ago)
        ScheduledTask.objects.filter(pk=self.task.pk).update(
            last_status='running', last_run_at=started, next_run_at=None,
        )
        self.task.refresh_from_db()
        return started

    def test_live_run_is_not_disturbed(self):
        self._interrupted(minutes_ago=1)
        self.assertFalse(self.task.is_stale_run())
        self.assertFalse(self.task.should_run())
        self.assertFalse(self.task.claim())

    def test_abandoned_run_is_reclaimed(self):
        self._interrupted(minutes_ago=ScheduledTask.STALE_RUN_MINUTES + 1)
        self.assertTrue(self.task.is_stale_run())
        self.assertTrue(self.task.should_run())
        self.assertTrue(self.task.claim())

    def test_reclaim_does_not_need_next_run_at(self):
        """A task interrupted on its very first run has no next_run_at to fall
        back on — before the fix that was a second, independent way to be stuck
        forever."""
        self._interrupted(minutes_ago=ScheduledTask.STALE_RUN_MINUTES + 1)
        self.assertIsNone(self.task.next_run_at)
        self.assertTrue(self.task.should_run())

    def test_running_with_no_start_time_is_stale(self):
        ScheduledTask.objects.filter(pk=self.task.pk).update(
            last_status='running', last_run_at=None,
        )
        self.task.refresh_from_db()
        self.assertTrue(self.task.is_stale_run())
        self.assertTrue(self.task.claim())

    def test_the_run_after_a_reclaim_reschedules_normally(self):
        """The point of reclaiming: the task is back on its cadence."""
        self._interrupted(minutes_ago=ScheduledTask.STALE_RUN_MINUTES + 1)
        self.task.claim()
        self.task.mark_completed()
        self.task.refresh_from_db()
        self.assertEqual(self.task.last_status, 'success')
        self.assertFalse(self.task.should_run())
        self.assertAlmostEqual(
            (self.task.next_run_at - self.task.last_run_at).total_seconds(),
            5 * 60,
            delta=1,
        )


class ClaimExclusionTests(TestCase):
    """Two scheduler processes, one task. The timer fires every minute and
    several shipped tasks run longer than that, so this overlap is routine."""

    def setUp(self):
        self.task, _ = ScheduledTask.objects.update_or_create(
            task_type='psa_sync',
            defaults={'interval_minutes': 60, 'enabled': True,
                      'last_status': 'pending', 'last_run_at': None,
                      'next_run_at': None},
        )

    def test_only_one_of_two_processes_claims_it(self):
        first = ScheduledTask.objects.get(pk=self.task.pk)
        second = ScheduledTask.objects.get(pk=self.task.pk)

        self.assertTrue(first.should_run())
        self.assertTrue(second.should_run())

        self.assertTrue(first.claim())
        self.assertFalse(second.claim())

    def test_a_disabled_task_cannot_be_claimed(self):
        ScheduledTask.objects.filter(pk=self.task.pk).update(enabled=False)
        self.task.refresh_from_db()
        self.assertFalse(self.task.should_run())
        self.assertFalse(self.task.claim())


class SchedulerCommandTests(TestCase):

    def test_command_reports_and_recovers_a_stale_task(self):
        from io import StringIO
        from unittest.mock import patch
        from django.core.management import call_command

        task, _ = ScheduledTask.objects.update_or_create(
            task_type='update_check',
            defaults={'interval_minutes': 60, 'enabled': True},
        )
        ScheduledTask.objects.filter(pk=task.pk).update(
            last_status='running',
            last_run_at=timezone.now() - timedelta(minutes=ScheduledTask.STALE_RUN_MINUTES + 1),
        )

        out = StringIO()
        with patch.object(
            __import__('core.management.commands.run_scheduler', fromlist=['Command']).Command,
            'run_task',
            lambda self, t: None,
        ):
            call_command('run_scheduler', stdout=out)

        output = out.getvalue()
        self.assertIn('Reclaimed', output)
        self.assertIn('stale run(s) reclaimed', output)

        task.refresh_from_db()
        self.assertEqual(task.last_status, 'success')
