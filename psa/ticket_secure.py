"""Copying people on ticket replies, and sending an encrypted one-time
message with a reply (v3.17.654).

A secure message is a link-only SecureNote: the text is sealed at rest, the
link token is generated once and goes only into the e-mail to the requester
(only its hash is stored), and the ticket shows that a secure message was
sent — never its content. The link opens behind a "Reveal" button so mail
scanners that pre-fetch links don't use up a one-time message.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

MAX_CC = 20
SECURE_EXPIRY_CHOICES = (24, 72, 168)  # hours
DEFAULT_SECURE_EXPIRY = 72
MAX_SECURE_LENGTH = 10000


def parse_addresses(raw, limit=MAX_CC):
    """(valid, invalid) from a comma / semicolon / whitespace separated list.
    Valid addresses are lower-cased and de-duplicated, in order."""
    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        parts = re.split(r'[\s,;]+', raw or '')
    valid, invalid, seen = [], [], set()
    for part in parts:
        addr = part.strip().strip('<>').lower()
        if not addr:
            continue
        try:
            validate_email(addr)
        except ValidationError:
            invalid.append(part.strip())
            continue
        if addr not in seen:
            seen.add(addr)
            valid.append(addr)
    if len(valid) > limit:
        invalid.append(f'more than {limit} addresses')
        valid = valid[:limit]
    return valid, invalid


def merge_cc(ticket, addresses, exclude=()):
    """Add `addresses` to the ticket's Cc list (not the requester, not any
    address in `exclude`). Returns the addresses actually added."""
    skip = {a.lower() for a in exclude if a} | {(ticket.requester_email or '').lower()}
    current = list(ticket.cc_emails or [])
    have = {a.lower() for a in current}
    added = [a for a in addresses if a.lower() not in have and a.lower() not in skip]
    room = MAX_CC - len(current)
    added = added[:max(room, 0)]
    if added:
        ticket.cc_emails = current + added
        ticket.save(update_fields=['cc_emails'])
    return added


def create_secure_message(*, ticket, sender, text, expires_hours=DEFAULT_SECURE_EXPIRY, read_once=True):
    """A sealed, link-only SecureNote for this ticket. The returned note
    carries the raw link token (`_raw_access_token`) until it is discarded."""
    from core.models import SecureNote
    if expires_hours not in SECURE_EXPIRY_CHOICES:
        expires_hours = DEFAULT_SECURE_EXPIRY
    note = SecureNote(
        sender=sender, organization=ticket.organization,
        title=f'Secure message for {ticket.ticket_number}', label=ticket.ticket_number,
        link_only=True, read_once=read_once,
        expires_at=timezone.now() + timedelta(hours=expires_hours),
    )
    note.set_content(text)
    note.generate_access_token()
    note.save()
    return note


def secure_status(note):
    """What the ticket shows about a secure message — never its content."""
    if note is None:
        return None
    opened = note.read_count > 0
    if opened:
        state = 'opened'
    elif note.is_deleted:
        state = 'withdrawn'
    elif note.is_expired:
        state = 'expired'
    else:
        state = 'waiting'
    return {'state': state, 'opened': opened, 'expires_at': note.expires_at,
            'read_once': note.read_once, 'note_id': note.pk}


_LINK_RE = re.compile(r'https?://[^\s]*/core/secret/[A-Za-z0-9_-]+/?|/core/secret/[A-Za-z0-9_-]+/?')
SCRUBBED = '[secure message link — sent to the recipient only]'


def scrub_secret_links(text):
    """Remove secure-message links from a stored copy of an e-mail, so the
    ticket's e-mail log can't be used to open (and use up) the message."""
    return _LINK_RE.sub(SCRUBBED, text or '')


def scrub_stored_copies(*objs):
    """Scrub `body_text` on stored outbound e-mail rows (EmailMessage, EmailOutboundJob)."""
    for obj in objs:
        if obj is None or not getattr(obj, 'body_text', ''):
            continue
        cleaned = scrub_secret_links(obj.body_text)
        if cleaned != obj.body_text:
            obj.body_text = cleaned
            obj.save(update_fields=['body_text'])


# ---------------------------------------------------------------------------
# Phase 12: two-way secure messages — the requester's secure replies.
# ---------------------------------------------------------------------------

SECURE_REPLY_RETENTION_HOURS = 168   # the longest one-way expiry (7 days)
REPLY_TOKEN_MAX_AGE = 24 * 3600      # the reply form is valid for a day after opening
MAX_REPLIES_PER_MESSAGE = 5
REPLY_TOKEN_SALT = 'psa.ticket_secure.reply'


def _note_stamp(note):
    return int(note.link_issued_at.timestamp()) if note.link_issued_at else 0


def comment_for_note(note):
    """The ticket reply that carried this secure message, or None."""
    if note is None or not note.pk:
        return None
    return note.ticket_comments.select_related('ticket', 'ticket__organization').first()


def issue_reply_token(note):
    """A signed token that lets whoever just opened `note` answer it.

    Handed out only on the opened-message page. Bound to the note's current
    link (regenerating the link voids it) and valid for REPLY_TOKEN_MAX_AGE."""
    from django.core import signing
    return signing.dumps({'n': note.pk, 'i': _note_stamp(note)}, salt=REPLY_TOKEN_SALT, compress=True)


def note_for_reply_token(token):
    """The SecureNote a reply token was issued for, or None (bad, expired, revoked)."""
    from django.core import signing
    from core.models import SecureNote
    try:
        data = signing.loads(token or '', salt=REPLY_TOKEN_SALT, max_age=REPLY_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    note = SecureNote.objects.filter(pk=data.get('n'), link_only=True).first()
    if note is None or _note_stamp(note) != data.get('i'):
        return None
    return note


def replies_left(note):
    return max(0, MAX_REPLIES_PER_MESSAGE - note.ticket_replies.count())


def reply_context_for_note(note):
    """Template context for the reply form on an opened secure message, or
    None when the message isn't a ticket message or can take no more replies."""
    comment = comment_for_note(note)
    if comment is None or not replies_left(note):
        return None
    return {'token': issue_reply_token(note), 'ticket_number': comment.ticket.ticket_number,
            'max_length': MAX_SECURE_LENGTH, 'retention_days': SECURE_REPLY_RETENTION_HOURS // 24}


def create_secure_reply(*, ticket, text, via, author=None, author_email='', in_reply_to=None,
                        ip_address=None, path=''):
    """Seal and store a requester's secure reply, note it on the ticket
    (without its content), audit it and tell the technicians."""
    from audit.models import AuditLog
    from .models import TicketComment, TicketSecureReply
    from .my_work import record_customer_reply
    user = author if (author is not None and author.is_authenticated) else None
    reply = TicketSecureReply(
        ticket=ticket, organization=ticket.organization, in_reply_to=in_reply_to,
        author=user, author_email=(author_email or '')[:254], via=via,
        expires_at=timezone.now() + timedelta(hours=SECURE_REPLY_RETENTION_HOURS))
    reply.set_body(text)
    reply.save()

    who = author_email or (user.get_username() if user else 'the requester')
    how = 'the secure message link' if via == TicketSecureReply.VIA_LINK else 'the customer portal'
    TicketComment.objects.create(
        ticket=ticket, author=user, is_internal=True, is_system=True,
        source='portal' if via == TicketSecureReply.VIA_PORTAL else 'secure',
        author_email=(author_email or '')[:254],
        body=(f'Secure reply received from {who} via {how}. The text is encrypted and is shown only '
              f'from Secure replies on this ticket (kept {SECURE_REPLY_RETENTION_HOURS // 24} days).'))
    record_customer_reply(ticket, via='portal' if via == TicketSecureReply.VIA_PORTAL else 'secure')

    AuditLog.log(
        user=user, action='create',
        organization=ticket.organization, object_type='psa.TicketSecureReply', object_id=reply.pk,
        object_repr=f'secure reply on {ticket.ticket_number}',
        description=f'Secure reply received on {ticket.ticket_number} via {via}',
        ip_address=ip_address, path=path,
        extra_data={'event': 'ticket_secure_reply', 'via': via, 'length': len(text),
                    'in_reply_to': in_reply_to.pk if in_reply_to else None,
                    'expires_at': reply.expires_at.isoformat()},
    )
    notify_secure_reply(ticket, reply)
    return reply


def notify_secure_reply(ticket, reply):
    """E-mail the assignee and watchers that a secure reply arrived. Never
    the content — only that it exists and where to read it. Best-effort."""
    import logging
    from django.conf import settings as dj
    from django.core.mail import send_mail
    from .models import TicketWatcher
    from .notifications import _ticket_url
    users = {}
    if ticket.assigned_to_id and ticket.assigned_to.email:
        users[ticket.assigned_to_id] = ticket.assigned_to
    for w in TicketWatcher.objects.filter(ticket=ticket).select_related('user'):
        if w.user.email:
            users[w.user_id] = w.user
    if reply.author_id:
        users.pop(reply.author_id, None)
    sent = 0
    for user in users.values():
        try:
            send_mail(
                subject=f'{ticket.ticket_number}: secure reply received',
                message=(f'A secure reply was received on {ticket.ticket_number} ({ticket.subject}).\n\n'
                         f'Its content is encrypted and is not included in e-mail. Open the ticket and use '
                         f'Secure replies to read it:\n{_ticket_url(ticket)}\n'),
                from_email=getattr(dj, 'DEFAULT_FROM_EMAIL', None) or 'noreply@localhost',
                recipient_list=[user.email], fail_silently=False)
            sent += 1
        except Exception as exc:
            logging.getLogger('psa.notifications').warning('secure reply notice failed: %s', exc)
    return sent


def thread_for_ticket(ticket):
    """The ticket's secure thread, oldest first, for the staff panel:
    staff messages (status only) and requester replies (metadata only)."""
    from .models import TicketComment
    items = []
    for c in (TicketComment.objects.filter(ticket=ticket, secure_note__isnull=False)
              .select_related('secure_note', 'author')):
        items.append({'kind': 'message', 'at': c.created_at, 'who': c.author,
                      'status': secure_status(c.secure_note), 'comment': c})
    for r in ticket.secure_replies.select_related('author', 'first_viewed_by'):
        items.append({'kind': 'reply', 'at': r.created_at, 'reply': r})
    items.sort(key=lambda i: i['at'])
    return items


def purge_expired_replies(now=None):
    """Erase the sealed text of secure replies past their retention."""
    from .models import TicketSecureReply
    now = now or timezone.now()
    return (TicketSecureReply.objects.filter(expires_at__lte=now, purged_at__isnull=True)
            .update(body='', purged_at=now))
