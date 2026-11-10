"""Tests for the GUI updater (`core.updater.UpdateService`).

perform_update() hands the work to the verified pipeline in core/upgrade/;
the root-helper precheck still runs first.
"""
from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, TestCase

from audit.models import AuditLog
from core.updater import UpdateService


class UpdateServiceDelegationTests(TestCase):
    """perform_update() runs the verified pipeline (core/upgrade/apply.py).

    The #128 guarantee (v3.17.284) -- a failed run's output lands in
    AuditLog.extra_data.output_tail -- is tested on the pipeline itself in
    core/tests/test_upgrade_pipeline.py.
    """

    def test_reviewed_target_is_passed_through(self):
        from core.upgrade.revision import Target
        t = Target('release', 'v9.9.9', '1' * 40)
        with mock.patch.object(UpdateService, '_is_systemd_service', return_value=False), \
                mock.patch('core.upgrade.apply.run', return_value={
                    'success': True, 'refused': False, 'error': None, 'output': ['ok'],
                    'backup': '/b', 'target': t.as_dict()}) as run:
            result = UpdateService().perform_update(target=t)
        self.assertTrue(result['success'])
        self.assertIs(run.call_args.args[0], t)
        self.assertEqual(result['backup'], '/b')

    def test_nothing_to_install_is_an_error_not_a_crash(self):
        with mock.patch.object(UpdateService, '_is_systemd_service', return_value=False), \
                mock.patch.object(UpdateService, 'check_for_updates',
                                  return_value={'target': None, 'error': None}), \
                mock.patch('core.upgrade.apply.run') as run:
            result = UpdateService().perform_update()
        self.assertFalse(result['success'])
        self.assertIn('Nothing newer', result['error'])
        run.assert_not_called()
        self.assertTrue(AuditLog.objects.filter(action='system_update_failed').exists())

    def test_failure_from_the_pipeline_is_returned(self):
        from core.upgrade.revision import Target
        t = Target('release', 'v9.9.9', '1' * 40)
        with mock.patch.object(UpdateService, '_is_systemd_service', return_value=False), \
                mock.patch('core.upgrade.apply.run', return_value={
                    'success': False, 'refused': True, 'error': 'not signed', 'output': [],
                    'backup': None, 'target': t.as_dict()}):
            result = UpdateService().perform_update(target=t)
        self.assertFalse(result['success'])
        self.assertTrue(result['refused'])
        self.assertEqual(result['error'], 'not signed')


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

    def setUp(self):
        # These cover the legacy probes, used only without a usable root helper.
        from unittest.mock import patch
        p = patch('core.root_helper.is_usable', return_value=False)
        p.start()
        self.addCleanup(p.stop)

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


# ---------------------------------------------------------------------------
# v3.17.645 — the root helper is what updates use; no sudoers rules asked for
# ---------------------------------------------------------------------------

class RootHelperSudoCheckTests(SimpleTestCase):
    """Settings -> Updates showed "One-Time Setup Required" and asked for
    NOPASSWD systemctl rules on a host where the root helper ran every
    update. The check now asks whether the helper can be run."""

    def _service(self):
        from core.updater import UpdateService
        svc = UpdateService.__new__(UpdateService)
        svc.service_name = 'clientst0r-gunicorn.service'
        return svc

    def test_usable_helper_is_enough_without_legacy_probes(self):
        from unittest.mock import patch
        with patch('core.root_helper.is_usable', return_value=True), \
                patch('core.updater.subprocess.run') as legacy:
            self.assertTrue(self._service()._check_passwordless_sudo())
        legacy.assert_not_called()

    def test_is_usable_asks_sudo_policy_without_running_the_helper(self):
        import subprocess
        from unittest.mock import patch
        from core import root_helper
        for rc, expected in ((0, True), (1, False)):
            with patch('core.root_helper.is_installed', return_value=True), \
                    patch('core.root_helper.subprocess.run',
                          return_value=subprocess.CompletedProcess([], rc, '', '')) as run:
                self.assertEqual(root_helper.is_usable(), expected)
            self.assertEqual(run.call_args[0][0], ['/usr/bin/sudo', '-n', '-l', root_helper.HELPER_PATH])
        with patch('core.root_helper.is_installed', return_value=False), \
                patch('core.root_helper.subprocess.run') as run:
            self.assertFalse(root_helper.is_usable())
        run.assert_not_called()

    def test_apply_precheck_never_asks_for_sudoers_rules(self):
        from unittest.mock import patch
        svc = self._service()
        svc.current_version = '0.0.0'
        with patch.object(type(svc), '_is_systemd_service', return_value=True), \
                patch.object(type(svc), '_check_passwordless_sudo', return_value=False), \
                patch('core.updater.AuditLog'):
            message = str(svc.perform_update()['error'])
        self.assertIn('install-root-helper.sh', message)
        self.assertNotIn('NOPASSWD', message)
        self.assertNotIn('sudoers.d', message)

    def test_updates_template_has_no_sudoers_instructions(self):
        from pathlib import Path
        from django.conf import settings
        html = (Path(settings.BASE_DIR) / 'templates' / 'core' / 'system_updates.html').read_text()
        self.assertNotIn('NOPASSWD:', html)
        self.assertNotIn('sudoers.d/clientst0r-auto-update', html)
