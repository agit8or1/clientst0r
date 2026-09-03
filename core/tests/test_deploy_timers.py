"""
Every shipped timer must be installable (v3.17.534).

install.sh only ever wrote the gunicorn unit. Nothing referenced deploy/*.timer
at all, so a fresh install came up with no scheduler, no monitoring and no
breach scan — the app looked healthy and simply never did anything on a
schedule. These tests pin the two halves of the fix: the units exist and are
well-formed, and the installer actually installs them.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings as django_settings
from django.test import SimpleTestCase


class DeployUnitTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = Path(django_settings.BASE_DIR)
        cls.deploy = cls.base / 'deploy'
        cls.installer = (cls.base / 'install.sh').read_text(encoding='utf-8')

    def timers(self):
        return sorted(self.deploy.glob('clientst0r-*.timer'))

    def test_timers_are_shipped(self):
        self.assertGreaterEqual(len(self.timers()), 6,
                                'expected the background timers in deploy/')

    def test_every_timer_has_a_matching_service(self):
        """A timer whose service is missing fails silently at every firing."""
        missing = [t.name for t in self.timers()
                   if not t.with_suffix('.service').is_file()]
        self.assertEqual(missing, [], f'timers with no service unit: {missing}')

    def test_every_service_declares_how_to_run(self):
        for service in sorted(self.deploy.glob('clientst0r-*.service')):
            text = service.read_text(encoding='utf-8')
            self.assertIn('ExecStart=', text, f'{service.name} has no ExecStart')
            self.assertIn('[Service]', text, f'{service.name} has no [Service]')

    def test_every_timer_declares_a_schedule(self):
        for timer in self.timers():
            text = timer.read_text(encoding='utf-8')
            self.assertTrue(
                'OnUnitActiveSec' in text or 'OnCalendar' in text,
                f'{timer.name} never fires — no OnUnitActiveSec or OnCalendar')

    def test_the_installer_installs_the_timers(self):
        """The regression this file exists for: nothing referenced them."""
        self.assertIn('install_timer_units', self.installer)
        self.assertIn('install_timer_units\n', self.installer,
                      'the function is defined but never called')

    def test_the_installer_rewrites_the_reference_paths(self):
        """deploy/ units hardcode the reference install so they can be copied
        by hand there. Any other install needs user and paths rewritten, or the
        units point at a directory that does not exist."""
        self.assertIn('s|/home/administrator|$INSTALL_DIR|g', self.installer)
        self.assertIn('User=$USER', self.installer)

    def test_units_that_act_on_their_own_are_not_enabled_by_default(self):
        """Applying releases unattended, and writing to a live accounting
        system, are decisions an operator makes — not installer defaults."""
        match = re.search(r'enable_by_default="([^"]*)"', self.installer)
        self.assertIsNotNone(match, 'no default enable list found')
        defaults = match.group(1).split()
        for risky in ('auto-update', 'accounting-sync'):
            self.assertNotIn(risky, defaults,
                             f'{risky} must not be enabled by the installer')

    def test_the_core_jobs_are_enabled_by_default(self):
        """Without the scheduler the app silently does nothing on a schedule,
        which is the failure that started this."""
        match = re.search(r'enable_by_default="([^"]*)"', self.installer)
        defaults = match.group(1).split()
        for needed in ('scheduler', 'monitor'):
            self.assertIn(needed, defaults)

    def test_uninstall_removes_the_timers(self):
        """Left behind, they fire against a deleted directory forever."""
        self.assertIn('/etc/systemd/system/clientst0r-*.timer', self.installer)
