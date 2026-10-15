"""
Customer-friendly ticket progress for the portal.

Internal statuses ("Assigned", "Escalated", "Waiting on Vendor", ...) mean
little to a customer. The portal shows one of five phrases instead:

    Received · In progress · Waiting for you · Waiting for approval · Resolved

Defaults come from the TicketStatus flags; a `PortalStatusPhrase` row
(Django admin → Portal status phrases) overrides the default for one status.
A pending customer approval on the ticket always reads "Waiting for
approval" unless the ticket is resolved.
"""
from __future__ import annotations

from .models import PortalStatusPhrase as P

PHRASES = dict(P.PHRASE_CHOICES)

DESCRIPTIONS = {
    P.PHRASE_RECEIVED: "We've received your request and will pick it up shortly.",
    P.PHRASE_IN_PROGRESS: 'Our team is working on this.',
    P.PHRASE_WAITING_ON_CUSTOMER: 'We need something from you before we can continue.',
    P.PHRASE_WAITING_APPROVAL: 'This request is waiting for approval from your organization.',
    P.PHRASE_RESOLVED: 'This request is complete.',
}

BADGES = {
    P.PHRASE_RECEIVED: 'secondary',
    P.PHRASE_IN_PROGRESS: 'primary',
    P.PHRASE_WAITING_ON_CUSTOMER: 'warning',
    P.PHRASE_WAITING_APPROVAL: 'warning',
    P.PHRASE_RESOLVED: 'success',
}

# Linear steps shown as a progress strip; waiting states sit on step 2.
STEP_INDEX = {
    P.PHRASE_RECEIVED: 0,
    P.PHRASE_IN_PROGRESS: 1,
    P.PHRASE_WAITING_ON_CUSTOMER: 1,
    P.PHRASE_WAITING_APPROVAL: 1,
    P.PHRASE_RESOLVED: 2,
}


def default_phrase_for_status(status, *, waiting_on_vendor=False):
    """Default mapping from TicketStatus flags."""
    if status is None:
        return P.PHRASE_RECEIVED
    if status.is_terminal:
        return P.PHRASE_RESOLVED
    slug = (status.slug or '').lower()
    if status.pauses_sla:
        # A paused SLA usually means "waiting on someone". If that someone
        # is a vendor, the customer has nothing to do — it's still ours.
        if waiting_on_vendor or 'vendor' in slug or 'third' in slug:
            return P.PHRASE_IN_PROGRESS
        return P.PHRASE_WAITING_ON_CUSTOMER
    if slug == 'new':
        return P.PHRASE_RECEIVED
    return P.PHRASE_IN_PROGRESS


def _overrides(status_ids):
    return dict(P.objects.filter(status_id__in=list(status_ids))
                .values_list('status_id', 'phrase'))


def phrase_code(ticket, *, overrides=None, has_pending_approval=False):
    if overrides is None:
        overrides = _overrides([ticket.status_id])
    code = overrides.get(ticket.status_id) or default_phrase_for_status(
        ticket.status, waiting_on_vendor=getattr(ticket, 'waiting_on_vendor', False))
    if has_pending_approval and code != P.PHRASE_RESOLVED:
        code = P.PHRASE_WAITING_APPROVAL
    return code


def _progress_dict(code):
    return {
        'code': code,
        'label': PHRASES[code],
        'description': DESCRIPTIONS[code],
        'badge': BADGES[code],
        'step': STEP_INDEX[code],
    }


def pending_client_approvals(ticket):
    from psa.models import PSAApproval
    return list(PSAApproval.objects.filter(
        related_ticket=ticket, is_client_approval=True,
        status__in=('pending', 'blocked'),
    ).select_related('requested_by').order_by('requested_at'))


def customer_progress(ticket):
    """Progress dict for one ticket: code/label/description/badge/step."""
    approvals = pending_client_approvals(ticket)
    return _progress_dict(phrase_code(ticket, has_pending_approval=bool(approvals)))


def progress_for_tickets(tickets):
    """{ticket_id: progress dict} for a list of tickets in two queries."""
    from psa.models import PSAApproval
    tickets = list(tickets)
    if not tickets:
        return {}
    overrides = _overrides({t.status_id for t in tickets})
    pending_ids = set(PSAApproval.objects.filter(
        related_ticket_id__in=[t.pk for t in tickets],
        is_client_approval=True, status__in=('pending', 'blocked'),
    ).values_list('related_ticket_id', flat=True))
    return {
        t.pk: _progress_dict(phrase_code(
            t, overrides=overrides, has_pending_approval=t.pk in pending_ids))
        for t in tickets
    }


def question_waiting(ticket, comments):
    """The latest public staff comment the customer hasn't answered yet,
    or None. `comments` must already be filtered to non-internal ones."""
    staff = [c for c in comments
             if c.source not in ('portal', 'email')
             and not getattr(c, 'is_system', False)]
    if not staff:
        return None
    last = staff[-1]
    replied = ticket.last_client_response_at
    if replied and replied >= last.created_at:
        return None
    return last
