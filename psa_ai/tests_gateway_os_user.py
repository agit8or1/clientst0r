"""Phase 57.3: the AI gateway worker running as its own OS user.

deploy/setup-ai-gateway-user.sh runs the worker as `clientst0r-ai`, which
can't read .env (APP_MASTER_KEY) or the web app's log files, and shares the
gateway key directory with the web app's group. These tests pin what the
Python side needs for that: an unreadable .env is tolerated by the worker
only, the worker keeps DB_PASSWORD (and nothing else secret), logs to the
console only, and keygen can make the key directory group-readable.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase

from psa_ai.services import gateway_keys

_SCRIPT = r'''
import json, os, sys
import dotenv
def _unreadable(*a, **k):
    raise PermissionError(13, "Permission denied", ".env")
dotenv.load_dotenv = _unreadable
import django
try:
    django.setup()
except PermissionError:
    print(json.dumps({"setup": "PermissionError"})); sys.exit(0)
from django.conf import settings
handlers = [h.get("class") for h in settings.LOGGING.get("handlers", {}).values()]
print(json.dumps({
    "setup": "ok",
    "db_password": os.environ.get("DB_PASSWORD"),
    "other_token": os.environ.get("SOME_API_TOKEN"),
    "master": os.environ.get("APP_MASTER_KEY"),
    "file_handlers": [h for h in handlers if "File" in (h or "")],
}))
'''


class WorkerAsOwnUserSettingsTests(SimpleTestCase):

    def _run(self, **env):
        base = {k: v for k, v in os.environ.items() if k != 'CLIENTST0R_PROCESS_ROLE'}
        base.update(env)
        r = subprocess.run([sys.executable, '-c', _SCRIPT], cwd=str(settings.BASE_DIR), env=base,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_worker_starts_without_a_readable_env_and_keeps_only_db_password(self):
        out = self._run(CLIENTST0R_PROCESS_ROLE='ai_gateway', DJANGO_SETTINGS_MODULE='config.settings_ai_gateway',
                        AI_GATEWAY_MODE='worker', DB_PASSWORD='db-pass-for-worker',
                        SOME_API_TOKEN='must-go', APP_MASTER_KEY='must-go-too')
        self.assertEqual(out['setup'], 'ok')
        self.assertEqual(out['db_password'], 'db-pass-for-worker')
        self.assertIsNone(out['other_token'])
        self.assertIsNone(out['master'])
        self.assertEqual(out['file_handlers'], [])

    def test_web_app_still_fails_on_an_unreadable_env(self):
        out = self._run(DJANGO_SETTINGS_MODULE='config.settings')
        self.assertEqual(out['setup'], 'PermissionError')


class GroupReadableKeyDirTests(SimpleTestCase):

    def test_default_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = gateway_keys.generate(Path(tmp) / 'keys')
            self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((d / 'private.key').stat().st_mode), 0o600)

    def test_group_readable_dir_keeps_private_key_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = gateway_keys.generate(Path(tmp) / 'keys', group_readable=True)
            self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o750)
            self.assertEqual(stat.S_IMODE((d / 'private.key').stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((d / 'public.key').stat().st_mode), 0o644)

    def test_keygen_command_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'gw'
            with self.settings(AI_GATEWAY_KEY_DIR=str(target)):
                call_command('ai_gateway_keygen', '--group-readable', stdout=open(os.devnull, 'w'))
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o750)


class DeploymentFilesTests(SimpleTestCase):
    """The unit and the setup script agree on the user and keep the master
    key out of the worker's environment."""

    def test_unit_runs_as_its_own_user_without_the_app_env_file(self):
        unit = (Path(settings.BASE_DIR) / 'deploy' / 'clientst0r-ai-gateway.service').read_text()
        self.assertIn('\nUser=clientst0r-ai\n', unit)
        self.assertIn('\nGroup=clientst0r-ai\n', unit)
        self.assertIn('EnvironmentFile=/etc/clientst0r/ai-gateway.env', unit)
        self.assertNotIn('/.env', unit.replace('ai-gateway.env', ''))
        self.assertIn('UnsetEnvironment=APP_MASTER_KEY', unit)

    def test_setup_script_checks_isolation(self):
        script = (Path(settings.BASE_DIR) / 'deploy' / 'setup-ai-gateway-user.sh').read_text()
        self.assertIn('AI_USER=clientst0r-ai', script)
        self.assertIn('can read', script)          # refuses when the worker could read .env
        r = subprocess.run(['bash', '-n', str(Path(settings.BASE_DIR) / 'deploy' / 'setup-ai-gateway-user.sh')],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
