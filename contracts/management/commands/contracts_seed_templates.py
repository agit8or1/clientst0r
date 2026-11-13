"""Create any missing starter contract templates and clauses (sample language)."""
from django.core.management.base import BaseCommand

from contracts.starter_templates import seed


class Command(BaseCommand):
    help = 'Create missing starter contract templates and clauses (idempotent).'

    def handle(self, *args, **options):
        self.stdout.write(f'created {seed()} starter template(s)')
