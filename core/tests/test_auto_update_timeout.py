"""manage.py auto_update must not give up on a normal upgrade."""
import subprocess
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from core.management.commands import auto_update


class AutoUpdateTimeoutTests(TestCase):
    def test_limit_leaves_room_for_backup_and_migrations(self):
        # v3.17.668 on prod took a little over 5 minutes end to end.
        self.assertGreaterEqual(auto_update.UPDATE_SCRIPT_TIMEOUT, 30 * 60)

    def test_script_runs_with_the_limit(self):
        done = subprocess.CompletedProcess([], 0)
        with mock.patch.object(auto_update.subprocess, 'run', return_value=done) as run:
            call_command('auto_update', stdout=mock.MagicMock())
        self.assertEqual(run.call_args.kwargs['timeout'], auto_update.UPDATE_SCRIPT_TIMEOUT)

    def test_timeout_message_says_the_upgrade_may_still_be_running(self):
        err = subprocess.TimeoutExpired('auto_update.sh', auto_update.UPDATE_SCRIPT_TIMEOUT)
        with mock.patch.object(auto_update.subprocess, 'run', side_effect=err):
            with self.assertRaises(CommandError) as ctx:
                call_command('auto_update', stdout=mock.MagicMock())
        self.assertIn('may still be running', str(ctx.exception))
