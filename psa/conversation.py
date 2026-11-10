"""
Ticket conversation: who said what, and what a viewer may see of it.

One place decides the sender role of every ticket message so the technician
page (templates/psa/ticket_detail.html) and the customer portal
(templates/portal/ticket_detail.html) agree on it.

Role is derived from provenance, never from an email address alone:

  * ``is_system`` rows are system events (status changes, assignment, ...).
  * A row with an ``author`` was posted by a signed-in user, which is trusted
    authorship:
      - MSP staff (psa.visibility.is_msp_staff) -> technician, except on the
        portal surface (source='portal'), where a staff account acting through
        a customer membership is shown as the customer it acted as;
      - a non-staff user with an active Membership in the ticket's customer
        -> customer;
      - any other user -> unclassified (neutral).
  * A row without an author:
      - source='portal' -> customer (the portal only accepts customer posts;
        the author was deleted later);
      - source='email' (inbound mail): customer when the From address is the
        ticket's requester, the ticket contact, or an active non-staff member
        of the ticket's customer. A From address that belongs to a staff user
        is NOT promoted to technician (inbound mail is unauthenticated), and an
        unknown address is unclassified;
      - anything else (partner sync, deleted author, legacy rows) ->
        unclassified.

Visibility (internal vs public) is a separate axis: ``build_conversation``
drops internal rows, and attachments of internal rows, unless the caller
explicitly asks for staff content, and only quotes a reply's parent when the
parent itself is part of what the viewer can see.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROLE_CUSTOMER = 'customer'
ROLE_TECHNICIAN = 'technician'
ROLE_SYSTEM = 'system'
ROLE_UNKNOWN = 'unknown'

ROLE_LABELS = {
    ROLE_CUSTOMER: 'Customer',
    ROLE_TECHNICIAN: 'Technician',
    ROLE_SYSTEM: 'System',
    ROLE_UNKNOWN: '',
}

# Provenance shown next to the sender ("via email"); purely informational.
SOURCE_LABELS = {
    'email': 'email',
    'portal': 'portal',
    'api': 'mobile app',
    'voice': 'voice',
    'partner': 'partner',
}

REPLY_EXCERPT_CHARS = 160


@dataclass
class Sender:
    role: str
    name: str
    via: str = ''

    @property
    def label(self) -> str:
        return ROLE_LABELS.get(self.role, '')


@dataclass
class ConversationEntry:
    """One rendered item of the conversation."""
    kind: str                      # 'message' | 'note' | 'event'
    sender: Sender
    body: str
    created_at: object
    id: int | None = None          # TicketComment pk; None for the opening request
    is_internal: bool = False
    is_opening: bool = False
    reply_to: dict | None = None   # {'id', 'name', 'excerpt', 'is_internal'}
    attachments: list = field(default_factory=list)
    cc: list = field(default_factory=list)       # addresses an e-mailed reply was copied to
    secure: dict | None = None     # psa.ticket_secure.secure_status — never the content

    @property
    def dom_id(self) -> str:
        return f'comment-{self.id}' if self.id else 'ticket-request'

    @property
    def role(self) -> str:
        return self.sender.role


class _Directory:
    """Per-ticket lookups, computed once so classifying N comments costs a
    fixed number of queries."""

    def __init__(self, ticket):
        self.ticket = ticket
        self._member_ids = None
        self._customer_emails = None

    def member_user_ids(self) -> set:
        if self._member_ids is None:
            from accounts.models import Membership
            self._member_ids = set(
                Membership.objects.filter(
                    organization_id=self.ticket.organization_id, is_active=True,
                ).values_list('user_id', flat=True)
            )
        return self._member_ids

    def customer_emails(self) -> set:
        """Addresses known to belong to this ticket's customer side."""
        if self._customer_emails is None:
            from accounts.models import Membership
            from .visibility import is_msp_staff
            emails = set()
            t = self.ticket
            if t.requester_email:
                emails.add(t.requester_email.strip().lower())
            contact = getattr(t, 'contact', None) if t.contact_id else None
            if contact is not None and getattr(contact, 'email', ''):
                emails.add(contact.email.strip().lower())
            members = (Membership.objects
                       .filter(organization_id=t.organization_id, is_active=True)
                       .exclude(user__email='')
                       .select_related('user', 'user__profile'))
            for m in members:
                if not is_msp_staff(m.user):
                    emails.add(m.user.email.strip().lower())
            self._customer_emails = emails
        return self._customer_emails


def _user_name(user) -> str:
    return (user.get_full_name() or user.username) if user else ''


def _classify_user(user, directory, *, via_portal=False) -> str:
    from .visibility import is_msp_staff
    if not via_portal and is_msp_staff(user):
        return ROLE_TECHNICIAN
    if user.pk in directory.member_user_ids():
        return ROLE_CUSTOMER
    return ROLE_UNKNOWN


