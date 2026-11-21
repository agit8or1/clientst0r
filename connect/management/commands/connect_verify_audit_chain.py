"""Verify the Agit8or Connect audit hash chain, its anchors in the main
audit log, and the main audit log's HMAC chain that seals those anchors.

    manage.py connect_verify_audit_chain [--connect-only]

Exit status 1 if any Connect row was changed, removed or reordered, if the
Connect chain no longer contains an anchored head (truncated or rewritten),
or (unless --connect-only) if the main audit chain does not verify.
"""
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Re-compute the Connected Applications audit hash chain, check its anchors, and report tampering'

    def add_arguments(self, parser):
        parser.add_argument('--connect-only', action='store_true',
                            help='Skip the main audit log chain (audit/chain.py) verification.')

    def handle(self, *args, **opts):
        from connect import audit_anchor
        from connect.models import ConnectAuditEvent
        n = ConnectAuditEvent.objects.count()
        anchors = audit_anchor._anchors().count()
        problems = audit_anchor.verify()
        main_ok, main_problems = (True, []) if opts['connect_only'] else audit_anchor.verify_main()
        if not problems:
            self.stdout.write(self.style.SUCCESS(f'Audit chain intact ({n} entries, {anchors} anchor(s) match).'))
        else:
            for p in problems:
                self.stderr.write(self.style.ERROR(f'Audit chain BROKEN: {p}.'))
        if not opts['connect_only']:
            if main_ok:
                self.stdout.write(self.style.SUCCESS('Main audit log chain intact.'))
            else:
                for p in main_problems[:10]:
                    self.stderr.write(self.style.ERROR(f'Main audit log chain BROKEN: {p}.'))
        if problems or (main_ok is not True and not opts['connect_only']):
            sys.exit(1)
