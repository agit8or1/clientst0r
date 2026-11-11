"""Agreements: issue any revision a save failed to issue, then e-mail
outstanding signers of each open agreement's current revision.

Run by the in-app scheduler ("Agreement Signature Reminders"). Throttled per
person and revision (the agreement's reminder interval, at most five per
revision); people with e-mail notifications off are skipped; nothing is sent
when SMTP is not configured.
"""
from django.core.management.base import BaseCommand

from docs import agreements


class Command(BaseCommand):
    help = 'Issue pending agreement revisions and send throttled signature reminders.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List who would be reminded; send nothing.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        issued = 0 if dry else agreements.issue_pending_revisions()
        counts = agreements.send_reminders(dry_run=dry, stdout=self.stdout)
        self.stdout.write(f'agreement revisions issued: {issued}; reminders: {counts}')
