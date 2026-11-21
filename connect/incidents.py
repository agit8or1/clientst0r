"""Connection incidents and the optional ticket per incident (Quick Connect
increment E; DESIGN.md §10, roadmap 79.19).

An incident is one problem period of a connection: it opens on the first
alerting status (Degraded, Offline, Security Blocked, Suspended by the kill
switch, Revoked by the other side), follows every later status change, and
resolves when the connection is Connected again (or is suspended, revoked
or removed by an administrator). Only status *transitions* reach this
module (connect.alerts.observe compares-and-sets ``status_key`` first), so
a thousand failing heartbeats while Offline change nothing here.

Each incident is a ``connect.ConnectIncident`` row. Saving it queues it for
the shared event layer (events/signals.py -> events/sources.ConnectAdapter),
which keeps one OperationalEvent per incident and its ticket link
(EventLink), so the Operations Center, retention and correlation see
Connect like any other alert source.

Flapping: a problem within REOPEN_WINDOW (30 minutes) of the recovery
reopens the same incident instead of starting a new one, so a connection
that goes up and down keeps one incident, one event and one ticket.

Ticket (opt-in per connection, ``alert_ticket`` + ``alert_organization``):
one per incident, opened on the first transition to Offline or Security
Blocked, a staff note on every later transition and on recovery; once the
incident stayed resolved for REOPEN_WINDOW (``settle``, from the monitor
job) the ticket is resolved -- only when nobody has worked on it -- or left
open for a person with a note. It reuses the alert
policy's queue / priority / type choice (psa/routing/alert_policy.py), so
the "Monitoring" queue and the P1..P4 mapping are the same as for RMM and
Rem0te alerts. Staff-only ticket; no address, token or key in it.
"""
from __future__ import annotations

import logging

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import status as st

logger = logging.getLogger('connect')

TICKET_ON = frozenset({st.OFFLINE, st.SECURITY_BLOCKED})
# Statuses that end an incident (any other non-alerting status, e.g.
# testing during a retest, keeps it open).
ENDS = frozenset({st.CONNECTED, st.SUSPENDED, st.REVOKED, st.SETUP_FAILED})
RANK = {st.SECURITY_BLOCKED: 0, st.OFFLINE: 1, st.SUSPENDED: 2, st.DEGRADED: 3, st.REVOKED: 4}
MAX_TRANSITIONS = 50
REOPEN_WINDOW = timedelta(minutes=30)
TICKET_SEVERITY = {st.SECURITY_BLOCKED: 'critical', st.OFFLINE: 'error'}


def _name(conn) -> str:
    return (conn.remote_display_name or conn.remote_app_type or str(conn.pk))[:120]


def current(conn):
    from .models import ConnectIncident
    return ConnectIncident.objects.filter(connection=conn, resolved_at__isnull=True).first()


def on_transition(conn, old: str, new: str, code: str, *, alertable: bool, muted: bool, now=None):
    """Called once per displayed-status transition. Never raises."""
    try:
        return _on_transition(conn, old, new, code, alertable=alertable, muted=muted, now=now or timezone.now())
    except Exception:
        logger.exception('could not record the Connect incident for %s', conn.pk)
        return None


def _step(old, new, code, now):
    return {'from': old or '', 'to': new, 'code': (code or '')[:40], 'at': now.isoformat()}


