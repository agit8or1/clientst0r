"""Last activity and "who acts next" for tickets (v3.17.654).

``last_actions`` says what happened last on each ticket (a reply from the
customer or a technician, an internal note, a file, a status change), by whom
and when. ``next_step`` says whose move it is, using the same definitions as
the My Work queues (psa.my_work): the customer spoke last → the technician
owes a reply; a technician spoke last or the ticket waits on the customer →
the customer does, and after FOLLOW_UP_DAYS without an answer the technician
should follow up.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .my_work import EPOCH, is_customer_wait_status

FOLLOW_UP_DAYS = 3

# (key, label, badge class)
NEXT_STEPS = {
    'reply': ('Needs reply', 'bg-danger'),
    'customer': ('Waiting on customer', 'bg-secondary'),
    'follow_up': ('Follow up', 'bg-warning text-dark'),
    'vendor': ('Waiting on vendor', 'bg-info text-dark'),
    'in_hand': ('In hand', 'bg-light text-dark border'),
    'closed': ('Closed', 'bg-success'),
}


def _name(user, fallback=''):
    if user is None:
        return fallback
    return user.get_full_name() or user.get_username()


def last_actions(tickets, include_internal=True):
    """{ticket_id: {'at', 'kind', 'by'}} for the given tickets, with two
    queries whatever their number. Without ``include_internal`` (customer
    views) internal notes, internal files and staff-only events are skipped."""
    from .models import TicketAttachment, TicketComment
    from .visibility import is_msp_staff
    ids = [t.pk for t in tickets]
    out = {t.pk: {'at': t.created_at, 'kind': 'opened', 'by': ''} for t in tickets}
    if not ids:
        return out
    comments = TicketComment.objects.filter(ticket_id__in=ids).select_related('author', 'author__profile')
    files = TicketAttachment.objects.filter(ticket_id__in=ids).select_related('uploaded_by')
    if not include_internal:
        comments = comments.filter(is_internal=False)
        files = files.filter(is_internal=False).exclude(comment__is_internal=True)
    # Newest per ticket: walk newest-first and keep the first one seen.
    seen = set()
    for c in comments.order_by('-created_at', '-pk')[:5000]:
        if c.ticket_id in seen:
            continue
        seen.add(c.ticket_id)
        if c.is_system:
            kind = 'update'
        elif c.is_internal:
            kind = 'internal note'
        elif c.author is not None and is_msp_staff(c.author):
            kind = 'technician reply'
        else:
            kind = 'customer reply'
        if c.created_at >= out[c.ticket_id]['at']:
            out[c.ticket_id] = {'at': c.created_at, 'kind': kind, 'by': _name(c.author, c.author_name)}
    seen = set()
    for a in files.order_by('-created_at', '-pk')[:5000]:
        if a.ticket_id in seen:
            continue
        seen.add(a.ticket_id)
        if a.created_at > out[a.ticket_id]['at']:
            out[a.ticket_id] = {'at': a.created_at, 'kind': 'file attached', 'by': _name(a.uploaded_by)}
    return out


def next_step(ticket, now=None):
    """Key into NEXT_STEPS for a ticket carrying the annotate_activity()
    columns (staff_activity_at, customer_activity_at)."""
    now = now or timezone.now()
    status = ticket.status
    if ticket.closed_at or (status is not None and status.is_terminal):
        return 'closed'
    if ticket.waiting_on_vendor or (status is not None and status.pauses_sla
                                    and not is_customer_wait_status(status)):
        return 'vendor'
    staff_at = getattr(ticket, 'staff_activity_at', EPOCH) or EPOCH
    customer_at = getattr(ticket, 'customer_activity_at', EPOCH) or EPOCH
    customer_wait = is_customer_wait_status(status)
    if not customer_wait and (customer_at > staff_at or staff_at == EPOCH):
        return 'reply'
    if customer_wait or staff_at > customer_at:
        last_ours = staff_at if staff_at != EPOCH else ticket.created_at
        return 'follow_up' if now - last_ours > timedelta(days=FOLLOW_UP_DAYS) else 'customer'
    return 'in_hand'


def decorate(tickets, include_internal=True):
    """Set ``last_action`` and ``next_step`` / ``next_label`` / ``next_badge``
    on each (annotated) ticket, for templates."""
    tickets = list(tickets)
    actions = last_actions(tickets, include_internal=include_internal)
    now = timezone.now()
    for t in tickets:
        t.last_action = actions.get(t.pk)
        t.next_step = next_step(t, now)
        t.next_label, t.next_badge = NEXT_STEPS[t.next_step]
    return tickets
