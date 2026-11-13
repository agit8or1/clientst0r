"""Send recurring pulse checks that are due (scheduled task ``pulse_send_due``).

    manage.py pulse_send_due

One send per check per month / quarter: running it again in the same period
does nothing. Does nothing while pulse checks are turned off.
"""
from django.core.management.base import BaseCommand

from pulse.sending import send_due


class Command(BaseCommand):
    help = 'Send recurring pulse checks that are due this period.'

    def handle(self, *args, **options):
        out = send_due()
        if out['disabled']:
            self.stdout.write('Pulse checks are turned off; nothing sent.')
            return
        self.stdout.write(f"Pulse checks: {out['sent']} sent, {out['skipped']} already sent this period.")
