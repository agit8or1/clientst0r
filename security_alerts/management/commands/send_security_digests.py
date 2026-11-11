"""Phase 9.4: e-mail each customer's opted-in contacts a digest of their
unresolved security alerts. Run weekly by the in-app scheduler
(`send_security_digests`); safe to run by hand — a contact who received a
digest in the last six days is skipped unless --force is given.

    manage.py send_security_digests [--org SLUG] [--dry-run] [--force]
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import Organization
from security_alerts.digest import send_digests


class Command(BaseCommand):
    help = 'Send the weekly security alert digest to opted-in customer contacts.'

    def add_arguments(self, parser):
        parser.add_argument('--org', help='Only this customer (slug).')
        parser.add_argument('--dry-run', action='store_true', help='List what would be sent; send nothing.')
        parser.add_argument('--force', action='store_true', help='Ignore the six-day resend guard.')

    def handle(self, *args, **options):
        org = None
        if options.get('org'):
            org = Organization.objects.filter(slug=options['org']).first()
            if org is None:
                raise CommandError(f'No organization with slug {options["org"]!r}.')
        out = send_digests(org=org, dry_run=options['dry_run'], force=options['force'], stdout=self.stdout)
        if out['no_smtp']:
            self.stdout.write(self.style.WARNING('SMTP is not configured; no digests were sent.'))
            return
        self.stdout.write(
            f'Customers: {out["customers"]}, sent: {out["sent"]}, nothing unresolved: {out["empty"]}, '
            f'skipped (sent this week): {out["skipped_recent"]}, failed: {out["failed"]}.')
        if out['failed']:
            raise CommandError(f'{out["failed"]} digest e-mail(s) failed; see the log.')
