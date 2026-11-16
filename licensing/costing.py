"""Per-customer license cost, for profitability / advisor / health-score use.

Internal figures: callers must hold `pricing_view_internal_cost_rates` for
the customer before showing them (see licensing.access.can_see_cost).

Following reports.costing, unknown is never zero: a live subscription with
no `unit_cost` is counted in `unknown_cost_count` and makes the result
incomplete; it never contributes 0.
"""
from decimal import Decimal

from .models import LicenseSubscription

MONTHS_PER_PERIOD = {'monthly': 1, 'quarterly': 3, 'annual': 12, 'biennial': 24, 'triennial': 36}
CENT = Decimal('0.01')


def monthly_license_cost(organization, subscriptions=None):
    """Monthly vendor cost of a customer's live licenses.

    `unit_cost` is per unit per billing period; a subscription's monthly cost
    is quantity * unit_cost / months in its period. One-time subscriptions
    are not recurring and are only counted (`one_time_count`).

    Returns a dict:
      monthly_cost       Decimal in `currency`, or None when nothing is known
                         or the known costs are in more than one currency
      currency           the single currency, else None
      by_currency        {code: Decimal} of the known monthly costs
      complete           True only when every recurring live subscription has
                         a cost and there is one currency
      subscriptions      live recurring subscriptions considered
      unknown_cost_count live recurring subscriptions without a unit_cost
      one_time_count     live one-time subscriptions (excluded)
      mixed_currency     True when known costs span several currencies
    """
    if subscriptions is None:
        subscriptions = LicenseSubscription.objects.filter(
            organization=organization, status__in=LicenseSubscription.LIVE_STATUSES)
    by_currency, considered, unknown, one_time = {}, 0, 0, 0
    for sub in subscriptions:
        if not sub.is_live:
            continue
        months = MONTHS_PER_PERIOD.get(sub.billing_frequency)
        if months is None:
            one_time += 1
            continue
        considered += 1
        if sub.unit_cost is None:
            unknown += 1
            continue
        monthly = Decimal(sub.quantity_purchased) * sub.unit_cost / months
        by_currency[sub.currency] = by_currency.get(sub.currency, Decimal('0')) + monthly
    by_currency = {k: v.quantize(CENT) for k, v in by_currency.items()}
    mixed = len(by_currency) > 1
    single = next(iter(by_currency)) if len(by_currency) == 1 else None
    return {
        'monthly_cost': by_currency[single] if single else None,
        'currency': single,
        'by_currency': by_currency,
        'complete': not unknown and not mixed and (bool(by_currency) or considered == 0),
        'subscriptions': considered,
        'unknown_cost_count': unknown,
        'one_time_count': one_time,
        'mixed_currency': mixed,
    }
