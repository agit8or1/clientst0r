"""Expire contract links and deadlines, queue reminders, raise renewal and
expiration alerts, retry finalization, apply access-log retention.

Scheduled hourly by the in-app scheduler ("Contract Reminders and Expirations")."""
from django.core.management.base import BaseCommand

from contracts import maintenance


class Command(BaseCommand):
    help = 'Contract documents: expirations, reminders, renewal alerts, retention.'

    def handle(self, *args, **options):
        self.stdout.write(f'contract maintenance: {maintenance.run()}')
