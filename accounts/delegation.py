"""
Delegation and privilege-escalation protection for every role, membership,
invitation, bulk, API, import and directory-mapping path.

The rules (all server-side; hiding a button is never the check):

  1. Superusers may assign anything (platform administration), still audited.
  2. Nobody changes their own role, scope or membership status (no
     self-promotion, and no self-demotion that strands an organization).
  3. Managing ordinary members needs `org_manage_members` AT THAT
     organization. Assigning or removing a *privileged* role (one holding a
     critical permission: user / role / settings / security / platform
     administration, an RMM tier, or ownership) needs `org_manage_privileged`
     there as well.
  4. Subset rule: a role can only be handed out by someone who holds every
     permission in it at that organization. Nobody grants what they do not
     have; this also bounds additional roles and record scopes.
  5. Ownership (`org_owner`) is never assigned through member / role forms:
     only through the ownership transfer workflow (accounts.ownership).
  6. Customer-side administrators (non-staff) may assign only role
     templates made of customer-assignable permissions (and the legacy simple
     Admin / Editor / Read-only roles, within the subset rule), never to MSP
     staff or superusers, and never platform roles (RMM tiers). Staff-only
     permissions never take effect for customer users and are not counted.
  7. Organization settings never confer platform access: is_superuser,
     Django staff, user type and global roles are changed only by
     superusers (accounts.views.user_* and tech_access protected changes).
  8. A target whose current access exceeds the actor's (e.g. an owner) can
     not be edited, suspended or removed by that actor.
  9. The last active owner of an organization can not be removed,
     suspended, demoted or deactivated; transfer ownership first.

Every refusal is audited (role_audit 'delegation.denied').
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .permission_registry import (CUSTOMER_ASSIGNABLE_KEYS, PRIVILEGED_KEYS, STAFF_ONLY_KEYS, TRANSFER_ONLY_KEYS,
                                  ALL_KEYS, granted_keys, is_privileged_role)
from .permission_utils import effective_permissions, is_msp_staff, user_has_org_perm


class DelegationError(Exception):
    pass


@dataclass
class Verdict:
    allowed: bool
    reason: str = ''

    def __bool__(self):
        return self.allowed


OK = Verdict(True)


def _deny(reason):
    return Verdict(False, reason)


def _org_id(org):
    return getattr(org, 'pk', org)


def is_customer_actor(user) -> bool:
    return not (user.is_superuser or is_msp_staff(user))


def role_keys(role) -> frozenset:
    """Permissions a role grants: a RoleTemplate, or a simple role string."""
    if role is None:
        return frozenset()
    if isinstance(role, str):
        from .models import Membership
        return granted_keys(Membership(role=role)._primary_permissions())
    return granted_keys(role)


def membership_keys(membership) -> frozenset:
    if membership is None:
        return frozenset()
    return granted_keys(membership.get_permissions())


def actor_keys(actor, organization) -> frozenset:
    eff = effective_permissions(actor, organization)
    return frozenset(k for k, v in eff.items() if v)


def _privileged_keys(keys) -> bool:
    return bool(set(keys) & PRIVILEGED_KEYS)


def count_active_owners(organization, exclude_membership=None) -> int:
    from .models import Membership
    from django.db.models import Q
    qs = Membership.objects.filter(organization=organization, is_active=True, user__is_active=True).filter(
        Q(role_template__isnull=True, role='owner') | Q(role_template__org_owner=True))
    if exclude_membership is not None:
        qs = qs.exclude(pk=exclude_membership.pk)
    return qs.count()


def would_strand_owner(membership, *, new_role=None, new_template=None,
                       deactivate=False, template_given=False) -> bool:
    """True if the change leaves the organization without an active owner."""
    if membership is None or not membership.is_owner():
        return False
    if not deactivate:
        role = new_role if new_role is not None else membership.role
        template = new_template if template_given else membership.role_template
        still_owner = bool(template.org_owner) if template is not None else role == 'owner'
        if still_owner:
            return False
    return count_active_owners(membership.organization, exclude_membership=membership) == 0


def can_manage_member(actor, organization, target_membership=None, *, privileged=False) -> Verdict:
    """May `actor` change (edit / suspend / remove) members at `organization`?"""
    if actor is None or not actor.is_authenticated or not actor.is_active:
        return _deny('Not signed in.')
    if actor.is_superuser:
        return OK
    if target_membership is not None and target_membership.user_id == actor.pk:
        return _deny('You cannot change your own membership.')
    if not user_has_org_perm(actor, organization, 'org_manage_members'):
        return _deny("Your role does not include managing members here ('org_manage_members').")
    if target_membership is not None:
        target_user = target_membership.user
        if target_user.is_superuser and not actor.is_superuser:
            return _deny('Only a superuser can change a superuser.')
        if is_customer_actor(actor) and (is_msp_staff(target_user)):
            return _deny('Customer administrators cannot change MSP staff memberships.')
        current = membership_keys(target_membership)
        if not is_msp_staff(target_user):
            current = current - STAFF_ONLY_KEYS   # never effective for a customer user
        mine = actor_keys(actor, organization)
        if _privileged_keys(current) or target_membership.is_owner():
            privileged = True
        missing = current - mine
        if missing:
            return _deny('This member holds permissions you do not have ('
                         + ', '.join(sorted(missing)[:6]) + ('...' if len(missing) > 6 else '') + ').')
    if privileged and not user_has_org_perm(actor, organization, 'org_manage_privileged'):
        return _deny("Changing a privileged member needs 'org_manage_privileged'.")
    return OK


def can_assign_role(actor, organization, role, *, simple_role=None, target_user=None, target_membership=None,
                    additional_roles=()) -> Verdict:
    """May `actor` give a member of `organization` the role `role`?

    `role` is a RoleTemplate, or None for "no template" - the member then
    holds the simple role (`simple_role`, default the membership's current
    one). `additional_roles` are extra templates in the same membership.
    The check covers everything the member would hold afterwards."""
    if actor is None or not actor.is_authenticated or not actor.is_active:
        return _deny('Not signed in.')
    org_id = _org_id(organization)
    if isinstance(role, str):
        simple_role, role = role, None
    if target_membership is not None and target_user is None:
        target_user = target_membership.user
    roles = [r for r in [role, *additional_roles] if r is not None]
    for r in roles:
        if hasattr(r, 'organization_id') and r.organization_id not in (None, org_id):
            return _deny(f"'{r.name}' belongs to another organization.")
        if getattr(r, 'is_archived', False):
            return _deny(f"'{r.name}' is archived and can not be assigned.")
    if actor.is_superuser:
        return OK
    if target_user is not None and target_user.pk == actor.pk:
        return _deny('You cannot change your own role.')
    if target_user is not None and target_user.is_superuser:
        return _deny('Only a superuser can change a superuser.')
    if target_membership is None:
        # A new member (invitation / add): inviting is enough.
        if not (user_has_org_perm(actor, org_id, 'org_manage_members')
                or user_has_org_perm(actor, org_id, 'org_invite_members')):
            return _deny("Your role does not include adding members here ('org_invite_members').")
    elif not user_has_org_perm(actor, org_id, 'org_manage_members'):
        return _deny("Your role does not include managing members here ('org_manage_members').")

    granted = frozenset().union(*[role_keys(r) for r in roles]) if roles else frozenset()
    if role is None:
        simple = simple_role or (target_membership.role if target_membership is not None else 'readonly')
        granted |= role_keys(simple)
    already_owner = target_membership is not None and target_membership.is_owner()
    if granted & TRANSFER_ONLY_KEYS and not already_owner:
        return _deny('Ownership is given only through Transfer ownership.')
    for r in roles:
        if getattr(r, 'rmm_tier', ''):
            return _deny(f"'{r.name}' carries an RMM tier; tiers are platform roles given only to MSP staff "
                         'by a superuser (global role).')
    customer_actor = is_customer_actor(actor)
    if customer_actor:
        if target_user is not None and is_msp_staff(target_user):
            return _deny('Customer administrators cannot assign roles to MSP staff.')
        # The member will be a customer user: staff-only permissions never
        # take effect for them, so they are neither checked nor counted.
        granted = granted - STAFF_ONLY_KEYS
        # Legacy simple roles (Admin / Editor / Read-only) stay assignable by
        # customer administrators, bounded by the subset rule below; role
        # templates must be customer roles.
        internal = sorted(frozenset().union(*[role_keys(r) for r in roles]) - STAFF_ONLY_KEYS
                          - CUSTOMER_ASSIGNABLE_KEYS) if roles else []
        if internal:
            return _deny('Customer administrators can assign customer roles only; this role includes '
                         + ', '.join(internal[:6]) + ('...' if len(internal) > 6 else '') + '.')
    mine = actor_keys(actor, org_id)
    missing = granted - mine
    if missing:
        return _deny('You can only assign permissions you hold yourself here; missing: '
                     + ', '.join(sorted(missing)[:6]) + ('...' if len(missing) > 6 else '') + '.')
    privileged = _privileged_keys(granted) or any(is_privileged_role(r) for r in roles if not isinstance(r, str))
    if target_membership is not None:
        verdict = can_manage_member(actor, org_id, target_membership, privileged=privileged)
        if not verdict:
            return verdict
    elif privileged and not user_has_org_perm(actor, org_id, 'org_manage_privileged'):
        return _deny("Assigning a privileged role needs 'org_manage_privileged'.")
    return OK


def assignable_roles(actor, organization):
    """Role templates `actor` may hand out at `organization` (for pickers)."""
    from django.db.models import Q
    from .models import RoleTemplate
    qs = RoleTemplate.objects.filter(Q(organization__isnull=True) | Q(organization=organization),
                                     is_archived=False).order_by('name')
    return [r for r in qs if can_assign_role(actor, organization, r)]


def check_or_raise(verdict: Verdict, request=None, what='', organization=None, target=None):
    if not verdict:
        from .role_audit import record_delegation_denied
        record_delegation_denied(request, what, verdict.reason, organization=organization, target=target)
        raise DelegationError(verdict.reason)
    return verdict


def check_owner_change(membership, *, new_role=None, new_template=None, template_given=False,
                       deactivate=False) -> Verdict:
    if would_strand_owner(membership, new_role=new_role, new_template=new_template,
                          template_given=template_given, deactivate=deactivate):
        return _deny(f'{membership.user.username} is the last active owner of {membership.organization.name}. '
                     'Transfer ownership first.')
    return OK


def last_owner_orgs(user):
    """Organizations where `user` is the only active owner (deactivation guard)."""
    from .models import Membership
    out = []
    for m in Membership.objects.filter(user=user, is_active=True).select_related('organization', 'role_template'):
        if m.is_owner() and m.organization.is_active and count_active_owners(m.organization,
                                                                            exclude_membership=m) == 0:
            out.append(m.organization)
    return out
