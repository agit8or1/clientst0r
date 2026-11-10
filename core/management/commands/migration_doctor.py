"""Show which migration a failed upgrade left unapplied or half applied, and
what to do about it. Read-only. See core/upgrade/doctor.py."""
from django.core.management.base import BaseCommand

from core.upgrade import doctor


class Command(BaseCommand):
    help = 'Diagnose unapplied / partially applied migrations (MySQL/MariaDB DDL is not transactional)'

    def handle(self, *args, **opts):
        for line in doctor.report_lines(doctor.diagnose()):
            self.stdout.write(line)
