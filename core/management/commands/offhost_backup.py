"""Off-host backups (Phase 94.3): run, verify, status, and decrypt for restore.

    manage.py offhost_backup tick        what the scheduler runs (does what is due)
    manage.py offhost_backup run         back up now
    manage.py offhost_backup verify      verify the newest archive at the destination now
    manage.py offhost_backup status
    manage.py offhost_backup decrypt ARCHIVE OUTPUT.tar.gz [--key-file FILE]
    manage.py offhost_backup check-archive ARCHIVE [--key-file FILE]

decrypt / check-archive are for disaster recovery and do not need a working
configuration or even this install's database: the key is read from
--key-file or typed at a prompt (never from the command line, where other
users could see it in the process list).
"""
import getpass
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Encrypted off-host backups: run, verify, status, decrypt.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['tick', 'run', 'verify', 'status', 'decrypt', 'check-archive'])
        parser.add_argument('paths', nargs='*')
        parser.add_argument('--key-file', help='File holding the backup key (csbk1_…)')

    def _out(self, msg):
        self.stdout.write(msg)

    def _key(self, opts):
        if opts.get('key_file'):
            return Path(opts['key_file']).read_text().strip()
        return getpass.getpass('Backup key (csbk1_…): ').strip()

    def handle(self, *args, **opts):
        from core.offhost_backup import archive, crypto, service
        action = opts['action']
        try:
            if action == 'tick':
                self._out(service.tick(out=self._out))
            elif action == 'run':
                r = service.run_backup(trigger='cli', out=self._out)
                self._out(self.style.SUCCESS(r.detail))
            elif action == 'verify':
                r = service.run_verify(trigger='cli', out=self._out)
                self._out(self.style.SUCCESS(r.detail))
            elif action == 'status':
                from core.models import OffhostBackupConfig
                cfg = OffhostBackupConfig.get()
                h = service.health()
                self._out(f'Destination: {cfg.destination_label()}')
                self._out(f'Enabled: {cfg.enabled}   state: {h["state"]}')
                self._out(f'Backup key fingerprint: {cfg.backup_key_fingerprint or "none"}')
                self._out(f'Last backup: {cfg.last_backup_at} {cfg.last_backup_status} {cfg.last_backup_detail}')
                self._out(f'Last verify: {cfg.last_verify_at} {cfg.last_verify_status} {cfg.last_verify_detail}')
            elif action == 'decrypt':
                if len(opts['paths']) != 2:
                    raise CommandError('usage: offhost_backup decrypt ARCHIVE OUTPUT.tar.gz')
                src, dst = opts['paths']
                if Path(dst).exists():
                    raise CommandError(f'{dst} already exists')
                n = crypto.decrypt_file(src, dst, self._key(opts))
                self._out(self.style.SUCCESS(f'Decrypted {n} bytes to {dst} (mode 0600). '
                                             f'Extract with: tar -xzf {dst}'))
            elif action == 'check-archive':
                if len(opts['paths']) != 1:
                    raise CommandError('usage: offhost_backup check-archive ARCHIVE')
                with tempfile.TemporaryDirectory(prefix='offhost-check-') as work:
                    ok, checks = service.verify_file(opts['paths'][0], self._key(opts), Path(work))
                for c, o, d in checks:
                    self._out(f'  [{"ok" if o else "FAIL"}] {c}: {d}')
                if not ok:
                    raise CommandError('The archive did not pass verification.')
                self._out(self.style.SUCCESS('The archive passed verification.'))
        except (service.NotReady, crypto.BackupCryptoError, archive.ArchiveError) as e:
            raise CommandError(str(e))
        except CommandError:
            raise
        except Exception as e:
            raise CommandError(service._safe_message(e))
