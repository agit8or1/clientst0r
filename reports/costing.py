"""
Cost and bill rates for profitability reporting.

Every margin, cost and attributed-revenue figure in the product reads its
rates from here, so there is one answer to "what did this hour cost, and
what was it billed at". The rule is simple: a rate is either known or it is
None. Nothing in this module invents a default — a report built on a guessed
rate is presented as measured, and that is worse than saying "unknown".

Lookup order
------------
Cost rate for a time entry (`entry_cost_rate`):
  1. `entry.cost_rate_snapshot`, when the model has that field and it is set
     (the per-entry snapshot the price book adds; read with getattr so this
     module works before and after that field exists);
  2. the technician's effective-dated `resourcing.TechCostRate` row on the
     day the work happened (queried directly — `TechCostRate.rate_for` falls
     back to a placeholder, which is exactly what this module refuses to do);
  3. otherwise None (unknown).

Bill rate for a time entry (`bill_rate_for`):
  1. `entry.bill_rate_snapshot`, when present and set;
  2. the contract the entry belongs to (`entry.contract` when that FK exists,
     else the non-draft contract of the ticket's client covering the entry
     date): its `hourly_rate`, else its `overage_rate`;
  3. otherwise None (unknown). A flat-fee contract with no hourly rate has no
     per-hour bill rate, so its time is "unknown", not "$0".

`RateBook` caches lookups for one report run; the module-level functions
are thin wrappers for one-off use.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

ZERO = Decimal('0')
SIXTY = Decimal('60')
CENT = Decimal('0.01')


def _dec(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def entry_date(entry):
    """Calendar day (active timezone) the work in `entry` happened."""
    from django.utils import timezone
    when = getattr(entry, 'started_at', None) or getattr(entry, 'created_at', None)
    if when is None:
        return None
    if isinstance(when, datetime):
        if timezone.is_aware(when):
            return timezone.localtime(when).date()
        return when.date()
    if isinstance(when, date):
        return when
    return None


def entry_hours(entry):
    return Decimal(int(getattr(entry, 'duration_minutes', 0) or 0)) / SIXTY


def _snapshot(entry, attr):
    """Per-entry rate snapshot when the model carries it and it is set."""
    value = getattr(entry, attr, None)
    return _dec(value) if value is not None else None


class RateBook:
    """Rate lookups with per-run caches (one query per technician for cost
    rates, one per client for contracts)."""

    def __init__(self):
        self._cost_rows = {}       # user_id -> [(effective_from, rate)] newest first
        self._contracts = {}       # client_org_id -> [Contract]

    # --- cost ---------------------------------------------------------------

    def _rows_for(self, user_id):
        rows = self._cost_rows.get(user_id)
        if rows is None:
            from resourcing.models import TechCostRate
            rows = list(TechCostRate.objects.filter(user_id=user_id)
                        .order_by('-effective_from')
                        .values_list('effective_from', 'rate_per_hour'))
            self._cost_rows[user_id] = rows
        return rows

    def cost_rate_for(self, tech, on_date):
        """The technician's configured loaded cost rate on `on_date`, or None."""
        if tech is None or on_date is None:
            return None
        user_id = getattr(tech, 'pk', tech)
        if user_id is None:
            return None
        for effective_from, rate in self._rows_for(user_id):
            if effective_from <= on_date:
                return _dec(rate)
        return None

    def entry_cost_rate(self, entry):
        snap = _snapshot(entry, 'cost_rate_snapshot')
        if snap is not None:
            return snap
        if not getattr(entry, 'user_id', None):
            return None
        return self.cost_rate_for(entry.user_id, entry_date(entry))

    # --- bill ---------------------------------------------------------------

    def _contracts_for(self, client_org_id):
        rows = self._contracts.get(client_org_id)
        if rows is None:
            from psa.models import Contract
            rows = list(Contract.objects.filter(client_org_id=client_org_id)
                        .exclude(status='draft')
                        .order_by('-start_date', '-pk'))
            self._contracts[client_org_id] = rows
        return rows

    def contract_for_entry(self, entry):
        """The contract a time entry belongs to: the entry's own `contract`
        FK when the model has one, else the client's non-draft contract whose
        window covers the entry date (an active one preferred)."""
        direct = getattr(entry, 'contract', None)
        if direct is not None:
            return direct
        ticket = getattr(entry, 'ticket', None)
        client_id = getattr(ticket, 'organization_id', None) if ticket is not None else None
        return self.contract_for_client_on(client_id, entry_date(entry))

    def contract_for_client_on(self, client_id, on_date):
        """The client's non-draft contract whose window covers `on_date` (an
        active one preferred), or None."""
        if not client_id or on_date is None:
            return None
        covering = [c for c in self._contracts_for(client_id)
                    if c.start_date and c.start_date <= on_date
                    and (c.end_date is None or c.end_date >= on_date)]
        if not covering:
            return None
        active = [c for c in covering if c.status == 'active']
        return (active or covering)[0]

    @staticmethod
    def contract_bill_rate(contract):
        if contract is None:
            return None
        for value in (contract.hourly_rate, contract.overage_rate):
            if value is not None and value > 0:
                return _dec(value)
        return None

    def bill_rate_for(self, entry):
        snap = _snapshot(entry, 'bill_rate_snapshot')
        if snap is not None:
            return snap
        return self.contract_bill_rate(self.contract_for_entry(entry))


def cost_rate_for(tech, on_date):
    """Loaded cost rate ($/hr) for `tech` on `on_date` from its effective-dated
    `TechCostRate` rows, or None when none applies."""
    return RateBook().cost_rate_for(tech, on_date)


