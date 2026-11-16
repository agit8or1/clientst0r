"""Verify the Agit8or Connect audit hash chain.

    manage.py connect_verify_audit_chain

Exit status 1 and the first bad sequence number if any row was changed,
removed or reordered.
"""
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Re-compute the Connected Applications audit hash chain and report tampering'

    def handle(self, *args, **opts):
        from connect import audit_log
        from connect.models import ConnectAuditEvent
        bad = audit_log.verify()
        n = ConnectAuditEvent.objects.count()
        if bad is None:
            self.stdout.write(self.style.SUCCESS(f'Audit chain intact ({n} entries).'))
            return
        self.stderr.write(self.style.ERROR(f'Audit chain BROKEN at entry {bad} (of {n}).'))
        sys.exit(1)