def classify_sender(comment, ticket=None, *, directory=None) -> Sender:
    """Sender role + display name for one TicketComment."""
    ticket = ticket or comment.ticket
    directory = directory or _Directory(ticket)
    source = (comment.source or '').lower()
    via = SOURCE_LABELS.get(source, '')
    author = comment.author if comment.author_id else None

    if comment.is_system:
        return Sender(ROLE_SYSTEM, _user_name(author) or 'System')

    name = (_user_name(author) or comment.author_name or comment.author_email
            or 'Unknown sender')

    if author is not None:
        return Sender(_classify_user(author, directory, via_portal=source == 'portal'),
                      name, via)

    if source == 'portal':
        return Sender(ROLE_CUSTOMER, name, via)
    if source == 'email':
        addr = (comment.author_email or '').strip().lower()
        if addr and addr in directory.customer_emails():
            return Sender(ROLE_CUSTOMER, name, via)
        return Sender(ROLE_UNKNOWN, name, via)
    return Sender(ROLE_UNKNOWN, name, via)


def classify_opening(ticket, *, directory=None) -> Sender:
    """Sender of the ticket's original request (its description)."""
    directory = directory or _Directory(ticket)
    source = (ticket.source or '').lower()
    via = SOURCE_LABELS.get(source, '')
    creator = ticket.created_by if ticket.created_by_id else None
    contact = ticket.contact if ticket.contact_id else None
    name = (_user_name(creator) or ticket.requester_name
            or (str(contact) if contact else '') or ticket.requester_email
            or 'Unknown sender')
    if creator is not None:
        return Sender(_classify_user(creator, directory, via_portal=source == 'portal'),
                      name, via)
    if source == 'portal':
        return Sender(ROLE_CUSTOMER, name, via)
    if source == 'email':
        # The poller files a new ticket with the From address as requester;
        # that requester (or the customer contact on the ticket) is the
        # customer by definition. A ticket with neither stays neutral.
        if ticket.requester_email or contact is not None:
            return Sender(ROLE_CUSTOMER, name, via)
    return Sender(ROLE_UNKNOWN, name, via)


def secure_status(note):
    from .ticket_secure import secure_status as _status
    return _status(note)


def _excerpt(text: str) -> str:
    text = ' '.join((text or '').split())
    if len(text) > REPLY_EXCERPT_CHARS:
        text = text[:REPLY_EXCERPT_CHARS - 1].rstrip() + '…'
    return text


def build_conversation(ticket, comments, *, attachments=(), include_internal=False,
                       include_opening=True):
    """Ordered ConversationEntry list for a ticket page.

    ``comments`` / ``attachments`` should already be narrowed to what the
    viewer may see; this function enforces the internal rule again so a
    caller can't leak staff content by passing an unfiltered queryset:
    with ``include_internal=False`` internal comments, internal attachments
    and attachments of internal comments are dropped, and a reply's parent is
    quoted only when the parent is itself in the rendered set.
    """
    directory = _Directory(ticket)
    rows = [c for c in comments if include_internal or not c.is_internal]
    rows.sort(key=lambda c: (c.created_at, c.pk))
    visible = {c.pk: c for c in rows}

    files_by_comment = {}
    for a in attachments:
        if not include_internal:
            if a.is_internal:
                continue
            if a.comment_id and a.comment_id not in visible:
                continue
        if a.comment_id and a.comment_id in visible:
            files_by_comment.setdefault(a.comment_id, []).append(a)

    entries = []
    if include_opening and (ticket.description or '').strip():
        entries.append(ConversationEntry(
            kind='message', sender=classify_opening(ticket, directory=directory),
            body=ticket.description, created_at=ticket.created_at, is_opening=True,
        ))

    senders = {}
    for c in rows:
        sender = classify_sender(c, ticket, directory=directory)
        senders[c.pk] = sender
        reply_to = None
        parent = visible.get(c.parent_comment_id) if c.parent_comment_id else None
        if parent is not None and not parent.is_system:
            p_sender = senders.get(parent.pk) or classify_sender(
                parent, ticket, directory=directory)
            reply_to = {
                'id': parent.pk,
                'name': p_sender.name,
                'excerpt': _excerpt(parent.body),
                'is_internal': parent.is_internal,
            }
        if c.is_system:
            kind = 'event'
        elif c.is_internal:
            kind = 'note'
        else:
            kind = 'message'
        entries.append(ConversationEntry(
            kind=kind, sender=sender, body=c.body, created_at=c.created_at,
            id=c.pk, is_internal=c.is_internal, reply_to=reply_to,
            attachments=sorted(files_by_comment.get(c.pk, []),
                               key=lambda a: (a.created_at, a.pk)),
            cc=list(c.cc_emails or []),
            secure=secure_status(c.secure_note) if c.secure_note_id else None,
        ))
    return entries


def customer_visible_attachments(ticket):
    """Attachments a customer may see, regardless of who is asking (the
    portal applies the customer rule even to a staff account with a portal
    membership)."""
    return (ticket.attachments.filter(is_internal=False)
            .exclude(comment__is_internal=True))
