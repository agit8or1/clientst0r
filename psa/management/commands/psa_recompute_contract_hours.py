"""
v3.17.600: recompute `Contract.hours_used_minutes` from the time entries.

Before v3.17.600 the field was a running counter bumped by
`TicketTimeEntry.save()`: non-billable entries and excluded roles were
counted, a re-saved entry was counted again, and deleted entries were never
subtracted. Migration `psa.0070_recompute_contract_hours_used` corrects every
contract once on upgrade; this command does the same on demand (e.g. after a
bulk import or a raw-SQL fix) and is safe to run any number of times.

    manage.py psa_recompute_contract_hours            # all contracts
    manage.py psa_recompute_contract_hours --contract 12 --contract 15
    manage.py psa_recompute_contract_hours --dry-run  # report drift only
"""
from django.core.management.base import BaseCommand

from psa.models import Contract


class Command(BaseCommand):
    help = 'Recompute Contract.hours_used_minutes from qualifying time entries.'

    def add_arguments(self, parser):
        parser.add_argument('--contract', type=int, action='append',
                            help='Contract id to recompute (repeatable). '
                                 'Default: all contracts.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report contracts whose stored value differs; '
                                 'change nothing.')

    def handle(self, *args, **opts):
        qs = Contract.objects.all().order_by('pk')
        if opts.get('contract'):
            qs = qs.filter(pk__in=opts['contract'])
        dry = opts['dry_run']
        checked = changed = 0
        for c in qs.iterator():
            checked += 1
            stored = c.hours_used_minutes or 0
            actual = c.compute_hours_used_minutes()
            if stored == actual:
                continue
            changed += 1
            self.stdout.write(
                f'{"[dry] " if dry else ""}{c.name} (#{c.pk}): '
                f'{stored} -> {actual} minutes')
            if not dry:
                c.recompute_hours_used()
        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}Checked {checked} contract(s); '
            f'{changed} {"would change" if dry else "corrected"}.'))
