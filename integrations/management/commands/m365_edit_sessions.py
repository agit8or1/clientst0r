"""Edit in Microsoft 365 upkeep (scheduled task ``m365_edit_sessions``).

    manage.py m365_edit_sessions

* ends sessions whose user lost permission (and those the signals missed);
* deletes working copies that the connection's policy says to delete, for
  sessions that ended while Microsoft could not be reached;
* for sessions idle longer than the connection's "remind after" time: ends
  them when the Microsoft copy has no changes clientst0r lacks (cTag
  unchanged), otherwise reminds the user (in-app status + e-mail when SMTP
  is set up). It never imports anything.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Remind about and clean up idle Edit in Microsoft 365 sessions (never imports).'

    def handle(self, *args, **options):
        from integrations.m365docs.editing import run_maintenance
        result = run_maintenance()
        self.stdout.write(', '.join(f'{k}={v}' for k, v in result.items()))
