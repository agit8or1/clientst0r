"""
Microsoft Graph outbound transport for PSA (issue #142, outbound).

Optional outbound transport that sends staff replies through Microsoft Graph
(sendMail / reply / replyAll) instead of SMTP, on the same M365 connection +
mailbox used for inbound. SMTP outbound (``psa.email_outbound``) is untouched.

Design highlights:
  * Graph send actions return HTTP 202 Accepted — accepted for processing, NOT a
    delivery confirmation. Every Graph send goes through an ``EmailOutboundJob``.
  * Idempotent + locked: a job is claimed with an atomic status transition
    (queued -> sending) so it can never be submitted twice, even if the inline
    attempt and the ``psa_send_outbound`` cron race.
  * Transient failures (429 / 5xx / connect timeout) retry with backoff and
    honor Retry-After. Auth / validation / malformed-recipient errors fail fast.
  * A read timeout AFTER submission is marked 'uncertain' and never auto-resent
    (the message may already be on its way) — it needs manual review.
  * The sender mailbox is always the server-configured one; callers cannot
    supply an arbitrary sender.
  * Message bodies are never written to the application log — only metadata.
"""
from __future__ import annotations

import base64
import logging
import re
import uuid

import requests
from django.conf import settings
from django.utils import timezone

from psa.email_parsing import sanitize_html
from psa.models import EmailOutboundJob, TicketAttachment

logger = logging.getLogger('psa.graph_outbound')

# Conservative RFC 5322-ish address check — enough to reject obvious garbage
# before we hand recipients to Graph.
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Statuses that mean "do not retry".
_PERMANENT_CATEGORIES = ('auth', 'validation', 'permanent', 'uncertain')


def validate_recipients(addresses) -> tuple[list, list]:
    """Split addresses into (valid, invalid), de-duplicated, order-preserving."""
    valid, invalid, seen = [], [], set()
    for a in addresses or []:
        a = (a or '').strip()
        if not a or a.lower() in seen:
            continue
        seen.add(a.lower())
        (valid if _EMAIL_RE.match(a) else invalid).append(a)
    return valid, invalid


def _attachment_limit_error(attachments) -> str | None:
    """Enforce the same size + MIME allowlist used for inbound attachments."""
    max_bytes = getattr(settings, 'PSA_EMAIL_ATTACHMENT_MAX_BYTES', 25 * 1024 * 1024)
    allow = [m.lower() for m in getattr(settings, 'PSA_EMAIL_ATTACHMENT_MIME_ALLOWLIST', [])]
    total = 0
    for att in attachments:
        total += att.size_bytes or 0
        if (att.size_bytes or 0) > max_bytes:
            return f'Attachment "{att.filename}" exceeds the {max_bytes} byte limit.'
        ct = (att.content_type or '').lower()
        if allow and ct and ct not in allow and not any(
                p.endswith('/*') and ct.startswith(p[:-1]) for p in allow):
            return f'Attachment "{att.filename}" type {ct} is not allowed.'
    if total > max_bytes:
        return f'Attachments total {total} bytes, over the {max_bytes} byte limit.'
    return None


def _graph_recipients(addresses) -> list:
    return [{'emailAddress': {'address': a}} for a in addresses]


def build_graph_message(job: EmailOutboundJob) -> dict:
    """Build the Graph ``message`` resource from a job. HTML is sanitized with
    the same allowlist as the rest of the app so user-supplied markup can't
    inject scripts / active content."""
    if job.body_html:
        clean_html = sanitize_html(job.body_html)
        body = {'contentType': 'HTML', 'content': clean_html}
    else:
        body = {'contentType': 'Text', 'content': job.body_text or ''}

    message: dict = {
        'subject': job.subject,
        'body': body,
        'toRecipients': _graph_recipients(job.to_recipients),
    }
    if job.cc_recipients:
        message['ccRecipients'] = _graph_recipients(job.cc_recipients)
    if job.bcc_recipients:
        message['bccRecipients'] = _graph_recipients(job.bcc_recipients)
    if job.reply_to:
        message['replyTo'] = _graph_recipients(job.reply_to)

    if job.attachment_ids:
        atts = []
        for att in TicketAttachment.objects.filter(id__in=job.attachment_ids):
            try:
                att.file.open('rb')
                data = att.file.read()
            finally:
                try:
                    att.file.close()
                except Exception:
                    pass
            atts.append({
                '@odata.type': '#microsoft.graph.fileAttachment',
                'name': att.filename or 'attachment',
                'contentType': att.content_type or 'application/octet-stream',
                'contentBytes': base64.b64encode(data).decode('ascii'),
            })
        if atts:
            message['attachments'] = atts
    return message


