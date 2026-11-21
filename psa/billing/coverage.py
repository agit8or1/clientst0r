"""Phase 101.1: the coverage resolver.

One function, `resolve(obj)`, answers for a time entry (or an account charge)
which customer and agreement it belongs to, how the agreement covers it and how
it splits into covered / prepaid / chargeable. The prepaid ledger
(psa.billing.ledger) posts from this answer when time is approved; the ticket
page and reports can call it read-only to show the treatment.

Agreement precedence (documented, never a guess):

1. An agreement a person chose for the entry (`billing_contract_chosen`), as
   long as it still covers the entry. If it no longer does, the answer is
   "needs choice".
2. Otherwise the customer's agreements that cover the work date: not draft,
   window start..end containing the date (open-ended when the end is blank;
   a cancelled agreement only with an end date), and whose role gates let
   the entry's role code count (the same gates as the old hour counter:
   excluded codes never count, a tagged entry counts only when the billable
   list is empty or names it, untagged entries count).
3. Of those, the highest `billing_priority` wins. Two or more at the same
   highest priority: "needs choice" - nothing is consumed until someone with
   the billing permission picks one (ledger.choose_agreement).
4. None: no agreement (time and materials).

Treatment once the agreement is known:

* not billable                     -> non_billable, nothing consumed
* allowance (total hours or rolled-over hours) -> prepaid: the hours come out
  of the agreement's blocks valid on the work date, earliest expiry first;
  what does not fit is overage at the overage rate (or the hourly rate),
  unless the agreement allows a negative balance
* flat-fee agreement (managed services / retainer) without an allowance ->
  covered (unlimited): tracked, never consumed, no labour charge
* any other agreement              -> chargeable at the agreement's hourly rate
* no agreement                     -> chargeable; the rate shown is the rate-card
  snapshot taken when the entry was created. Invoicing still bills time
  without an agreement at 0 until 101.4; `invoice_rate` says what the invoice
  uses today.

Coverage attributes are reported where the data exists: service category (the
ticket type), work type (remote / onsite / travel from the entry's rate type)
and business hours (False for after-hours, weekend, holiday and emergency rate
types; None when nothing says, since there is no business-hours calendar yet).
No coverage exclusion is applied on them yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

ZERO = Decimal('0')
OUT_OF_HOURS_RATE_TYPES = ('after_hours', 'weekend', 'holiday', 'emergency')
WORK_TYPES = ('remote', 'onsite', 'travel')


@dataclass
class Resolution:
    kind: str                       # 'time' | 'charge'
    status: str                     # resolved | needs_choice | no_agreement | not_ready
    reason: str = ''
    customer: object = None         # core.Organization
    agreement: object = None        # psa.Contract
    candidates: list = field(default_factory=list)
    on_date: date | None = None
    treatment: str = ''             # prepaid | covered | chargeable | non_billable | ''
    coverage: dict = field(default_factory=dict)
    minutes: int = 0
    rate: Decimal | None = None
    rate_source: str = ''
    invoice_rate: Decimal | None = None
    covered_hours: Decimal = ZERO
    prepaid_hours: Decimal = ZERO
    chargeable_hours: Decimal = ZERO
    chargeable_amount: Decimal = ZERO
    # [(block or None for a cycle block not opened yet, minutes)]
    allocations: list = field(default_factory=list)
    overage_minutes: int = 0
    negative_minutes: int = 0

    @property
    def resolution_code(self):
        """Value for TicketTimeEntry.billing_resolution."""
        if self.status == 'needs_choice':
            return 'needs_choice'
        if self.status == 'no_agreement':
            return 'no_agreement' if self.treatment != 'non_billable' else 'non_billable'
        if self.status != 'resolved':
            return ''
        if self.treatment == 'prepaid':
            if self.overage_minutes and self.overage_minutes < self.minutes:
                return 'partial'
            if self.overage_minutes:
                return 'overage'
            return 'prepaid'
        return self.treatment


def hours(minutes) -> Decimal:
    return (Decimal(int(minutes or 0)) / Decimal(60)).quantize(Decimal('0.000001'))


def work_date(entry):
    started = entry.started_at
    if started is None:
        return None
    if isinstance(started, datetime):
        return timezone.localtime(started).date() if timezone.is_aware(started) else started.date()
    return started


def role_allows(contract, role_code):
    """The old hour counter's role gates (Contract.qualifying_time_entries)."""
    code = role_code or ''
    excluded = [c for c in (contract.excluded_role_codes or []) if c]
    if code and code in excluded:
        return False
    included = [c for c in (contract.billable_role_codes or []) if c]
    if included and code and code not in included:
        return False
    return True


def candidate_agreements(client_org_id, on_date, role_code=None):
    """Agreements of this customer that can cover work on `on_date`."""
    from psa.models import Contract
    if not client_org_id or on_date is None:
        return []
    qs = (Contract.objects.filter(client_org_id=client_org_id, start_date__lte=on_date)
          .filter(Q(end_date__isnull=True) | Q(end_date__gte=on_date))
          .exclude(status='draft')
          .exclude(status='cancelled', end_date__isnull=True)
          .order_by('-billing_priority', 'start_date', 'pk'))
    out = list(qs)
    if role_code is not None:
        out = [c for c in out if role_allows(c, role_code)]
    return out


