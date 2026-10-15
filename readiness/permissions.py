"""Who may see / manage readiness.

* Managing standards, exceptions, the repair queue and the broken-relationship
  report: MSP staff only (superuser, Django is_staff, or a Staff profile).
* Viewing a customer's readiness: anyone holding docs_view in that customer
  (`accounts.permission_utils.orgs_with_perm`). Customer users see it
  read-only.
"""
from django.core.exceptions import PermissionDenied

from accounts.permission_utils import orgs_with_perm


def is_msp_staff(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, 'profile', None)
    check = getattr(profile, 'is_staff_user', None)
    return bool(check()) if callable(check) else False


def readable_org_ids(user):
    """None = every customer, else the set of customer ids whose readiness
    `user` may view."""
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    profile = getattr(user, 'profile', None)
    staff_profile = bool(profile is not None and profile.is_staff_user())
    # Django is_staff without a Staff profile has no global role to consult:
    # treat as every customer, as MSP staff.
    if user.is_staff and not user.is_superuser and not staff_profile:
        return None
    return orgs_with_perm(user, 'docs_view')


def can_view_org(user, org):
    allowed = readable_org_ids(user)
    return allowed is None or org.pk in allowed


def require_staff(user):
    if not is_msp_staff(user):
        raise PermissionDenied('MSP staff only.')


_KIND_PERMS = {
    'document': 'docs_view',
    'asset': 'assets_view',
    'contact': 'assets_view',
    'credential': 'vault_view',
}


class LinkPerms:
    """Which record kinds a viewer may see named / linked, per customer.
    Computed once per request (three permission lookups), then per-org
    checks are set lookups."""

    def __init__(self, user):
        profile = getattr(user, 'profile', None)
        staff_profile = bool(profile is not None and profile.is_staff_user())
        everything = user.is_staff and not user.is_superuser and not staff_profile
        self._allowed = {
            perm: (None if everything else orgs_with_perm(user, perm))
            for perm in set(_KIND_PERMS.values())
        }

    def kinds_for(self, org):
        org_id = getattr(org, 'pk', org)
        out = set()
        for kind, perm in _KIND_PERMS.items():
            allowed = self._allowed[perm]
            if allowed is None or org_id in allowed:
                out.add(kind)
        return out


def link_perms(user, org):
    return LinkPerms(user).kinds_for(org)
