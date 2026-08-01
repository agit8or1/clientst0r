"""
Outbound email helper — Phase 10.4.

When staff replies to a customer via a ticket, the outbound email must
carry RFC 5322 threading headers (``In-Reply-To`` + ``References``) so
the customer's mail client groups the reply with the original thread.
Without these headers each staff reply lands as an isolated message and
the customer sees a fragmented conversation.

This module provides a single entry point — ``send_threaded_reply`` —
that builds the message, sends it via Django's email backend, and
persists an ``EmailMessage(direction='out')`` row so the next inbound
reply can chain back via the existing 10.1 threading logic.

Callers (Phase 11 notification hooks, manual "Send as email" buttons,
mgmt commands) all funnel through here so threading is consistent.
"""
from __future__ import annotations

import email.utils
import logging
from typing import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from psa.models import EmailMessage, Ticket, TicketComment

logger = logging.getLogger('psa.email_outbound')


def _make_message_id(ticket: Ticket) -> str:
    """
    Generate an RFC 5322 Message-ID for the outbound email. Uses Django's
    ``email.utils.make_msgid`` with a domain hint that ties the ID back
    to the ticket so future replies are diagnosable from the header alone.
    """
    domain = getattr(settings, 'PSA_OUTBOUND_MESSAGE_ID_DOMAIN', None)
    if not domain:
        domain = 'clientst0r.local'
    return email.utils.make_msgid(idstring=f'psa-{ticket.ticket_number}', domain=domain)


def send_threaded_reply(
    *,
    ticket: Ticket,
    comment: TicketComment | None,
    body_text: str,
    body_html: str = '',
    subject: str | None = None,
    to_emails: Iterable[str] | None = None,
    from_email: str | None = None,
    cc_emails: Iterable[str] | None = None,
    bcc_emails: Iterable[str] | None = None,
    reply_to: Iterable[str] | None = None,
    attachments: Iterable | None = None,
) -> EmailMessage:
    """
    Send an outbound reply on ``ticket`` and persist the
    ``EmailMessage(direction='out')`` row. Returns the persisted row.

    Threading behavior:
      - The outbound message gets a fresh, server-generated Message-ID.
      - ``In-Reply-To`` is set to ``ticket.last_inbound_message_id`` when
        the ticket has captured an inbound (10.1+).
      - ``References`` is set to the same value (single-element chain is
        the spec-compliant minimum and matches what most clients write).

    The customer's reply to *this* outbound will set ``In-Reply-To`` to
    our generated Message-ID, which the 10.1 ``_thread_target`` lookup
    will resolve back to the same ticket — closing the round-trip.

    Args:
        ticket:        The ticket the reply attaches to.
        comment:       Optional TicketComment (for cross-linking; not
                       required — callers may send mail without an
                       associated comment).
        body_text:     Plain-text body. Required.
        body_html:     Optional HTML alternative. If provided, the
                       outbound message is sent as multipart/alternative.
        subject:       Override subject. Defaults to
                       ``Re: [<ticket_number>] <ticket.subject>``.
        to_emails:     Recipients. Falls back to the ticket's
                       ``requester_email`` when not provided.
        from_email:    Sender. Defaults to
                       ``settings.DEFAULT_FROM_EMAIL``.

    Returns:
        The persisted ``EmailMessage`` row (direction='out').
    """
    if not body_text:
        raise ValueError('body_text is required')

    recipients = list(to_emails) if to_emails else (
        [ticket.requester_email] if ticket.requester_email else []
    )
    if not recipients:
        raise ValueError(
            f'No recipients for ticket {ticket.ticket_number}; '
            'pass to_emails= or set ticket.requester_email.'
        )

    sender = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@localhost')

    # Build subject — wrap the ticket number in [...] so the existing
    # subject-regex fallback in psa_poll_email correlates legacy clients
    # that don't preserve threading headers.
    subj = subject or f'Re: [{ticket.ticket_number}] {ticket.subject}'

    message_id = _make_message_id(ticket)
    in_reply_to = (ticket.last_inbound_message_id or '').strip()

    extra_headers: dict[str, str] = {'Message-ID': message_id}
    if in_reply_to:
        extra_headers['In-Reply-To'] = in_reply_to
        extra_headers['References'] = in_reply_to

    cc_list = [c for c in (cc_emails or []) if c]
    bcc_list = [b for b in (bcc_emails or []) if b]
    reply_to_list = [r for r in (reply_to or []) if r]

    msg = EmailMultiAlternatives(
        subject=subj[:998],
        body=body_text,
        from_email=sender,
        to=recipients,
        cc=cc_list or None,
        bcc=bcc_list or None,
        reply_to=reply_to_list or None,
        headers=extra_headers,
    )
    if body_html:
        msg.attach_alternative(body_html, 'text/html')
    # Attachments are optional TicketAttachment rows (parity with the Graph path).
    for att in (attachments or []):
        try:
            att.file.open('rb')
            msg.attach(att.filename or 'attachment', att.file.read(),
                       att.content_type or 'application/octet-stream')
        finally:
            try:
                att.file.close()
            except Exception:
                pass

    msg.send(fail_silently=False)

    em = EmailMessage.objects.create(
        organization=ticket.organization,
        ticket=ticket,
        ingestion_config=None,
        direction='out',
        transport='smtp',
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=in_reply_to,
        from_email=sender[:320],
        to_emails=list(recipients)[:50],
        subject=subj[:998],
        headers_raw='\n'.join(f'{k}: {v}' for k, v in extra_headers.items())[:16000],
        body_text=body_text[:50000],
        body_html=body_html[:200000] if body_html else '',
    )
    logger.info(
        'sent outbound reply ticket=%s message_id=%s in_reply_to=%r recipients=%r',
        ticket.ticket_number, message_id, in_reply_to, recipients,
    )
    return em


