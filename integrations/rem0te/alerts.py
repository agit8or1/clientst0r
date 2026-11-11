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

Revision 2 (Rem0te 0.30) adds `alert.patch_summary` on REBOOT_PENDING
alerts: validated against the pinned patch-summary schema, stored on the
alert row, shown on the ticket and refreshed by update events. An event is
validated against the newest revision ClientSt0r implements, then older
ones; unknown fields are tolerated (and logged) only when Rem0te declared a
newer contract_revision ("revisions only add fields").

An authentic event that cannot be applied is never a reason to stall:
it is recorded as skipped (applied=False, with the reason), acknowledged so
Rem0te's push retries and the poll cursor move on, shown on the
connection's health, and retried by reconciliation after the next good
capabilities check. An event in this organization's feed naming another
peer or organization is recorded as foreign and never applied.
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


def _envelope_problem(signed) -> str:
    """'' when the event can be verified, de-duplicated and sequenced at all
    (what recording it needs), else why not."""
    if not isinstance(signed, dict) or set(signed) != {'alert_event', 'signature'}:
        return 'not a {alert_event, signature} object'
    ev = signed['alert_event']
    if not isinstance(ev, dict) or not isinstance(signed['signature'], dict):
        return 'alert_event and signature must be objects'
    seq = ev.get('sequence')
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        return 'sequence must be a positive integer'
    for k, n in (('event_id', 64), ('type', 20), ('peer_id', 128), ('organization_id', 128)):
        if not isinstance(ev.get(k), str) or not 1 <= len(ev[k]) <= n:
            return f'{k} missing or too long'
    if not isinstance(ev.get('alert'), dict) or not isinstance(ev['alert'].get('alert_id'), str) \
            or not 1 <= len(ev['alert']['alert_id']) <= 64:
        return 'alert.alert_id missing or too long'
    return ''


def apply_signed_alert_event(connection, signed: dict, via='push') -> Tuple[int, str]:
    """Verify and apply one {alert_event, signature}. Returns (HTTP status,
    outcome). Order: envelope → signature → peer/organization → schema of
    the negotiated revision → de-duplicate → apply.

    An authentic event (signature verified, ours) that this ClientSt0r cannot
    understand is recorded as skipped (applied=False) and acknowledged, so
    neither Rem0te's push retries nor the poll cursor loop on it; the
    connection's health shows it and reconciliation re-tries it after the
    next successful capabilities check (`reprocess_skipped`)."""
    from psa_ai.models import Rem0teAlertEvent
    from . import health
    why = _envelope_problem(signed)
    if why:
        health.note(connection, 'events', f'Rem0te sent an alert event ClientSt0r could not read ({why}).',
                    code='INVALID_EVENT', action='Run Test connection; if it repeats, report it with the Rem0te version.')
        return 400, 'invalid: ' + why
    event, signature = signed['alert_event'], signed['signature']
    problem = protocol.verify_event_signature(event, signature, pairing.keyring(connection), alert=True)
    if problem:
        logger.warning('Rem0te alert event refused for connection %s: %s', connection.pk, problem)
        health.note(connection, 'inbound_auth', f'An alert event did not verify with Rem0te\'s signing key ({problem}).',
                    code='EVENT_SIGNATURE', action="Compare Rem0te's signing key on this connection with its "
                                                   'capabilities (Test connection).')
        return 401, problem
    ident = identity.get(create=False)
    if event['peer_id'] != getattr(ident, 'peer_id', None) or event['organization_id'] != pairing.organization_id(connection):
        return 404, 'not for this peer or organization'
    peer_rev = pairing.last_check(connection).get('contract_revision') or 1
    errs, unknown, revision = schema.errors_from_peer('signed-alert-event', signed, peer_rev)
    if unknown:
        logger.info('Rem0te alert event %s: tolerated fields from revision %s: %s', event['event_id'], peer_rev,
                    ', '.join(unknown))
    if errs:
        return _skip(connection, event, via, 'not understood: ' + '; '.join(client.safe_text(e, 80) for e in errs[:3]))
    alert = event['alert']
    # The dedup record and its effect commit together: an event that could
    # not be applied (NotReady) is not recorded, so Rem0te's retry (or the
    # next poll) applies it instead of being acknowledged as a duplicate.
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
        health.note(connection, 'events', f'An alert could not become a ticket yet: {e}', code='NOT_READY',
                    action='Set up PSA (queues and statuses); Rem0te keeps retrying meanwhile.')
        return 503, str(e)
    if not _retryable(connection).exists():
        health.clear(connection, 'events')
    if row is not None:
        if created:
            _audit(connection, row)
        link(row)
    return 200, outcome


FOREIGN = 'foreign: '


def _retryable(connection):
    """Skipped events reconciliation may still apply (not the foreign ones,
    which are recorded only so the cursor moves past them)."""
    from psa_ai.models import Rem0teAlertEvent
    return Rem0teAlertEvent.objects.filter(connection=connection, applied=False).exclude(
        problem__startswith=FOREIGN)