def entry_cost_rate(entry):
    """Cost rate for one time entry: its snapshot, else the technician's rate
    on the entry date, else None."""
    return RateBook().entry_cost_rate(entry)


def bill_rate_for(entry):
    """Bill rate ($/hr) for one time entry: its snapshot, else its contract's
    hourly / overage rate, else None."""
    return RateBook().bill_rate_for(entry)


# ---------------------------------------------------------------------------
# Accumulating known and unknown amounts
# ---------------------------------------------------------------------------

class LaborTally:
    """Hours, known cost and known attributed revenue for a group of time
    entries, with the hours and entries that could not be priced kept
    separately so a partial total is never mistaken for a complete one."""

    __slots__ = ('hours', 'cost', 'unknown_cost_hours', 'unknown_cost_entries',
                 'billable_hours', 'revenue', 'unknown_bill_hours', 'unknown_bill_entries',
                 'billable_minutes')

    def __init__(self):
        self.hours = ZERO
        self.cost = ZERO
        self.unknown_cost_hours = ZERO
        self.unknown_cost_entries = 0
        self.billable_hours = ZERO
        self.billable_minutes = 0
        self.revenue = ZERO
        self.unknown_bill_hours = ZERO
        self.unknown_bill_entries = 0

    def add_cost(self, hours, rate):
        self.hours += hours
        if rate is None:
            if hours > 0:
                self.unknown_cost_hours += hours
                self.unknown_cost_entries += 1
        else:
            self.cost += hours * rate

    def add_revenue(self, hours, rate, minutes=0):
        self.billable_hours += hours
        self.billable_minutes += int(minutes or 0)
        if rate is None:
            if hours > 0:
                self.unknown_bill_hours += hours
                self.unknown_bill_entries += 1
        else:
            self.revenue += hours * rate

    @property
    def cost_complete(self):
        return self.unknown_cost_entries == 0

    @property
    def revenue_complete(self):
        return self.unknown_bill_entries == 0

    def cost_fields(self):
        return {
            'hours': float(round(self.hours, 2)),
            'cost': float(self.cost.quantize(CENT)),
            'unknown_cost_hours': float(round(self.unknown_cost_hours, 2)),
            'unknown_cost_entries': self.unknown_cost_entries,
            'cost_complete': self.cost_complete,
        }

    def revenue_fields(self):
        return {
            'billable_hours': float(round(self.billable_hours, 2)),
            'attributed_revenue': float(self.revenue.quantize(CENT)),
            'unknown_bill_hours': float(round(self.unknown_bill_hours, 2)),
            'unknown_bill_entries': self.unknown_bill_entries,
            'revenue_complete': self.revenue_complete,
        }


def margin_fields(revenue, cost, cost_complete=True, revenue_complete=True):
    """`margin`, `margin_pct` and `is_complete` for one row.

    Margin is None unless both sides are fully known: subtracting a partial
    cost from revenue produces a number that looks like a margin and isn't.
    `margin_pct` is also None when revenue is zero.
    """
    complete = bool(cost_complete and revenue_complete)
    if not complete or revenue is None or cost is None:
        return {'margin': None, 'margin_pct': None, 'is_complete': complete}
    margin = float(revenue) - float(cost)
    pct = round(margin / float(revenue) * 100, 1) if revenue else None
    return {'margin': round(margin, 2), 'margin_pct': pct, 'is_complete': True}


def summarize(rows, revenue_key='revenue'):
    """Totals across report rows produced by the profitability queries.

    Cost is partial when any row has an hour without a cost rate or an item
    without a cost (`reports.financials`); `partial_reasons` lists why, for
    the "Partial" label.
    """
    from .financials import cost_reasons
    total_revenue = sum((r.get(revenue_key) or 0.0) for r in rows)
    total_cost = sum((r.get('cost') or 0.0) for r in rows)
    unknown_cost_hours = sum((r.get('unknown_cost_hours') or 0.0) for r in rows)
    unknown_cost_entries = sum((r.get('unknown_cost_entries') or 0) for r in rows)
    unknown_bill_hours = sum((r.get('unknown_bill_hours') or 0.0) for r in rows)
    unknown_bill_entries = sum((r.get('unknown_bill_entries') or 0) for r in rows)
    unknown_item_count = sum((r.get('unknown_item_count') or 0) for r in rows)
    no_tech = sum((r.get('entries_without_technician') or 0) for r in rows)
    techs = set()
    for r in rows:
        techs.update(r.get('unknown_rate_technicians') or ())
    out = {
        'total_revenue': round(total_revenue, 2),
        'total_cost': round(total_cost, 2),
        'unknown_cost_hours': round(unknown_cost_hours, 2),
        'unknown_cost_entries': unknown_cost_entries,
        'unknown_bill_hours': round(unknown_bill_hours, 2),
        'unknown_bill_entries': unknown_bill_entries,
        'unknown_item_count': unknown_item_count,
        'unknown_rate_technician_count': len(techs),
    }
    cost_complete = unknown_cost_entries == 0 and unknown_item_count == 0
    m = margin_fields(total_revenue, total_cost,
                      cost_complete=cost_complete,
                      revenue_complete=unknown_bill_entries == 0)
    out['total_margin'] = m['margin']
    out['blended_margin_pct'] = m['margin_pct']
    out['is_complete'] = m['is_complete']
    out['partial'] = not m['is_complete']
    out['partial_reasons'] = cost_reasons(len(techs), unknown_cost_hours, no_tech,
                                          unknown_item_count, unknown_bill_hours)
    return out
