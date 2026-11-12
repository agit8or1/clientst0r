"""
Role permission checks, evaluated per organization.

Every check answers "may this user do <permission> at <organization>?". A
permission held in one organization's membership never answers for another
organization, and a permission held by one grant is never combined with the
organization or record scope of a different grant (accounts.scope).

Who holds what, at one organization:

  * Django superusers: everything (platform administration).
  * MSP staff (profile user type Staff): their *global* role template, at
    every client inside their client scope (UserProfile.client_scope; 'all'
    unless an administrator narrowed it). Memberships do not add to a global
    role. Staff without a global role: a permission any of their memberships
    grants holds at every client in scope, except vault permissions, which
    stay per membership (legacy_staff_holds; each such account is listed for
    review by accounts 0046). user_has_org_perm, user_has_perm and
    orgs_with_perm all follow this one rule.
  * Everyone else (customer users): the membership at that organization, or
    at a parent organization (a parent's members see its subsidiaries). A
    membership's additional roles add to its primary role.
  * Staff-only permissions (permission_registry.STAFF_ONLY_KEYS: internal
    notes, CRM, financial reports, AI...) are never effective for a customer
    user, whatever their role says.

Helpers:

  user_has_org_perm(user, org, perm)   the per-organization check. Use it
                                       whenever there is a record or a
                                       selected organization.
  user_has_perm(user, perm)            capability check for a page or action
                                       with no record yet. Inside a request
                                       a customer user is checked at the
                                       organization they have selected (never
                                       "any of their memberships"); MSP staff
                                       by their global role.
  user_has_perm_any_org(user, perm)    the old "any active membership"
                                       answer. Only for surfaces that are
                                       themselves cross-organization and
                                       gated elsewhere (e.g. a staff-only
                                       report that is then filtered with
                                       filter_by_org_perm).
  orgs_with_perm / filter_by_org_perm  which organizations a permission
                                       reaches, for querysets.
  explain_access(user, org, perm)      why (or why not), for the UI.

Results are memoized for the length of one request only and the memo is
dropped whenever a role, membership, profile, scope or account changes
(accounts.authz_cache), so a revocation applies to the next check.
"""
from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied

from . import authz_cache
from .permission_registry import STAFF_ONLY_KEYS


class CombinedPermissions:
    """Primary role + additional roles of ONE membership, added together."""

    def __init__(self, primary, extras):
        self._primary = primary
        self._roles = [primary] + list(extras)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        values = [getattr(r, name, None) for r in self._roles]
        if all(isinstance(v, bool) or v is None for v in values):
            return any(bool(v) for v in values)
        return getattr(self._primary, name)

    @property
    def roles(self):
        return list(self._roles)


# --- identity -----------------------------------------------------------------

def _active(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False)
                and getattr(user, 'is_active', False))


def is_msp_staff(user):
    from psa.visibility import is_msp_staff as _staff
    return _staff(user)


def _profile_staff(user):
    profile = getattr(user, 'profile', None)
    if profile is not None and getattr(profile, 'is_staff_user', lambda: False)():
        return profile
    return None


def staff_client_org_ids(user):
    """Clients an MSP staff member's global role reaches: None (all) or a set.

    'assigned' = customers where they hold a live technician access
    assignment (directly or through a technician group); 'selected' = the
    profile's scope organizations and their subsidiaries. Superusers and
    non-staff: None (customers are bounded by memberships elsewhere)."""
    if user is None or getattr(user, 'is_superuser', False):
        return None
    profile = _profile_staff(user)
    if profile is None:
        return None
    scope = getattr(profile, 'client_scope', 'all') or 'all'
    if scope == 'all':
        return None

    def compute():
        from core.utils import descendant_org_ids
        ids = set()
        if scope == 'selected':
            for org_id in profile.scope_organizations.filter(is_active=True).values_list('pk', flat=True):
                ids |= descendant_org_ids(org_id)
        elif scope == 'assigned':
            from django.db.models import Q
            from tech_access.models import AccessAssignment
            ids = set(AccessAssignment.objects.live()
                      .filter(Q(user=user) | Q(group__members=user))
                      .values_list('organization_id', flat=True))
        return ids
    return authz_cache.memo(('client_scope', user.pk), compute)


