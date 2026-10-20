"""Ping WAN connections that are due and alert on down / recovery.

Run every minute by the scheduler (task `check_wans`); each WAN is checked
at its own interval. See locations.wan_checks.

    python manage.py check_wans [--force]
"""
from django.core.management.base import BaseCommand

from locations.wan_checks import run_due_checks


class Command(BaseCommand):
    help = 'Check WAN connections with monitoring enabled that are due (or all with --force).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Check every monitored WAN now, ignoring intervals.')

    def handle(self, *args, **options):
        counts = run_due_checks(force=options['force'])
        total = sum(counts.values())
        if not total:
            self.stdout.write('No WAN connections due for a check.')
            return
        self.stdout.write(f"Checked {total} WAN connection(s): {counts['up']} answered, "
                          f"{counts['down']} no answer, {counts['error']} check error(s).")