def classify_error(status: int, blob: str = '') -> str:
    """Map an HTTP status (+ optional error text) to a retry category."""
    if status in (429, 500, 502, 503, 504):
        return 'transient'
    if status in (401, 403):
        return 'auth'
    if status == 400:
        return 'validation'
    if 400 <= status < 500:
        return 'permanent'
    if status >= 500:
        return 'transient'
    return 'permanent'


def _extract_error(resp) -> tuple[str, str]:
    """Return (error_message, request_id) from a Graph error response, never
    exposing tokens/headers beyond the Microsoft request id."""
    request_id = resp.headers.get('request-id') or resp.headers.get('client-request-id') or ''
    msg = ''
    try:
        err = (resp.json() or {}).get('error', {})
        msg = err.get('message') or ''
        code = err.get('code') or ''
        if code:
            msg = f'{code}: {msg}'
    except Exception:
        msg = (resp.text or '')[:300]
    return msg, request_id


def _backoff_seconds(job: EmailOutboundJob, retry_after: int | None) -> int:
    if retry_after and retry_after > 0:
        return min(retry_after, 3600)
    # Exponential: 60, 120, 240, ... capped at 15 min.
    return min(60 * (2 ** job.retry_count), 900)


def _schedule_retry(job: EmailOutboundJob, category: str, message: str,
                    request_id: str = '', retry_after: int | None = None):
    job.retry_count += 1
    job.error_category = category
    job.last_error = message[:2000]
    if request_id:
        job.ms_request_id = request_id[:200]
    if job.retry_count > job.max_retries:
        job.status = EmailOutboundJob.STATUS_FAILED
        job.last_error = (f'Gave up after {job.max_retries} retries. ' + message)[:2000]
        job.next_attempt_at = None
    else:
        job.status = EmailOutboundJob.STATUS_QUEUED
        job.next_attempt_at = timezone.now() + timezone.timedelta(
            seconds=_backoff_seconds(job, retry_after))
    job.locked_at = None
    job.save()


def _fail(job: EmailOutboundJob, category: str, message: str, request_id: str = ''):
    job.status = EmailOutboundJob.STATUS_FAILED
    job.error_category = category
    job.last_error = message[:2000]
    if request_id:
        job.ms_request_id = request_id[:200]
    job.next_attempt_at = None
    job.locked_at = None
    job.save()


def _provider_for(job: EmailOutboundJob):
    from integrations.providers.m365 import M365Provider
    conn = job.config.m365_connection if job.config else None
    if conn is None or not conn.is_active:
        return None
    creds = conn.get_credentials()
    return M365Provider(conn.tenant_id, creds.get('client_id', ''), creds.get('client_secret', ''))


def submit_job(job: EmailOutboundJob):
    """Submit a CLAIMED job (status must already be 'sending'). Mutates + saves
    the job to a terminal or retry state. Never raises."""
    provider = _provider_for(job)
    if provider is None:
        _fail(job, 'auth', 'Linked M365 connection is missing or inactive.')
        return

    try:
        message = build_graph_message(job)
    except Exception as exc:  # e.g. an attachment file went missing
        _fail(job, 'validation', f'Could not build message: {exc}')
        return

    try:
        if job.operation == EmailOutboundJob.OP_REPLY and job.graph_message_id:
            resp = provider.reply_message(job.mailbox, job.graph_message_id, message=message)
        elif job.operation == EmailOutboundJob.OP_REPLY_ALL and job.graph_message_id:
            resp = provider.reply_all_message(job.mailbox, job.graph_message_id, message=message)
        else:
            resp = provider.send_mail(job.mailbox, message, save_to_sent_items=job.save_to_sent_items)
    except requests.exceptions.ConnectTimeout:
        _schedule_retry(job, 'transient', 'Connection timeout before submission.')
        return
    except requests.exceptions.ReadTimeout:
        # Submitted but no response — outcome UNKNOWN. Never auto-resend.
        job.status = EmailOutboundJob.STATUS_UNCERTAIN
        job.error_category = 'uncertain'
        job.last_error = ('Read timeout after submission — outcome unknown. '
                          'Not auto-resent to avoid a duplicate; review manually.')
        job.next_attempt_at = None
        job.locked_at = None
        job.save()
        return
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        _schedule_retry(job, 'transient', 'Network error before submission.')
        return
    except Exception as exc:
        _fail(job, 'permanent', f'Unexpected send error: {exc}')
        return

    if resp.status_code in (200, 202):
        job.status = EmailOutboundJob.STATUS_SENT
        job.accepted_at = timezone.now()
        job.error_category = ''
        job.last_error = ''
        job.ms_request_id = (resp.headers.get('request-id')
                             or resp.headers.get('client-request-id') or '')[:200]
        job.next_attempt_at = None
        job.locked_at = None
        job.save()
        _finalize_sent_message(job)
        logger.info('graph outbound sent job=%s op=%s ticket=%s recipients=%d request_id=%s',
                    job.pk, job.operation, job.ticket_id, len(job.to_recipients), job.ms_request_id)
        return

    msg, request_id = _extract_error(resp)
    retry_after = None
    try:
        retry_after = int(resp.headers.get('Retry-After')) if resp.headers.get('Retry-After') else None
    except (TypeError, ValueError):
        retry_after = None
    category = classify_error(resp.status_code, msg)
    logger.warning('graph outbound error job=%s status=%s category=%s request_id=%s',
                   job.pk, resp.status_code, category, request_id)
    if category == 'transient':
        _schedule_retry(job, category, f'HTTP {resp.status_code}: {msg}', request_id, retry_after)
    else:
        detail = msg
        if resp.status_code == 403:
            detail = (f'{msg} — Mail.Send may not be granted, or the mailbox is outside the '
                      'app\'s Exchange RBAC scope.')
        _fail(job, category, f'HTTP {resp.status_code}: {detail}', request_id)


