"""
Permission utilities for cross-org RoleTemplate boolean checks.

Introduced in v3.17.145 alongside the Reports + financials permission groups.
Mirrors the v3.17.134 KB pattern (`psa.views._check_kb_perm`) but is now
the canonical entry-point for any view that gates on a RoleTemplate flag
spanning multiple memberships.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied


def user_has_perm(user, perm_name) -> bool:
    """
    Cross-org permission check — returns True if `user` has the named
    RoleTemplate boolean True on ANY active membership, OR is a Django
    superuser. Mirrors `_check_kb_perm` from psa/views.py.

    Use this in any view gating on a report / financial surface.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from accounts.models import Membership
    qs = Membership.objects.filter(
        user=user, is_active=True
    ).select_related('role_template')
    for m in qs:
        perms = m.get_permissions()
        if getattr(perms, perm_name, False):
            return True
    return False


def require_perm(perm_name):
    """Decorator: raises PermissionDenied if user lacks the permission."""
    def decorator(view_fn):
        @wraps(view_fn)
        def _wrapped(request, *args, **kwargs):
            if not user_has_perm(request.user, perm_name):
                raise PermissionDenied(
                    f"You don't have the '{perm_name}' permission."
                )
            return view_fn(request, *args, **kwargs)
        return _wrapped
    return decorator


def user_has_org_perm(user, organization, perm_name) -> bool:
    """Check a capability on the target organization, never an unrelated one.

    Parent memberships cover descendants, matching core.tenancy. MSP staff use
    their global role template; staff status alone is not a vault capability.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    if profile is not None and getattr(profile, 'is_staff_user', lambda: False)():
        global_permissions = profile.get_global_permissions()
        if global_permissions is not None:
            return bool(getattr(global_permissions, perm_name, False))
    org_id = getattr(organization, 'pk', organization)
    if org_id is None:
        return False
    from core.utils import descendant_org_ids
    for membership in user.memberships.filter(
            is_active=True, organization__is_active=True).select_related('role_template'):
        if org_id in descendant_org_ids(membership.organization_id):
            if getattr(membership.get_permissions(), perm_name, False):
                return True
    return False
