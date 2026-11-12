"""
Ownership transfer: the only way ownership of an organization moves.

    transfer_ownership(actor, organization, to_user, *, password, confirm_name,
                       previous_owner_role=None, request=None) -> OwnershipTransfer

Who may start it: a current active owner of the organization (or a
superuser). The actor re-enters their password and types the
organization's name. The new owner must already be an active member of the
organization and an active account; MSP staff can not be made owner of a
customer by a customer owner. On success, in one transaction:

  * the new owner's membership becomes the simple Owner role (template
    cleared; additional roles kept);
  * the previous owner keeps `previous_owner_role` (a role template they
    could assign) or, when None, stays a co-owner;
  * an OwnershipTransfer row and an 'ownership.transferred' audit entry are
    written.

Generic member / user edit forms refuse ownership changes
(accounts.delegation rule 5).
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .delegation import DelegationError, can_assign_role, count_active_owners
from .permission_utils import is_msp_staff


def transfer_ownership(actor, organization, to_user, *, password, confirm_name, previous_owner_role=None,
                       request=None):
    from .models import Membership, OwnershipTransfer
    from . import role_audit

    def refuse(reason):
        role_audit.record_delegation_denied(request, 'ownership transfer', reason, organization=organization,
                                            target=to_user)
        raise DelegationError(reason)

    if actor is None or not actor.is_authenticated or not actor.is_active:
        refuse('Not signed in.')
    if not actor.check_password(password or ''):
        refuse('Password is not correct.')
    if (confirm_name or '').strip() != organization.name:
        refuse('Type the organization name exactly to confirm.')
    actor_m = Membership.objects.filter(user=actor, organization=organization, is_active=True).first()
    if not actor.is_superuser and (actor_m is None or not actor_m.is_owner()):
        refuse('Only a current owner can transfer ownership.')
    if to_user is None or not to_user.is_active:
        refuse('The new owner must be an active account.')
    if to_user.pk == actor.pk:
        refuse('You already own this organization.')
    target_m = Membership.objects.filter(user=to_user, organization=organization, is_active=True).first()
    if target_m is None:
        refuse('The new owner must already be an active member of the organization.')
    if not actor.is_superuser and not is_msp_staff(actor) and is_msp_staff(to_user):
        refuse('A customer owner cannot make MSP staff the owner.')
    if previous_owner_role is not None and actor_m is not None:
        if previous_owner_role.organization_id not in (None, organization.pk) or previous_owner_role.is_archived:
            refuse('That role can not be used here.')
        if previous_owner_role.org_owner:
            previous_owner_role = None  # stays owner

    with transaction.atomic():
        before_target = {'role': target_m.role, 'role_template': getattr(target_m.role_template, 'name', None)}
        target_m.role = 'owner'
        target_m.role_template = None
        target_m.save()
        before_actor = None
        if actor_m is not None and previous_owner_role is not None:
            before_actor = {'role': actor_m.role, 'role_template': getattr(actor_m.role_template, 'name', None)}
            actor_m.role = 'admin'
            actor_m.role_template = previous_owner_role
            actor_m.save()
        if count_active_owners(organization) == 0:  # pragma: no cover - defensive
            raise DelegationError('The transfer would leave no owner.')
        row = OwnershipTransfer.objects.create(
            organization=organization, from_user=actor if actor_m is not None else None, to_user=to_user,
            requested_by=actor, previous_owner_role=previous_owner_role, status=OwnershipTransfer.COMPLETED,
            completed_at=timezone.now())
    role_audit.record('ownership.transferred', target_type='organization', target_id=organization.pk,
                      target_repr=organization.name, organization=organization, request=request, actor=actor,
                      before={'new_owner': before_target, 'previous_owner': before_actor},
                      after={'new_owner': to_user.username,
                             'previous_owner_keeps': getattr(previous_owner_role, 'name', 'Owner')},
                      description=f'Ownership of {organization.name} transferred to {to_user.username}')
    return row


__all__ = ['transfer_ownership', 'DelegationError', 'can_assign_role']