def _membership_rows(user):
    def compute():
        return list(user.memberships.filter(is_active=True, organization__is_active=True)
                    .select_related('role_template', 'organization').prefetch_related('additional_roles'))
    return authz_cache.memo(('memberships', user.pk), compute)


def memberships_covering(user, organization):
    """Active memberships that apply at `organization`: its own, or a parent's."""
    org_id = getattr(organization, 'pk', organization)
    if org_id is None:
        return []
    from core.utils import descendant_org_ids
    out = []
    for m in _membership_rows(user):
        reach = authz_cache.memo(('descendants', m.organization_id),
                                 lambda m=m: descendant_org_ids(m.organization_id))
        if org_id in reach:
            out.append(m)
    return out


def legacy_staff_holds(user, perm_name) -> bool:
    """MSP staff WITHOUT a global role: their memberships together act as the
    global role - a permission any of their active memberships grants holds
    at every client inside their client scope. Vault permissions
    (MEMBERSHIP_SCOPED_PREFIXES) are the exception and stay per membership.
    Each such account is on the roles review list (accounts 0046): give it a
    global role.

    A staff account with neither a global role nor any membership keeps the
    historical data reach of orgs_with_perm (every client outside the vault)
    for lists and records, but holds no capability in user_has_org_perm /
    user_has_perm until it gets a global role or a membership."""
    return any(getattr(m.get_permissions(), perm_name, False) for m in _membership_rows(user))


# --- the checks -------------------------------------------------------------------

def user_has_org_perm(user, organization, perm_name) -> bool:
    """May `user` use `perm_name` at `organization` (an Organization or pk)?"""
    if not _active(user):
        return False
    if user.is_superuser:
        return True
    org_id = getattr(organization, 'pk', organization)

    def compute():
        profile = _profile_staff(user)
        if profile is not None:
            if org_id is not None:
                scope = staff_client_org_ids(user)
                if scope is not None and org_id not in scope:
                    return False
            global_permissions = profile.get_global_permissions()
            if global_permissions is not None:
                return bool(getattr(global_permissions, perm_name, False))
            if not perm_name.startswith(MEMBERSHIP_SCOPED_PREFIXES):
                return legacy_staff_holds(user, perm_name)
        elif perm_name in STAFF_ONLY_KEYS and not is_msp_staff(user):
            return False
        if org_id is None:
            return False
        return any(getattr(m.get_permissions(), perm_name, False)
                   for m in memberships_covering(user, org_id))
    return authz_cache.memo(('org_perm', user.pk, org_id, perm_name), compute)


def user_has_perm_any_org(user, perm_name) -> bool:
    """True if `user` holds `perm_name` on ANY active membership (or their
    global role, or is a superuser).

    Deliberately cross-organization: it says nothing about any particular
    organization. Use it only to decide whether a cross-organization surface
    is shown at all, and then narrow the rows with `filter_by_org_perm`.
    """
    if not _active(user):
        return False
    if user.is_superuser:
        return True
    profile = _profile_staff(user)
    if profile is not None:
        global_permissions = profile.get_global_permissions()
        if global_permissions is not None and getattr(global_permissions, perm_name, False):
            return True
        # A membership still adds to the global role here (psa
        # test_staff_tech_access: the global role never removes a membership
        # grant). Surfaces that aggregate every customer must not rely on
        # this answer: use orgs_with_perm / filter_by_org_perm (global role
        # authoritative for reach) or reports.access.has_msp_wide_perm.
    elif perm_name in STAFF_ONLY_KEYS and not is_msp_staff(user):
        return False
    scope = staff_client_org_ids(user) if profile is not None else None
    for m in _membership_rows(user):
        if scope is not None and m.organization_id not in scope:
            continue
        if getattr(m.get_permissions(), perm_name, False):
            return True
    return False


