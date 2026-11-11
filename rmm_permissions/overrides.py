"""
Creating, reviewing and revoking RMM permission overrides.

Narrowing (deny, require approval, ending an allow) applies at once.
Widening (allow, or lifting a deny / require approval) is saved pending and takes effect only when a different Platform
Administrator — not the person it grants to — approves it after
re-authenticating. Every step is audited.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from . import catalog
from .decision import can
from .models import RMMPermissionOverride as O


def _audit(user, o, verb, request=None, success=True):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='create' if verb == 'created' else 'update', organization=o.organization,
                 object_type='rmm_permission_override', object_id=o.pk, object_repr=str(o)[:255],
                 description=f'RMM override #{o.pk} {verb}: {o}' + (f' — {o.reason}' if o.reason else ''),
                 path=getattr(request, 'path', '') or '', success=success,
                 extra_data={'override': o.pk, 'action': o.action, 'effect': o.effect, 'status': o.status,
                             'organization': o.organization_id, 'user': o.user_id,
                             'role_template': o.role_template_id, 'approval_level': o.approval_level,
                             'expires_at': o.expires_at.isoformat() if o.expires_at else None})


def _admin(user, organization=None):
    if not can(user, organization, 'policy.manage').allowed:
        raise PermissionDenied('Managing RMM permissions needs “Manage RMM policy and roles”.')


def create(by, *, action, effect, organization=None, user=None, role_template=None, approval_level='',
           reason='', expires_at=None, request=None) -> O:
    _admin(by, organization)
    if effect not in dict(O.EFFECTS):
        raise ValidationError('Choose allow, deny or require approval.')
    if action in catalog.LOCKED:
        raise ValidationError('That is a locked safeguard; nothing can switch it on.')
    if action != '*' and action not in catalog.ACTIONS:
        raise ValidationError('Unknown RMM action.')
    if user is not None and role_template is not None:
        raise ValidationError('Choose a technician or a role, not both.')
    if expires_at is not None and expires_at <= timezone.now():
        raise ValidationError('The expiry is in the past.')
    status = O.ACTIVE
    if effect == O.ALLOW:
        if action == '*':
            raise ValidationError('Allow overrides name one action.')
        if organization is None:
            raise ValidationError('Allow overrides name one customer; nothing grants every customer.')
        if action == 'credential.reveal':
            raise ValidationError('Credential reveal comes from the vault permission, not an override.')
        status = O.PENDING
        approval_level = ''
    elif effect == O.REQUIRE_APPROVAL:
        approval_level = approval_level or catalog.PEER
        if approval_level not in catalog.APPROVAL_LEVELS:
            raise ValidationError('Unknown approval level.')
    else:
        approval_level = ''
    o = O.objects.create(organization=organization, action=action, user=user, role_template=role_template,
                         effect=effect, approval_level=approval_level, reason=(reason or '')[:300],
                         status=status, expires_at=expires_at, created_by=by)
    _audit(by, o, 'created' if status == O.ACTIVE else 'proposed (waiting for a second administrator)', request)
    return o


def review_refusal(o, reviewer) -> str:
    if o.status != O.PENDING:
        return 'This override is not waiting for review.'
    if reviewer.pk == o.created_by_id:
        return 'A different administrator must approve it.'
    if o.user_id and reviewer.pk == o.user_id:
        return 'You cannot approve an override that widens your own access.'
    if o.role_template_id:
        from .decision import global_role
        if getattr(global_role(reviewer), 'pk', None) == o.role_template_id:
            return 'You cannot approve an override that widens your own role.'
    if not can(reviewer, o.organization, 'policy.manage').allowed:
        return 'Only a Platform Administrator may approve this.'
    return ''


def review(o, request, approve=True):
    from tech_access.protected import has_fresh_auth
    reviewer = request.user
    if not has_fresh_auth(request):
        return False, 'Confirm your password first.'
    with transaction.atomic():
        o = O.objects.select_for_update().get(pk=o.pk)
        why = review_refusal(o, reviewer)
        if why:
            _audit(reviewer, o, f'review refused ({why})', request, success=False)
            return False, why
        o.status = O.ACTIVE if approve else O.REJECTED
        o.reviewed_by, o.reviewed_at = reviewer, timezone.now()
        o.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    _audit(reviewer, o, 'approved' if approve else 'rejected', request)
    return True, f'Override #{o.pk} {"approved" if approve else "rejected"}.'


def revoke(o, by, request=None):
    """Ending an allow (or a pending proposal) narrows: at once. Lifting a
    deny or require-approval widens: it waits for a second administrator."""
    _admin(by, o.organization)
    if o.status not in (O.ACTIVE, O.PENDING):
        return False, 'Already ended.'
    if o.effect == O.ALLOW or o.status == O.PENDING:
        o.status, o.revoked_by, o.revoked_at = O.REVOKED, by, timezone.now()
        o.save(update_fields=['status', 'revoked_by', 'revoked_at'])
        _audit(by, o, 'revoked', request)
        return True, f'Override #{o.pk} revoked.'
    o.lift_requested_by, o.lift_requested_at = by, timezone.now()
    o.save(update_fields=['lift_requested_by', 'lift_requested_at'])
    _audit(by, o, 'lift requested (stays in force until a second administrator confirms)', request)
    return True, f'Override #{o.pk} stays in force until a second administrator confirms the lift.'


def lift_refusal(o, reviewer) -> str:
    if o.status != O.ACTIVE or not o.lift_requested_by_id:
        return 'No lift is waiting for review.'
    if reviewer.pk == o.lift_requested_by_id:
        return 'A different administrator must confirm the lift.'
    if o.user_id and reviewer.pk == o.user_id:
        return 'You cannot lift a restriction on yourself.'
    if o.role_template_id:
        from .decision import global_role
        if getattr(global_role(reviewer), 'pk', None) == o.role_template_id:
            return 'You cannot lift a restriction on your own role.'
    if not can(reviewer, o.organization, 'policy.manage').allowed:
        return 'Only a Platform Administrator may confirm this.'
    return ''


def review_lift(o, request, approve=True):
    from tech_access.protected import has_fresh_auth
    reviewer = request.user
    if not has_fresh_auth(request):
        return False, 'Confirm your password first.'
    with transaction.atomic():
        o = O.objects.select_for_update().get(pk=o.pk)
        why = lift_refusal(o, reviewer)
        if why:
            _audit(reviewer, o, f'lift review refused ({why})', request, success=False)
            return False, why
        if approve:
            o.status, o.revoked_by, o.revoked_at = O.REVOKED, reviewer, timezone.now()
            o.save(update_fields=['status', 'revoked_by', 'revoked_at'])
        else:
            o.lift_requested_by, o.lift_requested_at = None, None
            o.save(update_fields=['lift_requested_by', 'lift_requested_at'])
    _audit(reviewer, o, 'lifted' if approve else 'lift rejected', request)
    return True, f'Override #{o.pk} {"lifted" if approve else "kept"}.'
