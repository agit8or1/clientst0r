"""
Protected changes: widening a protected setting takes two administrators.

Protected settings: technician access above the L1 baseline (assignments,
preset capabilities, group membership), RMM business mappings (a Rem0te
ticket-processor pairing), the approver list, the recovery contact, AI
provider destinations, and security limits (theft-detection thresholds and
containment).

Narrowing — revoking, lowering, tightening — applies at once and is
audited. Widening goes through these steps:

  1. propose()   records what would change, who it affects and what it
                 grants beyond today. Nothing changes yet.
  2. confirm()   the requester re-authenticates (password, plus their
                 authenticator code when they have one).
  3. approve()   a different approver re-authenticates and approves. The
                 change is applied in the same transaction.

Refused outright: approving your own change; approving a change that widens
your own access (self-promotion); approving a recovery-contact change that
names you or your address; approving after expiry. Every proposal, approval,
rejection and application is announced to the recovery contact as it was
*before* the change, and to the requester and the affected technician.

A one-administrator install can't widen anything until a second approver
exists; the Technician Access page says so.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import ProtectedChange, ProtectionSettings

logger = logging.getLogger('tech_access')

FRESH_AUTH_SECONDS = 300
CHANGE_LIFETIME = timedelta(hours=72)
SESSION_KEY = 'tech_access_reauth_at'

_APPLIERS = {}


class ProtectedChangeError(Exception):
    pass


def applier(kind):
    def register(fn):
        _APPLIERS[kind] = fn
        return fn
    return register


# --- fresh authentication --------------------------------------------------

def verify_credentials(user, password, otp_token='') -> str:
    """'' when the password (and authenticator code, if the user has a
    confirmed device) are right, else why not."""
    if not password or not user.check_password(password):
        return 'Password incorrect.'
    from django_otp.plugins.otp_totp.models import TOTPDevice
    devices = list(TOTPDevice.objects.filter(user=user, confirmed=True))
    if devices:
        token = (otp_token or '').strip().replace(' ', '')
        if not token or not any(d.verify_token(token) for d in devices):
            return 'Authenticator code incorrect.'
    return ''


def reauthenticate(request, password, otp_token='') -> str:
    error = verify_credentials(request.user, password, otp_token)
    if not error:
        request.session[SESSION_KEY] = int(timezone.now().timestamp())
    return error


def has_fresh_auth(request) -> bool:
    ts = request.session.get(SESSION_KEY)
    # Written by reauthenticate() as whole seconds; anything else is not fresh.
    if not isinstance(ts, int) or isinstance(ts, bool):
        return False
    age = int(timezone.now().timestamp()) - ts
    return 0 <= age <= FRESH_AUTH_SECONDS


# --- approvers and notifications ------------------------------------------

def approvers():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    chosen = ProtectionSettings.load().approvers.filter(is_active=True, is_superuser=True)
    if chosen.exists():
        return chosen
    return User.objects.filter(is_active=True, is_superuser=True)


def is_approver(user) -> bool:
    return bool(user and user.is_authenticated and approvers().filter(pk=user.pk).exists())


def can_widen_at_all(requester) -> bool:
    return approvers().exclude(pk=requester.pk).exists()


def _notify(change, event, recovery_email=None):
    """Tell the verified recovery contact (as captured before the change),
    the requester and the affected technician. No secrets, no ticket text."""
    settings_obj = ProtectionSettings.load()
    recipients = set()
    contact = recovery_email if recovery_email is not None else (
        settings_obj.recovery_email if settings_obj.recovery_verified_at else '')
    if contact:
        recipients.add(contact)
    for u in (change.requested_by, change.target_user):
        if u is not None and u.email:
            recipients.add(u.email)
    if not recipients:
        return []
    who = change.requested_by.get_username() if change.requested_by else 'someone'
    body = (f'Protected change #{change.pk} was {event}.\n\n'
            f'Change: {change.summary}\n'
            f'Requested by: {who}\n'
            f'Grants beyond the current state: {", ".join(change.widening) or "nothing"}\n\n'
            'If you did not expect this, sign in and review Settings → Security → Technician Access.')
    try:
        send_mail(f'[ClientSt0r] Protected change {event}', body, None, sorted(recipients), fail_silently=True)
    except Exception:  # mail is best effort; the audit log is the record
        logger.exception('protected change notification failed')
    return sorted(recipients)


def _audit(user, change, verb, request=None):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='update', object_type='protected_change', object_id=change.pk,
                 object_repr=change.summary[:255], description=f'Protected change {verb}: {change.summary}',
                 ip_address=(request.META.get('REMOTE_ADDR') if request else None),
                 path=(request.path if request else ''),
                 extra_data={'kind': change.kind, 'widening': change.widening, 'status': change.status})


# --- lifecycle --------------------------------------------------------------

def propose(kind, summary, payload, widening, requested_by, target_user=None, affected=(), request=None):
    change = ProtectedChange.objects.create(
        kind=kind, summary=summary[:300], payload=payload, widening=list(widening),
        affected_users=sorted({int(u) for u in affected}), target_user=target_user,
        requested_by=requested_by, expires_at=timezone.now() + CHANGE_LIFETIME)
    change.notified = _notify(change, 'proposed')
    change.save(update_fields=['notified'])
    _audit(requested_by, change, 'proposed', request)
    return change


def _live(change):
    if change.status != ProtectedChange.PENDING:
        raise ProtectedChangeError(f'This change is already {change.get_status_display().lower()}.')
    if change.expires_at <= timezone.now():
        change.status = ProtectedChange.EXPIRED
        change.save(update_fields=['status'])
        raise ProtectedChangeError('This change expired. Propose it again.')


def confirm(change, request):
    _live(change)
    if request.user.pk != change.requested_by_id:
        raise ProtectedChangeError('Only the requester can confirm their own change.')
    if not has_fresh_auth(request):
        raise ProtectedChangeError('Re-enter your password first.')
    change.requester_reauth_at = timezone.now()
    change.save(update_fields=['requester_reauth_at'])
    _audit(request.user, change, 'confirmed by requester', request)


def approval_refusal(change, reviewer) -> str:
    if not is_approver(reviewer):
        return 'You are not an approver for protected changes.'
    if reviewer.pk == change.requested_by_id:
        return 'A second administrator must approve this; you proposed it.'
    if change.target_user_id and reviewer.pk == change.target_user_id:
        return 'You cannot approve a change that widens your own access.'
    if reviewer.pk in (change.affected_users or []):
        return 'You cannot approve a change that affects your own access.'
    if change.kind == 'recovery_contact':
        new = (change.payload.get('recovery_email') or '').lower()
        if new and reviewer.email and new == reviewer.email.lower():
            return 'You cannot approve a recovery contact that is your own address.'
    if change.kind == 'approvers' and reviewer.pk in (change.payload.get('add') or []):
        return 'You cannot approve adding yourself as an approver.'
    if not change.requester_reauth_at:
        return 'The requester has not confirmed this change yet.'
    return ''


def approve(change, request):
    reviewer = request.user
    with transaction.atomic():
        change = ProtectedChange.objects.select_for_update().get(pk=change.pk)
        _live(change)
        refusal = approval_refusal(change, reviewer)
        if refusal:
            raise ProtectedChangeError(refusal)
        if not has_fresh_auth(request):
            raise ProtectedChangeError('Re-enter your password first.')
        before_contact = ProtectionSettings.load()
        contact = before_contact.recovery_email if before_contact.recovery_verified_at else ''
        fn = _APPLIERS.get(change.kind)
        if fn is None:
            raise ProtectedChangeError('This kind of change cannot be applied.')
        fn(change, reviewer)
        now = timezone.now()
        change.status, change.reviewed_by, change.reviewed_at, change.reviewer_reauth_at = (
            ProtectedChange.APPLIED, reviewer, now, now)
        change.save()
    change.notified = sorted(set(change.notified or []) | set(_notify(change, 'approved and applied', contact)))
    change.save(update_fields=['notified'])
    _audit(reviewer, change, 'approved and applied', request)
    return change


def reject(change, request, cancel=False):
    _live(change)
    if cancel and request.user.pk != change.requested_by_id:
        raise ProtectedChangeError('Only the requester can cancel.')
    if not cancel and not is_approver(request.user):
        raise ProtectedChangeError('You are not an approver for protected changes.')
    change.status = ProtectedChange.CANCELLED if cancel else ProtectedChange.REJECTED
    change.reviewed_by, change.reviewed_at = request.user, timezone.now()
    change.save()
    _notify(change, 'cancelled' if cancel else 'rejected')
    _audit(request.user, change, change.status, request)
