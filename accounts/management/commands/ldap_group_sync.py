"""Re-check LDAP group -> customer membership mappings for a batch of LDAP
users (accounts.ldap_group_sync). Scheduled as task `ldap_group_sync`.

A run that could not use the directory changes nothing (or stops where it
lost the directory) and exits with an error, so Settings > Scheduler shows
it as failed with the reason.
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.ldap_group_sync import (
    DEFAULT_BATCH_SIZE, DEFAULT_MIN_INTERVAL_MINUTES, run_sync,
)


class Command(BaseCommand):
    help = 'Re-check mapped LDAP group membership for LDAP users (bounded batch)'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
        parser.add_argument('--min-interval-minutes', type=int,
                            default=DEFAULT_MIN_INTERVAL_MINUTES,
                            help='Do not re-check a user more often than this')

    def handle(self, *args, **options):
        batch = max(1, min(int(options['batch_size']), 1000))
        interval = max(1, int(options['min_interval_minutes']))
        report = run_sync(batch_size=batch, min_interval_minutes=interval)
        if report.status == 'failed':
            raise CommandError(report.summary())
        if options.get('verbosity', 1):
            self.stdout.write(report.summary())
