"""A scheduled task that fails must not record success.

Nine of `run_scheduler`'s `run_*` methods wrapped their `call_command` in
`try/except Exception` and wrote the failure to stdout. `run_task` then
returned normally, `handle` called `task.mark_completed()` with no error, and
the task recorded `last_status='success'`. A nightly job could fail every
night while the Scheduled Tasks page showed a green tick; the only trace was a
line in the systemd journal.

The caller already handled exceptions properly — `mark_completed(error=...)`
records `failed` and the message — so those guards were not adding protection,
only hiding the outcome.
"""
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from core.models import ScheduledTask


# The nine that used to swallow, and the command each delegates to.
SWALLOWED = [
    ('network_config_backup', 'backup_network_configs'),
    ('psa_sync', 'sync_psa'),
    ('password_breach_scan', 'check_password_breaches'),
    ('equipment_catalog_update', 'update_equipment_catalog'),
    ('python_dep_scan', 'scan_python_packages'),
    ('update_check', 'check_updates'),
    ('cleanup_stuck_scans', 'cleanup_stuck_scans'),
    ('scheduling_alerts', 'check_scheduled_task_alerts'),
    ('security_scan', 'run_security_scan'),
]


def due_task(task_type):
    from datetime import timedelta

    from django.utils import timezone
    task, _ = ScheduledTask.objects.get_or_create(
        task_type=task_type,
        defaults={'description': task_type, 'enabled': True,
                  'interval_minutes': 60},
    )
    task.enabled = True
    task.last_status = ''
    task.next_run_at = timezone.now() - timedelta(minutes=5)
    task.save()
    return task


class FailingTasksAreRecordedAsFailedTests(TestCase):

    def _run_with_failing_command(self, task_type, command_name):
        task = due_task(task_type)
        real = call_command

        def _boom(name, *a, **kw):
            if name == command_name:
                raise RuntimeError('the job blew up')
            return real(name, *a, **kw)

        with mock.patch('django.core.management.call_command', side_effect=_boom):
            call_command('run_scheduler', verbosity=0)
        task.refresh_from_db()
        return task

    def test_every_previously_swallowing_task_records_failure(self):
        for task_type, command_name in SWALLOWED:
            with self.subTest(task=task_type):
                ScheduledTask.objects.filter(task_type=task_type).delete()
                task = self._run_with_failing_command(task_type, command_name)
                self.assertEqual(task.last_status, 'failed',
                                 f'{task_type} reported success despite failing')
                self.assertIn('blew up', task.last_error)

    def test_a_task_that_succeeds_still_records_success(self):
        task = due_task('update_check')
        with mock.patch('django.core.management.call_command') as cc:
            cc.side_effect = lambda name, *a, **kw: (
                None if name != 'run_scheduler' else call_command(name, *a, **kw))
            call_command('run_scheduler', verbosity=0)
        task.refresh_from_db()
        self.assertEqual(task.last_status, 'success')
        self.assertEqual(task.last_error, '')


class NoHandlerSwallowsAgainTests(TestCase):
    """Guards the shape, so the pattern cannot creep back in."""

    def test_no_run_method_catches_an_exception_without_re_raising(self):
        import ast
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[2] / (
            'core/management/commands/run_scheduler.py')
        tree = ast.parse(src.read_text())

        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('run_'):
                for handler in [n for n in ast.walk(node)
                                if isinstance(n, ast.ExceptHandler)]:
                    if not any(isinstance(x, ast.Raise)
                               for x in ast.walk(handler)):
                        offenders.append(f'{node.name}:{handler.lineno}')
        self.assertEqual(
            offenders, [],
            'a run_* method swallows its exception again — the task will '
            'report success while the job fails')
