"""Phase 12: erase secure replies whose retention has ended.

A secure reply (`psa.TicketSecureReply`) is kept for
`psa.ticket_secure.SECURE_REPLY_RETENTION_HOURS` and is unreadable after
that even before this runs; this command removes the sealed text itself and
stamps `purged_at`. The row (who, when, via what) stays for the ticket's
history. Run hourly by the in-app scheduler (`psa_purge_secure_replies`).
"""
from django.core.management.base import BaseCommand

from psa.ticket_secure import purge_expired_replies


class Command(BaseCommand):
    help = 'Erase the text of secure ticket replies past their retention period.'

    def handle(self, *args, **options):
        n = purge_expired_replies()
        self.stdout.write(f'Erased {n} expired secure repl{"y" if n == 1 else "ies"}.')
