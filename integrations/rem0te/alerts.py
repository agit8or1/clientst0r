"""
Rem0te monitoring alerts → ClientSt0r tickets (contract ticket-rmm-v1,
Rem0te ≥ 0.29).

Rem0te pushes `{alert_event, signature}` to ClientSt0r's events URL, signed
over `rem0te-alert-event-v1` (a different prefix from job events, so neither
can stand in for the other), sequenced per organization from 1 with no
gaps. A gap is recovered with GET /alerts/events?organization_id=…&after=n
(`poll()`, run by the scheduler).

  alert.raised    → exactly one ticket per (connection, alert id). The
                    unique Rem0teAlertTicket row is the guard: a pushed,
                    polled, retried or re-delivered raise after a restart
                    finds the row and opens nothing new. Then
                    POST /alerts/{id}/ticket links it back (retried until
                    linked; a different ticket already linked is a conflict,
                    shown, never overwritten).
  alert.updated   → the stored alert state only.
  alert.resolved  → the stored alert state only. No event closes, changes or
                    comments on a ticket: people do that.

The ticket is the connection's own organization's, staff-only, and its asset
is set only through the connection's verified device for Rem0te's immutable
computer id — never by computer name, so two customers with a FRONTDESK-01
never meet. Computer and site names are device- or customer-supplied text
and are stored and shown as text.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Tuple

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from . import client, identity, pairing, protocol, schema

logger = logging.getLogger('integrations.rem0te')

LINK_RETRY_MAX = timedelta(hours=1)
PRIORITY_FOR_SEVERITY = {'critical': 'P1', 'warning': 'P3', 'info': 'P4'}


class NotReady(Exception):
    """This instance cannot open the ticket yet (e.g. PSA not set up).
    Answered 503 so Rem0te retries; nothing about the event is recorded."""


def _text(v, n):
    return client.safe_text(v, n) if v is not None else ''


def apply_signed_alert_event(connection, signed: dict, via='push') -> Tuple[int, str]:
    from psa_ai.models import Rem0teAlertEvent
    errs = schema.errors('signed-alert-event', signed)
    if errs:
        return 400, 'invalid: ' + '; '.join(errs[:3])
    event, signature = signed['alert_event'], signed['signature']
    problem = protocol.verify_event_signature(event, signature, pairing.keyring(connection), alert=True)
    if problem:
        logger.warning('Rem0te alert event refused for connection %s: %s', connection.pk, problem)
        return 401, problem
    ident = identity.get(create=False)
    if event['peer_id'] != getattr(ident, 'peer_id', None) or event['organization_id'] != pairing.organization_id(connection):
        return 404, 'not for this peer or organization'
    alert = event['alert']
    # The dedup record and its effect commit together: an event that could
    # not be applied is not recorded, so Rem0te's retry (or the next poll)
    # applies it instead of being acknowledged as a duplicate.
    try:
        with transaction.atomic():
            try:
                with transaction.atomic():
                    Rem0teAlertEvent.objects.create(connection=connection, event_id=event['event_id'],
                                                    sequence=event['sequence'], event_type=event['type'],
                                                    alert_id=alert['alert_id'], body=event, received_via=via)
            except IntegrityError:
                return 200, 'duplicate'
            outcome, row, created = _apply(connection, event)
    except NotReady as e:
        logger.warning('Rem0te alert %s not applied yet for connection %s: %s', alert['alert_id'], connection.pk, e)
        return 503, str(e)
    if row is not None:
        if created:
            _audit(connection, row)
        link(row)
    return 200, outcome


def _apply(connection, event):
    """(outcome, row to link back or None, ticket newly opened)."""
    from psa_ai.models import Rem0teAlertTicket
    alert, seq = event['alert'], event['sequence']
    fields = {'state': alert['state'], 'severity': alert['severity'], 'kind': alert['kind'],
              'title': _text(alert['title'], 300), 'computer_name': _text(alert.get('computer_name'), 128),
              'rem0te_endpoint_id': _text(alert.get('rem0te_endpoint_id'), 64)}
    if event['type'] != 'alert.raised':
        row = Rem0teAlertTicket.objects.filter(connection=connection, alert_id=alert['alert_id']).first()
        if row is None:
            return 'recorded (no raise seen yet; recovered by polling)', None, False
        if seq > row.last_sequence:
            updates = dict(fields, last_sequence=seq)
            if alert['state'] == 'resolved':
                updates['resolved_at'] = timezone.now()
            Rem0teAlertTicket.objects.filter(pk=row.pk, last_sequence__lt=seq).update(**updates,
                                                                                     updated_at=timezone.now())
        return 'applied', None, False
    row, created = Rem0teAlertTicket.objects.get_or_create(
        connection=connection, alert_id=alert['alert_id'],
        defaults=dict(fields, organization_id=connection.organization_id, last_sequence=seq))
    if created:
        row.ticket = _open_ticket(connection, alert)
        row.save(update_fields=['ticket'])
    return ('ticket opened' if created else 'already has a ticket'), row, created


def _device_asset(connection, endpoint_id):
    if not endpoint_id:
        return None
    from integrations.models import RMMDevice
    d = (RMMDevice.objects.filter(connection=connection, external_id=endpoint_id,
                                  organization_id=connection.organization_id)
         .exclude(link_status__in=[RMMDevice.LINK_REVIEW, RMMDevice.LINK_UNLINKED]).first())
    asset = getattr(d, 'linked_asset', None) if d else None
    return asset if asset is not None and asset.organization_id == connection.organization_id else None


def _open_ticket(connection, alert):
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    queue = Queue.objects.filter(is_active=True).first() or Queue.objects.first()
    status = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first()
    if queue is None or status is None:
        raise NotReady('PSA has no ticket queue or status yet (run psa_seed_defaults).')
    priority = (TicketPriority.objects.filter(code=PRIORITY_FOR_SEVERITY.get(alert['severity'], 'P3')).first()
                or TicketPriority.objects.first())
    title = _text(alert['title'], 250)
    lines = [
        'Opened automatically for a Rem0te monitoring alert.',
        '',
        f'Alert: {title}',
        f'Kind: {alert["kind"]}   Severity: {alert["severity"]}   State: {alert["state"]}',
        f'Computer (as reported by the device): {_text(alert.get("computer_name"), 128) or "—"}',
        f'Site: {_text(alert.get("site_name"), 128) or "—"}',
        f'First seen: {alert["first_seen_at"]}   Occurrences: {alert["occurrences"]}',
        f'Rem0te alert id: {alert["alert_id"]}   Rem0te computer id: {alert.get("rem0te_endpoint_id") or "—"}',
        '',
        'Acknowledge or resolve the alert in Rem0te. Nothing in ClientSt0r acts on the computer.',
    ]
    return Ticket.objects.create(
        organization=connection.organization, subject=f'[Rem0te] {title}'[:300], description='\n'.join(lines),
        queue=queue, priority=priority, status=status,
        ticket_type=TicketType.objects.first(), source='rmm', visibility='staff', client_can_view=False,
        related_asset=_device_asset(connection, alert.get('rem0te_endpoint_id')))


def _audit(connection, row):
    from audit.models import AuditLog
    AuditLog.log(user=None, action='create', organization=connection.organization, object_type='psa.Ticket',
                 object_id=row.ticket_id, object_repr=f'Ticket for Rem0te alert {row.alert_id}'[:255],
                 description=f'Ticket {row.ticket.ticket_number if row.ticket else "?"} opened for Rem0te alert '
                             f'{row.alert_id} ({row.severity}) via {connection.name}'[:1000],
                 extra_data={'connection': connection.pk, 'alert': row.alert_id})


def ticket_url(ticket) -> str | None:
    ident = identity.get(create=False)
    base = getattr(ident, 'public_base_url', '') or ''
    if not base.startswith('https://') or ticket is None:
        return None  # the contract accepts https links only
    return base + reverse('psa:ticket_detail', args=[ticket.ticket_number])


def link(row) -> str:
    """POST /alerts/{id}/ticket. Idempotent on Rem0te's side: the same ticket
    again is 200; a different one is 409 TICKET_ALREADY_LINKED."""
    from psa_ai.models import Rem0teAlertTicket
    from .jobs import ticket_ext_id
    if row.ticket is None or row.link_status in (Rem0teAlertTicket.LINK_LINKED, Rem0teAlertTicket.LINK_CONFLICT):
        return row.link_status
    body = {'contract': protocol.CONTRACT, 'organization_id': pairing.organization_id(row.connection),
            'ticket_id': ticket_ext_id(row.ticket), 'ticket_url': ticket_url(row.ticket)}
    schema.validate('alert-ticket-link', body)
    try:
        r = client.request(row.connection, 'POST', f'/alerts/{row.alert_id}/ticket', body)
    except client.NotSent as e:
        r = client.Result(False, code=e.code, message=e.message)
    attempts = row.link_attempts + 1
    if r.ok:
        status, err = Rem0teAlertTicket.LINK_LINKED, ''
    elif r.status == 409 and r.code == 'TICKET_ALREADY_LINKED':
        status, err = Rem0teAlertTicket.LINK_CONFLICT, 'Rem0te already has a different ticket linked to this alert.'
    else:
        status, err = Rem0teAlertTicket.LINK_FAILED, f'{r.code}: {r.message}'
    delay = min(LINK_RETRY_MAX, timedelta(seconds=30 * 2 ** min(attempts, 7)))
    Rem0teAlertTicket.objects.filter(pk=row.pk).update(
        link_status=status, link_error=err[:300], link_attempts=attempts,
        next_link_at=None if status != Rem0teAlertTicket.LINK_FAILED else timezone.now() + delay)
    row.link_status, row.link_error = status, err[:300]
    return status


def cursor(connection) -> int:
    """The highest sequence n such that events 1..n have all been received."""
    from psa_ai.models import Rem0teAlertEvent
    seqs = sorted(set(Rem0teAlertEvent.objects.filter(connection=connection).values_list('sequence', flat=True)))
    n = 0
    for s in seqs:
        if s == n + 1:
            n = s
        elif s > n + 1:
            break
    return n


def poll(connection, pages=5) -> int:
    """Fetch signed alert events after the gap-free cursor, apply them, and
    retry ticket links that are due. Returns events applied."""
    from psa_ai.models import Rem0teAlertTicket
    if not pairing.is_processor(connection) or 'alerts' not in pairing.advertised(connection):
        return 0
    n = 0
    for _ in range(pages):
        after = cursor(connection)
        r = client.request(connection, 'GET', '/alerts/events',
                           query={'organization_id': pairing.organization_id(connection), 'after': after})
        if not r.ok:
            logger.warning('Rem0te alert poll failed for connection %s: %s %s', connection.pk, r.code, r.message)
            break
        events = (r.data or {}).get('events') or []
        stalled = False
        for item in events:
            if isinstance(item, dict):
                status, _ = apply_signed_alert_event(connection, item, via='poll')
                n += status == 200
                stalled = stalled or status >= 500
        if stalled or len(events) < 100:
            break
    for row in Rem0teAlertTicket.objects.filter(connection=connection, link_status__in=['pending', 'failed'],
                                                ticket__isnull=False).select_related('ticket', 'connection')[:50]:
        if row.next_link_at is None or row.next_link_at <= timezone.now():
            link(row)
    return n