def _on_transition(conn, old, new, code, *, alertable, muted, now):
    from .models import ConnectIncident
    inc = current(conn)
    if inc is None and alertable:
        inc = _reopen(conn, now)
    if inc is None:
        if not alertable:
            return None
        try:
            with transaction.atomic():
                inc = ConnectIncident.objects.create(
                    connection=conn, status=new, worst_status=new, code=(code or '')[:40], opened_at=now,
                    updated_at=now, muted=muted, transitions=[_step(old, new, code, now)])
        except IntegrityError:        # another worker opened it
            inc = current(conn)
            if inc is None:
                return None
        else:
            _maybe_ticket(conn, inc, new, muted, now)
            return inc
    # An open incident follows every later transition.
    inc.transitions = (list(inc.transitions or []) + [_step(old, new, code, now)])[-MAX_TRANSITIONS:]
    inc.transition_count += 1
    inc.updated_at = now
    inc.status = new
    if code:
        inc.code = code[:40]
    if new in RANK and RANK[new] < RANK.get(inc.worst_status, 99):
        inc.worst_status = new
    ending = new in ENDS
    if ending:
        inc.resolved_at = now
        inc.resolution = 'recovered' if new == st.CONNECTED else new
    inc.save()
    if ending:
        _ticket_recovery_note(conn, inc, new, now)
    elif alertable:
        if not inc.ticket_id:
            _maybe_ticket(conn, inc, new, muted, now)
        else:
            _ticket_note(inc, f'Connected application "{_name(conn)}" is now {st.LABELS.get(new, new)}'
                              + (f' ({code}).' if code else '.'))
    return inc


def _reopen(conn, now):
    """The incident resolved less than REOPEN_WINDOW ago, open again."""
    from .models import ConnectIncident
    last = (ConnectIncident.objects.filter(connection=conn, resolved_at__gte=now - REOPEN_WINDOW)
            .order_by('-resolved_at').first())
    if last is None:
        return None
    try:
        with transaction.atomic():
            if not ConnectIncident.objects.filter(pk=last.pk, resolved_at__isnull=False).update(
                    resolved_at=None, resolution='', ticket_settled=False):
                return current(conn)
    except IntegrityError:        # another incident was opened meanwhile
        return current(conn)
    last.refresh_from_db()
    return last


def settle(now=None) -> int:
    """Monitor upkeep: close out the tickets of incidents that stayed
    resolved for REOPEN_WINDOW. Returns how many were settled."""
    from .models import ConnectIncident
    now = now or timezone.now()
    n = 0
    for inc in (ConnectIncident.objects.select_related('connection')
                .filter(resolved_at__lte=now - REOPEN_WINDOW, ticket_id__isnull=False, ticket_settled=False)[:50]):
        if not ConnectIncident.objects.filter(pk=inc.pk, ticket_settled=False,
                                              resolved_at__isnull=False).update(ticket_settled=True):
            continue
        _ticket_closed(inc.connection, inc, now)
        n += 1
    return n


# --- the ticket ----------------------------------------------------------------------------------

def _maybe_ticket(conn, inc, key, muted, now):
    if key not in TICKET_ON or not conn.alert_ticket or not conn.alert_organization_id or inc.ticket_id:
        return None
    if muted and key != st.SECURITY_BLOCKED:
        return None
    from .models import ConnectIncident
    try:
        with transaction.atomic():
            locked = ConnectIncident.objects.select_for_update().get(pk=inc.pk)
            if locked.ticket_id:
                inc.ticket_id = locked.ticket_id
                return None
            ticket = _create_ticket(conn, locked, key, now)
            locked.ticket_id, locked.ticket_error = ticket.pk, ''
            locked.save(update_fields=['ticket_id', 'ticket_error'])
            inc.ticket_id = ticket.pk
    except Exception as e:      # a PSA without queues must not stop the alert
        logger.warning('could not open the ticket for Connect incident %s', inc.pk, exc_info=True)
        ConnectIncident.objects.filter(pk=inc.pk).update(ticket_error=str(e)[:200])
        return None
    from . import audit_log
    audit_log.record('incident.ticket', 'ok', connection=conn, app=conn.remote_installation_id,
                     detail={'incident': inc.pk, 'ticket': ticket.pk, 'status': key})
    return ticket


