"""Phase 101.2: compare the prepaid-hour ledger with the old hour counter.

    manage.py prepaid_ledger_reconcile --dry-run      # report only (writes nothing)
    manage.py prepaid_ledger_reconcile                # also repair: open missing ledgers,
                                                      # re-sync blocks, refresh cached balances
    manage.py prepaid_ledger_reconcile --contract 12

For every contract with an allowance it prints, per block, the hours
purchased, consumed, expired and left, then the remaining hours the old
counter shows ("before"), what the ledger shows ("after"), and what the
balance would be if only approved time counted. Notes explain differences:

  cycle reset        retainer billed per cycle: the ledger shows the current cycle
  expired rollover   the old counter dropped rolled-over hours on expiry even when used
  unapproved         hours of time not (yet) approved still counted from the opening balance
  overlap            time also counted by another contract (the old counter's double count)
  needs choice       approved time waiting for someone to pick the agreement
  cache              cached balance differs from the postings (repaired without --dry-run)

Invoices are never touched by this command.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.utils import timezone

from psa.billing import coverage, ledger, seed
from psa.models import (
    Contract, PrepaidLedgerAccount, PrepaidPosting, TicketTimeEntry, TimesheetSubmission,
)

ZERO = Decimal('0')


def _h(v):
    if v is None:
        return 'unlimited'
    return f'{Decimal(v).quantize(Decimal("0.01")):.2f}'


class Command(BaseCommand):
    help = 'Report (and with no --dry-run, repair) the prepaid-hour ledger against the old hour counter.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report only; write nothing.')
        parser.add_argument('--contract', type=int, action='append', help='Only this contract id (repeatable).')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        today = timezone.localdate()
        qs = Contract.objects.select_related('client_org').order_by('client_org__name', 'pk')
        if opts.get('contract'):
            qs = qs.filter(pk__in=opts['contract'])
        approved_subs = set(TimesheetSubmission.objects.filter(status='approved').values_list('pk', flat=True))
        totals = {'contracts': 0, 'changed': 0, 'missing': 0, 'repaired': 0}
        self.stdout.write(f'Prepaid-hour ledger reconciliation, {today}'
                          + (' (dry run: nothing written)' if dry else ''))
        for c in qs:
            acc = PrepaidLedgerAccount.objects.filter(contract=c).first()
            if acc is None and not coverage.has_allowance(c):
                continue
            totals['contracts'] += 1
            before = seed.legacy_remaining(c, today)
            self.stdout.write('')
            self.stdout.write(f'#{c.pk} {c.client_org.name} - {c.name} [{c.contract_type}, {c.status}, '
                              f'{c.start_date} to {c.end_date or "open"}]')
            if acc is None:
                totals['missing'] += 1
                p = seed.plan_contract(c, seed.live_models(), today)
                after = seed.ledger_remaining(p, ledger.display_date(c, today))
                self.stdout.write(f'  NO LEDGER yet (would open in {p.mode} mode).')
                if not dry:
                    ledger.open_ledger(c)
                    for e in self._approved_entries(c, approved_subs):
                        ledger.post_entry(e, event='reconciled')
                    totals['repaired'] += 1
                    after = ledger.summary(c).remaining
                self._line(before, after, None, [])
                continue

            notes = []
            if acc.mode != ledger.mode_for(c):
                notes.append(f'mode: ledger is "{acc.mode}", contract settings now suggest '
                             f'"{ledger.mode_for(c)}" (mode is fixed when opened)')
            if not dry:
                ledger.open_ledger(c)
            balances = ledger.block_balances(c)
            for b in c.prepaid_blocks.all().order_by('starts_on', 'pk'):
                kinds = {r['kind']: r['t'] or ZERO for r in b.postings.values('kind').annotate(t=Sum('hours'))}
                state = 'valid today' if b.covers(today) else ('expired' if b.expires_on and b.expires_on < today
                                                              else 'not started')
                self.stdout.write(
                    f'  block {b.pk} {b.kind:<9} {b.starts_on} to {str(b.expires_on or "open"):<10} '
                    f'purchased {_h(kinds.get("purchase", ZERO))}  adjusted {_h(kinds.get("adjustment", ZERO))}  '
                    f'consumed {_h(-(kinds.get("consumption", ZERO) + kinds.get("reversal", ZERO)))}  '
                    f'expired {_h(-kinds.get("expiry", ZERO))}  left {_h(balances.get(b.pk, ZERO))}  ({state})')
            s = ledger.summary(c)
            after = s.remaining
            if acc.mode == 'cycle':
                notes.append('cycle reset: shows the current billing cycle only')
            if c.rolled_over_minutes and c.rollover_expires_at and today > c.rollover_expires_at:
                notes.append('expired rollover: the old counter dropped it even where it was used')
            unapproved = self._unapproved_held(c, approved_subs)
            if unapproved:
                notes.append(f'unapproved: {_h(unapproved)}h of time not approved is still counted from the '
                             f'opening balance (released if rejected, kept if approved)')
            overlap = self._overlap(c)
            if overlap:
                notes.append(f'overlap: {_h(overlap)}h also counted by another contract')
            waiting = TicketTimeEntry.objects.filter(billing_resolution='needs_choice',
                                                     ticket__organization_id=c.client_org_id).count()
            if waiting:
                notes.append(f'needs choice: {waiting} approved entr{"y" if waiting == 1 else "ies"} of this '
                             f'customer wait for an agreement choice')
            if acc.cached_remaining_hours is not None and \
                    acc.cached_remaining_hours.quantize(Decimal('0.01')) != after.quantize(Decimal('0.01')):
                notes.append(f'cache: cached {_h(acc.cached_remaining_hours)}h, postings {_h(after)}h')
                if not dry:
                    ledger._refresh(c)
                    totals['repaired'] += 1
            approved_only = self._approved_only(c, approved_subs, today)
            if before is not None and before != after.quantize(Decimal('0.01')):
                totals['changed'] += 1
            self._line(before, after, approved_only, notes)

        due = ledger.due_expiries(today)
        self.stdout.write('')
        self.stdout.write(f'Contracts with prepaid hours: {totals["contracts"]}; remaining hours differ from the '
                          f'old counter: {totals["changed"]}; without a ledger: {totals["missing"]}'
                          + ('' if dry else f'; repaired: {totals["repaired"]}')
                          + f'; blocks due to expire (after {ledger.EXPIRY_GRACE_DAYS} days\' grace): {len(due)}.')

    def _line(self, before, after, approved_only, notes):
        diff = '' if before is None else f'  difference {_h(Decimal(after) - before)}'
        self.stdout.write(f'  remaining before (old counter) {_h(before)}  after (ledger) {_h(after)}{diff}'
                          + (f'  approved-only {_h(approved_only)}' if approved_only is not None else ''))
        for n in notes:
            self.stdout.write(f'    - {n}')

    def _approved_entries(self, c, approved_subs):
        return [e for e in seed.legacy_entries(c, seed.live_models()) if e.submission_id in approved_subs]

    def _unapproved_held(self, c, approved_subs):
        rows = (PrepaidPosting.objects.filter(contract=c, kind='consumption', status='migrated',
                                              reversed_by__isnull=True, time_entry__isnull=False)
                .exclude(time_entry__submission_id__in=approved_subs)
                .aggregate(t=Sum('hours')))
        return -(rows['t'] or ZERO)

    def _overlap(self, c):
        mine = PrepaidPosting.objects.filter(contract=c, kind='consumption', reversed_by__isnull=True)
        refs = list(mine.values_list('time_entry_ref', flat=True))
        if not refs:
            return ZERO
        shared = (PrepaidPosting.objects.filter(kind='consumption', reversed_by__isnull=True,
                                                time_entry_ref__in=refs).exclude(contract=c)
                  .values('time_entry_ref').annotate(n=Count('pk')))
        shared_refs = [r['time_entry_ref'] for r in shared]
        t = mine.filter(time_entry_ref__in=shared_refs).aggregate(t=Sum('hours'))['t']
        return -(t or ZERO)

    def _approved_only(self, c, approved_subs, today):
        """Remaining hours on the display date if only approved time counted."""
        if ledger.mode_for(c) == 'cycle':
            bounds = ledger.cycle_bounds(c, ledger.display_date(c, today))
            if not bounds:
                return None
            allowance = Decimal(c.total_hours or 0)
            entries = [e for e in self._approved_entries(c, approved_subs)
                       if bounds[0] <= coverage.work_date(e) <= bounds[1]]
        else:
            allowance = Decimal(c.effective_total_minutes()) / 60
            entries = self._approved_entries(c, approved_subs)
        used = Decimal(sum(e.duration_minutes or 0 for e in entries)) / 60
        return max(ZERO, allowance - used)
