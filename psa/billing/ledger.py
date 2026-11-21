"""Phase 101.2 / 101.3: the prepaid-hour ledger.

Model: psa.PrepaidLedgerAccount (one per contract with prepaid hours, the lock
row), psa.PrepaidBlock (lots of hours), psa.PrepaidPosting (immutable signed
lines). A block's balance is the sum of its postings.

Rules
-----
* Draft, pending and rejected time consumes nothing. Approving a timesheet
  posts consumption (`post_entry`); time beyond the prepaid hours becomes an
  `overage` posting (chargeable, never a balance movement) unless the
  agreement allows a negative balance. Rejecting, returning or deleting an
  entry, or changing it after approval, reverses what it consumed exactly.
* Consumption follows the entry's own agreement (psa.billing.coverage) and is
  stored on the entry (`billing_contract`). Two overlapping agreements never
  both count the same time.
* Blocks valid on the work date are consumed earliest expiry first
  (rolled-over hours before the allowance when they expire together).
* A retainer billed per cycle ('cycle' account mode) gets one block per
  billing cycle, so its allowance resets every cycle; unused cycle hours
  expire with the cycle.
* Expiry posts the unused balance of a block once the block has been expired
  for EXPIRY_GRACE_DAYS (so late timesheet approvals for work done while the
  block was valid still use it). Displayed balances drop expired blocks at
  once.
* Manual adjustments and extra blocks need `billing_manage_charges` at the
  customer, a reason and an idempotency key.
* Every posting is written to the audit log.

Concurrency: every write runs in a transaction that first takes the
contract's account row (`lock_account`: an UPDATE of its revision, which
takes the row lock on MySQL / PostgreSQL and the write lock on SQLite, then
SELECT ... FOR UPDATE), so balances are read after the lock. Each posting
carries a unique idempotency key derived from what it is (entry + allocation
number + block, block + purchase number, posting reversed, ...), so a retry,
a job run twice or a racing worker that gets past the lock hits the unique
constraint and changes nothing.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import coverage

logger = logging.getLogger('psa.billing.ledger')

ZERO = Decimal('0')
Q6 = Decimal('0.000001')
EXPIRY_GRACE_DAYS = 45
LOW_BALANCE_DEFAULT_FRACTION = Decimal('0.20')
CYCLE_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}
ADJUST_PERMISSION = 'billing_manage_charges'
VIEW_PERMISSION = 'billing_view_invoices'
ENTRY_KINDS = ('consumption', 'overage')


class LedgerError(ValueError):
    pass


hours = coverage.hours


def minutes_of(h) -> int:
    return int((Decimal(h) * 60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# --- suspension (tests that build pre-upgrade data; never in production) ----

_state = threading.local()


@contextmanager
def suspended():
    """Do not open ledgers from Contract saves inside this block."""
    prev = getattr(_state, 'suspended', False)
    _state.suspended = True
    try:
        yield
    finally:
        _state.suspended = prev


def is_suspended():
    return getattr(_state, 'suspended', False)


# --- modes and cycles ---------------------------------------------------------

def mode_for(contract):
    if (contract.contract_type == 'retainer' and contract.billing_frequency in CYCLE_MONTHS
            and (contract.total_hours or ZERO) > 0):
        return 'cycle'
    return 'window'


def cycle_bounds(contract, on_date):
    """(start, end) of the billing cycle containing `on_date`, anchored on the
    contract start (start + k*n months, so month ends do not drift)."""
    step = CYCLE_MONTHS.get(contract.billing_frequency)
    start = contract.start_date
    if not step or start is None or on_date is None or on_date < start:
        return None
    k = ((on_date.year - start.year) * 12 + (on_date.month - start.month)) // step
    k = max(0, k)
    while k > 0 and start + relativedelta(months=k * step) > on_date:
        k -= 1
    while start + relativedelta(months=(k + 1) * step) <= on_date:
        k += 1
    c_start = start + relativedelta(months=k * step)
    c_end = start + relativedelta(months=(k + 1) * step) - timedelta(days=1)
    if contract.end_date and c_end > contract.end_date:
        c_end = contract.end_date
    return c_start, c_end


def cycles_until(contract, last_date):
    out = []
    if contract.start_date is None or last_date is None:
        return out
    if contract.end_date and last_date > contract.end_date:
        last_date = contract.end_date
    d = contract.start_date
    while d <= last_date:
        b = cycle_bounds(contract, d)
        if b is None:
            break
        out.append(b)
        d = b[1] + timedelta(days=1)
    return out


# --- locking ------------------------------------------------------------------

def lock_account(contract):
    """Take the contract's ledger lock (opening the account when needed).
    Must run inside transaction.atomic()."""
    from psa.models import PrepaidLedgerAccount
    if not connection.in_atomic_block:
        raise LedgerError('lock_account must run inside a transaction')
    acc = PrepaidLedgerAccount.objects.filter(contract_id=contract.pk).first()
    if acc is None:
        try:
            with transaction.atomic():
                acc = PrepaidLedgerAccount.objects.create(contract_id=contract.pk, mode=mode_for(contract))
        except IntegrityError:
            acc = PrepaidLedgerAccount.objects.get(contract_id=contract.pk)
    PrepaidLedgerAccount.objects.filter(pk=acc.pk).update(revision=F('revision') + 1)
    return PrepaidLedgerAccount.objects.select_for_update().get(pk=acc.pk)


def _lock_many(contracts):
    accounts = {}
    for c in sorted({c.pk: c for c in contracts if c is not None}.values(), key=lambda c: c.pk):
        accounts[c.pk] = lock_account(c)
    return accounts


# --- postings -----------------------------------------------------------------

def _audit(posting, actor):
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=actor if getattr(actor, 'pk', None) else None, action='create',
            organization=posting.client_org, object_type='psa.PrepaidPosting', object_id=posting.pk,
            object_repr=f'{posting.get_kind_display()} {posting.hours:+.2f}h'[:255],
            description=f'Prepaid ledger: {posting.get_kind_display().lower()} of '
                        f'{posting.hours:+.4f}h on contract {posting.contract_id}'
                        + (f' (time entry {posting.time_entry_ref})' if posting.time_entry_ref else '')
                        + (f': {posting.reason}' if posting.reason else ''),
            extra_data={'kind': posting.kind, 'status': posting.status, 'hours': str(posting.hours),
                        'contract_id': posting.contract_id, 'block_id': posting.block_id,
                        'time_entry_id': posting.time_entry_ref, 'allocation': posting.allocation,
                        'reverses': posting.reverses_id, 'idempotency_key': posting.idempotency_key},
        )
    except Exception:  # pragma: no cover - the posting stands; the log is best effort
        logger.exception('audit log for prepaid posting %s failed', posting.pk)


def _post(contract, *, kind, hours_, key, block=None, effective_date=None, entry=None, entry_ref=None,
          allocation=0, reverses=None, actor=None, reason='', status='posted'):
    from psa.models import PrepaidPosting
    with transaction.atomic():
        posting = PrepaidPosting.objects.create(
            organization_id=contract.organization_id, client_org_id=contract.client_org_id,
            contract=contract, block=block, kind=kind, status=status,
            hours=Decimal(hours_).quantize(Q6), effective_date=effective_date or timezone.localdate(),
            time_entry=entry, time_entry_ref=entry_ref if entry_ref is not None else getattr(entry, 'pk', None),
            allocation=allocation, reverses=reverses, actor=actor if getattr(actor, 'pk', None) else None,
            reason=(reason or '')[:5000], idempotency_key=key[:160],
        )
    _audit(posting, actor)
    return posting


def _existing(key):
    from psa.models import PrepaidPosting
    return PrepaidPosting.objects.filter(idempotency_key=key).first()


def block_balances(contract):
    """{block_id: balance hours} for every block of the contract."""
    from psa.models import PrepaidPosting
    rows = (PrepaidPosting.objects.filter(contract=contract, block__isnull=False)
            .values('block_id').annotate(total=Sum('hours')))
    return {r['block_id']: r['total'] or ZERO for r in rows}


def _order_key(block):
    return (block.expires_on is None, block.expires_on or block.starts_on,
            0 if block.kind == 'rollover' else 1, block.starts_on, block.pk or 0)


# --- blocks -------------------------------------------------------------------

def _ensure_block(contract, *, kind, key, starts_on, expires_on, label, actor=None):
    from psa.models import PrepaidBlock
    block = PrepaidBlock.objects.filter(key=key).first()
    if block is None:
        block = PrepaidBlock.objects.create(
            organization_id=contract.organization_id, client_org_id=contract.client_org_id,
            contract=contract, kind=kind, key=key, starts_on=starts_on, expires_on=expires_on,
            label=label[:200], created_by=actor if getattr(actor, 'pk', None) else None)
    return block


def _sync_purchase(contract, block, target, *, actor=None, reason_first='', status='posted'):
    from psa.models import PrepaidPosting
    purchases = PrepaidPosting.objects.filter(block=block, kind='purchase')
    current = purchases.aggregate(t=Sum('hours'))['t'] or ZERO
    target = Decimal(target).quantize(Q6)
    if current == target:
        return None
    n = purchases.count()
    key = f'purchase:{block.pk}:{n + 1}'
    if _existing(key):
        return None
    reason = reason_first if n == 0 else f'Allowance changed on the contract: {current:.2f}h to {target:.2f}h.'
    return _post(contract, kind='purchase', hours_=target - current, key=key, block=block,
                 effective_date=block.starts_on, actor=actor, reason=reason, status=status)


def sync_blocks(contract, account, *, upto=None, actor=None):
    """Bring the contract's blocks in line with its allowance fields. Runs
    under lock_account. Idempotent."""
    from psa.models import PrepaidBlock
    today = timezone.localdate()
    upto = max(upto or today, today)
    if account.mode == 'cycle':
        current = cycle_bounds(contract, min(today, contract.end_date) if contract.end_date else today)
        for c_start, c_end in cycles_until(contract, upto):
            existed = PrepaidBlock.objects.filter(key=f'cycle:{contract.pk}:{c_start.isoformat()}').exists()
            block = _ensure_block(contract, kind='cycle', key=f'cycle:{contract.pk}:{c_start.isoformat()}',
                                  starts_on=c_start, expires_on=c_end,
                                  label=f'{contract.name}: cycle {c_start} to {c_end}', actor=actor)
            if block.expires_on != c_end:
                PrepaidBlock.objects.filter(pk=block.pk).update(expires_on=c_end)
            # Past cycles keep the allowance they opened with; the current
            # and future cycles follow the contract's hours.
            if not existed or (current and c_start >= current[0]):
                _sync_purchase(contract, block, contract.total_hours or ZERO, actor=actor,
                               reason_first='Billing-cycle allowance from the contract.')
    else:
        allowance = PrepaidBlock.objects.filter(key=f'allowance:{contract.pk}').first()
        if (contract.total_hours or ZERO) > 0 or allowance is not None:
            block = allowance or _ensure_block(
                contract, kind='allowance', key=f'allowance:{contract.pk}', starts_on=contract.start_date,
                expires_on=contract.end_date, label=f'{contract.name}: allowance', actor=actor)
            if block.starts_on != contract.start_date or block.expires_on != contract.end_date:
                # The allowance follows the contract window (postings do not move).
                PrepaidBlock.objects.filter(pk=block.pk).update(starts_on=contract.start_date,
                                                               expires_on=contract.end_date)
                block.starts_on, block.expires_on = contract.start_date, contract.end_date
            _sync_purchase(contract, block, contract.total_hours or ZERO, actor=actor,
                           reason_first='Allowance from the contract.')
    rollover = PrepaidBlock.objects.filter(key=f'rollover:{contract.pk}').first()
    if (contract.rolled_over_minutes or 0) > 0 or rollover is not None:
        block = rollover or _ensure_block(
            contract, kind='rollover', key=f'rollover:{contract.pk}', starts_on=contract.start_date,
            expires_on=contract.rollover_expires_at, label=f'{contract.name}: rolled over', actor=actor)
        if block.expires_on != contract.rollover_expires_at:
            PrepaidBlock.objects.filter(pk=block.pk).update(expires_on=contract.rollover_expires_at)
        _sync_purchase(contract, block, hours(contract.rolled_over_minutes or 0), actor=actor,
                       reason_first='Hours rolled over from the previous period.')


def open_ledger(contract, *, actor=None):
    """Open (or re-sync) the ledger of a contract that has prepaid hours."""
    from psa.models import PrepaidLedgerAccount
    if not coverage.has_allowance(contract) and not PrepaidLedgerAccount.objects.filter(
            contract_id=contract.pk).exists():
        return None
    with transaction.atomic():
        account = lock_account(contract)
        sync_blocks(contract, account, actor=actor)
        _refresh(contract, account)
    return account


# --- planning -----------------------------------------------------------------

def plan(contract, on_date, minutes, *, exclude_entry=None, balances=None):
    """How `minutes` of work on `on_date` would come out of the contract's
    blocks now: ([(block or None, minutes)], overage_minutes, negative_minutes).
    `None` stands for a cycle block that is not opened yet (full allowance).
    Read-only; ledger writes call it again under the lock."""
    from psa.models import PrepaidBlock, PrepaidLedgerAccount, PrepaidPosting
    minutes = int(minutes or 0)
    blocks = [b for b in PrepaidBlock.objects.filter(contract=contract) if b.covers(on_date)]
    if balances is None:
        balances = block_balances(contract)
    if exclude_entry is not None and getattr(exclude_entry, 'pk', None):
        # What this entry already holds is available to it again (re-allocation).
        held = (PrepaidPosting.objects.filter(time_entry_ref=exclude_entry.pk, kind='consumption',
                                              reversed_by__isnull=True, contract=contract)
                .values('block_id').annotate(t=Sum('hours')))
        balances = dict(balances)
        for r in held:
            balances[r['block_id']] = balances.get(r['block_id'], ZERO) - (r['t'] or ZERO)
    acc = PrepaidLedgerAccount.objects.filter(contract_id=contract.pk).first()
    mode = acc.mode if acc else mode_for(contract)
    avail = []
    for b in sorted(blocks, key=_order_key):
        avail.append([b, minutes_of(balances.get(b.pk, ZERO))])
    virtual = False
    if mode == 'cycle' and not any(b.kind == 'cycle' for b in blocks):
        bounds = cycle_bounds(contract, on_date)
        if bounds:
            virtual = True
            avail.append([None, minutes_of(contract.total_hours or ZERO)])
    if not blocks and not virtual and mode == 'window' and (contract.total_hours or ZERO) > 0 \
            and acc is None:
        avail.append([None, minutes_of(contract.total_hours)])
    left = minutes
    allocs = []
    for b, a in avail:
        if left <= 0:
            break
        take = min(left, max(0, a))
        if take > 0:
            allocs.append((b, take))
            left -= take
    negative = 0
    if left > 0 and contract.allow_negative_balance and avail:
        # Run the latest-expiring valid block below zero.
        target = avail[-1][0]
        merged = False
        for i, (b, m) in enumerate(allocs):
            if b is target:
                allocs[i] = (b, m + left)
                merged = True
        if not merged:
            allocs.append((target, left))
        negative = left
        left = 0
    return allocs, left, negative


# --- time entries -------------------------------------------------------------

def is_approved(entry):
    # Read from the database: callers may hold a stale instance.
    from psa.models import TimesheetSubmission
    return TimesheetSubmission.objects.filter(entries__pk=entry.pk, status='approved').exists()


def active_entry_postings(entry_ref):
    from psa.models import PrepaidPosting
    return list(PrepaidPosting.objects.filter(time_entry_ref=entry_ref, kind__in=ENTRY_KINDS,
                                              reversed_by__isnull=True).select_related('contract', 'block'))


def active_postings_by_entry(entry_refs):
    """{entry ref: active_entry_postings(ref)} for many entries in one read,
    each list in the same order active_entry_postings returns."""
    from psa.models import PrepaidPosting
    refs = [r for r in entry_refs if r is not None]
    out = {r: [] for r in refs}
    if not refs:
        return out
    for p in (PrepaidPosting.objects.filter(time_entry_ref__in=refs, kind__in=ENTRY_KINDS,
                                            reversed_by__isnull=True).select_related('contract', 'block')):
        out[p.time_entry_ref].append(p)
    return out


def _reverse(posting, *, actor=None, reason=''):
    key = f'rev:{posting.pk}'
    existing = _existing(key)
    if existing:
        return existing
    return _post(posting.contract, kind='reversal', hours_=-posting.hours, key=key, block=posting.block,
                 effective_date=posting.effective_date, entry=posting.time_entry,
                 entry_ref=posting.time_entry_ref, allocation=posting.allocation, reverses=posting,
                 actor=actor, reason=reason or f'Reverses {posting.get_kind_display().lower()} posting {posting.pk}.')


def _mark_entry(entry_pk, **fields):
    from psa.models import TicketTimeEntry
    fields.setdefault('billing_resolved_at', timezone.now())
    TicketTimeEntry.objects.filter(pk=entry_pk).update(**fields)


def post_entry(entry, *, actor=None, event='approved'):
    """Make the ledger match an approved entry. Returns 'posted',
    'unchanged', 'needs_choice', 'not_prepaid', 'not_approved'.

    Safe to call any number of times and concurrently: what the entry should
    consume is compared with what it already holds; a racing duplicate hits
    the idempotency keys and is discarded."""
    from psa.models import TicketTimeEntry
    try:
        return _post_entry(entry, actor=actor, event=event)
    except IntegrityError:
        # Another worker posted the same allocation first (unique key).
        logger.info('prepaid posting for entry %s already made by a concurrent worker', entry.pk)
        if not TicketTimeEntry.objects.filter(pk=entry.pk).exists():
            raise
        return 'unchanged'


def _post_entry(entry, *, actor, event):
    from psa.models import TicketTimeEntry
    if not is_approved(entry):
        return 'not_approved'
    first = coverage.resolve(entry, plan=False)
    held = active_entry_postings(entry.pk)
    with transaction.atomic():
        def _prepaid(c):
            return c if c is not None and coverage.has_allowance(c) else None
        _lock_many([_prepaid(first.agreement)] + [p.contract for p in held])
        entry = (TicketTimeEntry.objects.select_for_update().select_related('ticket', 'ticket__ticket_type')
                 .get(pk=entry.pk))
        held = active_entry_postings(entry.pk)
        res = coverage.resolve(entry, plan=False)
        if _prepaid(res.agreement) is not None and (first.agreement is None
                                                    or res.agreement.pk != first.agreement.pk):
            lock_account(res.agreement)
        wants = res.status == 'resolved' and res.treatment == 'prepaid' and res.agreement is not None
        held_minutes = sum(minutes_of(p.hours if p.kind == 'overage' else -p.hours) for p in held)
        held_contracts = {p.contract_id for p in held}
        if wants and held and held_contracts == {res.agreement.pk} and held_minutes == res.minutes:
            _mark_entry(entry.pk, billing_contract=res.agreement,
                        billing_resolution=_code_from_held(held, res.minutes))
            return 'unchanged'
        touched = {p.contract_id: p.contract for p in held}
        for p in held:
            _reverse(p, actor=actor, reason=f'Re-allocated ({event}).')
        if not wants:
            if res.status == 'needs_choice':
                code = 'needs_choice'
            elif res.treatment == 'non_billable':
                code = 'non_billable'
            else:
                code = res.resolution_code
            _mark_entry(entry.pk, billing_contract=res.agreement if res.status == 'resolved' else None,
                        billing_resolution=code)
            for c in touched.values():
                _refresh(c)
            return 'needs_choice' if res.status == 'needs_choice' else 'not_prepaid'

        contract = res.agreement
        account = lock_account(contract)
        sync_blocks(contract, account, upto=res.on_date, actor=actor)
        allocs, over, _neg = plan(contract, res.on_date, res.minutes, exclude_entry=None)
        from psa.models import PrepaidPosting
        # Allocation number = 1 + allocations of this entry already reversed.
        # Derived from history, not from "what is active now", so a worker
        # that read the entry before a racing worker committed computes the
        # same number, the same keys, and fails on the unique constraint.
        seq = PrepaidPosting.objects.filter(time_entry_ref=entry.pk, kind='reversal').values(
            'allocation').order_by().distinct().count() + 1
        reason = f'Time entry {entry.pk} {event}' + (f' on ticket {entry.ticket.ticket_number}'
                                                   if entry.ticket_id else '') + '.'
        for block, m in allocs:
            if block is None:  # pragma: no cover - sync_blocks opened every block
                raise LedgerError('cycle block missing after sync')
            _post(contract, kind='consumption', hours_=-hours(m), key=f'te:{entry.pk}:{seq}:c:{block.pk}',
                  block=block, effective_date=res.on_date, entry=entry, allocation=seq, actor=actor,
                  reason=reason)
        if over:
            _post(contract, kind='overage', hours_=hours(over), key=f'te:{entry.pk}:{seq}:o:{contract.pk}',
                  effective_date=res.on_date, entry=entry, allocation=seq, actor=actor,
                  reason=reason + ' Beyond the prepaid hours: chargeable at the overage rate.')
        code = 'prepaid' if not over else ('overage' if over >= res.minutes else 'partial')
        _mark_entry(entry.pk, billing_contract=contract, billing_resolution=code)
        _refresh(contract, account)
        for c in touched.values():
            if c.pk != contract.pk:
                _refresh(c)
    return 'posted'


def _code_from_held(held, minutes):
    over = sum(minutes_of(p.hours) for p in held if p.kind == 'overage')
    if not over:
        return 'prepaid'
    return 'overage' if over >= minutes else 'partial'


def post_entries(entries, *, actor=None, event='approved'):
    """Post several entries, oldest work first, so a batch approval uses the
    prepaid hours in the order the work was done (overage lands on the
    latest work)."""
    out = {}
    for e in sorted(entries, key=lambda x: (x.started_at is None, x.started_at or 0, x.pk)):
        out[e.pk] = post_entry(e, actor=actor, event=event)
    return out


def release_entry(entry=None, *, entry_ref=None, actor=None, reason='', mark=True):
    """Reverse everything an entry consumed (rejected, returned, deleted or
    reopened). Returns the number of postings reversed."""
    ref = entry.pk if entry is not None else entry_ref
    if ref is None:
        return 0
    held = active_entry_postings(ref)
    if not held:
        if mark and entry is not None:
            _mark_entry(ref, billing_resolution='released')
        return 0
    try:
        with transaction.atomic():
            _lock_many([p.contract for p in held])
            held = active_entry_postings(ref)
            for p in held:
                _reverse(p, actor=actor, reason=reason or 'Time entry released.')
            for c in {p.contract_id: p.contract for p in held}.values():
                _refresh(c)
            if mark and entry is not None:
                _mark_entry(ref, billing_resolution='released')
    except IntegrityError:
        logger.info('release of entry %s already done by a concurrent worker', ref)
        return 0
    return len(held)


def release_entries(entries, *, actor=None, reason=''):
    return sum(release_entry(e, actor=actor, reason=reason) for e in entries)


def choose_agreement(entry, contract, *, actor):
    """A person with the billing permission picks the agreement for an entry
    (an ambiguous overlap, or a correction). Re-posts when it is approved."""
    customer = entry.ticket.organization
    _require(actor, customer, ADJUST_PERMISSION)
    ok = [c.pk for c in coverage.candidate_agreements(customer.pk, coverage.work_date(entry), entry.role_code)]
    if contract.pk not in ok:
        raise LedgerError('That agreement does not cover this entry (customer, dates or role codes).')
    _mark_entry(entry.pk, billing_contract=contract, billing_contract_chosen=True)
    entry.billing_contract, entry.billing_contract_chosen = contract, True
    try:
        from audit.models import AuditLog
        AuditLog.log(user=actor, action='update', organization=customer, object_type='psa.TicketTimeEntry',
                     object_id=entry.pk, object_repr=f'time entry {entry.pk}',
                     description=f'Agreement chosen for billing: {contract.name}',
                     extra_data={'contract_id': contract.pk})
    except Exception:  # pragma: no cover
        logger.exception('audit log for agreement choice failed')
    return post_entry(entry, actor=actor, event='agreement chosen')


# --- manual adjustments and purchases ----------------------------------------

def _require(actor, customer, perm):
    from accounts.permission_utils import has_perm_for_org, is_msp_staff
    # Per-permission reach (client scope + access groups granting `perm`).
    # Ledger changes are MSP work: customer users never post.
    if (actor is None or not (actor.is_superuser or is_msp_staff(actor))
            or not has_perm_for_org(actor, customer, perm)):
        raise PermissionDenied(f"Your role does not include '{perm}' for this customer.")


def adjust(contract, hours_delta, *, actor, reason, idempotency_key, block=None, on_date=None):
    """Authorized manual adjustment (+ adds hours, - removes them)."""
    _require(actor, contract.client_org, ADJUST_PERMISSION)
    reason = (reason or '').strip()
    if not reason:
        raise LedgerError('A reason is required for a manual adjustment.')
    delta = Decimal(str(hours_delta)).quantize(Q6)
    if delta == 0:
        raise LedgerError('The adjustment is zero.')
    if not idempotency_key:
        raise LedgerError('An idempotency key is required.')
    key = f'adj:{idempotency_key}'
    existing = _existing(key)
    if existing:
        return existing
    on_date = on_date or timezone.localdate()
    with transaction.atomic():
        account = lock_account(contract)
        sync_blocks(contract, account, actor=actor)
        existing = _existing(key)
        if existing:
            return existing
        balances = block_balances(contract)
        if block is None:
            valid = sorted([b for b in contract.prepaid_blocks.all() if b.covers(on_date)], key=_order_key)
            if not valid:
                raise LedgerError('No prepaid block is valid on that date.')
            block = valid[0]
        elif block.contract_id != contract.pk:
            raise LedgerError('That block belongs to another agreement.')
        after = balances.get(block.pk, ZERO) + delta
        if after < 0 and not contract.allow_negative_balance:
            raise LedgerError('That would take the block below zero; this agreement does not allow it.')
        posting = _post(contract, kind='adjustment', hours_=delta, key=key, block=block, effective_date=on_date,
                        actor=actor, reason=reason)
        _refresh(contract, account)
    return posting


def purchase_block(contract, hours_bought, *, actor, reason, idempotency_key, starts_on=None, expires_on=None,
                   source_invoice=None):
    """Record an extra block of hours bought under the agreement. Recording
    is not billing: the purchase is invoiced once (source_invoice), and
    consuming it later is never revenue again."""
    _require(actor, contract.client_org, ADJUST_PERMISSION)
    qty = Decimal(str(hours_bought)).quantize(Q6)
    if qty <= 0:
        raise LedgerError('A block needs a positive number of hours.')
    if not (reason or '').strip() or not idempotency_key:
        raise LedgerError('A reason and an idempotency key are required.')
    from psa.models import PrepaidBlock
    starts_on = starts_on or timezone.localdate()
    with transaction.atomic():
        account = lock_account(contract)
        sync_blocks(contract, account, actor=actor)
        key = f'block:{contract.pk}:{idempotency_key}'
        block = PrepaidBlock.objects.filter(key=key).first() or _ensure_block(
            contract, kind='purchase', key=key, starts_on=starts_on, expires_on=expires_on,
            label=f'{contract.name}: {qty:.2f}h block from {starts_on}', actor=actor)
        if source_invoice is not None and block.source_invoice_id is None:
            PrepaidBlock.objects.filter(pk=block.pk).update(source_invoice=source_invoice)
        posting = _existing(f'purchase:{block.pk}:1') or _post(
            contract, kind='purchase', hours_=qty, key=f'purchase:{block.pk}:1', block=block,
            effective_date=starts_on, actor=actor, reason=reason.strip())
        _refresh(contract, account)
    return block, posting


# --- expiry -------------------------------------------------------------------

def due_expiries(as_of=None, grace_days=EXPIRY_GRACE_DAYS):
    """[(block, unused hours)] for blocks expired more than `grace_days` ago
    that still hold hours."""
    from psa.models import PrepaidBlock
    as_of = as_of or timezone.localdate()
    cutoff = as_of - timedelta(days=grace_days)
    out = []
    for block in PrepaidBlock.objects.filter(expires_on__lt=cutoff).select_related('contract'):
        bal = block.postings.aggregate(t=Sum('hours'))['t'] or ZERO
        if bal > 0:
            out.append((block, bal))
    return out


def expire_due(as_of=None, grace_days=EXPIRY_GRACE_DAYS, actor=None):
    from psa.models import PrepaidPosting
    done = 0
    for block, _bal in due_expiries(as_of, grace_days):
        contract = block.contract
        try:
            with transaction.atomic():
                account = lock_account(contract)
                bal = block.postings.aggregate(t=Sum('hours'))['t'] or ZERO
                if bal <= 0:
                    continue
                n = PrepaidPosting.objects.filter(block=block, kind='expiry').count()
                _post(contract, kind='expiry', hours_=-bal, key=f'expire:{block.pk}:{n + 1}', block=block,
                      effective_date=block.expires_on, actor=actor,
                      reason=f'Unused hours expired on {block.expires_on}.')
                _refresh(contract, account)
                done += 1
        except IntegrityError:
            logger.info('expiry of block %s already posted', block.pk)
    return done


# --- balances and display -----------------------------------------------------

@dataclass
class PrepaidSummary:
    tracked: bool
    unlimited: bool
    purchased: Decimal = ZERO
    adjusted: Decimal = ZERO
    used: Decimal = ZERO
    expired: Decimal = ZERO
    remaining: Decimal = ZERO
    overage: Decimal = ZERO
    threshold: Decimal | None = None
    as_of: object = None
    mode: str = 'window'

    @property
    def low(self):
        return (not self.unlimited and self.threshold is not None and self.purchased > 0
                and self.remaining <= self.threshold)

    @property
    def depleted(self):
        return not self.unlimited and self.remaining <= 0

    @property
    def negative(self):
        return not self.unlimited and self.remaining < 0

    def _r(self, v):
        return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def remaining_hours(self):
        return self._r(self.remaining)

    @property
    def used_hours(self):
        return self._r(self.used)

    @property
    def total_hours(self):
        return self._r(self.purchased + self.adjusted)


def display_date(contract, today=None):
    today = today or timezone.localdate()
    if contract.end_date and today > contract.end_date:
        return contract.end_date
    if contract.start_date and today < contract.start_date:
        return contract.start_date
    return today


def summary(contract, as_of=None):
    from psa.models import PrepaidLedgerAccount, PrepaidPosting
    acc = PrepaidLedgerAccount.objects.filter(contract_id=contract.pk).first()
    if acc is None:
        if not coverage.has_allowance(contract):
            return PrepaidSummary(tracked=False, unlimited=True)
        total = Decimal(contract.effective_total_minutes()) / 60
        used = Decimal(contract.hours_used_minutes or 0) / 60
        return PrepaidSummary(tracked=False, unlimited=False, purchased=total, used=used,
                              remaining=max(ZERO, total - used), threshold=_threshold(contract, total))
    as_of = as_of or display_date(contract)
    blocks = [b for b in contract.prepaid_blocks.all() if b.covers(as_of)]
    ids = [b.pk for b in blocks]
    by_kind = {r['kind']: r['t'] or ZERO for r in PrepaidPosting.objects.filter(block_id__in=ids)
               .values('kind').annotate(t=Sum('hours'))}
    purchased = by_kind.get('purchase', ZERO)
    if acc.mode == 'cycle' and not any(b.kind == 'cycle' for b in blocks) and cycle_bounds(contract, as_of):
        purchased += Decimal(contract.total_hours or 0)  # cycle not opened yet: full allowance
    s = PrepaidSummary(
        tracked=True, unlimited=False, purchased=purchased, adjusted=by_kind.get('adjustment', ZERO),
        used=-(by_kind.get('consumption', ZERO) + by_kind.get('reversal', ZERO)),
        expired=-by_kind.get('expiry', ZERO), as_of=as_of, mode=acc.mode)
    s.remaining = s.purchased + s.adjusted - s.used - s.expired
    over = PrepaidPosting.objects.filter(contract=contract, block__isnull=True).aggregate(t=Sum('hours'))['t']
    s.overage = over or ZERO
    s.threshold = _threshold(contract, s.purchased + s.adjusted)
    return s


def totals(contract, *, start=None, end=None):
    """Ledger sums for a contract, in hours, over its whole life or postings
    whose effective date is in [start, end). None when the contract has no
    ledger. `consumed` and `overage` are net of reversals (approved time)."""
    from psa.models import PrepaidLedgerAccount, PrepaidPosting
    if not PrepaidLedgerAccount.objects.filter(contract_id=contract.pk).exists():
        return None
    qs = PrepaidPosting.objects.filter(contract=contract)
    if start is not None:
        qs = qs.filter(effective_date__gte=start)
    if end is not None:
        qs = qs.filter(effective_date__lt=end)
    out = {'purchased': ZERO, 'adjusted': ZERO, 'consumed': ZERO, 'expired': ZERO, 'overage': ZERO}
    for r in qs.values('kind', 'block_id').annotate(t=Sum('hours')).order_by():
        t = r['t'] or ZERO
        k = r['kind']
        if k == 'purchase':
            out['purchased'] += t
        elif k == 'adjustment':
            out['adjusted'] += t
        elif k == 'expiry':
            out['expired'] -= t
        elif k == 'consumption':
            out['consumed'] -= t
        elif k == 'overage':
            out['overage'] += t
        elif k == 'reversal':
            if r['block_id'] is None:
                out['overage'] += t      # reversal of overage: negative
            else:
                out['consumed'] -= t     # reversal of consumption: positive hours back
    return out


def _threshold(contract, purchased):
    if contract.low_balance_threshold_hours is not None:
        return Decimal(contract.low_balance_threshold_hours)
    if purchased > 0:
        return (purchased * LOW_BALANCE_DEFAULT_FRACTION).quantize(Decimal('0.01'))
    return None


def _refresh(contract, account=None):
    """Update the cached balance and the low-balance marker; log a crossing."""
    from psa.models import PrepaidLedgerAccount
    if account is None:
        account = PrepaidLedgerAccount.objects.filter(contract_id=contract.pk).first()
        if account is None:
            return None
    if hasattr(contract, '_prepaid_summary'):
        del contract._prepaid_summary
    s = summary(contract, as_of=display_date(contract))
    low_since = account.low_since
    if s.low and contract.status == 'active':
        if low_since is None:
            low_since = timezone.localdate()
            try:
                from audit.models import AuditLog
                AuditLog.log(user=None, action='update', organization=contract.client_org,
                             object_type='psa.Contract', object_id=contract.pk, object_repr=contract.name[:255],
                             description=f'Prepaid balance low: {s.remaining_hours}h left of '
                                         f'{s.total_hours}h (threshold {s.threshold}h).',
                             extra_data={'remaining_hours': str(s.remaining_hours),
                                         'threshold_hours': str(s.threshold)})
            except Exception:  # pragma: no cover
                logger.exception('low-balance audit failed')
    else:
        low_since = None
    PrepaidLedgerAccount.objects.filter(pk=account.pk).update(
        cached_remaining_hours=s.remaining.quantize(Q6), low_since=low_since)
    return s


def low_balance_warnings():
    """System warnings (core.system_warnings) for active agreements whose
    prepaid balance is at or under the low-balance threshold."""
    from psa.models import PrepaidLedgerAccount
    out = []
    accounts = (PrepaidLedgerAccount.objects.filter(low_since__isnull=False, contract__status='active')
                .select_related('contract', 'contract__client_org'))
    for acc in accounts:
        c = acc.contract
        remaining = (acc.cached_remaining_hours or ZERO).quantize(Decimal('0.01'))
        depleted = remaining <= 0
        try:
            from django.urls import reverse
            url = reverse('psa:contract_ledger', kwargs={'pk': c.pk})
        except Exception:
            url = ''
        out.append({
            'id': f'prepaid_low:{c.pk}:{acc.low_since:%Y%m%d}',
            'severity': 'medium' if depleted else 'low',
            'category': 'prepaid_hours',
            'title': (f'Prepaid hours used up: {c.client_org.name} - {c.name}' if depleted
                      else f'Prepaid hours running low: {c.client_org.name} - {c.name}'),
            'detail': f'{remaining}h left.',
            'action_url': url,
            'action_label': 'Open ledger',
            'source_date': timezone.now(),
        })
    return out


def visible_postings_qs(user):
    """Postings of customers where `user` holds the ledger view permission."""
    from accounts.permission_utils import filter_by_org_perm
    from psa.models import PrepaidPosting
    return filter_by_org_perm(PrepaidPosting.objects.all(), user, VIEW_PERMISSION, field='client_org')


__all__ = [
    'LedgerError', 'PrepaidSummary', 'adjust', 'choose_agreement', 'expire_due', 'lock_account', 'open_ledger',
    'plan', 'post_entry', 'post_entries', 'purchase_block', 'release_entry', 'release_entries', 'summary',
    'sync_blocks', 'suspended', 'low_balance_warnings',
]
