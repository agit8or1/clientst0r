"""
Recommendation math. Every proposal is a deterministic calculation from the
facts, returned with its "show your work" record:

  formula      the rule in words
  steps        each arithmetic step with its result
  inputs       the figures used: value, unit, basis (verified / estimate /
               unknown) and links to the records behind them
  assumptions  what the calculation takes for granted
  unknown      what is missing and how that affects the answer

No rate, price or cost is invented: when an input is unknown the proposal
says so and either uses only what is known (stated as a minimum) or gives no
number at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import List, Optional

from .facts import HUNDRED, ZERO, money_str, q2


@dataclass
class RecSpec:
    key: str
    rec_type: str
    title: str
    rationale: str
    proposed: dict
    work: dict
    contract: object = None


def inp(label, value, unit='money', basis='verified', records=None, note=''):
    return {'label': label, 'value': None if value is None else f'{q2(value):.2f}', 'unit': unit,
            'basis': basis, 'records': list(records or [])[:10], 'note': note}


def fact_inp(fact, label=None):
    return inp(label or fact.label, fact.value if fact.value is not None else fact.lower, fact.unit,
               fact.basis if fact.value is not None else ('estimate' if fact.lower is not None else 'unknown'),
               fact.records, note='' if fact.is_complete else 'known part only')


def work(formula, steps, inputs, assumptions=(), unknown=()):
    return {'formula': formula, 'steps': list(steps), 'inputs': list(inputs),
            'assumptions': list(assumptions), 'unknown': list(unknown)}


def target_fraction(target_pct):
    return Decimal(str(target_pct)) / HUNDRED


def price_for_margin(cost, target_pct):
    """Revenue needed for `cost` to leave `target_pct` margin: cost ÷ (1 − target)."""
    t = target_fraction(target_pct)
    if t >= 1:
        return None
    return q2(Decimal(str(cost)) / (Decimal('1') - t))


def ceil_hours(value):
    return Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING)


def price_change(key, rec_type, title, rationale, *, contract, current, proposed, unit, formula, steps,
                 inputs, assumptions=(), unknown=(), field_name='recurring_amount', minimum=False, extra=None):
    current = q2(current) if current is not None else None
    proposed = q2(proposed) if proposed is not None else None
    change = q2(proposed - current) if (proposed is not None and current is not None) else None
    pct = q2(change / current * HUNDRED) if (change is not None and current) else None
    return RecSpec(key, rec_type, title, rationale, {
        'field': field_name, 'unit': unit, 'current': money_str(current), 'proposed': money_str(proposed),
        'change': money_str(change), 'change_pct': None if pct is None else f'{pct:.2f}',
        'is_minimum': bool(minimum), **(extra or {}),
    }, work(formula, steps, inputs, assumptions, unknown), contract)


def required_monthly_for_target(cost, months, target_pct):
    """(monthly cost, required monthly revenue) for a window's cost."""
    monthly_cost = q2(Decimal(str(cost)) / Decimal(months))
    return monthly_cost, price_for_margin(monthly_cost, target_pct)


def main_recurring_contract(contracts):
    """The active contract with the largest monthly recurring amount, or None."""
    from . import inputs as _inputs
    best, best_amt = None, ZERO
    for c in contracts:
        amt = _inputs.monthly_amount(c)
        if amt is not None and amt > best_amt:
            best, best_amt = c, amt
    return best


def steps_list(*pairs) -> List[str]:
    return [p for p in pairs if p]


def opt(v: Optional[Decimal]):
    return 'unknown' if v is None else f'{q2(v):.2f}'
