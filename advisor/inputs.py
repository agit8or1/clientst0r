"""
The advisor's only door to cost, rate and price data.

Several pieces the advisor wants are being built on other branches and may or
may not be installed:

  * reports.costing (profitability work): `RateBook` with per-entry cost and
    bill rates that answer None for "unknown", rate snapshots on time entries;
  * reports.queries.monthly_amount: a contract's recurring amount per month;
  * the `pricing` app: price book costs, cost history, service plans;
  * the `licensing` app: license subscriptions with unit cost / unit price.

Each is detected at run time (getattr / apps.is_installed); nothing here fakes
a value. When a source is missing, the answer is None (unknown) and the caller
marks the fact incomplete. In particular the cost rate never falls back to the
placeholder `TechCostRate.rate_for` uses: effective-dated TechCostRate rows are
queried directly, and a technician without one has an unknown cost.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.apps import apps as django_apps

ZERO = Decimal('0')
MONTHS_PER_PERIOD = {'monthly': Decimal('1'), 'quarterly': Decimal('3'), 'yearly': Decimal('12')}


def _dec(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _costing():
    try:
        from reports import costing
    except ImportError:
        return None
    return costing if hasattr(costing, 'RateBook') else None


def _queries_fn(name):
    try:
        from reports import queries
    except ImportError:  # pragma: no cover
        return None
    return getattr(queries, name, None)


def entry_date(entry):
    from django.utils import timezone
    when = getattr(entry, 'started_at', None)
    if isinstance(when, datetime):
        return timezone.localtime(when).date() if timezone.is_aware(when) else when.date()
    if isinstance(when, date):
        return when
    return None


def entry_hours(entry) -> Decimal:
    return Decimal(int(entry.duration_minutes or 0)) / Decimal('60')


# --- availability -------------------------------------------------------------

def licensing_installed() -> bool:
    return django_apps.is_installed('licensing')


def pricing_installed() -> bool:
    return django_apps.is_installed('pricing')


def _model(app_label, name):
    try:
        return django_apps.get_model(app_label, name)
    except (LookupError, ValueError):
        return None


def sources():
    """Which inputs this run reads, for the coverage panel and show-your-work."""
    return {
        'cost_rates': ('reports.costing.RateBook (rate snapshots, then effective-dated tech cost rates)'
                       if _costing() else 'effective-dated technician cost rates (resourcing.TechCostRate)'),
        'monthly_amount': ('reports.queries.monthly_amount' if _queries_fn('monthly_amount')
                           else 'contract recurring amount ÷ billing frequency'),
        'licensing': 'licensing app (subscription unit cost)' if licensing_installed() else None,
        'pricing': 'pricing app (price book, cost history, service plans)' if pricing_installed() else None,
        'distributor_prices': None,  # looked up live by procurement, never stored
    }


# --- rates --------------------------------------------------------------------

class Rates:
    """Cost and bill rates for one run (cached)."""

    def __init__(self):
        costing = _costing()
        self._book = costing.RateBook() if costing else None
        self._cost_rows = {}

    def _tech_rows(self, user_id):
        rows = self._cost_rows.get(user_id)
        if rows is None:
            from resourcing.models import TechCostRate
            rows = list(TechCostRate.objects.filter(user_id=user_id).order_by('-effective_from')
                        .values_list('effective_from', 'rate_per_hour'))
            self._cost_rows[user_id] = rows
        return rows

    def cost_rate(self, entry):
        """Loaded cost per hour for this entry, or None (unknown)."""
        if self._book is not None:
            return _dec(self._book.entry_cost_rate(entry))
        snap = getattr(entry, 'cost_rate_snapshot', None)
        if snap is not None:
            return _dec(snap)
        if not entry.user_id:
            return None
        on = entry_date(entry)
        for effective_from, rate in self._tech_rows(entry.user_id):
            if on is not None and effective_from <= on:
                return _dec(rate)
        return None

    @staticmethod
    def contract_bill_rate(contract):
        if contract is None:
            return None
        for value in (contract.hourly_rate, contract.overage_rate):
            if value is not None and value > 0:
                return _dec(value)
        return None

    def bill_rate(self, entry, contract=None):
        """Hourly bill rate for this entry, or None (unknown)."""
        if self._book is not None:
            return _dec(self._book.bill_rate_for(entry))
        snap = getattr(entry, 'bill_rate_snapshot', None)
        if snap is not None:
            return _dec(snap)
        return self.contract_bill_rate(contract)


def monthly_amount(contract):
    """A contract's recurring amount per month, or None when it has none."""
    fn = _queries_fn('monthly_amount')
    if fn is not None:
        return _dec(fn(contract))
    months = MONTHS_PER_PERIOD.get(contract.billing_frequency)
    if months is None:
        return None
    amount = contract.effective_recurring_amount
    if not amount or amount <= 0:
        return None
    return (Decimal(str(amount)) / months).quantize(Decimal('0.01'))


