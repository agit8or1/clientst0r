"""
Per-customer daily AI spend, enforced atomically.

`reserve()` takes the worst-case cost with a single conditional UPDATE —
reserved + spent + amount must stay within the ceiling — so any number of
concurrent runs (several workers, retries, a double-click) can never push a
customer past its budget. `settle()` swaps the reservation for the actual
cost once the provider has answered; `release()` gives it back on failure.

Amounts are in 1/100 cent; AIBusinessPolicy.daily_budget_cents is in cents.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone


def _row(organization):
    from psa_ai.models import AIBudgetDay
    day = timezone.localdate()
    try:
        with transaction.atomic():
            AIBudgetDay.objects.get_or_create(organization=organization, day=day)
    except IntegrityError:
        pass  # created by a concurrent request
    return AIBudgetDay.objects.filter(organization=organization, day=day)


def reserve(organization, amount: int, ceiling: int) -> bool:
    """True if `amount` was reserved under `ceiling` (both 1/100 cent)."""
    if amount < 0 or ceiling <= 0:
        return False
    rows = _row(organization).filter(
        reserved__lte=ceiling - amount - F('spent'),
    ).update(reserved=F('reserved') + amount)
    return rows == 1


def settle(organization, reserved: int, actual: int):
    """Replace a reservation with what the run actually cost. Never more than
    was reserved: the reservation is the worst case by construction."""
    actual = min(actual, reserved)
    _row(organization).update(reserved=F('reserved') - reserved, spent=F('spent') + actual)


def release(organization, reserved: int):
    if reserved:
        _row(organization).update(reserved=F('reserved') - reserved)
