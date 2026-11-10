"""Where the last upgrade got to, and what to do if it did not finish.

    manage.py upgrade_status [--json]

Exit status 2 when the last upgrade needs recovery.
"""
import json
import sys

from django.core.management.base import BaseCommand

from core.upgrade import journal, snapshot


class Command(BaseCommand):
    help = 'Show the upgrade journal, the pre-upgrade backup and the recovery options'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **opts):
        a = journal.assess()
        data = a['journal'] or {}
        if opts['json']:
            self.stdout.write(json.dumps({k: v for k, v in a.items()}, indent=2, default=str))
        else:
            self.stdout.write(f"State: {a['state']}")
            self.stdout.write(a['message'] or '')
            if data:
                t = data.get('target') or {}
                self.stdout.write(f"  from v{data.get('prev_version')} @ {(data.get('prev_sha') or '?')[:12]}"
                                  f" to {t.get('ref')} @ {(t.get('sha') or '?')[:12]}")
                self.stdout.write(f"  stage: {data.get('stage')}  status: {data.get('status')}")
                if data.get('error'):
                    self.stdout.write(f"  error: {data['error']}")
                if data.get('backup'):
                    ok, detail = snapshot.is_verified(data['backup'])
                    self.stdout.write(f"  pre-upgrade backup: {data['backup']} ({detail})")
            if a['needs_recovery']:
                self.stdout.write('')
                self.stdout.write('Options (docs/UPGRADE_AND_RECOVERY.md):')
                self.stdout.write('  1. see what the migration left behind:  manage.py migration_doctor')
                self.stdout.write('  2. finish it (same reviewed revision):    manage.py upgrade_apply --resume')
                self.stdout.write('  3. go back to before the upgrade:        manage.py upgrade_restore'
                                  + (f" {data['backup']}" if data.get('backup') else ' PATH'))
        if a['needs_recovery']:
            sys.exit(2)
