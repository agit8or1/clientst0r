"""Agreement reconciliation figures, shared by the summary report and its
per-contract drill-down so the two can never disagree (Phase 101.4).

For a contract with a prepaid-hour ledger, the ledger decides: the allowance
is the hours bought (purchases + adjustments), and each time entry's active
consumption / overage postings are its covered / overage minutes, walked in
the order they were posted (the order hours were used). Time the ledger does
not hold yet (not approved, or waiting for an agreement choice) is listed
separately and uses nothing.

A contract without a ledger (no allowance: unlimited / flat fee) keeps the
old counter: its qualifying time entries, all counted as covered.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal

from . import coverage, ledger

D = Decimal


@dataclass
class Reconciliation:
    contract: object
    tracked: bool
    allowance_minutes: int = 0
    covered_minutes: int = 0
    overage_minutes: int = 0
    rows: list = field(default_factory=list)
    pending: list = field(default_factory=list)   # [{'entry', 'minutes', 'reason'}]

    @property
    def used_minutes(self):
        return self.covered_minutes + self.overage_minutes

    @property
    def pending_minutes(self):
        return sum(p['minutes'] for p in self.pending)

    @property
    def unlimited(self):
        return not self.tracked and self.allowance_minutes <= 0

    def hours(self, minutes):
        return (D(int(minutes)) / D(60)).quantize(D('0.01'))


def summary_figures(contract):
    """(consumed_hours, allowance_hours, overage_hours) for the summary row.
    Light: ledger sums only, no per-entry walk."""
    lt = ledger.totals(contract)
    if lt is None:
        used = D(contract.hours_used_minutes or 0) / D(60)
        allowance = D(contract.total_hours or 0)
        overage = max(used - allowance, D(0)) if allowance > 0 else D(0)
        return used, allowance, overage
    return lt['consumed'] + lt['overage'], lt['purchased'] + lt['adjusted'], lt['overage']


def build(contract, *, with_pending=True):
    lt = ledger.totals(contract)
    if lt is None:
        rec = Reconciliation(contract=contract, tracked=False,
                             allowance_minutes=int(D(contract.total_hours or 0) * 60))
        cumulative = 0
        for e in contract.qualifying_time_entries().select_related('ticket', 'user').order_by('started_at', 'pk'):
            dur = int(e.duration_minutes or 0)
            cumulative += dur
            rec.covered_minutes += dur
            rec.rows.append({'entry': e, 'entry_ref': e.pk, 'duration_minutes': dur,
                             'cumulative_minutes': cumulative, 'covered_minutes': dur,
                             'overage_minutes': 0, 'classification': 'unlimited', 'status': ''})
        return rec

    from psa.models import PrepaidPosting, TicketTimeEntry
    rec = Reconciliation(contract=contract, tracked=True,
                         allowance_minutes=ledger.minutes_of(lt['purchased'] + lt['adjusted']))
    held = (PrepaidPosting.objects.filter(contract=contract, kind__in=['consumption', 'overage'],
                                          reversed_by__isnull=True)
            .select_related('time_entry', 'time_entry__ticket', 'time_entry__user')
            .order_by('created_at', 'pk'))
    groups = OrderedDict()
    for p in held:
        key = p.time_entry_ref if p.time_entry_ref is not None else f'p{p.pk}'
        g = groups.setdefault(key, {'entry': p.time_entry, 'entry_ref': p.time_entry_ref,
                                    'covered_minutes': 0, 'overage_minutes': 0, 'statuses': set(),
                                    'effective_date': p.effective_date})
        if p.kind == 'consumption':
            g['covered_minutes'] += ledger.minutes_of(-p.hours)
        else:
            g['overage_minutes'] += ledger.minutes_of(p.hours)
        g['statuses'].add(p.status)
    cumulative = 0
    for g in groups.values():
        cov, over = g['covered_minutes'], g['overage_minutes']
        if cov <= 0 and over <= 0:
            continue
        cumulative += cov + over
        rec.covered_minutes += cov
        rec.overage_minutes += over
        rec.rows.append({
            'entry': g['entry'], 'entry_ref': g['entry_ref'], 'duration_minutes': cov + over,
            'cumulative_minutes': cumulative, 'covered_minutes': cov, 'overage_minutes': over,
            'classification': 'overage' if cov <= 0 else ('split' if over > 0 else 'covered'),
            'status': 'opening balance' if g['statuses'] == {'migrated'} else 'approved',
            'effective_date': g['effective_date'],
        })

    if with_pending:
        held_refs = set(PrepaidPosting.objects.filter(kind__in=['consumption', 'overage'],
                                                      reversed_by__isnull=True,
                                                      time_entry_ref__isnull=False)
                        .filter(time_entry__ticket__organization_id=contract.client_org_id)
                        .values_list('time_entry_ref', flat=True))
        qs = (TicketTimeEntry.objects.filter(ticket__organization_id=contract.client_org_id, is_billable=True,
                                             ended_at__isnull=False, duration_minutes__gt=0,
                                             started_at__date__gte=contract.start_date)
              .exclude(pk__in=held_refs).select_related('ticket', 'user', 'ticket__organization')
              .order_by('started_at', 'pk'))
        if contract.end_date:
            qs = qs.filter(started_at__date__lte=contract.end_date)
        for e in qs:
            res = coverage.resolve(e, plan=False)
            if res.status == 'needs_choice' and any(c.pk == contract.pk for c in res.candidates):
                reason = 'needs an agreement choice; uses nothing yet'
            elif res.agreement is not None and res.agreement.pk == contract.pk and res.treatment == 'prepaid':
                reason = 'not yet approved; uses nothing'
            else:
                continue
            rec.pending.append({'entry': e, 'minutes': int(e.duration_minutes or 0), 'reason': reason})
    return rec
