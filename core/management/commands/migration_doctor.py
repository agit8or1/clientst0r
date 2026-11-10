"""Show which migration a failed upgrade left unapplied or half applied, and
what to do about it. Read-only. See core/upgrade/doctor.py.

--check exits 1 when a pending migration is already partly or wholly in the
schema (half applied, or applied but unrecorded): migrating on top of that
fails, and a backup taken now would capture the damaged state. The update
script runs it before taking the pre-upgrade backup."""
import sys

from django.core.management.base import BaseCommand

from core.upgrade import doctor

DAMAGED = ('partial', 'applied_unrecorded')


class Command(BaseCommand):
    help = 'Diagnose unapplied / partially applied migrations (MySQL/MariaDB DDL is not transactional)'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true',
                            help='exit 1 if a pending migration is already partly in the schema')

    def handle(self, *args, **opts):
        findings = doctor.diagnose()
        damaged = [f for f in findings if f.state in DAMAGED]
        if opts['check']:
            if not damaged:
                self.stdout.write('No pending migration is already in the schema.')
                return
            for line in doctor.report_lines(damaged):
                self.stdout.write(line)
            sys.exit(1)
        for line in doctor.report_lines(findings):
            self.stdout.write(line)