def pick_agreement(candidates):
    """(agreement, status, reason) by priority; ties need a choice."""
    if not candidates:
        return None, 'no_agreement', 'No agreement of this customer covers the date.'
    top = max(c.billing_priority for c in candidates)
    best = [c for c in candidates if c.billing_priority == top]
    if len(best) == 1:
        others = len(candidates) - 1
        why = 'Only agreement covering the date.' if not others else (
            f'Highest billing priority ({top}) of {len(candidates)} agreements covering the date.')
        return best[0], 'resolved', why
    names = ', '.join(c.name for c in best)
    return None, 'needs_choice', (f'{len(best)} agreements cover the date at the same billing priority '
                                  f'({names}); choose one.')


def has_allowance(contract):
    return bool((contract.total_hours or ZERO) > 0 or (contract.rolled_over_minutes or 0) > 0)


def _coverage_attrs(entry):
    ticket = getattr(entry, 'ticket', None)
    ttype = getattr(ticket, 'ticket_type', None) if ticket is not None else None
    rate_type = entry.rate_type or ''
    return {
        'service_category': getattr(ttype, 'name', '') or '',
        'work_type': rate_type if rate_type in WORK_TYPES else '',
        'rate_type': rate_type,
        'business_hours': False if rate_type in OUT_OF_HOURS_RATE_TYPES else None,
        'role_code': entry.role_code or '',
    }


def resolve(obj, *, plan=True):
    """Resolve a psa.TicketTimeEntry or psa.Charge. Read-only."""
    from psa.models import Charge
    if isinstance(obj, Charge):
        return _resolve_charge(obj)
    return _resolve_entry(obj, plan=plan)


def _resolve_entry(entry, *, plan=True):
    ticket = entry.ticket
    customer = getattr(ticket, 'organization', None)
    on = work_date(entry)
    minutes = int(entry.duration_minutes or 0)
    res = Resolution(kind='time', status='resolved', customer=customer, on_date=on, minutes=minutes,
                     coverage=_coverage_attrs(entry))
    if entry.ended_at is None or minutes <= 0:
        res.status = 'not_ready'
        res.reason = 'The timer is running or the entry has no duration.'
        return res

    candidates = candidate_agreements(getattr(customer, 'pk', None), on, entry.role_code)
    res.candidates = candidates
    if entry.billing_contract_chosen and entry.billing_contract_id:
        chosen = next((c for c in candidates if c.pk == entry.billing_contract_id), None)
        if chosen is None:
            res.status = 'needs_choice'
            res.reason = 'The agreement chosen for this entry no longer covers it; choose again.'
        else:
            res.agreement = chosen
            res.reason = 'Chosen for this entry.'
    else:
        res.agreement, res.status, res.reason = pick_agreement(candidates)

    if not entry.is_billable:
        res.treatment = 'non_billable'
        return res
    if res.status == 'needs_choice':
        return res
    if res.agreement is None:
        res.treatment = 'chargeable'
        res.rate = entry.bill_rate_snapshot
        res.rate_source = 'rate card snapshot' if entry.bill_rate_snapshot is not None else 'none'
        res.invoice_rate = ZERO
        res.chargeable_hours = hours(minutes)
        res.chargeable_amount = (res.chargeable_hours * (res.rate or ZERO)).quantize(Decimal('0.01'))
        return res
    return _treat(res, res.agreement, minutes, on, entry=entry, plan=plan)


def _treat(res, contract, minutes, on, *, entry=None, plan=True):
    from psa.models import Contract
    if has_allowance(contract):
        res.treatment = 'prepaid'
        over_rate = contract.overage_rate or contract.hourly_rate or ZERO
        res.rate = Decimal(str(over_rate))
        res.rate_source = 'agreement overage rate' if contract.overage_rate else 'agreement hourly rate'
        res.invoice_rate = res.rate
        if plan:
            from . import ledger
            allocs, over, negative = ledger.plan(contract, on, minutes, exclude_entry=entry)
            res.allocations = allocs
            res.overage_minutes = over
            res.negative_minutes = negative
        else:
            res.overage_minutes = 0
        res.prepaid_hours = hours(minutes - res.overage_minutes)
        res.chargeable_hours = hours(res.overage_minutes)
        res.chargeable_amount = (res.chargeable_hours * res.rate).quantize(Decimal('0.01'))
        return res
    if contract.contract_type in Contract.FLAT_FEE_TYPES:
        res.treatment = 'covered'
        res.covered_hours = hours(minutes)
        res.rate = ZERO
        res.rate_source = 'covered by the agreement fee'
        res.invoice_rate = ZERO
        return res
    res.treatment = 'chargeable'
    res.rate = Decimal(str(contract.hourly_rate or 0))
    res.rate_source = 'agreement hourly rate'
    res.invoice_rate = res.rate
    res.chargeable_hours = hours(minutes)
    res.chargeable_amount = (res.chargeable_hours * res.rate).quantize(Decimal('0.01'))
    return res


def _resolve_charge(charge):
    """Account charges are money, not hours: they resolve to an agreement for
    reporting and are always chargeable (a credit is a negative charge)."""
    customer = charge.client_org
    on = charge.charge_date
    res = Resolution(kind='charge', status='resolved', customer=customer, on_date=on)
    res.candidates = candidate_agreements(charge.client_org_id, on)
    res.agreement, res.status, res.reason = pick_agreement(res.candidates)
    amount = Decimal(str(charge.amount or 0))
    res.treatment = 'chargeable'
    res.chargeable_amount = -amount if charge.is_credit else amount
    res.rate_source = 'charge amount'
    return res
