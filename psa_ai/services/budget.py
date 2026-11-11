"""
Per-customer AI spend, enforced atomically, per day and per calendar month.

`reserve()` takes the worst-case cost with a single conditional UPDATE —
reserved + spent + amount must stay within the ceiling — so any number of
concurrent runs (several workers, retries, a double-click) can never push a
customer past its budget. It does this for the day (the ceiling passed in,
from AIBusinessPolicy.daily_budget_cents) and then for the month
(AIBusinessPolicy.monthly_budget_cents, read here; blank = no monthly
ceiling, but the month is still tracked). If the month refuses, the day's
reservation is given back. `settle()` swaps the reservation for the actual
cost once the provider has answered; `release()` gives it back on failure.

Every AI path that reserves here — ticket analysis, Rem0te jobs and AI
Troubleshoot — counts against the same day and month.

Amounts are in 1/100 cent; the policy ceilings are in cents.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone


def _day_row(organization):
    from psa_ai.models import AIBudgetDay
    day = timezone.localdate()
    try:
        with transaction.atomic():
            AIBudgetDay.objects.get_or_create(organization=organization, day=day)
    except IntegrityError:
        pass  # created by a concurrent request
    return AIBudgetDay.objects.filter(organization=organization, day=day)


# Kept for callers that used the old name.
_row = _day_row


def month_start(day=None):
    day = day or timezone.localdate()
    return day.replace(day=1)


def _month_row(organization):
    from psa_ai.models import AIBudgetMonth
    month = month_start()
    try:
        with transaction.atomic():
            AIBudgetMonth.objects.get_or_create(organization=organization, month=month)
    except IntegrityError:
        pass
    return AIBudgetMonth.objects.filter(organization=organization, month=month)


def monthly_ceiling(organization):
    """This month's ceiling in 1/100 cent, or None for no monthly ceiling."""
    from psa_ai.models import AIBusinessPolicy
    cents = (AIBusinessPolicy.objects.filter(organization=organization)
             .values_list('monthly_budget_cents', flat=True).first())
    return None if cents is None else cents * 100


def reserve(organization, amount: int, ceiling: int) -> bool:
    """True if `amount` was reserved under the daily `ceiling` and the
    customer's monthly ceiling (all 1/100 cent)."""
    if amount < 0 or ceiling <= 0:
        return False
    rows = _day_row(organization).filter(
        reserved__lte=ceiling - amount - F('spent'),
    ).update(reserved=F('reserved') + amount)
    if rows != 1:
        return False
    month = _month_row(organization)
    monthly = monthly_ceiling(organization)
    if monthly is not None:
        month = month.filter(reserved__lte=monthly - amount - F('spent'))
    if month.update(reserved=F('reserved') + amount) != 1:
        _day_row(organization).update(reserved=Greatest(F('reserved') - amount, 0))
        return False
    return True


def settle(organization, reserved: int, actual: int):
    """Replace a reservation with what the run actually cost. Never more than
    was reserved: the reservation is the worst case by construction."""
    actual = min(actual, reserved)
    for rows in (_day_row(organization), _month_row(organization)):
        rows.update(reserved=Greatest(F('reserved') - reserved, 0), spent=F('spent') + actual)


def release(organization, reserved: int):
    if reserved:
        for rows in (_day_row(organization), _month_row(organization)):
            rows.update(reserved=Greatest(F('reserved') - reserved, 0))


def month_remaining(organization):
    """This month's remaining spend in 1/100 cent, or None without a monthly ceiling."""
    from psa_ai.models import AIBudgetMonth
    monthly = monthly_ceiling(organization)
    if monthly is None:
        return None
    row = AIBudgetMonth.objects.filter(organization=organization, month=month_start()).first()
    used = (row.reserved + row.spent) if row else 0
    return max(0, monthly - used)
