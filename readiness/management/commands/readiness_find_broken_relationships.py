"""Report (and optionally delete) assets.Relationship rows whose source or
target no longer resolves.

    manage.py readiness_find_broken_relationships
    manage.py readiness_find_broken_relationships --delete
    manage.py readiness_find_broken_relationships --delete --include-other-customer
    manage.py readiness_find_broken_relationships --org 12

Rows with an unknown type string are reported but never deleted.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from readiness.relationships import deletable, find_broken_relationships


class Command(BaseCommand):
    help = 'Find relationships whose source or target record no longer exists.'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true',
                            help='Delete relationships with a missing end.')
        parser.add_argument('--include-other-customer', action='store_true',
                            help='With --delete, also delete links to another customer\'s record.')
        parser.add_argument('--org', type=int, action='append', dest='orgs',
                            help='Limit to this customer id (repeatable).')

    def handle(self, *args, **opts):
        broken = find_broken_relationships(opts['orgs'])
        current = None
        for b in broken:
            org = b.relationship.organization
            if org != current:
                current = org
                self.stdout.write(f'\n{org.name} (#{org.pk})')
            self.stdout.write(f'  #{b.relationship.pk} {b.relationship}: ' + '; '.join(b.problems))
        self.stdout.write(f'\n{len(broken)} broken relationship(s) found.')
        if not opts['delete']:
            return
        doomed = deletable(broken, include_other_customer=opts['include_other_customer'])
        with transaction.atomic():
            for b in doomed:
                b.relationship.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {len(doomed)} relationship(s).'))
        skipped = len(broken) - len(doomed)
        if skipped:
            self.stdout.write(f'{skipped} left in place (unknown type, or other-customer '
                              f'link without --include-other-customer).')
