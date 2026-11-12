"""Run due contract background jobs (e-mail, finalization) with retries.

Scheduled every minute by the in-app scheduler ("Contract Jobs")."""
from django.core.management.base import BaseCommand

from contracts import jobs


class Command(BaseCommand):
    help = 'Run due contract document jobs (invitation e-mails, reminders, finalization, signed copies).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        counts = jobs.run_due(limit=options['limit'])
        self.stdout.write(f'contract jobs: {counts or "nothing due"}')
