"""Pull Microsoft 365 and Pax8 license subscriptions.

    python manage.py sync_licenses [--org SLUG] [--no-assignments]
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import Organization
from licensing.sync import sync_all


class Command(BaseCommand):
    help = 'Sync license subscriptions from Microsoft 365 and Pax8 connections.'

    def add_arguments(self, parser):
        parser.add_argument('--org', help='Only this customer (slug); Microsoft 365 only.')
        parser.add_argument('--no-assignments', action='store_true',
                            help='Skip the per-user assignment listing (subscription totals only).')

    def handle(self, *, org=None, no_assignments=False, **kwargs):
        organization = None
        if org:
            organization = Organization.objects.filter(slug=org).first()
            if organization is None:
                raise CommandError(f'No customer with slug {org!r}')
        failures = 0
        for r in sync_all(organization, with_assignments=not no_assignments):
            self.stdout.write(str(r))
            failures += bool(r.errors)
        if failures:
            self.stdout.write(self.style.WARNING(f'{failures} connection(s) reported errors'))