def _skip(connection, event, via, why, foreign=False) -> Tuple[int, str]:
    from psa_ai.models import Rem0teAlertEvent
    from . import health
    try:
        with transaction.atomic():
            Rem0teAlertEvent.objects.create(connection=connection, event_id=event['event_id'],
                                            sequence=event['sequence'], event_type=event['type'][:20],
                                            alert_id=event['alert']['alert_id'], body=event, received_via=via,
                                            applied=False, problem=((FOREIGN if foreign else '') + why)[:300])
    except IntegrityError:
        return 200, 'duplicate'
    if foreign:
        # Rem0te's feed for this organization carried an event for another
        # peer or organization: never applied. Shown until the next event
        # applies normally.
        logger.warning('Rem0te alert event %s for connection %s names another peer/organization; skipped',
                       event.get('event_id'), connection.pk)
        health.note(connection, 'events', f'Rem0te sent alert event sequence {event["sequence"]} for another peer or '
                                          'organization in this organization\'s feed; it was not applied.',
                    code='EVENT_FOREIGN', action='Report it to the Rem0te administrator with the sequence number.')
        return 200, 'skipped'
    n = _retryable(connection).count()
    health.note(connection, 'events', f'{n} authentic alert event(s) from Rem0te could not be applied and were '
                                      f'skipped (latest: sequence {event["sequence"]}, {why}).',
                code='EVENT_NOT_UNDERSTOOD', action='Press Test connection (ClientSt0r re-reads the contract revision '
                                                    'and retries them); if it persists, update ClientSt0r.')
    _flag_recheck(connection)
    return 200, 'skipped'


def _flag_recheck(connection):
    from integrations.ticket_rmm import CAPS, _save
    mappings = dict(connection.field_mappings or {})
    doc = mappings.get(CAPS)
    if isinstance(doc, dict) and not doc.get('recheck'):
        mappings[CAPS] = dict(doc, recheck=True)
        _save(connection, mappings)


def reprocess_skipped(connection, limit=100) -> int:
    """Re-try events recorded as skipped (after a successful check, e.g.
    once the contract revision is known). Returns how many now applied."""
    from psa_ai.models import Rem0teAlertEvent
    from . import health
    peer_rev = pairing.last_check(connection).get('contract_revision') or 1
    n = 0
    ident = identity.get(create=False)
    for rec in _retryable(connection).order_by("sequence")[:limit]:
        body = rec.body if isinstance(rec.body, dict) else {}
        if body.get('peer_id') != getattr(ident, 'peer_id', None) or \
                body.get('organization_id') != pairing.organization_id(connection):
            continue  # recorded only so the cursor moves on; never applied here
        errs, _, _ = schema.errors_from_peer('alert-event', body, peer_rev)
        if errs:
            continue
        try:
            with transaction.atomic():
                outcome, row, created = _apply(connection, rec.body)
                Rem0teAlertEvent.objects.filter(pk=rec.pk).update(applied=True, problem='')
        except NotReady:
            break
        n += 1
        if row is not None:
            if created:
                _audit(connection, row)
            link(row)
    if not _retryable(connection).exists():
        health.clear(connection, 'events', code='EVENT_NOT_UNDERSTOOD')
    return n


def _apply(connection, event):
    """(outcome, row to link back or None, ticket newly opened)."""
    from psa_ai.models import Rem0teAlertTicket
    alert, seq = event['alert'], event['sequence']
    fields = {'state': alert['state'], 'severity': alert['severity'], 'kind': alert['kind'],
              'title': _text(alert['title'], 300), 'computer_name': _text(alert.get('computer_name'), 128),
              'rem0te_endpoint_id': _text(alert.get('rem0te_endpoint_id'), 64),
              'patch_summary': patch_summary(alert)}
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


def patch_summary(alert) -> dict:
    """Revision 2's redacted patch summary, re-checked field by field against
    the pinned patch-summary schema; {} when absent, null or not valid."""
    ps = alert.get('patch_summary') if isinstance(alert, dict) else None
    if not isinstance(ps, dict) or schema.errors('patch-summary', ps):
        return {}
    return ps


