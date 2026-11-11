"""Remove Office quarantined saves past retention and expired diagnostics
files; close expired sessions. Scheduled hourly as task
`office_purge_quarantine` (core.ScheduledTask)."""
from django.core.management.base import BaseCommand

from office.quarantine import purge_expired


class Command(BaseCommand):
    help = 'Purge expired Office quarantine entries and diagnostics documents.'

    def handle(self, *args, **options):
        result = purge_expired()
        self.stdout.write(
            f"Removed {result['quarantine_removed']} quarantined save(s), "
            f"{result['diagnostic_files_removed']} diagnostics file(s); "
            f"closed {result['sessions_expired']} expired session(s).")
