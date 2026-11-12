"""
PSA tech notifications - fired when a ticket is assigned, or when an
already-assigned ticket gets a due date set/changed.

Channels (email + SMS) are opt-in per user via UserProfile fields. SMS
requires SystemSetting.sms_enabled AND a phone number on the profile.

Failures are caught + logged; they NEVER block ticket save flow.

Note: PSA Ticket uses `resolution_due_at` (DateTimeField) as the
"scheduled-for" timestamp; that's what dispatch board treats as
the due date and what these notifications act on.
"""
import logging

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger('psa.notifications')


def _ticket_url(ticket) -> str:
    """Best-effort absolute-ish URL for the ticket (depends on SITE_URL)."""
    base = getattr(django_settings, 'SITE_URL', '').rstrip('/')
    try:
        path = reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number})
    except Exception:
        path = f'/psa/t/{ticket.ticket_number}/'
    return f'{base}{path}' if base else path


def _user_profile(user):
    return getattr(user, 'profile', None)


def _send_email(user, subject, body):
    if not user.email:
        return False, 'no email on user'
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', None) or 'noreply@localhost',
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True, ''
    except Exception as exc:
        logger.warning('email notification failed for %s: %s', user.username, exc)
        return False, str(exc)[:200]


def _send_sms(user, body):
    profile = _user_profile(user)
    if not profile or not profile.phone:
        return False, 'no phone on profile'
    try:
        from core.sms import send_sms as core_send_sms
        result = core_send_sms(profile.phone, body)
        if result.get('success'):
            return True, ''
        return False, str(result.get('error') or 'sms provider returned failure')[:200]
    except Exception as exc:
        logger.warning('SMS notification failed for %s: %s', user.username, exc)
        return False, str(exc)[:200]


def _sms_globally_enabled() -> bool:
    try:
        from core.models import SystemSetting
        return bool(SystemSetting.get_settings().sms_enabled)
    except Exception:
        return False


def notify_tech_assigned(ticket, *, by_user=None):
    """
    Fire when ticket.assigned_to becomes (or changes to) a user. Skips
    self-assignment (by_user == new assignee) since the tech who clicked
    the button doesn't need an email back from themselves.
    """
    if not ticket.assigned_to_id:
        return {'email': None, 'sms': None}
    user = ticket.assigned_to
    if by_user and by_user.id == user.id:
        return {'email': 'self', 'sms': 'self'}
    profile = _user_profile(user)
    if not profile:
        return {'email': 'no profile', 'sms': 'no profile'}

    org = getattr(ticket, 'organization', None)
    org_name = getattr(org, 'name', '') or 'a client'
    subject = f'[{ticket.ticket_number}] Assigned to you - {ticket.subject[:80]}'
    url = _ticket_url(ticket)
    priority_code = getattr(ticket.priority, 'code', '') if ticket.priority_id else ''
    priority_name = getattr(ticket.priority, 'name', '') if ticket.priority_id else ''
    priority_str = (priority_code + ' ' + priority_name).strip() if priority_code else ''
    status_name = getattr(ticket.status, 'name', '') if ticket.status_id else ''
    body_email = (
        f'You have been assigned ticket {ticket.ticket_number} for {org_name}.\n\n'
        f'Subject: {ticket.subject}\n'
        f'Priority: {priority_str}\n'
        f'Status: {status_name}\n'
        f'{f"Assigned by {by_user.username}." if by_user else ""}\n\n'
        f'Open it: {url}\n'
    )
    body_sms = f'PSA: {ticket.ticket_number} assigned to you - {ticket.subject[:80]}'

    out = {'email': None, 'sms': None}
    if profile.notify_assigned_email:
        ok, err = _send_email(user, subject, body_email)
        out['email'] = 'sent' if ok else f'fail: {err}'
    if profile.notify_assigned_sms and _sms_globally_enabled():
        ok, err = _send_sms(user, body_sms)
        out['sms'] = 'sent' if ok else f'fail: {err}'
    return out


def notify_tech_scheduled(ticket, *, by_user=None, prior_due_date=None):
    """
    Fire when an already-assigned ticket has its due_date set or changed.
    No-op if the ticket is unassigned (no recipient).

    Uses Ticket.resolution_due_at as the scheduled timestamp.
    """
    due = getattr(ticket, 'resolution_due_at', None)
    if not ticket.assigned_to_id or not due:
        return {'email': None, 'sms': None}
    user = ticket.assigned_to
    if by_user and by_user.id == user.id:
        return {'email': 'self', 'sms': 'self'}
    profile = _user_profile(user)
    if not profile:
        return {'email': 'no profile', 'sms': 'no profile'}

    when = due.strftime('%Y-%m-%d %H:%M') if hasattr(due, 'strftime') else str(due)
    subject = f'[{ticket.ticket_number}] Scheduled for {when} - {ticket.subject[:80]}'
    url = _ticket_url(ticket)
    body_email = (
        f'Ticket {ticket.ticket_number} is now scheduled for {when}.\n\n'
        f'Subject: {ticket.subject}\n'
        f'{"Reschedule from " + str(prior_due_date) + "." if prior_due_date else ""}\n'
        f'{f"Set by {by_user.username}." if by_user else ""}\n\n'
        f'Open it: {url}\n'
    )
    body_sms = f'PSA: {ticket.ticket_number} due {when} - {ticket.subject[:60]}'

    out = {'email': None, 'sms': None}
    if profile.notify_scheduled_email:
        ok, err = _send_email(user, subject, body_email)
        out['email'] = 'sent' if ok else f'fail: {err}'
    if profile.notify_scheduled_sms and _sms_globally_enabled():
        ok, err = _send_sms(user, body_sms)
        out['sms'] = 'sent' if ok else f'fail: {err}'
    return out


def notify_portal_status_change(ticket):
    """
    Phase 12 v8 (v3.17.238): SMS the portal-side requester when their
    ticket changes status. Best-effort — failures log. Returns a dict
    mirroring `notify_tech_*` shape so callers can inspect outcomes.

    Resolves the recipient via `ticket.requester_email`. If the email
    doesn't match a User, or that User's profile has the SMS opt-in
    flag off, returns silently — no fallback attempt to email-only here
    since email-on-status-change already lives elsewhere in the
    codebase via Phase 12 portal notify_status_change preference.
    """
    if not ticket.requester_email:
        return {'sms': 'no recipient'}
    try:
        from django.contrib.auth.models import User
        user = User.objects.filter(email=ticket.requester_email).first()
    except Exception:
        return {'sms': 'lookup error'}
    if not user:
        return {'sms': 'no user account'}
    # Only someone the portal would show this ticket to: an internal ticket
    # (client_can_view off), or a requester who has since left the customer,
    # gets nothing.
    from .visibility import user_can_view_ticket
    if not user_can_view_ticket(user, ticket):
        return {'sms': 'not visible to requester'}
    profile = _user_profile(user)
    if not profile:
        return {'sms': 'no profile'}
    if not profile.portal_notify_sms_status_change:
        return {'sms': 'opted out'}
    if not _sms_globally_enabled():
        return {'sms': 'sms globally off'}

    status_name = getattr(ticket.status, 'name', '') if ticket.status_id else ''
    body_sms = f'Ticket {ticket.ticket_number}: status changed to {status_name}'[:160]
    ok, err = _send_sms(user, body_sms)
    return {'sms': 'sent' if ok else f'fail: {err}'}
