"""Restore a verified pre-upgrade backup: database, uploaded files and (by
default) the code revision that was installed when it was taken.

    manage.py upgrade_restore [PATH] [--no-code] [--restore-keys] [--yes]

Without PATH it uses the backup the upgrade journal recorded. Stop the web
service and the scheduler first on a native install (see
docs/UPGRADE_AND_RECOVERY.md), then start them again afterwards.
"""
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.upgrade import journal, snapshot


class Command(BaseCommand):
    help = 'Restore a verified pre-upgrade backup (database, uploads, code revision, optionally keys)'

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?',
                            help='snapshot directory (default: the one the upgrade journal recorded)')
        parser.add_argument('--no-code', action='store_true', help='leave the code revision as it is')
        parser.add_argument('--restore-keys', action='store_true',
                            help='also put back .env (needed when APP_MASTER_KEY changed or was lost)')
        parser.add_argument('--yes', action='store_true', help='do not ask for confirmation')

    def handle(self, *args, **opts):
        path = opts['path'] or (journal.read() or {}).get('backup')
        if not path:
            raise CommandError('No backup recorded in the upgrade journal; pass the path '
                               '(`manage.py upgrade_backup --list`).')
        try:
            manifest = snapshot.load_manifest(path)
        except snapshot.SnapshotError as e:
            raise CommandError(str(e))
        self.stdout.write(f"Backup: {path}\n  taken {manifest.get('created_at')} on "
                          f"v{manifest.get('app_version')} @ {(manifest.get('git_sha') or '?')[:12]}\n"
                          f"  database: {manifest['db']['engine']}, uploads: "
                          f"{manifest.get('media', {}).get('files', 0)} file(s)")
        if not opts['yes']:
            if input('This replaces the current database and uploaded files. Type "restore": ') != 'restore':
                self.stdout.write('Cancelled.')
                return
        try:
            snapshot.restore(path, code=not opts['no_code'], keys=opts['restore_keys'],
                             out=self.stdout.write)
        except snapshot.SnapshotError as e:
            raise CommandError(str(e))
        # Check with a fresh interpreter: this process still has the newer code loaded.
        r = subprocess.run([sys.executable, str(Path(settings.BASE_DIR) / 'manage.py'),
                            'migrate', '--check'], capture_output=True, text=True,
                           cwd=str(settings.BASE_DIR))
        if r.returncode == 0:
            self.stdout.write(self.style.SUCCESS('Restored. migrate --check: the code and database agree.'))
        else:
            self.stdout.write(self.style.WARNING(
                'Restored, but `migrate --check` reports unapplied migrations for the code on disk:\n'
                + (r.stdout + r.stderr)[-1500:]))
        self.stdout.write('Now restart the web service and the scheduler '
                          '(Settings -> Updates shows the version once it is back).')