def resolve_ticket_email_config(ticket: Ticket):
    """Pick the ``EmailIngestionConfig`` a reply on ``ticket`` should send through.

    Preference order:
      1. The config that ingested the ticket's most recent inbound message —
         a reply goes back out of the same mailbox it arrived on, which is
         what keeps the M365 conversation (and Sent Items copy) coherent.
      2. The organization's only active config, when there is exactly one.
         Ambiguous (2+) is not guessed at.

    Returns ``None`` when neither applies. ``None`` is a valid answer, not an
    error — ``send_ticket_reply`` treats it as "use the plain SMTP backend".
    """
    from psa.models import EmailIngestionConfig

    inbound = (
        ticket.email_messages
        .filter(direction='in', ingestion_config__isnull=False)
        .select_related('ingestion_config')
        .order_by('-received_at')
        .first()
    )
    if inbound and inbound.ingestion_config and inbound.ingestion_config.is_active:
        return inbound.ingestion_config

    active = list(
        EmailIngestionConfig.objects
        .filter(organization_id=ticket.organization_id, is_active=True)[:2]
    )
    return active[0] if len(active) == 1 else None


def send_ticket_reply(
    *,
    ticket: Ticket,
    config=None,
    comment: TicketComment | None = None,
    body_text: str,
    body_html: str = '',
    subject: str | None = None,
    to_emails: Iterable[str] | None = None,
    cc_emails: Iterable[str] | None = None,
    bcc_emails: Iterable[str] | None = None,
    reply_to: Iterable[str] | None = None,
    attachments: Iterable | None = None,
    reply_all: bool = False,
    created_by=None,
):
    """Route a ticket reply to the transport configured on ``config``.

    Returns an ``EmailMessage`` (SMTP) or an ``EmailOutboundJob`` (Graph). When
    ``config`` is None or its ``outbound_method`` is 'smtp', this is exactly the
    existing SMTP behavior. Graph is used only when explicitly configured.
    """
    from psa.models import EmailIngestionConfig

    use_graph = bool(
        config is not None
        and getattr(config, 'outbound_method', EmailIngestionConfig.OUTBOUND_SMTP)
        == EmailIngestionConfig.OUTBOUND_GRAPH
    )

    if use_graph:
        conn = config.m365_connection
        graph_available = bool(conn and conn.is_active and config.graph_mailbox)
        if not graph_available:
            # Fallback may only happen BEFORE any Graph submission, and only when
            # explicitly enabled — never after an uncertain Graph submission.
            if config.smtp_fallback_enabled:
                logger.warning(
                    'graph outbound unavailable for config=%s; SMTP fallback', config.pk)
                return send_threaded_reply(
                    ticket=ticket, comment=comment, body_text=body_text,
                    body_html=body_html, subject=subject, to_emails=to_emails,
                    cc_emails=cc_emails, bcc_emails=bcc_emails, reply_to=reply_to,
                    attachments=attachments)
            raise ValueError(
                'Graph outbound is selected but its M365 connection/mailbox is '
                'unavailable, and no SMTP fallback is configured.')
        return _send_via_graph(
            ticket=ticket, config=config, body_text=body_text, body_html=body_html,
            subject=subject, to_emails=to_emails, cc_emails=cc_emails,
            bcc_emails=bcc_emails, reply_to=reply_to, attachments=attachments,
            reply_all=reply_all, created_by=created_by)

    return send_threaded_reply(
        ticket=ticket, comment=comment, body_text=body_text, body_html=body_html,
        subject=subject, to_emails=to_emails, cc_emails=cc_emails,
        bcc_emails=bcc_emails, reply_to=reply_to, attachments=attachments)