def user_has_perm(user, perm_name) -> bool:
    """Capability check with no particular record.

    MSP staff: their global role plus any of their memberships, as before.
    Customer users inside a request with an organization selected: that
    organization - a permission from one customer's membership no longer opens
    a page while another customer is selected. Outside a request (jobs,
    shell) customer users fall back to `user_has_perm_any_org`.
    """
    if not _active(user):
        return False
    if user.is_superuser:
        return True
    if is_msp_staff(user):
        return user_has_perm_any_org(user, perm_name)
    ctx = authz_cache.current_context()
    if ctx is not None and ctx.organization_id is not None:
        return user_has_org_perm(user, ctx.organization_id, perm_name)
    # No organization selected (API token requests authenticate after the
    # middleware; jobs; shell): the cross-organization answer.
    return user_has_perm_any_org(user, perm_name)


def require_perm(perm_name):
    """Decorator: raises PermissionDenied if user lacks the permission."""
    def decorator(view_fn):
        @wraps(view_fn)
        def _wrapped(request, *args, **kwargs):
            if not user_has_perm(request.user, perm_name):
                from .role_audit import record_denied
                record_denied(request, perm_name)
                raise PermissionDenied(
                    f"You don't have the '{perm_name}' permission."
                )
            return view_fn(request, *args, **kwargs)
        return _wrapped
    return decorator


def require_perm_any_org(perm_name):
    """Decorator: the user holds `perm_name` in at least one organization
    (user_has_perm_any_org). Only for views that then check EVERY record
    against its own organization (orgs_with_perm / has_perm_for_org) and
    offer only those organizations - e.g. a list of several customers'
    holidays. Never the only check on a record."""
    def decorator(view_fn):
        @wraps(view_fn)
        def _wrapped(request, *args, **kwargs):
            if not user_has_perm_any_org(request.user, perm_name):
                from .role_audit import record_denied
                record_denied(request, perm_name)
                raise PermissionDenied(f"You don't have the '{perm_name}' permission.")
            return view_fn(request, *args, **kwargs)
        return _wrapped
    return decorator


def require_org_perm(perm_name, org_kwarg='org_id', org_getter=None):
    """Decorator: the permission at the organization named by the URL
    (`org_kwarg`), or returned by `org_getter(request, *args, **kwargs)`
    (e.g. the organization of the record in the URL), else at the selected
    organization. Use this instead of require_perm on any view that acts on
    one organization's data."""
    def decorator(view_fn):
        @wraps(view_fn)
        def _wrapped(request, *args, **kwargs):
            org = org_getter(request, *args, **kwargs) if org_getter is not None else kwargs.get(org_kwarg)
            if org is None:
                org = getattr(request, 'current_organization', None)
            if not user_has_org_perm(request.user, org, perm_name):
                from .role_audit import record_denied
                record_denied(request, perm_name, organization=org)
                raise PermissionDenied(f"You don't have the '{perm_name}' permission here.")
            return view_fn(request, *args, **kwargs)
        return _wrapped
    return decorator


# Flags that staff without a global role hold only through memberships.
MEMBERSHIP_SCOPED_PREFIXES = ('vault_',)


def orgs_with_perm(user, perm_name):
    """Customers in which `user` holds `perm_name`.

    Returns None for "every customer" (superusers, and MSP staff whose global
    role grants it - or, outside the vault, who have no global role and hold
    it on any membership: accounts.permission_utils.legacy_staff_holds),
    otherwise a set of organization ids. A membership
    in a parent customer covers its subsidiaries, matching `user_has_org_perm`.
    An MSP staff member's client scope bounds all of this.

    Vault flags (`vault_*`) are the exception since v3.17.653: staff without a
    global role reach only the customers their memberships grant, the same
    rule `user_has_org_perm` already applied to reveals.
    """
    if not _active(user):
        return set()
    if user.is_superuser:
        return None

    def compute():
        profile = _profile_staff(user)
        if profile is not None:
            scope = staff_client_org_ids(user)
            global_permissions = profile.get_global_permissions()
            if global_permissions is not None:
                if not getattr(global_permissions, perm_name, False):
                    return set()
                return None if scope is None else set(scope)
            if not perm_name.startswith(MEMBERSHIP_SCOPED_PREFIXES):
                if _membership_rows(user) and not legacy_staff_holds(user, perm_name):
                    return set()
                return None if scope is None else set(scope)
        elif perm_name in STAFF_ONLY_KEYS and not is_msp_staff(user):
            return set()
        else:
            scope = None
        from core.utils import descendant_org_ids
        allowed = set()
        for membership in _membership_rows(user):
            if getattr(membership.get_permissions(), perm_name, False):
                allowed |= descendant_org_ids(membership.organization_id)
        if scope is not None:
            allowed &= scope
        return allowed
    result = authz_cache.memo(('orgs_with', user.pk, perm_name), compute)
    return None if result is None else set(result)


