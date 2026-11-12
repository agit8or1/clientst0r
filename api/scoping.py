"""
Multi-organization scoping for the public REST API (issue #134).

The original REST API was single-tenant *per request*: an API key was bound
to exactly one organization and every endpoint filtered to that one org. MSPs
building a single-pane-of-glass need one connection that can read/write across
many client organizations.

This module centralises three questions:

  * `accessible_org_ids(request)` — which organizations may this request's
    principal reach *at all*? Bounded by the API key's `scope` and, ultimately,
    by what the underlying user can already access. Never widens user access.

  * `resolve_scope_org_ids(request)` — given an optional `?organization=`
    query parameter, which org(s) should THIS request be filtered to?
      - `?organization=all`     → every accessible org
      - `?organization=<id|slug>` → that one org (403 if not accessible)
      - omitted                  → the primary org for SINGLE keys / web
        sessions (backward-compatible), or every accessible org for a
        multi-org key (ergonomic single-pane default).

  * `resolve_create_org(request, serializer)` — which org a newly-created row
    belongs to: explicit `?organization=` param > request body `organization`
    > primary org. Always validated against the accessible set.

Mirrors the established `api_mobile/scoping.py` pattern.
"""
from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from core.middleware import get_request_organization
from core.models import Organization
from core.utils import descendant_org_ids
from .models import APIKey, APIKeyScope


def _is_staff_user(user) -> bool:
    """True for MSP staff techs / superusers (full multi-org reach)."""
    if getattr(user, 'is_superuser', False):
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile is not None and profile.is_staff_user())


def _user_reach_ids(user) -> list:
    """Every org id `user` can reach as a person (not via any key scope)."""
    if not user or not user.is_authenticated:
        return []
    if _is_staff_user(user):
        return list(
            Organization.objects.filter(is_active=True).values_list('id', flat=True)
        )
    try:
        return list(
            user.memberships.filter(is_active=True)
            .values_list('organization_id', flat=True)
        )
    except Exception:
        return []


def accessible_org_ids(request) -> list:
    """
    The set of organization ids this request's principal may address.

    For API-key auth the set is gated by the key's `scope`; for session auth
    it is the user's full personal reach. The result is always a subset of
    what the user could already access in the web app.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return []

    api_key = getattr(request, 'api_key', None)
    if api_key is not None:
        if api_key.scope == APIKeyScope.SINGLE:
            return [api_key.organization_id]
        if api_key.scope == APIKeyScope.DESCENDANTS:
            # Deactivated sub-customers drop out, as they do for ALL keys.
            return list(Organization.objects.filter(
                id__in=descendant_org_ids(api_key.organization), is_active=True,
            ).values_list('id', flat=True))
        # APIKeyScope.ALL falls through to the owner's full reach.

    return _user_reach_ids(user)


def _lookup_org(param):
    """Resolve an `?organization=` value (numeric id or slug) to an Org."""
    if param is None:
        return None
    try:
        if str(param).isdigit():
            return Organization.objects.filter(id=int(param)).first()
        return Organization.objects.filter(slug=param).first()
    except Exception:
        return None


def resolve_scope_org_ids(request) -> list:
    """
    The org ids THIS request should be filtered to, honoring `?organization=`.

    Raises PermissionDenied (403) if the caller asks for an organization
    outside their accessible set.
    """
    accessible = accessible_org_ids(request)
    accessible_set = set(accessible)

    param = None
    if hasattr(request, 'query_params'):
        param = request.query_params.get('organization')

    if param:
        if param == 'all':
            return accessible
        org = _lookup_org(param)
        if org is None or org.id not in accessible_set:
            raise PermissionDenied(
                f"This API key does not have access to organization '{param}'."
            )
        return [org.id]

    # No explicit param: multi-org keys default to their whole accessible set
    # (single-pane ergonomics); SINGLE keys and web sessions stay pinned to
    # the primary org for full backward compatibility.
    api_key = getattr(request, 'api_key', None)
    if api_key is not None and api_key.scope != APIKeyScope.SINGLE:
        return accessible

    primary = get_request_organization(request)
    if primary is not None:
        return [primary.id] if primary.id in accessible_set else []
    return accessible


def resolve_create_org(request, serializer):
    """
    Resolve + validate the target Organization for a create.

    Precedence: explicit `?organization=` param > request body `organization`
    > the request's primary org. The resolved org must be in the accessible
    set, otherwise PermissionDenied (403).
    """
    accessible_set = set(accessible_org_ids(request))
    candidate_id = None

    param = None
    if hasattr(request, 'query_params'):
        param = request.query_params.get('organization')
    if param and param != 'all':
        org = _lookup_org(param)
        candidate_id = org.id if org else None

    if candidate_id is None:
        body_org = serializer.validated_data.get('organization')
        if body_org is not None:
            candidate_id = body_org.id

    if candidate_id is None:
        primary = get_request_organization(request)
        candidate_id = primary.id if primary is not None else None

    if candidate_id is None or candidate_id not in accessible_set:
        raise PermissionDenied(
            "You do not have access to the target organization for this object."
        )
    return Organization.objects.get(id=candidate_id)
