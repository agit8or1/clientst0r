"""Signed events: outbound queue with backoff + dead letter, inbound
verification with dedup and loop protection (PROTOCOL.md §8)."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Callable, Dict

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


def deliver(ev, now=None) -> bool:
    from .models import Connection, DeliveryAttempt, OutboundEvent
    conn = ev.connection
    from . import client, destinations
    if not client.usable_state(conn, conn.state) or identity.kill_switch_engaged():
        return False
    if not destinations.ready(conn):
        return False     # no approved destination: nothing sent, the attempt is not counted
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
    ev.attempts += 1
    if ok:
        ev.status, ev.delivered_at, ev.last_error = OutboundEvent.DELIVERED, timezone.now(), ''
        Connection.objects.filter(pk=conn.pk).update(last_success_at=timezone.now(), failure_count=0)
    elif code in PERMANENT_STATUSES or ev.attempts >= webhooks.MAX_ATTEMPTS:
        ev.status, ev.last_error = OutboundEvent.DEAD, err
        audit_log.record('event.dead_letter', 'failed', connection=conn, app=identity.installation_id(),
                         detail={'event': str(ev.pk), 'type': ev.event_type, 'attempts': ev.attempts})
    else:
        ev.last_error = err
        ev.next_attempt_at = timezone.now() + timedelta(seconds=webhooks.backoff_seconds(ev.attempts))
        from django.db.models import F
        Connection.objects.filter(pk=conn.pk).update(failure_count=F('failure_count') + 1,
                                                     last_failure_at=timezone.now(), last_error=err[:500])
    ev.save()
    return ok


def deliver_due(limit=100) -> dict:
    from .models import Connection, OutboundEvent
    counts = {'delivered': 0, 'retry': 0, 'dead': 0}
    if identity.kill_switch_engaged():
        return counts
    due = OutboundEvent.objects.filter(status=OutboundEvent.QUEUED, next_attempt_at__lte=timezone.now(),
                                       connection__state=Connection.ACTIVE).select_related('connection')
    for ev in due.order_by('next_attempt_at')[:limit]:
        if deliver(ev):
            counts['delivered'] += 1
        elif ev.status == OutboundEvent.DEAD:
            counts['dead'] += 1
        else:
            counts['retry'] += 1
    return counts


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