def filter_by_org_perm(qs, user, perm_name, field='organization'):
    """Narrow `qs` to rows whose customer (`field`) the user holds `perm_name` in."""
    allowed = orgs_with_perm(user, perm_name)
    if allowed is None:
        return qs
    return qs.filter(**{f'{field}_id__in': allowed})


def has_perm_for_org(user, organization, perm_name):
    """`orgs_with_perm` for a single customer. `organization=None` is global
    view, which only users with every-customer reach hold."""
    allowed = orgs_with_perm(user, perm_name)
    if allowed is None:
        return True
    org_id = getattr(organization, 'pk', organization)
    return org_id is not None and org_id in allowed


def effective_permissions(user, organization):
    """{perm_key: bool} for every registry permission at `organization`."""
    from .permission_registry import ALL_KEYS
    return {k: user_has_org_perm(user, organization, k) for k in ALL_KEYS}


def explain_access(user, organization, perm_name):
    """Why `user` does (not) hold `perm_name` at `organization`.

    Returns {'allowed': bool, 'sources': [{'label', 'grants', 'scope',
    'note'}...], 'notes': [...]} built from the same rules as
    user_has_org_perm (the verdict is user_has_org_perm's)."""
    from .permission_registry import get as reg_get
    org_id = getattr(organization, 'pk', organization)
    allowed = user_has_org_perm(user, org_id, perm_name)
    sources, notes = [], []
    perm = reg_get(perm_name)
    if perm is None:
        notes.append(f"'{perm_name}' is not a registered permission.")
    if user is None or not getattr(user, 'is_active', False):
        notes.append('The account is inactive: it holds nothing.')
        return {'allowed': False, 'sources': sources, 'notes': notes}
    if user.is_superuser:
        sources.append({'label': 'Django superuser (platform administration)', 'grants': True,
                        'scope': 'Every organization', 'note': ''})
        return {'allowed': True, 'sources': sources, 'notes': notes}
    profile = _profile_staff(user)
    if profile is not None:
        scope = staff_client_org_ids(user)
        scope_label = profile.get_client_scope_display()
        in_scope = scope is None or org_id in scope
        if not in_scope:
            notes.append(f'This organization is outside the client scope ({scope_label}).')
        gr = profile.get_global_permissions()
        if gr is not None:
            sources.append({'label': f'Global role: {gr.name}', 'grants': bool(getattr(gr, perm_name, False))
                            and in_scope, 'scope': f'{scope_label}; records: {profile.get_record_scope_display()}',
                            'note': 'MSP staff: the global role decides; memberships do not add to it.'})
            return {'allowed': allowed, 'sources': sources, 'notes': notes}
        notes.append('MSP staff without a global role: a permission any of their memberships grants applies at '
                     'every client in scope; vault permissions stay per membership (listed for review).')
    elif perm is not None and perm.staff_only and not is_msp_staff(user):
        notes.append('Staff-only permission: never effective for a customer user.')
    for m in memberships_covering(user, org_id):
        perms = m.get_permissions()
        roles = getattr(perms, 'roles', None) or [perms]
        for r in roles:
            name = getattr(r, 'name', None) or f'simple role {m.get_role_display()}'
            via = '' if m.organization_id == org_id else f' (membership in parent {m.organization.name})'
            sources.append({'label': f'{name}{via}', 'grants': bool(getattr(r, perm_name, False)),
                            'scope': m.get_record_scope_display(), 'note': ''})
    if not sources:
        notes.append('No membership applies at this organization.')
    return {'allowed': allowed, 'sources': sources, 'notes': notes}