def _finalize_sent_message(job: EmailOutboundJob):
    """Persist an EmailMessage(direction='out', transport='graph') row on
    acceptance so the conversation view shows the reply."""
    from psa.models import EmailMessage
    import email.utils
    if job.email_message_id:
        return
    message_id = email.utils.make_msgid(
        idstring=f'psa-graph-{job.ticket.ticket_number if job.ticket else job.pk}',
        domain=getattr(settings, 'PSA_OUTBOUND_MESSAGE_ID_DOMAIN', None) or 'clientst0r.local')
    em = EmailMessage.objects.create(
        organization=job.organization,
        ticket=job.ticket,
        ingestion_config=job.config,
        direction='out',
        transport='graph',
        message_id=message_id,
        from_email=job.mailbox[:320],
        to_emails=list(job.to_recipients)[:50],
        subject=job.subject[:512],
        body_text=job.body_text[:50000],
        body_html=(job.body_html or '')[:200000],
    )
    job.email_message = em
    job.save(update_fields=['email_message'])


def process_job(job: EmailOutboundJob) -> bool:
    """Atomically CLAIM (queued -> sending) then submit. Returns True if this
    caller claimed and processed the job, False if another worker had it. This
    is the single lock point that prevents duplicate sends."""
    claimed = EmailOutboundJob.objects.filter(
        pk=job.pk, status=EmailOutboundJob.STATUS_QUEUED,
    ).update(status=EmailOutboundJob.STATUS_SENDING, locked_at=timezone.now())
    if not claimed:
        return False
    job.refresh_from_db()
    submit_job(job)
    return True


def enqueue_graph_reply(*, organization, ticket, config, operation, mailbox,
                        to_recipients, subject, body_text='', body_html='',
                        cc_recipients=None, bcc_recipients=None, reply_to=None,
                        graph_message_id='', attachment_ids=None,
                        save_to_sent_items=True, created_by=None,
                        idempotency_key=None) -> EmailOutboundJob:
    """Create (or return the existing) outbound job. Idempotent on
    idempotency_key so a retried enqueue never creates a duplicate send."""
    key = idempotency_key or uuid.uuid4().hex
    job, _created = EmailOutboundJob.objects.get_or_create(
        idempotency_key=key,
        defaults=dict(
            organization=organization,
            ticket=ticket,
            config=config,
            operation=operation,
            mailbox=mailbox,
            graph_message_id=graph_message_id or '',
            to_recipients=list(to_recipients or []),
            cc_recipients=list(cc_recipients or []),
            bcc_recipients=list(bcc_recipients or []),
            reply_to=list(reply_to or []),
            subject=(subject or '')[:998],
            body_text=body_text or '',
            body_html=body_html or '',
            attachment_ids=list(attachment_ids or []),
            save_to_sent_items=save_to_sent_items,
            created_by=created_by,
            status=EmailOutboundJob.STATUS_QUEUED,
        ),
    )
    return job