def patch_summary_lines(ps) -> list:
    """Plain-text lines for the ticket (KB numbers, states, ages, labels)."""
    if not ps:
        return []
    src = {'signed_agent_scan': 'signed agent scan', 'standard_agent_scan': 'standard agent scan (read-only)',
           'none': 'no scan received'}.get(ps['evidence_source'], ps['evidence_source'])
    age = ps.get('evidence_age_hours')
    managed = {'rem0te_or_windows_update': 'Rem0te / Windows Update', 'external': 'external manager',
               'unknown': 'unknown'}.get(ps['managed_by'], ps['managed_by'])
    reboot = {True: 'yes', False: 'no', None: 'unknown'}[ps.get('reboot_required')]
    out = ['', 'Patch status (from Rem0te):',
           f'Evidence: {src}' + (f', {age:.1f} h old ({ps["freshness"]})' if isinstance(age, (int, float)) else
                                 f' ({ps["freshness"]})'),
           f'Last boot: {ps.get("last_boot_at") or "unknown"}   Restart pending: {reboot}',
           f'Patching managed by: {managed}' + (f' ({", ".join(client.safe_text(m, 64) for m in ps["managers"])})'
                                                if ps.get('managers') else ''),
           f'Pending updates: {ps["pending_count"]}' + (f' ({", ".join(ps["pending_kbs"])})' if ps['pending_kbs'] else '')]
    for key, label in (('confirmed_kbs', 'Confirmed by a later scan'), ('failed_kbs', 'Failed'),
                       ('awaiting_confirmation_kbs', 'Awaiting confirmation')):
        if ps.get(key):
            out.append(f'{label}: {", ".join(ps[key])}')
    out.append('Rem0te can deploy updates here.' if ps.get('deploy_available') else
               'Rem0te cannot deploy updates to this computer.')
    return out


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
    ]
    lines += patch_summary_lines(patch_summary(alert))
    lines += [
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
    retry ticket links that are due. Returns events applied (or skipped).
    Every failure lands on the connection's health: the poll itself, an
    event that cannot be applied, a gap Rem0te reports that is still open,
    a ticket link that keeps failing."""
    from psa_ai.models import Rem0teAlertTicket
    from . import health
    if not pairing.is_processor(connection) or 'alerts' not in pairing.advertised(connection):
        return 0
    n = 0
    last_seq = None
    polled = False
    for _ in range(pages):
        after = cursor(connection)
        try:
            r = client.request(connection, 'GET', '/alerts/events',
                               query={'organization_id': pairing.organization_id(connection), 'after': after})
        except client.NotSent as e:
            health.note(connection, 'alerts_poll', f'Alert events not fetched: {e.message}', code=e.code)
            break
        if not r.ok:
            logger.warning('Rem0te alert poll failed for connection %s: %s %s', connection.pk, r.code, r.message)
            health.note(connection, 'alerts_poll', f'Fetching alert events from Rem0te failed ({r.code}: {r.message})',
                        code=r.code, action='ClientSt0r retries every minute; Test connection shows why.')
            break
        polled = True
        data = r.data if isinstance(r.data, dict) else {}
        if isinstance(data.get('last_sequence'), int):
            last_seq = data['last_sequence']
        events = data.get('events') or []
        stalled = False
        for item in events:
            if not isinstance(item, dict):
                continue
            status, _ = apply_signed_alert_event(connection, item, via='poll')
            if status == 404 and not _envelope_problem(item):
                # Authentic but naming another peer/organization in this
                # organization's feed: record so the cursor moves on, never apply.
                status, _ = _skip(connection, item['alert_event'], 'poll', 'not for this peer or organization',
                                  foreign=True)
            n += status == 200
            stalled = stalled or status >= 500
        if stalled or len(events) < 100:
            break
    if polled:
        health.clear(connection, 'alerts_poll')
        have = cursor(connection)
        if last_seq is not None and have < last_seq:
            health.note(connection, 'alerts_gap', f'Rem0te has sequenced {last_seq} alert event(s) for this '
                                                  f'organization; ClientSt0r has 1–{have} without a gap.',
                        code='ALERT_GAP', action='ClientSt0r keeps polling; a gap that stays open means an event '
                                                 'is refused — see the other issues.')
        else:
            health.clear(connection, 'alerts_gap')
    for row in Rem0teAlertTicket.objects.filter(connection=connection, link_status__in=['pending', 'failed'],
                                                ticket__isnull=False).select_related('ticket', 'connection')[:50]:
        if row.next_link_at is None or row.next_link_at <= timezone.now():
            link(row)
    failing = Rem0teAlertTicket.objects.filter(connection=connection, link_status='failed', link_attempts__gte=3)
    if failing.exists():
        last = failing.order_by('-updated_at').first()
        health.note(connection, 'ticket_link', f'{failing.count()} ticket(s) could not be linked back to their Rem0te '
                                               f'alert (latest: {last.link_error})', code='LINK_FAILED',
                    action='ClientSt0r retries with backoff (up to hourly).')
    else:
        health.clear(connection, 'ticket_link')
    conflicts = Rem0teAlertTicket.objects.filter(connection=connection, link_status='conflict').count()
    if conflicts:
        health.note(connection, 'ticket_link', f'{conflicts} Rem0te alert(s) are already linked to a different '
                                               'ticket; ClientSt0r did not overwrite them.', code='TICKET_ALREADY_LINKED',
                    action='Check the alert in Rem0te.')
    return n
