"""Tests for the GUI updater (`core.updater.UpdateService`).

Focused on v3.17.284 (issue #128): when the update script exits non-zero,
the captured stdout/stderr lines must land in `AuditLog.extra_data.output_tail`
so superusers can diagnose without SSHing in.
"""
from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, TestCase

from audit.models import AuditLog
from core.updater import UpdateService


class UpdateServiceFailureCaptureTests(TestCase):
    """Phase / issue-128 (v3.17.284): persist failed-update output."""

    def _fake_response(self, script_text: str = '#!/bin/bash\necho hi\n'):
        r = mock.MagicMock()
        r.text = script_text
        r.raise_for_status.return_value = None
        return r

    def _fake_process(self, lines, returncode):
        proc = mock.MagicMock()
        # `iter(process.stdout.readline, '')` is what the updater uses
        # to consume output. A list iterator works as a stand-in.
        proc.stdout.readline.side_effect = list(lines) + ['']
        proc.wait.return_value = None
        proc.returncode = returncode
        return proc

    def test_failed_run_persists_output_tail_to_audit_log(self):
        updater = UpdateService()
        fake_lines = [
            'Step 1/5: Fetching latest code...\n',
            'Step 1/5: Code updated. New version: 3.17.999\n',
            'Step 2/5: Installing Python dependencies...\n',
            'Step 2/5: Core dependencies installed\n',
            'Step 3/5: Running database migrations...\n',
            'Traceback (most recent call last):\n',
            '  File "/srv/venv/bin/django-admin", line 8, in <module>\n',
            'django.db.utils.ProgrammingError: column "x" of relation does not exist\n',
            'ERROR: command failed at line 99: migrate (exit 1)\n',
        ]
        proc = self._fake_process(fake_lines, returncode=1)

        with mock.patch.object(updater, '_is_systemd_service', return_value=False), \
             mock.patch('core.updater.requests.get',
                         return_value=self._fake_response()), \
             mock.patch('core.updater.subprocess.Popen', return_value=proc):
            result = updater.perform_update(user=None, progress_tracker=None)

        self.assertFalse(result['success'])
        self.assertIn('exited with code 1', result['error'])

        # Audit row must exist + carry the full output tail
        row = AuditLog.objects.filter(action='system_update_failed').first()
        self.assertIsNotNone(row)
        tail = row.extra_data.get('output_tail', '')
        self.assertIn('ProgrammingError', tail)
        self.assertIn('Traceback', tail)
        # Steps that DID complete should be reflected
        self.assertIn('Step 2/5: Core dependencies installed', tail)

    def test_output_tail_capped_at_50kb(self):
        updater = UpdateService()
        # Generate ~120kb of fake output
        big_lines = [f'noisy line {i}: ' + ('x' * 200) + '\n' for i in range(600)]
        proc = self._fake_process(big_lines, returncode=1)

        with mock.patch.object(updater, '_is_systemd_service', return_value=False), \
             mock.patch('core.updater.requests.get',
                         return_value=self._fake_response()), \
             mock.patch('core.updater.subprocess.Popen', return_value=proc):
            updater.perform_update(user=None, progress_tracker=None)

        row = AuditLog.objects.filter(action='system_update_failed').first()
        self.assertIsNotNone(row)
        tail = row.extra_data.get('output_tail', '')
        self.assertLessEqual(len(tail), 50_000)

    def test_successful_run_does_not_create_failure_audit(self):
        updater = UpdateService()
        proc = self._fake_process(
            ['Step 1/5: Fetching latest code...\n',
             'Step 5/5: Scheduling restart...\n',
             'Update complete!\n'],
            returncode=0,
        )

        with mock.patch.object(updater, '_is_systemd_service', return_value=False), \
             mock.patch('core.updater.requests.get',
                         return_value=self._fake_response()), \
             mock.patch('core.updater.subprocess.Popen', return_value=proc):
            result = updater.perform_update(user=None, progress_tracker=None)

        self.assertTrue(result['success'])
        # Failed-update audit row must NOT exist for a successful run
        self.assertFalse(
            AuditLog.objects.filter(action='system_update_failed').exists()
        )


# ---------------------------------------------------------------------------
# v3.17.520 — _check_passwordless_sudo must not conclude from one denied probe
# ---------------------------------------------------------------------------

class PasswordlessSudoCheckTests(SimpleTestCase):
    """The check reported "not configured" on a host where updates worked.

    It led with `sudo -n systemd-run --version` and, on refusal, returned False
    immediately — never reaching the `systemctl status` probe that would have
    succeeded. That was fine while sudoers granted systemd-run bare; under the
    least-privilege ruleset (v3.17.518) systemd-run is pinned to the single
    restart invocation the updater issues, so `--version` is denied and the
    Settings -> Updates page showed a spurious "One-Time Setup Required" banner.
    """

    def _service(self):
        from core.updater import UpdateService
        svc = UpdateService.__new__(UpdateService)      # skip __init__ / disk probing
        svc.service_name = 'clientst0r-gunicorn.service'
        return svc

    def _run_with(self, outcomes):
        """Patch subprocess.run to answer each probe from `outcomes`, keyed by
        a substring of the command."""
        import subprocess
        from unittest.mock import patch

        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(cmd)
            joined = ' '.join(cmd)
            for needle, (rc, stderr) in outcomes.items():
                if needle in joined:
                    return subprocess.CompletedProcess(cmd, rc, stdout='', stderr=stderr)
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='sudo: a password is required\n')

        return patch('core.updater.subprocess.run', side_effect=fake_run), calls

    def test_denied_systemd_run_still_passes_via_systemctl_probe(self):
        """The exact regression: systemd-run denied, systemctl status allowed."""
        patcher, calls = self._run_with({
            'systemd-run': (1, 'sudo: a password is required\n'),
            'systemctl status': (0, ''),
        })
        with patcher:
            self.assertTrue(self._service()._check_passwordless_sudo())
        self.assertTrue(any('systemctl' in ' '.join(c) for c in calls),
                        'systemctl probe was never attempted')

    def test_inactive_service_still_counts_as_configured(self):
        """`systemctl status` exits non-zero for a stopped unit — that still
        proves sudo permitted the command."""
        patcher, _ = self._run_with({'systemctl status': (3, '')})
        with patcher:
            self.assertTrue(self._service()._check_passwordless_sudo())

    def test_all_probes_denied_returns_false(self):
        patcher, _ = self._run_with({
            'systemctl status': (1, 'sudo: a password is required\n'),
            'systemd-run': (1, 'sudo: a password is required\n'),
        })
        with patcher:
            self.assertFalse(self._service()._check_passwordless_sudo())

    def test_not_allowed_to_execute_is_treated_as_denied(self):
        patcher, _ = self._run_with({
            'systemctl status': (1, "sudo: user is not allowed to execute\n"),
            'systemd-run': (1, "sudo: user is not allowed to execute\n"),
        })
        with patcher:
            self.assertFalse(self._service()._check_passwordless_sudo())
