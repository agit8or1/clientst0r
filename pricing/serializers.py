"""Plain-dict serializers for pricing rows.

Internal cost data (item cost, target margin, vendor SKU, internal notes,
resolved unit cost, technician cost rates) is left out unless the viewer
holds `pricing_view_internal_cost_rates` at the row's tenant. Any API or
template built on pricing should go through these functions (or reuse
`COST_FIELDS`) rather than dumping model fields.
"""
from decimal import Decimal

from .models import PriceBookItem
from .permissions import can_view_costs

COST_FIELDS = PriceBookItem.COST_FIELDS
RESULT_COST_FIELDS = ('unit_cost',)


def _s(v):
    if isinstance(v, Decimal):
        return str(v)
    return v


def item_to_dict(item, user):
    data = {
        'id': item.pk, 'price_book': item.price_book_id, 'sku': item.sku, 'name': item.name,
        'description': item.description, 'category': item.category, 'item_type': item.item_type,
        'unit_of_measure': item.unit_of_measure, 'pricing_model': item.pricing_model,
        'default_price': _s(item.default_price), 'minimum_price': _s(item.minimum_price),
        'currency': item.effective_currency, 'is_recurring': item.is_recurring,
        'billing_frequency': item.billing_frequency, 'is_active': item.is_active,
        'customer_visible': item.customer_visible, 'tax_category': item.tax_category,
        'revenue_account_code': item.revenue_account_code,
        'effective_from': item.effective_from.isoformat() if item.effective_from else None,
        'effective_to': item.effective_to.isoformat() if item.effective_to else None,
        'tiers': [{'min_quantity': _s(t.min_quantity), 'max_quantity': _s(t.max_quantity),
                   'unit_price': _s(t.unit_price)} for t in item.tiers.all()],
    }
    if can_view_costs(user, item.price_book.organization_id):
        for f in COST_FIELDS:
            data[f] = _s(getattr(item, f))
    return data


def price_result_to_dict(result, user, organization):
    data = {k: _s(v) for k, v in result.__dict__.items() if k not in ('override',)}
    data['override'] = result.override.pk if result.override is not None else None
    if not can_view_costs(user, organization):
        for f in RESULT_COST_FIELDS:
            data.pop(f, None)
    return data


def cost_rate_to_dict(result, user, organization=None):
    """A technician cost rate, or None when the viewer may not see it."""
    if not can_view_costs(user, organization):
        return None
    return {'rate': _s(result.rate), 'unknown': result.unknown, 'reason': result.reason,
            'burdened': result.burdened}
