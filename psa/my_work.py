"""
Technician work queues — shared by the My Work page (/psa/my-work/) and the
ticket list's ``?queue=`` work-queue filters, so a count on My Work and the
list it links to can never disagree.

Definitions
-----------
Open
    Not closed: ``closed_at`` is empty and the status is not terminal.

Customer-wait status
    A status that pauses the SLA clock (``TicketStatus.pauses_sla``) and is not
    a vendor wait. The seeded defaults give "Waiting on Client" (customer wait)
    and "Waiting on Vendor" (not one). A status counts as a vendor wait when its
    slug or name contains "vendor"; an operator who adds their own paused status
    gets it treated as a customer wait unless it says vendor.

Public activity
    Only comments a customer can see count: ``is_internal=False`` and
    ``is_system=False``. Internal notes never move a ticket between queues —
    otherwise a tech jotting a note would look like a reply to the customer, and
    a customer user's view of these queues would leak that a note exists.

Last staff activity
    The newest public comment written by MSP staff (superuser, Django is_staff,
    or profile user_type Staff — the same rule as psa.visibility.is_msp_staff).
    ``Ticket.last_tech_response_at`` is NOT used: the reply view also stamps it
    for internal notes.

Last customer activity
    The later of ``Ticket.last_client_response_at`` (stamped by portal replies
    and inbound customer emails) and the newest public comment written by a
    signed-in user who is not MSP staff. Author-less comments (email ingest) are
    counted through ``last_client_response_at`` only, because the poller is what
    decides whether an email came from the customer or from a staff address.

Customer replied
    Open, and there is customer activity newer than the last staff activity
    (or the customer has written and staff never has).

Waiting on customer
    Open, and the status is a customer-wait status.

Waiting on us
    Open, the status does not pause the SLA, the ticket is not flagged as
    waiting on a vendor, and either the customer spoke last or no staff reply
    has been sent yet. A ticket where staff replied last and the status is still
    an active one sits in neither queue: work is in hand.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.db.models import (
    Case, DateTimeField, F, OuterRef, Q, Subquery, Value, When,
)
from django.db.models.functions import Coalesce, Greatest

# Sentinel for "never" so Greatest() behaves the same on every backend
# (SQLite/MySQL return NULL from GREATEST if any argument is NULL).
EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)

WORK_QUEUES = {
    'open': 'Open',
    'waiting_us': 'Waiting on us',
    'waiting_customer': 'Waiting on customer',
    'customer_replied': 'Customer replied',
}


def staff_author_q(prefix: str = 'author__') -> Q:
    """Q matching rows whose user (at ``prefix``) is MSP staff."""
    from accounts.models import UserType
    return (Q(**{f'{prefix}is_superuser': True})
            | Q(**{f'{prefix}is_staff': True})
            | Q(**{f'{prefix}profile__user_type': UserType.STAFF}))


def open_q(prefix: str = '') -> Q:
    return (Q(**{f'{prefix}closed_at__isnull': True})
            & Q(**{f'{prefix}status__is_terminal': False}))


def vendor_status_q(prefix: str = 'status__') -> Q:
    return (Q(**{f'{prefix}slug__icontains': 'vendor'})
            | Q(**{f'{prefix}name__icontains': 'vendor'}))


def customer_wait_status_q(prefix: str = 'status__') -> Q:
    return Q(**{f'{prefix}pauses_sla': True}) & ~vendor_status_q(prefix)


def is_customer_wait_status(status) -> bool:
    if status is None or not status.pauses_sla:
        return False
    text = f'{status.slug} {status.name}'.lower()
    return 'vendor' not in text


def annotate_activity(qs):
    """Add ``staff_activity_at``, ``customer_activity_at`` (EPOCH = never)
    and ``sla_due_at`` (next SLA deadline) to a Ticket queryset."""
    from psa.models import TicketComment

    public = TicketComment.objects.filter(
        ticket=OuterRef('pk'), is_internal=False, is_system=False,
    )
    last_staff = (public.filter(staff_author_q())
                  .order_by('-created_at').values('created_at')[:1])
    last_customer_comment = (public.filter(author__isnull=False)
                             .exclude(staff_author_q())
                             .order_by('-created_at').values('created_at')[:1])
    epoch = Value(EPOCH, output_field=DateTimeField())
    return qs.annotate(
        staff_activity_at=Coalesce(
            Subquery(last_staff, output_field=DateTimeField()), epoch),
        customer_activity_at=Greatest(
            Coalesce(F('last_client_response_at'), epoch),
            Coalesce(Subquery(last_customer_comment,
                              output_field=DateTimeField()), epoch),
            output_field=DateTimeField(),
        ),
        # The deadline that matters next: first response until one is made,
        # then resolution.
        sla_due_at=Case(
            When(first_response_at__isnull=True,
                 first_response_due_at__isnull=False,
                 then=F('first_response_due_at')),
            default=F('resolution_due_at'),
            output_field=DateTimeField(),
        ),
    )


def customer_replied_q() -> Q:
    return (open_q()
            & Q(customer_activity_at__gt=EPOCH)
            & Q(customer_activity_at__gt=F('staff_activity_at')))


def waiting_customer_q() -> Q:
    return open_q() & customer_wait_status_q()


def waiting_us_q() -> Q:
    return (open_q()
            & Q(status__pauses_sla=False)
            & Q(waiting_on_vendor=False)
            & (Q(customer_activity_at__gt=F('staff_activity_at'))
               | Q(staff_activity_at=EPOCH)))


def apply_work_queue(qs, queue: str):
    """Filter an (unannotated) Ticket queryset to one of WORK_QUEUES. The
    result carries the annotate_activity() columns, so it can be passed to
    order_by_sla()."""
    qs = annotate_activity(qs)
    if queue == 'open':
        return qs.filter(open_q())
    if queue == 'customer_replied':
        return qs.filter(customer_replied_q())
    if queue == 'waiting_customer':
        return qs.filter(waiting_customer_q())
    if queue == 'waiting_us':
        return qs.filter(waiting_us_q())
    return qs


def order_by_sla(qs):
    """Soonest SLA deadline first; tickets without one last."""
    return qs.order_by(F('sla_due_at').asc(nulls_last=True), 'created_at')


def resume_status():
    """Status a ticket returns to when the customer answers: the seeded
    "In Progress", else the first active, non-paused status."""
    from psa.models import TicketStatus
    return (TicketStatus.objects.filter(slug='in-progress').first()
            or TicketStatus.objects.filter(is_terminal=False, pauses_sla=False)
            .order_by('sort_order', 'id').first())


def record_customer_reply(ticket, *, via: str = 'portal', when=None):
    """Stamp a customer reply on ``ticket`` and, if it was waiting on the
    customer, put it back in the technician's court.

    Shared by the portal reply view and the inbound email poller. Returns the
    new status when it changed, else None.
    """
    from django.utils import timezone
    when = when or timezone.now()
    ticket.last_client_response_at = when
    fields = ['last_client_response_at', 'updated_at']
    moved_to = None
    if (ticket.closed_at is None and ticket.status_id
            and not ticket.status.is_terminal
            and is_customer_wait_status(ticket.status)):
        target = resume_status()
        if target is not None and target.pk != ticket.status_id:
            ticket.status = target
            fields.append('status')
            moved_to = target
    ticket.save(update_fields=fields)
    if moved_to is not None:
        from psa.models import TicketComment
        # Internal system note so the tech can see why the status moved.
        TicketComment.objects.create(
            ticket=ticket, is_internal=True, is_system=True, source=via,
            body=f'Customer replied via {via}; status moved to {moved_to.name}.',
        )
    return moved_to
