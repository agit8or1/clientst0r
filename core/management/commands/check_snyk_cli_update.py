"""Check for a newer Snyk CLI and alert superusers once per new version.

Run daily by the scheduler (task `snyk_cli_update_check`). Does nothing when
Snyk is disabled or the CLI is not installed, and never installs anything.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Check for a newer Snyk CLI release and e-mail superusers once per new version'

    def handle(self, *args, **options):
        from core.snyk_cli import run_scheduled_check
        self.stdout.write(f'Snyk CLI update check: {run_scheduled_check()}')
