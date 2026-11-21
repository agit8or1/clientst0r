"""Phase 101.2: opening the prepaid-hour ledger on upgrade.

Approach (billing plan rule 1, "do not break existing installations"): the
ledger starts from the state the old hour counter shows, so the remaining
hours admins see do not jump on upgrade, and invoices are not touched.

For every contract with an allowance (total hours or rolled-over hours):

* blocks are opened as the live ledger would: the contract allowance for its
  window, or, for a retainer billed per cycle, one block per billing cycle up
  to today (the allowance resets each cycle from now on), plus the
  rolled-over hours as their own block with their expiry;
* each block gets a purchase posting for its hours;
* every time entry the old counter counts (Contract.qualifying_time_entries:
  billable, stopped, in the window, role gates; approved or not) gets a
  consumption posting, in work order, earliest-expiry block first; minutes
  beyond the blocks get an overage posting.

All of these carry status 'migrated'. An entry consumed this way is already
counted: approving it later changes nothing (the ledger compares, it does not
add), rejecting or deleting it reverses it. Entries counted by two
overlapping contracts stay counted by both until they are approved (the
resolver then needs one agreement) - `prepaid_ledger_reconcile` lists them.

Works with the migration's historical models (pass them in `M`) or the live
ones. Nothing here reads model methods.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from dateutil.relativedelta import relativedelta
from django.db.models import Q

ZERO = Decimal('0')
Q6 = Decimal('0.000001')
CYCLE_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}
FLAT_FEE_TYPES = ('managed_services', 'retainer')


def live_models():
    from psa import models as m
    return SimpleNamespace(Contract=m.Contract, TicketTimeEntry=m.TicketTimeEntry,
                           PrepaidLedgerAccount=m.PrepaidLedgerAccount, PrepaidBlock=m.PrepaidBlock,
                           PrepaidPosting=m.PrepaidPosting)


def hm(minutes):
    return (Decimal(int(minutes)) / Decimal(60)).quantize(Q6)


def to_min(h):
    return int((Decimal(h) * 60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def has_allowance(c):
    return (c.total_hours or ZERO) > 0 or (c.rolled_over_minutes or 0) > 0


def mode_for(c):
    if c.contract_type == 'retainer' and c.billing_frequency in CYCLE_MONTHS and (c.total_hours or ZERO) > 0:
        return 'cycle'
    return 'window'


def _cycles(c, last):
    step = CYCLE_MONTHS[c.billing_frequency]
    if c.end_date and last > c.end_date:
        last = c.end_date
    out, k = [], 0
    while True:
        start = c.start_date + relativedelta(months=k * step)
        if start > last:
            break
        end = c.start_date + relativedelta(months=(k + 1) * step) - timedelta(days=1)
        if c.end_date and end > c.end_date:
            end = c.end_date
        out.append((start, end))
        k += 1
    return out


def legacy_entries(c, M):
    """Contract.qualifying_time_entries, on any model class."""
    qs = M.TicketTimeEntry.objects.filter(ticket__organization_id=c.client_org_id, ended_at__isnull=False,
                                          duration_minutes__gt=0, is_billable=True)
    if c.start_date:
        qs = qs.filter(started_at__date__gte=c.start_date)
    if c.end_date:
        qs = qs.filter(started_at__date__lte=c.end_date)
    excluded = [x for x in (c.excluded_role_codes or []) if x]
    if excluded:
        qs = qs.exclude(role_code__in=excluded)
    included = [x for x in (c.billable_role_codes or []) if x]
    if included:
        qs = qs.filter(Q(role_code='') | Q(role_code__in=included))
    return qs.order_by('started_at', 'pk')


@dataclass
class BlockPlan:
    kind: str
    key: str
    starts_on: object
    expires_on: object
    label: str
    hours: Decimal
    consumed_min: int = 0
    pk: int | None = None

    def covers(self, d):
        return self.starts_on <= d and (self.expires_on is None or d <= self.expires_on)

    @property
    def remaining_min(self):
        return to_min(self.hours) - self.consumed_min


@dataclass
class ContractPlan:
    contract: object
    mode: str
    blocks: list = field(default_factory=list)
    consumption: list = field(default_factory=list)   # (entry, block_index, minutes)
    overage: list = field(default_factory=list)       # (entry, minutes)
    entries: int = 0


def _local_date(dt):
    from django.utils import timezone
    return timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()


def plan_contract(c, M, today):
    mode = mode_for(c)
    p = ContractPlan(contract=c, mode=mode)
    entries = list(legacy_entries(c, M))
    p.entries = len(entries)
    if mode == 'cycle':
        last = max([today] + [_local_date(e.started_at) for e in entries])
        for start, end in _cycles(c, last):
            p.blocks.append(BlockPlan('cycle', f'cycle:{c.pk}:{start.isoformat()}', start, end,
                                      f'{c.name}: cycle {start} to {end}', Decimal(c.total_hours)))
    elif (c.total_hours or ZERO) > 0:
        p.blocks.append(BlockPlan('allowance', f'allowance:{c.pk}', c.start_date, c.end_date,
                                  f'{c.name}: allowance', Decimal(c.total_hours)))
    if (c.rolled_over_minutes or 0) > 0:
        p.blocks.append(BlockPlan('rollover', f'rollover:{c.pk}', c.start_date, c.rollover_expires_at,
                                  f'{c.name}: rolled over', hm(c.rolled_over_minutes)))

    def order(i):
        b = p.blocks[i]
        return (b.expires_on is None, b.expires_on or b.starts_on, 0 if b.kind == 'rollover' else 1,
                b.starts_on, i)

    for e in entries:
        d = _local_date(e.started_at)
        left = int(e.duration_minutes or 0)
        for i in sorted([i for i, b in enumerate(p.blocks) if b.covers(d)], key=order):
            if left <= 0:
                break
            take = min(left, max(0, p.blocks[i].remaining_min))
            if take > 0:
                p.blocks[i].consumed_min += take
                p.consumption.append((e, i, take))
                left -= take
        if left > 0:
            p.overage.append((e, left))
    return p


def ledger_remaining(p, as_of):
    """Remaining hours the ledger would show on `as_of` for this plan."""
    return sum(((b.hours - hm(b.consumed_min)) for b in p.blocks if b.covers(as_of)), ZERO)


def display_date(c, today):
    if c.end_date and today > c.end_date:
        return c.end_date
    if c.start_date and today < c.start_date:
        return c.start_date
    return today


def legacy_remaining(c, today):
    """Contract.effective_hours_remaining, on any model class (hours)."""
    base = int(float(c.total_hours or 0) * 60)
    rolled = c.rolled_over_minutes or 0
    if c.rollover_expires_at and today > c.rollover_expires_at:
        rolled = 0
    total = base + rolled
    if not c.total_hours and not c.rolled_over_minutes:
        return None
    return (Decimal(max(0, total - (c.hours_used_minutes or 0))) / 60).quantize(Decimal('0.01'))


def write_plan(p, M, now):
    """Create the account, blocks and migrated postings for one plan."""
    c = p.contract
    acc = M.PrepaidLedgerAccount.objects.create(contract_id=c.pk, mode=p.mode, migrated_at=now)
    rows = []
    for b in p.blocks:
        blk = M.PrepaidBlock.objects.create(
            organization_id=c.organization_id, client_org_id=c.client_org_id, contract_id=c.pk, kind=b.kind,
            key=b.key, starts_on=b.starts_on, expires_on=b.expires_on, label=b.label[:200])
        b.pk = blk.pk
        rows.append(M.PrepaidPosting(
            organization_id=c.organization_id, client_org_id=c.client_org_id, contract_id=c.pk, block_id=blk.pk,
            kind='purchase', status='migrated', hours=Decimal(b.hours).quantize(Q6), effective_date=b.starts_on,
            idempotency_key=f'purchase:{blk.pk}:1',
            reason='Opening balance: allowance of the contract when the ledger was introduced.'))
    for e, i, m in p.consumption:
        b = p.blocks[i]
        rows.append(M.PrepaidPosting(
            organization_id=c.organization_id, client_org_id=c.client_org_id, contract_id=c.pk, block_id=b.pk,
            kind='consumption', status='migrated', hours=-hm(m), effective_date=_local_date(e.started_at),
            time_entry_id=e.pk, time_entry_ref=e.pk, allocation=1,
            idempotency_key=f'mig:te:{e.pk}:c:{b.pk}',
            reason='Opening balance: counted by the hour counter before the ledger (approved or not).'))
    for e, m in p.overage:
        rows.append(M.PrepaidPosting(
            organization_id=c.organization_id, client_org_id=c.client_org_id, contract_id=c.pk, block_id=None,
            kind='overage', status='migrated', hours=hm(m), effective_date=_local_date(e.started_at),
            time_entry_id=e.pk, time_entry_ref=e.pk, allocation=1,
            idempotency_key=f'mig:te:{e.pk}:o:{c.pk}',
            reason='Opening balance: beyond the allowance before the ledger.'))
    M.PrepaidPosting.objects.bulk_create(rows, batch_size=500)
    return acc


def seed_all(M=None, *, today=None, now=None, contract_ids=None, write=True):
    """Open the ledger for every contract with an allowance that has none.
    Returns the list of ContractPlan (written when `write`)."""
    from django.utils import timezone
    M = M or live_models()
    today = today or timezone.localdate()
    now = now or timezone.now()
    have = set(M.PrepaidLedgerAccount.objects.values_list('contract_id', flat=True))
    qs = M.Contract.objects.all().order_by('pk')
    if contract_ids is not None:
        qs = qs.filter(pk__in=contract_ids)
    plans = []
    for c in qs:
        if c.pk in have or not has_allowance(c):
            continue
        p = plan_contract(c, M, today)
        if write:
            acc = write_plan(p, M, now)
            remaining = ledger_remaining(p, display_date(c, today))
            M.PrepaidLedgerAccount.objects.filter(pk=acc.pk).update(cached_remaining_hours=remaining)
        plans.append(p)
    return plans
