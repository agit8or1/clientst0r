"""Fire ticket reminders that have come due (roadmap 52.21).

Run every minute by the in-app scheduler (task type psa_ticket_reminders).
Each due reminder is stamped ``fired_at`` once; it then shows in the owner's
My Work page and the top bar's notification bell until completed.

Usage:
    python manage.py psa_ticket_reminders
"""
from django.core.management.base import BaseCommand

from psa.reminders import fire_due


class Command(BaseCommand):
    help = 'Mark due ticket reminders as fired so they notify their owners.'

    def handle(self, *args, **options):
        n = fire_due()
        self.stdout.write(f'{n} reminder(s) fired.')
