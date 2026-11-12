"""Take and verify a pre-upgrade backup (database + uploaded files + keys).

    manage.py upgrade_backup                         create + verify (exit 1 if it does not verify)
    manage.py upgrade_backup --verify PATH           re-verify an existing backup
    manage.py upgrade_backup --check-verified PATH   exit 0 only if PATH verified and is unchanged
    manage.py upgrade_backup --list
    manage.py upgrade_backup --export PATH --to FILE --passphrase-file F
    manage.py upgrade_backup --import FILE --passphrase-file F
    manage.py upgrade_backup --prune                 apply the retention rules now
    manage.py upgrade_backup --delete PATH           remove one backup (not the newest verified,
                                                     not the one the upgrade journal points at)

Creating a backup also grooms the backup directory (before, counting the new
one, and after it verifies); --no-groom skips that. Retention rules:
core/upgrade/retention.py.

See core/upgrade/snapshot.py and docs/UPGRADE_AND_RECOVERY.md.
"""
import argparse
import json
import sys

from django.core.management.base import BaseCommand, CommandError

from core.upgrade import retention, snapshot


class Command(BaseCommand):
    help = 'Create and verify a pre-upgrade backup that includes the keys needed to restore it'

    def add_arguments(self, parser):
        parser.add_argument('--reason', default='manual')
        parser.add_argument('--verify', metavar='PATH')
        parser.add_argument('--check-verified', metavar='PATH')
        parser.add_argument('--list', action='store_true')
        parser.add_argument('--export', metavar='PATH', help='snapshot directory to export')
        parser.add_argument('--import', dest='import_file', metavar='FILE')
        parser.add_argument('--to', metavar='FILE', help='export destination')
        parser.add_argument('--passphrase-file', metavar='FILE',
                            help='file holding the export passphrase (never pass it on the command line)')
        parser.add_argument('--print-path', action='store_true',
                            help='print the backup path as the last line (for scripts)')
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--code-sha', help='revision that matches the database (if the '
                            'checked-out code is already newer)')
        parser.add_argument('--code-version', help='version of --code-sha')
        parser.add_argument('--prune', action='store_true',
                            help='remove backups the retention rules no longer keep')
        parser.add_argument('--delete', metavar='PATH',
                            help='remove one backup directory directly under the backup root')
        parser.add_argument('--no-groom', action='store_true',
                            help='when creating a backup, do not apply the retention rules')
        parser.add_argument('--in-upgrade', action='store_true',
                            help='called by the update script during its own run (its journal '
                                 'entry says running; grooming is still allowed)')
        parser.add_argument('--trigger', default='cli', help=argparse.SUPPRESS)

    def _passphrase(self, opts):
        if not opts['passphrase_file']:
            raise CommandError('--passphrase-file is required')
        with open(opts['passphrase_file'], encoding='utf-8') as f:
            return f.read().strip()

    def _groom(self, opts, out, reserve=0):
        if opts['no_groom']:
            return
        try:
            retention.prune(trigger=opts['trigger'], out=out, reserve=reserve,
                            in_run=opts['in_upgrade'])
        except retention.RetentionRefused as e:
            out(f'Old backups were not cleaned up: {e}')

    def handle(self, *args, **opts):
        out = self.stdout.write
        try:
            if opts['list']:
                rows = snapshot.list_snapshots()
                if opts['json']:
                    out(json.dumps(rows, indent=2))
                    return
                for r in rows:
                    out(f"{r['path']}  v{r['app_version']}  {r['created_at']}  "
                        f"{'VERIFIED' if r['verified'] else 'not verified'}  {r['reason'] or ''}")
                return
            if opts['prune']:
                try:
                    removed = retention.prune(trigger=opts['trigger'], out=out,
                                              in_run=opts['in_upgrade'])
                except retention.RetentionRefused as e:
                    if opts['trigger'] == 'scheduler':
                        out(f'Skipped: {e}')   # the next daily run tries again
                        return
                    raise CommandError(str(e))
                out(f'Removed {len(removed)} backup(s).' if removed else
                    'Nothing to remove: every backup is within the retention rules.')
                return
            if opts['delete']:
                try:
                    path = retention.delete(opts['delete'], out=out, trigger=opts['trigger'])
                except retention.RetentionRefused as e:
                    raise CommandError(str(e))
                out(f'Removed {path}')
                return
            if opts['check_verified']:
                ok, detail = snapshot.is_verified(opts['check_verified'])
                out(f"{opts['check_verified']}: {detail}")
                if not ok:
                    sys.exit(1)
                return
            if opts['export']:
                if not opts['to']:
                    raise CommandError('--to FILE is required with --export')
                dest = snapshot.export(opts['export'], opts['to'], self._passphrase(opts))
                out(f'Exported (passphrase-encrypted, mode 0600): {dest}')
                return
            if opts['import_file']:
                path = snapshot.import_export(opts['import_file'], self._passphrase(opts))
                report = snapshot.verify(path, out=out)
                out(f"Imported to {path}: {'verified' if report['ok'] else 'DID NOT VERIFY'}")
                if not report['ok']:
                    sys.exit(1)
                return
            created = not opts['verify']
            if opts['verify']:
                path = opts['verify']
            else:
                # Free the space first, counting the backup about to be taken
                # (never below one verified backup).
                self._groom(opts, out, reserve=1)
                path = snapshot.create(reason=opts['reason'], out=out, code_sha=opts['code_sha'],
                                       code_version=opts['code_version'])
            out('Verifying the backup (restore test)...')
            report = snapshot.verify(path, out=out)
        except snapshot.SnapshotError as e:
            raise CommandError(str(e))
        if opts['json']:
            out(json.dumps(report, indent=2))
        if not report['ok']:
            self.stderr.write(f'Backup {path} did NOT verify.')
            sys.exit(1)
        if created:
            self._groom(opts, out)
        out(self.style.SUCCESS(f"Backup verified ({report['level']}): {path}"))
        if opts['print_path']:
            out(str(path))
