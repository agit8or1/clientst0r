"""Request-scoped tenancy helpers.

`accounts.permission_utils.user_has_perm` answers a *capability* question —
"does this user hold the flag on any active membership" — which is the right
question for "may they manage holidays at all" and the wrong one for "may they
manage *this* holiday". A view that gates on a capability and then looks a
record up by primary key alone is reachable across tenants by anyone holding
that capability anywhere.

These helpers supply the missing half. They sit on top of the existing
`core.utils.OrganizationManager` / `descendant_org_ids` rather than beside
them, so parent/child organization behaviour stays consistent with the rest of
the application.
"""
from __future__ import annotations

from django.db import models
from django.shortcuts import get_object_or_404

from core.utils import descendant_org_ids


def is_cross_tenant_user(request) -> bool:
    """True for principals entitled to see every tenant.

    Mirrors the rule already used by `psa.views._scoped_ticket_qs`: Django
    superusers and staff users operate across clients; everybody else is
    bounded by membership.
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return False
    return bool(user.is_superuser or getattr(request, 'is_staff_user', False))


def accessible_org_ids(request) -> set[int] | None:
    """Organization ids this request may touch, or None for "all of them".

    None is deliberately distinct from an empty set: None means unrestricted,
    an empty set means "this user is a member of nothing" and must match no
    rows at all.
    """
    if is_cross_tenant_user(request):
        return None

    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or not hasattr(user, 'memberships'):
        return set()

    ids: set[int] = set()
    for org_id in user.memberships.filter(is_active=True).values_list(
            'organization_id', flat=True):
        # Membership of a parent implies access to its descendants, matching
        # core.utils.OrganizationQuerySet.for_organization.
        ids.update(descendant_org_ids(org_id))
    return ids


def scope_to_request(queryset, request, field: str = 'organization', *,
                     include_global: bool = False):
    """Narrow `queryset` to the organizations this request may touch.

    Some tenant-scoped models treat a NULL organization as "applies to every
    tenant" — `resourcing.Holiday` does this for national holidays. Those rows
    are readable by everyone, so read paths pass `include_global=True`.

    Write paths deliberately do not: editing a shared row changes it for every
    tenant, which is an administrator's decision rather than a member's. A
    non-cross-tenant user gets a 404 on those, exactly as they would for
    another tenant's row.
    """
    allowed = accessible_org_ids(request)
    if allowed is None:
        return queryset
    predicate = models.Q(**{f'{field}_id__in': allowed})
    if include_global:
        predicate |= models.Q(**{f'{field}__isnull': True})
    return queryset.filter(predicate)


def get_scoped_object_or_404(model_or_qs, request, *, field: str = 'organization',
                             include_global: bool = False, **lookup):
    """`get_object_or_404`, bounded to the caller's organizations.

    Raises Http404 rather than PermissionDenied on purpose: a 404 does not
    confirm that the record exists in some other tenant.
    """
    qs = model_or_qs if hasattr(model_or_qs, 'filter') else model_or_qs._default_manager.all()
    return get_object_or_404(
        scope_to_request(qs, request, field=field, include_global=include_global),
        **lookup,
    )