def _send_via_graph(*, ticket, config, body_text, body_html, subject, to_emails,
                    cc_emails, bcc_emails, reply_to, attachments, reply_all, created_by):
    from psa.graph_outbound import (
        enqueue_graph_reply, process_job, validate_recipients, _attachment_limit_error)
    from psa.models import EmailOutboundJob

    recipients = list(to_emails) if to_emails else (
        [ticket.requester_email] if ticket and ticket.requester_email else [])
    valid, invalid = validate_recipients(recipients)
    if invalid:
        raise ValueError(f'Invalid recipient(s): {", ".join(invalid)}')
    if not valid:
        raise ValueError('No valid recipients for the reply.')
    cc_valid, cc_invalid = validate_recipients(cc_emails or [])
    bcc_valid, bcc_invalid = validate_recipients(bcc_emails or [])
    if cc_invalid or bcc_invalid:
        raise ValueError(f'Invalid Cc/Bcc address(es): {", ".join(cc_invalid + bcc_invalid)}')

    att_list = list(attachments or [])
    if att_list:
        err = _attachment_limit_error(att_list)
        if err:
            raise ValueError(err)
    attachment_ids = [a.id for a in att_list]

    # Reply on the M365 conversation when we stored the ingested message's
    # immutable id; otherwise send a fresh message.
    inbound = None
    if ticket is not None:
        inbound = (ticket.email_messages.filter(direction='in')
                   .exclude(graph_message_id='').order_by('-received_at').first())
    if inbound and inbound.graph_message_id:
        operation = EmailOutboundJob.OP_REPLY_ALL if reply_all else EmailOutboundJob.OP_REPLY
        graph_message_id = inbound.graph_message_id
    else:
        operation = EmailOutboundJob.OP_SEND
        graph_message_id = ''

    subj = subject or f'Re: [{ticket.ticket_number}] {ticket.subject}'
    job = enqueue_graph_reply(
        organization=ticket.organization, ticket=ticket, config=config,
        operation=operation, mailbox=config.graph_mailbox,
        graph_message_id=graph_message_id, to_recipients=valid,
        cc_recipients=cc_valid, bcc_recipients=bcc_valid,
        reply_to=[r for r in (reply_to or []) if r], subject=subj,
        body_text=body_text, body_html=body_html, attachment_ids=attachment_ids,
        created_by=created_by)

    # Best-effort inline send. If it stays queued (transient failure), the
    # psa_send_outbound cron retries; the claim-lock prevents a double send.
    process_job(job)
    job.refresh_from_db()
    return job
