"""
The update must actually reload the server, or say it did not (v3.17.595).

The nightly clientst0r-auto-update.service ran with NoNewPrivileges=true, which
makes sudo refuse to run. Every `sudo systemctl reload` failed, the last
fallback backgrounded a `sudo systemctl restart` that failed unseen, and the
script logged "Update completed successfully!" — so each night pulled and
migrated new code while gunicorn kept serving the old version.

These tests run the real reload block from deploy/update_instructions.sh with
sudo, systemctl, ps and kill replaced by shell functions, so each path is
exercised without touching a real service.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings as django_settings
from django.test import SimpleTestCase

_START = '# v3.17.595: if nothing below manages a reload or restart'
_END = 'log "Update complete! Please wait 10 seconds then refresh."'


class UpdateReloadTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(django_settings.BASE_DIR)
        script = (base / 'deploy' / 'update_instructions.sh').read_text(encoding='utf-8')
        start, end = script.index(_START), script.index(_END)
        cls.block = script[start:end]
        cls.unit = (base / 'deploy' / 'clientst0r-auto-update.service').read_text(encoding='utf-8')
        cls.installer = (base / 'scripts' / 'install_auto_update.sh').read_text(encoding='utf-8')

    def run_block(self, *, sudo_ok, main_pid='4242', pid_uid=None, nnp=0,
                  root_helper='/nonexistent/clientst0r-root-helper'):
        """Run the reload block; return (exit code, output, calls, progress)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            calls = tmp / 'calls'
            progress = tmp / 'progress.json'
            progress.write_text(json.dumps({'status': 'completed'}))
            uid = subprocess.run(['id', '-u'], capture_output=True, text=True).stdout.strip()
            harness = f'''
set -euo pipefail
log() {{ echo "$1"; }}
sudo() {{ echo "sudo $*" >> {calls}; {'return 0' if sudo_ok else 'return 1'}; }}
fake_systemctl() {{ [ "$1" = show ] && echo "{main_pid}"; }}
ps() {{ echo "{pid_uid if pid_uid is not None else uid}"; }}
kill() {{ echo "kill $*" >> {calls}; }}
SERVICE=clientst0r-gunicorn.service
SYSTEMCTL=fake_systemctl
SYSTEMD_RUN=/usr/bin/systemd-run
BASE_DIR=/srv/app
NO_NEW_PRIVS={nnp}
ROOT_HELPER={root_helper}
PROGRESS_FILE={progress}
PYTHON_BIN=python3
{self.block}
'''
            result = subprocess.run(['bash', '-c', harness], capture_output=True,
                                    text=True, timeout=30)
            return (result.returncode, result.stdout + result.stderr,
                    calls.read_text() if calls.exists() else '',
                    json.loads(progress.read_text()))

    def test_root_helper_reload_is_preferred(self):
        """v3.17.597: with the root helper installed, it does the reload."""
        code, out, calls, progress = self.run_block(sudo_ok=True, root_helper='/bin/true')
        self.assertEqual(code, 0, out)
        self.assertIn('sudo -n /bin/true reload', calls)
        self.assertNotIn('systemctl', calls.replace('fake_systemctl', ''))
        self.assertIn('via root helper', out)

    def test_sudo_reload_is_used_when_it_works(self):
        code, out, calls, progress = self.run_block(sudo_ok=True)
        self.assertEqual(code, 0, out)
        self.assertIn('reload clientst0r-gunicorn.service', calls)
        self.assertNotIn('kill', calls)
        self.assertEqual(progress['status'], 'completed')

    def test_without_sudo_the_master_is_sent_sighup_directly(self):
        """The nightly case: sudo is blocked, but gunicorn runs as us."""
        code, out, calls, progress = self.run_block(sudo_ok=False, nnp=1)
        self.assertEqual(code, 0, out)
        self.assertIn('kill -HUP 4242', calls)
        self.assertIn('via SIGHUP to master PID 4242', out)
        self.assertEqual(progress['status'], 'completed')

    def test_a_master_owned_by_another_user_is_not_signalled(self):
        code, out, calls, progress = self.run_block(sudo_ok=False, pid_uid='0', nnp=1)
        self.assertNotIn('kill', calls)
        self.assertEqual(code, 1, out)

    def test_no_way_to_reload_fails_loudly_instead_of_claiming_success(self):
        code, out, calls, progress = self.run_block(sudo_ok=False, main_pid='0', nnp=1)
        self.assertEqual(code, 1, out)
        self.assertIn('could not reload or restart', out)
        self.assertIn('no_new_privs', out)
        self.assertNotIn('scheduled via nohup', out)
        self.assertEqual(progress['status'], 'failed')

    def test_auto_update_unit_does_not_set_no_new_privileges(self):
        """Its whole job is to call sudo and crontab; that flag breaks both."""
        for text in (self.unit, self.installer):
            self.assertNotRegex(text, r'(?m)^\s*NoNewPrivileges\s*=\s*(true|yes)')
