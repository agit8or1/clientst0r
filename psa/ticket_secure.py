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