def billed_time_ids(ids=None):
    from psa.models import InvoiceLineItem
    return InvoiceLineItem.billed_source_ids('time', ids=ids)


# --- licensing ----------------------------------------------------------------

def license_cost(client, months):
    """(value, missing, records) for the licensing cost of `months` months.

    Without the licensing app the cost is not tracked at all: (None, [reason], []).
    With it, active subscriptions' quantity x unit cost, normalized to a month;
    a subscription with no unit cost makes the total unknown."""
    if not licensing_installed():
        return None, ['Vendor / licensing costs are not tracked (licensing module not installed).'], []
    Sub = _model('licensing', 'LicenseSubscription')
    if Sub is None:
        return None, ['Vendor / licensing costs are not tracked (no subscription model).'], []
    per_month = MONTHS_PER_PERIOD
    total, missing, records = ZERO, [], []
    qs = Sub.objects.filter(organization=client)
    if hasattr(Sub, 'status'):
        qs = qs.filter(status='active')
    for sub in qs:
        qty = Decimal(int(getattr(sub, 'quantity_purchased', 0) or 0))
        cost = _dec(getattr(sub, 'unit_cost', None))
        label = str(sub)[:120]
        records.append({'label': label, 'model': 'licensing.LicenseSubscription', 'id': sub.pk, 'url': ''})
        if cost is None:
            missing.append(f'No unit cost on license subscription "{label}".')
            continue
        divisor = per_month.get(getattr(sub, 'billing_frequency', 'monthly'), Decimal('1'))
        total += qty * cost / divisor * Decimal(months)
    if missing:
        return None, missing, records
    return total.quantize(Decimal('0.01')), [], records


def cost_history_available() -> bool:
    """Cost increases can only be judged with a cost history (pricing app)."""
    return pricing_installed() and _model('pricing', 'PriceChangeHistory') is not None


def cost_increases(client, start, end):
    """Price book items this customer is charged for whose unit cost rose in
    [start, end]: list of dicts. Empty when there is no history."""
    if not cost_history_available():
        return []
    History = _model('pricing', 'PriceChangeHistory')
    Override = _model('pricing', 'CustomerPriceOverride')
    item_ids = set()
    if Override is not None:
        item_ids |= set(Override.objects.filter(client_org=client).values_list('item_id', flat=True))
    Plan = _model('pricing', 'ClientServicePlan')
    PlanItem = _model('pricing', 'ServicePlanItem')
    if Plan is not None and PlanItem is not None:
        plan_ids = Plan.objects.filter(client_org=client).values_list('plan_id', flat=True)
        item_ids |= set(PlanItem.objects.filter(plan_id__in=list(plan_ids)).values_list('item_id', flat=True))
    if not item_ids:
        return []
    out = []
    rows = (History.objects.filter(price_book_item_id__in=item_ids, field='cost',
                                   changed_at__date__gte=start, changed_at__date__lte=end)
            .order_by('changed_at'))
    for h in rows:
        old, new = _dec(h.old_value), _dec(h.new_value)
        if old is None or new is None or old <= 0 or new <= old:
            continue
        price_changed = History.objects.filter(
            price_book_item_id=h.price_book_item_id, field='default_price',
            changed_at__gte=h.changed_at).exists()
        item = h.price_book_item
        out.append({
            'item_id': h.price_book_item_id, 'item': str(item)[:120] if item else h.object_repr,
            'old_cost': old, 'new_cost': new, 'changed_at': h.changed_at.date(),
            'price': _dec(getattr(item, 'default_price', None)) if item else None,
            'price_changed_since': price_changed,
        })
    return out


def service_plans(client):
    """Active ClientServicePlan rows (pricing app) for tier-fit, else []."""
    if not pricing_installed():
        return []
    Plan = _model('pricing', 'ClientServicePlan')
    if Plan is None:
        return []
    qs = Plan.objects.filter(client_org=client).select_related('plan')
    if hasattr(Plan, 'status'):
        qs = qs.filter(status='active')
    return list(qs)


def higher_plans(plan):
    """Active plans in the same tenant with more included hours, cheapest first."""
    Model = type(plan)
    qs = Model.objects.filter(organization_id=plan.organization_id, is_active=True, is_addon=False,
                              included_support_hours__gt=plan.included_support_hours or 0)
    return list(qs.order_by('included_support_hours'))
