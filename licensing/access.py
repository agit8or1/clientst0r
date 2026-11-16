"""Who may see and change licensing.

The /licensing/ pages are MSP-staff only (accounts.middleware
STAFF_ONLY_PREFIXES). Within that:

  view   assets_view in the customer (orgs_with_perm)
  manage manage_licensing in the customer
  cost   pricing_view_internal_cost_rates in the customer

`unit_cost` (what the MSP pays) is never rendered, exported or accepted by a
form unless `can_see_cost` holds for the subscription's customer.
"""
from django.http import Http404

from accounts.permission_utils import orgs_with_perm, user_has_org_perm
from core.models import Organization


def viewable_org_ids(user):
    """None = every customer, else a set of customer ids."""
    return orgs_with_perm(user, 'assets_view')


def can_view(user, org):
    allowed = viewable_org_ids(user)
    return allowed is None or org.pk in allowed


def can_manage(user, org):
    return user_has_org_perm(user, org, 'manage_licensing')


def can_see_cost(user, org):
    return user_has_org_perm(user, org, 'pricing_view_internal_cost_rates')


def viewable_orgs(user):
    qs = Organization.objects.filter(is_active=True).order_by('name')
    allowed = viewable_org_ids(user)
    return qs if allowed is None else qs.filter(pk__in=allowed)


def get_viewable_org(user, org_id):
    org = Organization.objects.filter(pk=org_id, is_active=True).first()
    if org is None or not can_view(user, org):
        raise Http404
    return org
