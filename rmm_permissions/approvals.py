"""
Second-person approval for high-impact RMM operations.

    request_approval(user, organization, action, device=None, ticket=None,
                     digest='', summary='', request=None) -> RMMApproval
    approve(approval, request, note='') -> (ok, message)
    reject(approval, request, note='') -> (ok, message)
    consume(user, organization, action, device_key, digest) -> RMMApproval | None

Rules:
  - Nobody approves their own request (and an approver must be someone
    other than the requester even when both hold the same tier).
  - The approver re-authenticates (tech_access.protected's fresh-auth
    window) and must qualify for the level *now*:
        peer            may do the same action here themselves
        l3              holds the RMM L3 tier, scoped to this customer, or
                        a live technician-access assignment here whose
                        preset is level 3
        platform_admin  holds policy.manage
    If the requirement tightened since the request, the stricter level
    applies.
  - The requester must still be allowed the action when it is approved
    and again when it runs (rmm_action re-decides; consume only adds the
    approval).
  - An approval is single use and bound to requester, customer, action,
    device and the caller's digest of the exact operation; it expires
    after 24 hours.

For Rem0te-managed devices this is in addition to Rem0te's own approvals
(its roster, passkeys, signer), which ClientSt0r never replaces.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from . import catalog
from .decision import RMMPermissionDenied, can, device_ref, is_technician, resolve_device, scoped, tier_of
from .models import RMMApproval


def _audit(user, approval, verb, request=None, success=True):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='update' if verb != 'requested' else 'create',
                 organization=approval.organization, object_type='rmm_approval', object_id=approval.pk,
                 object_repr=f'{approval.action} approval #{approval.pk}'[:255],
                 description=(f'RMM approval #{approval.pk} {verb}: {approval.action} for '
                              f'{approval.requester.get_username()}'
                              + (f' on {approval.device_label}' if approval.device_label else '')
                              + (f' — {approval.decision_note}' if approval.decision_note else ''))[:1000],
                 path=getattr(request, 'path', '') or '', success=success,
                 extra_data={'approval': approval.pk, 'action': approval.action, 'level': approval.approval_level,
                             'device': approval.device_key, 'digest': approval.digest, 'status': approval.status})


def request_approval(user, organization, action, device=None, ticket=None, digest='', summary='',
                     request=None) -> RMMApproval:
    d = can(user, organization, action, device=device, ticket=ticket)
    if not d.allowed:
        raise RMMPermissionDenied(d)
    if not d.needs_approval:
        raise ValueError('This action needs no approval here.')
    key, label = device_ref(device)
    now = timezone.now()
    existing = (RMMApproval.objects.filter(requester=user, organization=organization, action=action,
                                           device_key=key, digest=digest or '',
                                           status__in=[RMMApproval.PENDING, RMMApproval.APPROVED],
                                           expires_at__gt=now).order_by('-created_at').first())
    if existing is not None:
        return existing
    a = RMMApproval.objects.create(requester=user, organization=organization, action=action, device_key=key,
                                   device_label=label, ticket=ticket, digest=digest or '',
                                   summary=(summary or '')[:500], approval_level=d.approval_level)
    _audit(user, a, 'requested', request)
    return a


def qualifies(approver, organization, action, device, level) -> str:
    """'' if `approver` may approve at `level`, else why not."""
    if level == catalog.PLATFORM_ADMIN:
        return '' if can(approver, organization, 'policy.manage').allowed else \
            'Only a Platform Administrator may approve this.'
    if level == catalog.L3:
        if not is_technician(approver):
            return 'Only an MSP technician may approve this.'
        if tier_of(approver) == 'l3' and scoped(approver, organization):
            return ''
        from tech_access.resolver import live_assignments
        if any(a.preset.level >= 3 for a in live_assignments(approver, organization)):
            return ''
        return 'Only an L3 technician at this customer may approve this.'
    d = can(approver, organization, action, device=device)
    return '' if d.allowed else f'You may not do this here yourself, so you cannot approve it: {d.reason}'


def refusal(approval, approver) -> str:
    if approver is None or not getattr(approver, 'is_authenticated', False):
        return 'Sign in first.'
    if approver.pk == approval.requester_id:
        return catalog.LOCKED['approval.self']
    if not approval.is_open:
        return 'This approval is no longer pending.'
    from tech_access.resolver import active_containment
    if active_containment(approver) is not None:
        return 'Your access is contained pending review.'
    device = resolve_device(approval.device_key)
    if approval.device_key and device is None:
        return 'The device no longer exists.'
    now_d = can(approval.requester, approval.organization, approval.action, device=device, ticket=approval.ticket)
    if not now_d.allowed:
        return f'The requester may no longer do this: {now_d.reason}'
    level = catalog.stronger(approval.approval_level, now_d.approval_level or approval.approval_level)
    return qualifies(approver, approval.organization, approval.action, device, level)


def _fresh(request) -> bool:
    from tech_access.protected import has_fresh_auth
    return has_fresh_auth(request)


def _decide(approval, request, new_status, note):
    user = getattr(request, 'user', None)
    if not _fresh(request):
        return False, 'Confirm your password first.'
    with transaction.atomic():
        a = RMMApproval.objects.select_for_update().get(pk=approval.pk)
        why = refusal(a, user)
        if why:
            _audit(user, a, f'{new_status} refused ({why})', request, success=False)
            return False, why
        a.status, a.decided_by, a.decided_at = new_status, user, timezone.now()
        a.decision_note = (note or '')[:300]
        a.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
    _audit(user, a, new_status, request)
    approval.refresh_from_db()
    return True, f'Approval #{a.pk} {new_status}.'


def approve(approval, request, note=''):
    return _decide(approval, request, RMMApproval.APPROVED, note)


def reject(approval, request, note=''):
    """A qualified approver rejects; the requester may cancel their own."""
    user = getattr(request, 'user', None)
    if user is not None and user.pk == approval.requester_id:
        n = RMMApproval.objects.filter(pk=approval.pk, status__in=[RMMApproval.PENDING, RMMApproval.APPROVED]
                                       ).update(status=RMMApproval.CANCELLED, decided_by=user,
                                                decided_at=timezone.now(), decision_note=(note or '')[:300])
        approval.refresh_from_db()
        if n:
            _audit(user, approval, 'cancelled', request)
        return bool(n), 'Cancelled.' if n else 'Nothing to cancel.'
    return _decide(approval, request, RMMApproval.REJECTED, note)


def consume(user, organization, action, device_key, digest) -> RMMApproval | None:
    """Use one approved, unexpired approval for exactly this operation."""
    now = timezone.now()
    for a in (RMMApproval.objects.filter(requester=user, organization=organization, action=action,
                                         device_key=device_key or '', digest=digest or '',
                                         status=RMMApproval.APPROVED, expires_at__gt=now)
              .select_related('decided_by').order_by('created_at')):
        if a.decided_by_id == user.pk:  # belt and braces: never self-approved
            continue
        if RMMApproval.objects.filter(pk=a.pk, status=RMMApproval.APPROVED).update(
                status=RMMApproval.CONSUMED, consumed_at=now):
            a.status, a.consumed_at = RMMApproval.CONSUMED, now
            return a
    return None


def open_for(user):
    """Pending approvals `user` might act on: their own, and others' at
    customers they can reach (qualification is checked on approve)."""
    from django.db.models import Q
    from tech_access.models import AccessAssignment
    now = timezone.now()
    qs = RMMApproval.objects.filter(status=RMMApproval.PENDING, expires_at__gt=now).select_related(
        'requester', 'organization', 'ticket')
    if can(user, None, 'policy.manage').allowed:
        return qs
    orgs = (AccessAssignment.objects.live().filter(Q(user=user) | Q(group__members=user))
            .values_list('organization_id', flat=True))
    return qs.filter(Q(requester=user) | Q(organization_id__in=list(orgs)))
