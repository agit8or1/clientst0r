"""
Data scope: which records a permission reaches, decided together with the
permission itself.

A *grant* is one source of a permission with its own boundary:

    Grant(label, org_ids, record_scope)

  org_ids       None = every organization (superusers; MSP staff whose
                client scope is 'all'), otherwise the set of organization
                ids the grant covers (a membership covers its organization
                and that organization's subsidiaries; an MSP staff member's
                global role covers their client scope).
  record_scope  'organization' every record there
                'assigned'     records assigned to the user
                'own'          records the user created / requested

`grants_for(user, perm)` lists the grants that HOLD `perm`. Each grant is
applied on its own: a row is visible when one single grant both holds the
permission and covers the row (organization AND record scope). Nothing
combines grant A's permission with grant B's organization or B's record
scope, so holding `billing_view_invoices` as a read-only "own records"
member of customer A and as a full member of customer B never shows
customer A's other invoices.

    scoped_queryset(qs, user, perm, org_field='organization',
                    owner_fields=('created_by',), assignee_fields=('assigned_to',))
    can_access_object(user, perm, obj, ...)

A model with no owner / assignee field passes empty tuples; an 'own' or
'assigned' grant then covers nothing on it (deny by default, never "all").

Scopes in the product:
  * assigned records only       Membership.record_scope / UserProfile.record_scope = 'assigned'
  * records created by the user  ... = 'own'
  * their own customer org       a customer membership (record_scope 'organization')
  * explicitly assigned clients  UserProfile.client_scope = 'assigned' (technician access assignments)
  * selected organizations       UserProfile.client_scope = 'selected' + scope_organizations
  * all clients of the provider  UserProfile.client_scope = 'all' (MSP staff default)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from django.db.models import Q

from .permission_registry import STAFF_ONLY_KEYS

ORGANIZATION, ASSIGNED, OWN = 'organization', 'assigned', 'own'


@dataclass(frozen=True)
class Grant:
    label: str
    org_ids: Optional[frozenset]
    record_scope: str = ORGANIZATION
    kind: str = 'membership'

    def covers_org(self, org_id) -> bool:
        return self.org_ids is None or org_id in self.org_ids


def grants_for(user, perm_name) -> List[Grant]:
    """Every grant through which `user` holds `perm_name`, each with its own scope."""
    from .permission_utils import (MEMBERSHIP_SCOPED_PREFIXES, _active, _membership_rows, _profile_staff,
                                   is_msp_staff, legacy_staff_holds, staff_client_org_ids)
    if not _active(user):
        return []
    if user.is_superuser:
        return [Grant('Superuser', None, ORGANIZATION, 'superuser')]
    profile = _profile_staff(user)
    if profile is not None:
        scope = staff_client_org_ids(user)
        org_ids = None if scope is None else frozenset(scope)
        role = profile.get_global_permissions()
        if role is not None:
            if getattr(role, perm_name, False):
                return [Grant(f'Global role {role.name}', org_ids, profile.record_scope or ORGANIZATION,
                              'global_role')]
            return []
        if not perm_name.startswith(MEMBERSHIP_SCOPED_PREFIXES):
            # Staff without a global role: their memberships act as one
            # (accounts.permission_utils.legacy_staff_holds).
            if legacy_staff_holds(user, perm_name) or not _membership_rows(user):
                return [Grant('MSP staff without a global role (memberships)', org_ids, ORGANIZATION,
                              'legacy_staff')]
            return []
    elif perm_name in STAFF_ONLY_KEYS and not is_msp_staff(user):
        return []
    from core.utils import descendant_org_ids
    out = []
    scope = staff_client_org_ids(user) if profile is not None else None
    for m in _membership_rows(user):
        if not getattr(m.get_permissions(), perm_name, False):
            continue
        ids = set(descendant_org_ids(m.organization_id))
        if scope is not None:
            ids &= set(scope)
        out.append(Grant(f'Membership in {m.organization.name}', frozenset(ids),
                         m.record_scope or ORGANIZATION, 'membership'))
    return out


def _record_q(grant: Grant, user, owner_fields: Iterable[str], assignee_fields: Iterable[str]) -> Optional[Q]:
    """Q for the grant's record scope, or None when it covers nothing here."""
    if grant.record_scope == ORGANIZATION:
        return Q()
    fields = list(owner_fields if grant.record_scope == OWN else assignee_fields)
    if not fields:
        return None
    q = Q()
    for f in fields:
        q |= Q(**{f: user})
    return q


def scope_q(user, perm_name, org_field='organization', owner_fields=('created_by',),
            assignee_fields=('assigned_to',)):
    """Q selecting the rows `user` may use `perm_name` on, or None for "all rows".

    Returns Q(pk__in=[]) when nothing is reachable."""
    q_total = None
    for g in grants_for(user, perm_name):
        rq = _record_q(g, user, owner_fields, assignee_fields)
        if rq is None:
            continue
        if g.org_ids is None and g.record_scope == ORGANIZATION:
            return None
        oq = Q() if g.org_ids is None else Q(**{f'{org_field}_id__in': list(g.org_ids)})
        part = oq & rq
        q_total = part if q_total is None else (q_total | part)
    return q_total if q_total is not None else Q(pk__in=[])


def scoped_queryset(qs, user, perm_name, org_field='organization', owner_fields=('created_by',),
                    assignee_fields=('assigned_to',)):
    """`qs` narrowed to rows one single grant of `perm_name` covers."""
    q = scope_q(user, perm_name, org_field, owner_fields, assignee_fields)
    return qs if q is None else qs.filter(q).distinct()


def can_access_object(user, perm_name, obj, org_attr='organization', owner_fields=('created_by',),
                      assignee_fields=('assigned_to',)) -> bool:
    """Object-level check: one grant holds `perm_name`, covers the object's
    organization AND its record scope."""
    org_id = getattr(obj, f'{org_attr}_id', None)
    for g in grants_for(user, perm_name):
        if org_id is None and g.org_ids is not None:
            continue
        if org_id is not None and not g.covers_org(org_id):
            continue
        if g.record_scope == ORGANIZATION:
            return True
        fields = owner_fields if g.record_scope == OWN else assignee_fields
        if any(getattr(obj, f'{f}_id', None) == user.pk for f in fields):
            return True
    return False


def reachable_org_ids(user, perm_name) -> Optional[Set[int]]:
    """Union of organizations of the grants holding `perm_name` (None = all).
    For counts and pickers only - row filtering must use scoped_queryset,
    which keeps each grant's record scope."""
    ids = set()
    for g in grants_for(user, perm_name):
        if g.org_ids is None:
            return None
        ids |= set(g.org_ids)
    return ids


# --- customer portal ------------------------------------------------------------

def portal_sees_org_tickets(membership) -> bool:
    """Whether a portal user sees every shared ticket of the customer or only
    their own (created or requested by them)."""
    if membership is None or not membership.is_active:
        return False
    if (membership.record_scope or ORGANIZATION) != ORGANIZATION:
        return False
    return bool(getattr(membership.get_permissions(), 'portal_tickets_view_org', False))


def portal_ticket_queryset(qs, membership, user):
    """Portal ticket rows for `membership`: client-visible tickets of the
    membership's customer only; all of them with portal_tickets_view_org,
    otherwise the user's own. Internal-only tickets never appear."""
    if membership is None:
        return qs.none()
    qs = qs.filter(organization_id=membership.organization_id, client_can_view=True)
    if portal_sees_org_tickets(membership):
        return qs
    own = Q(created_by=user)
    if getattr(user, 'email', ''):
        own |= Q(requester_email__iexact=user.email)
    return qs.filter(own)
