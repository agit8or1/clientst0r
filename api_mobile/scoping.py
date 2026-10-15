"""
Shared helpers for org-scoped queries on the mobile API.

`accessible_org_ids(user)` returns the set of organization IDs the user
has an active Membership for. All list endpoints filter by this set so
a user from Org A cannot list / read rows from Org B even by guessing
the primary key.
"""
from __future__ import annotations

from django.contrib.auth.models import User


def accessible_org_ids(user: User):
    """Return the queryset of org IDs the user has active memberships in."""
    if not user or not user.is_authenticated:
        return []
    try:
        return list(
            user.memberships.filter(is_active=True).values_list('organization_id', flat=True)
        )
    except Exception:
        return []


def in_user_orgs(user: User, qs, field='organization_id'):
    """Filter `qs` to rows whose `field` is in the user's accessible orgs."""
    return qs.filter(**{f'{field}__in': accessible_org_ids(user)})


def perm_org_ids(user: User, perm: str):
    """Accessible org IDs narrowed to customers where the user holds `perm`.

    Role flags such as `vault_view` / `docs_view` / `assets_view` are
    per-customer: membership alone no longer implies the user may read a
    customer's passwords, documents or assets. `orgs_with_perm` returns None
    for every-customer reach (superusers, MSP staff whose global role grants
    it), in which case the membership scoping above is the only limit.
    """
    from accounts.permission_utils import orgs_with_perm
    base = accessible_org_ids(user)
    allowed = orgs_with_perm(user, perm)
    if allowed is None:
        return list(base)
    return [oid for oid in base if oid in allowed]


def has_any_perm(user: User, perm: str) -> bool:
    """True if `user` holds `perm` in at least one customer (or everywhere)."""
    from accounts.permission_utils import orgs_with_perm
    allowed = orgs_with_perm(user, perm)
    return allowed is None or bool(allowed)
