"""Signed events: outbound queue with ordered drain, recovery after an
outage and dead letters by age (Quick Connect increment D, DESIGN.md §8.4),
inbound verification with dedup and loop protection (PROTOCOL.md §8)."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Callable, Dict

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from agit8or_connect import webhooks
from agit8or_connect.errors import ConnectError
from agit8or_connect.tenants import authorize

from . import audit_log, catalog, identity, store, transport

logger = logging.getLogger('connect')

PERMANENT_STATUSES = (400, 403, 404, 405, 410, 413, 422)
HANDLERS: Dict[str, Callable] = {}


def handler(event_type):
    def register(fn):
        HANDLERS[event_type] = fn
        return fn
    return register


@handler('connect.test')
def _test_event(conn, grant, env):
    return 'accepted'


@handler('connect.connection.revoked')
def _peer_revoked(conn, grant, env):
    """The other application disconnected: end ours too (records kept)."""
    from . import lifecycle
    lifecycle.revoke(conn, None, reason='peer_disconnected')
    return 'revoked'


def enqueue(conn, event_type: str, data: dict, *, grant=None, correlation_id=None, causation_id=None,
            origin=None, hops=0):
    from .models import OutboundEvent
    env = webhooks.envelope(event_type=event_type, tenant=catalog.tenant_id(grant.organization_id) if grant else '',
                            data=data, sender=identity.installation_id(), origin=origin,
                            correlation_id=correlation_id, causation_id=causation_id, hops=hops)
    ev = OutboundEvent.objects.create(id=env['id'], connection=conn, tenant_grant=grant, event_type=event_type,
                                      envelope=env)
    return ev


def _max_age() -> timedelta:
    days = int(getattr(settings, 'AGIT8OR_CONNECT_EVENT_MAX_AGE_DAYS', 7) or 7)
    return timedelta(days=max(1, min(30, days)))


def _dead(ev, err, now):
    from .models import OutboundEvent
    ev.status, ev.last_error, ev.next_attempt_at = OutboundEvent.DEAD, err[:300], now   # next_attempt_at = when it died
    audit_log.record('event.dead_letter', 'failed', connection=ev.connection, app=identity.installation_id(),
                     detail={'event': str(ev.pk), 'type': ev.event_type, 'attempts': ev.attempts, 'reason': err[:80]})


def deliver(ev, now=None, *, force=False) -> bool:
    """Send one queued event. DESIGN.md §8.4 (fixes QC-06):

    * while the connection's circuit is open (the peer is Offline) nothing
      is sent and nothing is counted: the event waits for the probe time;
    * ``attempts`` counts only attempts that reached the peer (an HTTP
      answer). A transport failure is the connection's problem, not the
      event's: it asks the monitor to check soon and is never counted;
    * dead letter only on a permanent status, after 12 delivered-to-peer
      attempts, or by age (AGIT8OR_CONNECT_EVENT_MAX_AGE_DAYS, default 7).
    ``force`` (the connection test and diagnostics) ignores the circuit."""
    from .models import Connection, DeliveryAttempt, OutboundEvent
    conn = ev.connection
    from . import client, destinations, health
    if not client.usable_state(conn, conn.state) or identity.kill_switch_engaged():
        return False
    if not destinations.ready(conn):
        return False     # no approved destination: nothing sent, the attempt is not counted
    now = timezone.now()
    if conn.circuit == Connection.CIRCUIT_OPEN and not force:
        nxt = Connection.objects.filter(pk=conn.pk).values_list('next_check_at', flat=True).first()
        OutboundEvent.objects.filter(pk=ev.pk).update(next_attempt_at=max(nxt or now, now) +
                                                      timedelta(seconds=1))
        return False
    body = webhooks.body_of(ev.envelope)
    started = time.monotonic()
    code, ok, err = None, False, ''
    try:
        _, priv = store.active_key(conn)
        headers = webhooks.sign(priv, connection_id=conn.remote_connection_id, event_id=str(ev.pk),
                                sender=identity.installation_id(), receiver=conn.remote_installation_id, body=body)
        r = transport.for_connection(conn).request('POST', conn.endpoint('events'), headers=headers, body=body)
        code = r.status
        ok = 200 <= r.status < 300
        if not ok:
            err = f'HTTP {r.status}'
    except ConnectError as e:
        err = e.message[:300]
    DeliveryAttempt.objects.create(event=ev, status_code=code, ok=ok, error=err,
                                   duration_ms=int((time.monotonic() - started) * 1000))
    now = timezone.now()
    if code is not None:
        ev.attempts += 1          # reached the peer
    if ok:
        ev.status, ev.delivered_at, ev.last_error = OutboundEvent.DELIVERED, now, ''
        Connection.objects.filter(pk=conn.pk).update(last_success_at=now, last_outbound_ok_at=now, failure_count=0)
    elif code in PERMANENT_STATUSES or (code is not None and ev.attempts >= webhooks.MAX_ATTEMPTS):
        _dead(ev, err, now)
    elif code is None:
        # Not reached: wait for the connection, not a per-event ladder.
        ev.last_error = err
        ev.next_attempt_at = now + timedelta(seconds=health.LADDER[0])
        health.note_delivery_trouble(conn)
    else:
        ev.last_error = err
        ev.next_attempt_at = now + timedelta(seconds=webhooks.backoff_seconds(ev.attempts))
        from django.db.models import F
        Connection.objects.filter(pk=conn.pk).update(failure_count=F('failure_count') + 1,
                                                     last_failure_at=now, last_error=err[:500])
    ev.save()
    return ok


DRAIN_PER_PASS = 50


def deliver_due(limit=DRAIN_PER_PASS) -> dict:
    """Ordered drain (DESIGN §8.4): per connection, queued events in
    ``created_at`` order; the oldest blocks the rest until it is delivered
    or dead-lettered, so the receiver sees them in order. Connections whose
    circuit is open are skipped without touching their events. Each event is
    claimed with a compare-and-set on ``next_attempt_at`` so two runners
    never send it twice in one pass (the receiver dedupes by id anyway)."""
    from .models import Connection, OutboundEvent
    counts = {'delivered': 0, 'retry': 0, 'dead': 0}
    if identity.kill_switch_engaged():
        return counts
    now = timezone.now()
    conn_ids = list(OutboundEvent.objects.filter(
        status=OutboundEvent.QUEUED, next_attempt_at__lte=now, connection__state=Connection.ACTIVE).exclude(
        connection__circuit=Connection.CIRCUIT_OPEN).values_list('connection_id', flat=True).distinct())
    budget = limit
    for cid in conn_ids:
        if budget <= 0:
            break
        queue = OutboundEvent.objects.filter(connection_id=cid, status=OutboundEvent.QUEUED).select_related(
            'connection').order_by('created_at', 'pk')[:budget]
        for ev in queue:
            if ev.next_attempt_at > now:
                break          # the oldest is waiting: keep the order
            if not OutboundEvent.objects.filter(pk=ev.pk, status=OutboundEvent.QUEUED,
                                                next_attempt_at=ev.next_attempt_at).update(
                    next_attempt_at=now + timedelta(seconds=120)):
                break          # another runner has it
            budget -= 1
            if deliver(ev):
                counts['delivered'] += 1
                continue
            if ev.status == OutboundEvent.DEAD:
                counts['dead'] += 1
                continue
            counts['retry'] += 1
            break
    return counts


def expire_aged(now=None) -> int:
    """Queued events older than the age limit become dead letters (one audit
    record per connection per run)."""
    from django.db.models import Q
    from .models import OutboundEvent
    now = now or timezone.now()
    cutoff = now - _max_age()
    rows = OutboundEvent.objects.filter(status=OutboundEvent.QUEUED).filter(
        Q(requeued_at__isnull=True, created_at__lt=cutoff) | Q(requeued_at__lt=cutoff))
    by_conn = {}
    for cid, eid in rows.values_list('connection_id', 'pk')[:1000]:
        by_conn.setdefault(cid, []).append(eid)
    n = 0
    for cid, ids in by_conn.items():
        n += OutboundEvent.objects.filter(pk__in=ids, status=OutboundEvent.QUEUED).update(
            status=OutboundEvent.DEAD, next_attempt_at=now,
            last_error=f'Expired: not delivered within {_max_age().days} days.')
        audit_log.record('event.expired', 'failed', connection=cid, detail={'events': len(ids),
                                                                         'max_age_days': _max_age().days})
    return n


def requeue(ev, user=None):
    """An administrator puts a dead letter back in the queue (same id, so the
    receiver still deduplicates); attempts and the age limit start again."""
    from .models import Connection, OutboundEvent
    if ev.status != OutboundEvent.DEAD:
        raise ConnectError('invalid_request', 'only a failed event can be requeued', 409)
    if ev.connection.state in (Connection.REVOKED, Connection.FAILED):
        raise ConnectError('connection_inactive', 'the connection has ended', 409)
    now = timezone.now()
    OutboundEvent.objects.filter(pk=ev.pk, status=OutboundEvent.DEAD).update(
        status=OutboundEvent.QUEUED, attempts=0, next_attempt_at=now, requeued_at=now, last_error='')
    audit_log.record('event.requeued', 'ok', connection=ev.connection, user=user,
                     detail={'event': str(ev.pk), 'type': ev.event_type})
    from .source_policy import _audit_admin
    _audit_admin(user, f'Agit8or Connect event {ev.pk} requeued for connection {ev.connection_id}',
                 {'event': str(ev.pk), 'type': ev.event_type})


DELIVERED_RETENTION = timedelta(days=90)


def prune_delivered(now=None) -> int:
    """Delivered events (and their attempt rows) older than 90 days. Queued,
    dead, cancelled and inbound events are never deleted here."""
    from .models import DeliveryAttempt, OutboundEvent
    now = now or timezone.now()
    old = OutboundEvent.objects.filter(status=OutboundEvent.DELIVERED, delivered_at__lt=now - DELIVERED_RETENTION)
    ids = list(old.values_list('pk', flat=True)[:5000])
    if not ids:
        return 0
    DeliveryAttempt.objects.filter(event_id__in=ids).delete()
    return OutboundEvent.objects.filter(pk__in=ids).delete()[0]


def receive(request) -> tuple:
    """(status, body dict). Verifies signature + freshness BEFORE recording
    anything; a duplicate event id is answered 200 'duplicate'."""
    from .models import Connection, InboundEvent
    if identity.kill_switch_engaged():
        raise ConnectError('kill_switch', 'connected applications are stopped', 503)
    body = request.body or b''
    cid = request.headers.get(webhooks.H_CONNECTION, '')
    from .auth import _connection
    conn = _connection(cid)
    if conn is None or conn.state not in (Connection.ACTIVE, Connection.TESTING):
        raise ConnectError('invalid_signature', 'unknown or inactive connection', 401)
    ring = store.remote_keyring(conn)
    if request.headers.get(webhooks.H_KEY_ID, '') not in ring:
        from .auth import refresh_remote_jwks
        if refresh_remote_jwks(conn):
            ring = store.remote_keyring(conn)
    eid, _ = webhooks.verify(dict(request.headers), body, ring, sender=conn.remote_installation_id,
                             receiver=identity.installation_id(), connection_id=str(conn.pk))
    from . import source_policy
    source_policy.bind(request, conn)   # step 11: signer == connection the source matched
    try:
        env = webhooks.validate_envelope(json.loads(body), event_id=eid, sender=conn.remote_installation_id,
                                         receiver=identity.installation_id())
    except ValueError:
        raise ConnectError('invalid_request', 'event body is not JSON')
    if conn.state == Connection.TESTING and env['type'] != 'connect.test':
        # A connection under test (C3) accepts only the test event.
        raise ConnectError('connection_inactive', 'the connection is being tested; only connect.test is accepted',
                           409)
    if InboundEvent.objects.filter(connection=conn, event_id=eid).exists():
        return 200, {'status': 'duplicate', 'id': eid}
    if env['loop']:
        return 200, {'status': 'ignored_loop', 'id': eid}
    if webhooks.is_connection_event(env):
        grant = None
    else:
        if env['type'] not in (conn.inbound_event_types or []):
            raise ConnectError('event_type_not_allowed', 'this connection may not send that event type', 403)
        grant = authorize(store.tenant_resolver, str(conn.pk), env.get('tenant', ''), 'events:publish',
                          conn.inbound_scopes).local_tenant
    try:
        with transaction.atomic():
            InboundEvent.objects.create(connection=conn, event_id=eid, event_type=env['type'], tenant_grant=grant,
                                        correlation_id=str(env.get('correlation_id') or '')[:128],
                                        data=env.get('data') or {})
    except IntegrityError:
        return 200, {'status': 'duplicate', 'id': eid}
    fn = HANDLERS.get(env['type'])
    outcome = fn(conn, grant, env) if fn else 'stored'
    audit_log.record('event.received', 'ok', connection=conn, app=conn.remote_installation_id,
                     tenant=grant.remote_tenant_id if grant else '',
                     scopes=[] if grant is None else ['events:publish'],
                     correlation_id=str(env.get('correlation_id') or '')[:64],
                     detail={'type': env['type'], 'event': eid})
    Connection.objects.filter(pk=conn.pk).update(last_success_at=timezone.now())
    return 200, {'status': 'accepted', 'id': eid, 'outcome': outcome}