def _create_ticket(conn, inc, key, now):
    from psa.models import Ticket, TicketStatus
    from psa.routing import alert_policy as ap
    from psa.routing.models import AlertPolicySettings
    from psa.sla import apply_due_dates
    s = AlertPolicySettings.load()
    queue = ap._queue_for(None, s)
    status = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.order_by('sort_order').first()
    priority = ap._priority_for(None, TICKET_SEVERITY.get(key, 'warning'))
    ttype = ap._type_for(None)
    if queue is None or status is None or priority is None or ttype is None:
        raise ap.NotReady('PSA has no ticket queue, status, priority or type yet (run psa_seed_defaults).')
    label = st.LABELS.get(key, key)
    lines = [f'Opened for a Connected Applications incident: "{_name(conn)}" ({conn.remote_app_type}) is {label}.',
             '',
             f'Since: {timezone.localtime(inc.opened_at):%Y-%m-%d %H:%M}   Failure code: {inc.code or "—"}',
             f'Connection: /settings/integrations/connected-apps/{conn.pk}/', '']
    if key == st.SECURITY_BLOCKED:
        lines.append('Security Blocked: nothing is exchanged and it does not reconnect by itself. Review the '
                     'evidence on the connection page with the other application\'s administrator, then retest.')
    else:
        lines.append('Offline: Clientst0r retries with increasing waits (up to every 15 minutes); queued events '
                     'are delivered in order when it is back.')
    lines += ['', 'One ticket per incident: later status changes and the recovery are added as notes.']
    ticket = Ticket(organization_id=conn.alert_organization_id,
                    subject=f'[Connected application] {_name(conn)} is {label}'[:300], description='\n'.join(lines),
                    queue=queue, priority=priority, status=status, ticket_type=ttype, source='monitoring',
                    visibility='staff', client_can_view=False, tags=['alert', 'connected-application'],
                    custom_fields={'connect_incident': {'incident_id': inc.pk, 'connection': str(conn.pk)}})
    ticket.save()
    apply_due_dates(ticket)
    return ticket


def _ticket(inc):
    if not inc.ticket_id:
        return None
    from psa.models import Ticket
    return Ticket.objects.select_related('status').filter(pk=inc.ticket_id).first()


def _ticket_note(inc, body):
    try:
        t = _ticket(inc)
        if t is not None and not t.status.is_terminal:
            from psa.routing.alert_policy import note
            note(t, body)
    except Exception:
        logger.warning('could not add a note to the Connect incident ticket', exc_info=True)


def _untouched(ticket) -> bool:
    from django.db.models import Q
    from psa.models import TicketComment
    if ticket.status.is_terminal or ticket.first_response_at or ticket.time_entries.exists():
        return False
    return not TicketComment.objects.filter(ticket=ticket).filter(Q(is_system=False) | Q(author__isnull=False)).exists()


def _ticket_recovery_note(conn, inc, new, now):
    when = timezone.localtime(now).strftime('%Y-%m-%d %H:%M')
    if new == st.CONNECTED:
        _ticket_note(inc, f'Connected application "{_name(conn)}" is connected again at {when}; every check '
                          f'passes. If it stays connected for {int(REOPEN_WINDOW.total_seconds() // 60)} minutes '
                          'and nobody has worked on this ticket, it is resolved automatically.')
    else:
        _ticket_note(inc, f'The incident ended at {when}: the connection is now {st.LABELS.get(new, new)}.')


def _ticket_closed(conn, inc, now):
    try:
        t = _ticket(inc)
        if t is None or t.status.is_terminal:
            return
        from psa.routing import alert_policy as ap
        if inc.resolution == 'recovered' and _untouched(t):
            class _L:      # what _resolve_ticket() reads from an alert link
                title = f'connected application "{_name(conn)}" is connected again'
            if ap._resolve_ticket(t, _L, now):
                ap.note(t, 'Resolved this ticket: the connection stayed connected and nobody had worked on it.')
                return
        ap.note(t, 'The incident is over. The ticket stays open for a person to close.')
    except Exception:
        logger.warning('could not close out the Connect incident ticket', exc_info=True)
