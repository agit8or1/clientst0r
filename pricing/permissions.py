"""Pricing permission helpers (keys live in accounts.permission_registry).

Every pricing permission is MSP-staff-only. Checks are made against the
tenant that owns the row (`organization`) through the shared
accounts.permission_utils rules, so client scope and global roles apply.
"""
from accounts.permission_utils import user_has_org_perm, user_has_perm

MANAGE_PRICE_BOOKS = 'pricing_manage_price_books'
MANAGE_SERVICE_PLANS = 'pricing_manage_service_plans'
VIEW_INTERNAL_COST_RATES = 'pricing_view_internal_cost_rates'
MANAGE_LABOR_RATE_CARDS = 'pricing_manage_labor_rate_cards'
APPROVE_DISCOUNTS = 'pricing_approve_discounts'

ALL = (MANAGE_PRICE_BOOKS, MANAGE_SERVICE_PLANS, VIEW_INTERNAL_COST_RATES, MANAGE_LABOR_RATE_CARDS,
       APPROVE_DISCOUNTS)


def has(user, perm, organization=None):
    """`perm` at `organization` (an Organization / pk), or anywhere when None."""
    if user is None:
        return False
    if organization is None:
        return user_has_perm(user, perm)
    return user_has_org_perm(user, organization, perm)


def can_view_costs(user, organization=None):
    return has(user, VIEW_INTERNAL_COST_RATES, organization)
