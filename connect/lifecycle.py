"""
Connection lifecycle: test, rotate, suspend / resume, disconnect, revoke,
per-customer revoke, emergency kill switch.

None of these ever deletes customer records, devices, tickets or the
connection's own history: Disconnect and Revoke end the credentials and the
grants, and keep the rows (state REVOKED, grants inactive with who / when).
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from agit8or_connect import discovery as sdk_discovery
from agit8or_connect.errors import ConnectError

from . import audit_log, client, events, identity, store, transport

logger = logging.getLogger('connect')


def retire_keys(conn):
    """Every key retired and its private half wiped. Irreversible."""
    from .models import ConnectionKey
    now = timezone.now()
    for row in conn.keys.exclude(state=ConnectionKey.RETIRED):
        row.state, row.retired_at, row.private_key = ConnectionKey.RETIRED, now, ''
        row.save(update_fields=['state', 'retired_at', 'private_key'])


def suspend(conn, user=None, reason='manual'):
    from .models import Connection
    if conn.state not in (Connection.ACTIVE,):
        return conn
    conn.state, conn.suspended_reason, conn.tokens_not_before = Connection.SUSPENDED, reason[:40], timezone.now()
    conn.save()
    client.clear_cache(conn)
    audit_log.record('connection.suspended', 'ok', connection=conn, user=user, detail={'reason': reason})
    return conn


def resume(conn, user=None):
    from .models import Connection
    if conn.state != Connection.SUSPENDED:
        return conn
    if identity.kill_switch_engaged():
        raise ConnectError('kill_switch', 'release the kill switch first', 409)
    conn.state, conn.suspended_reason = Connection.ACTIVE, ''
    conn.save()
    audit_log.record('connection.resumed', 'ok', connection=conn, user=user)
    return conn


def revoke(conn, user=None, reason='revoked'):
    """Immediately: tokens refused, keys destroyed, grants revoked, queued
    events cancelled. Rows are kept."""
    from .models import Connection, OutboundEvent
    now = timezone.now()
    with transaction.atomic():
        conn.state, conn.tokens_not_before, conn.revoked_at, conn.revoked_by = Connection.REVOKED, now, now, user
        conn.suspended_reason = reason[:40]
        conn.save()
        conn.tenant_grants.filter(active=True).update(active=False, revoked_at=now, revoked_by=user)
        conn.outbound_events.filter(status=OutboundEvent.QUEUED).update(status=OutboundEvent.CANCELLED)
        retire_keys(conn)
    client.clear_cache(conn)
    audit_log.record('connection.revoked', 'ok', connection=conn, user=user, app=conn.remote_installation_id,
                     detail={'reason': reason})
    return conn


def disconnect(conn, user=None):
    """Tell the other app (best effort, one signed event), then revoke."""
    from .models import Connection
    notified = False
    if conn.state == Connection.ACTIVE and not identity.kill_switch_engaged():
        try:
            ev = events.enqueue(conn, 'connect.connection.revoked', {'reason': 'disconnected'})
            notified = events.deliver(ev)
        except ConnectError:
            notified = False
    revoke(conn, user, reason='disconnected')
    audit_log.record('connection.disconnected', 'ok', connection=conn, user=user,
                     detail={'peer_notified': notified})
    return notified


def revoke_grant(grant, user=None):
    now = timezone.now()
    grant.active, grant.revoked_at, grant.revoked_by = False, now, user
    grant.save(update_fields=['active', 'revoked_at', 'revoked_by'])
    audit_log.record('tenant_grant.revoked', 'ok', connection=grant.connection, user=user,
                     tenant=grant.remote_tenant_id, detail={'organization_id': grant.organization_id})


def engage_kill_switch(user=None) -> int:
    """Stop every connection now: all API calls answer 503, no token is
    issued, nothing is delivered, every active connection is suspended."""
    from .models import Connection, InstallationIdentity
    ident = identity.get()
    InstallationIdentity.objects.filter(pk=ident.pk).update(kill_switch_engaged=True, kill_switch_at=timezone.now(),
                                                            kill_switch_by=user)
    n = 0
    for conn in Connection.objects.filter(state=Connection.ACTIVE):
        suspend(conn, user, reason='kill_switch')
        n += 1
    client.clear_cache()
    audit_log.record('kill_switch.engaged', 'ok', user=user, detail={'suspended': n})
    return n


def release_kill_switch(user=None):
    """Lifts the stop. Connections stay suspended until resumed one by one."""
    from .models import InstallationIdentity
    InstallationIdentity.objects.update(kill_switch_engaged=False)
    audit_log.record('kill_switch.released', 'ok', user=user)


# --- rotation ---------------------------------------------------------------------

def rotate(conn, user=None) -> bool:
    """Stage a new key (published in our endorsed JWKS), prove the other app
    accepts it by obtaining a token signed with it, then promote it and keep
    the old key as 'retiring' for the overlap. If the other app refuses the
    new key, it is marked failed and the old key stays active."""
    from .models import Connection, ConnectionKey
    if conn.state != Connection.ACTIVE:
        return False
    old_row, _ = store.active_key(conn)
    new_row, _ = store.new_key(conn, state=ConnectionKey.STAGED)
    now = timezone.now()
    try:
        client.get_token(conn, key_row=new_row, use_cache=False)
    except ConnectError as e:
        new_row.state, new_row.private_key, new_row.retired_at = ConnectionKey.FAILED, '', now
        new_row.save(update_fields=['state', 'private_key', 'retired_at'])
        conn.last_rotation_error = f'The other application did not accept the new key ({e.code}).'[:300]
        conn.next_rotation_at = now + timedelta(hours=6)
        conn.save(update_fields=['last_rotation_error', 'next_rotation_at', 'updated_at'])
        audit_log.record('key.rotation', 'failed', connection=conn, user=user,
                         detail={'staged_kid': new_row.kid, 'active_kid': old_row.kid, 'error': e.code})
        return False
    with transaction.atomic():
        old_row.state, old_row.retire_after = ConnectionKey.RETIRING, now + timedelta(
            hours=conn.rotation_overlap_hours or 24)
        old_row.save(update_fields=['state', 'retire_after'])
        new_row.state, new_row.activated_at = ConnectionKey.ACTIVE, now
        new_row.save(update_fields=['state', 'activated_at'])
        conn.last_rotation_at, conn.last_rotation_error = now, ''
        conn.next_rotation_at = now + timedelta(days=conn.rotation_interval_days or 90)
        conn.save(update_fields=['last_rotation_at', 'last_rotation_error', 'next_rotation_at', 'updated_at'])
    client.clear_cache(conn)
    audit_log.record('key.rotation', 'ok', connection=conn, user=user,
                     detail={'new_kid': new_row.kid, 'retiring_kid': old_row.kid})
    return True


def retire_due() -> int:
    from .models import ConnectionKey
    n = 0
    for row in ConnectionKey.objects.filter(state=ConnectionKey.RETIRING, retire_after__lte=timezone.now()):
        row.state, row.retired_at, row.private_key = ConnectionKey.RETIRED, timezone.now(), ''
        row.save(update_fields=['state', 'retired_at', 'private_key'])
        audit_log.record('key.retired', 'ok', connection=row.connection_id, detail={'kid': row.kid})
        n += 1
    return n


def rotate_due() -> dict:
    from .models import Connection
    out = {'rotated': 0, 'failed': 0, 'retired': retire_due()}
    if identity.kill_switch_engaged():
        return out
    for conn in Connection.objects.filter(state=Connection.ACTIVE, next_rotation_at__lte=timezone.now()):
        out['rotated' if rotate(conn) else 'failed'] += 1
    return out


# --- connection test ----------------------------------------------------------------

def test_connection(conn, user=None) -> dict:
    """A pass/fail report: discovery + identity + compatibility, auth,
    permissions, tenant mapping, event delivery (signature accepted)."""
    from .models import Connection
    checks = []

    def check(name, ok, message):
        checks.append({'name': name, 'ok': bool(ok), 'message': message})
        return ok

    if conn.state != Connection.ACTIVE:
        check('State', False, f'The connection is {conn.get_state_display().lower()}.')
    else:
        try:
            info = sdk_discovery.fetch(transport.for_connection(conn), conn.base_url)
            same = info.installation_id == conn.remote_installation_id
            check('Connectivity and identity', same, f'Reached {info.display_name or info.app_type} '
                  f'(installation {info.installation_id[:8]}…).' if same else
                  'The address now leads to a different installation. Disconnect and pair again.')
            check('Compatibility', True, f'Protocol agit8or-connect/{info.version}; '
                                         f'{info.app_type} {info.app_version or ""}'.strip())
        except ConnectError as e:
            from .pairing import friendly
            check('Connectivity and identity', False, friendly(e))
        token = None
        try:
            token = client.get_token(conn, use_cache=False)
            check('Authentication', True, 'The other application issued a short-lived, key-bound access token.')
        except ConnectError as e:
            check('Authentication', False, f'Token refused ({e.code}): {e.message}')
        if token is not None:
            granted = set(str(token.get('scope', '')).split())
            want = set(conn.requested_outbound_scopes or [])
            missing = sorted(want - granted)
            check('Permissions', not missing, 'All requested permissions are granted.' if not missing else
                  'Not granted by the other application: ' + ', '.join(missing))
            url = conn.endpoint('capabilities')
            if url:
                try:
                    r = client.call(conn, 'GET', url)
                    data = json.loads(r.body or b'{}') if r.status == 200 else {}
                    remote = {t.get('tenant') for t in data.get('tenants', []) if isinstance(t, dict)}
                    ours = set(conn.tenant_grants.filter(active=True).values_list('remote_tenant_id', flat=True))
                    check('Customer mapping', r.status == 200,
                          f'{len(ours)} customer(s) granted here; the other application reports '
                          f'{len(remote)} customer grant(s) for us.' if r.status == 200 else
                          f'Capabilities answered HTTP {r.status}.')
                except ConnectError as e:
                    check('Customer mapping', False, e.message)
        try:
            ev = events.enqueue(conn, 'connect.test', {'requested_by': 'connection test'})
            ok = events.deliver(ev)
            check('Event delivery and webhook signature', ok, 'A signed test event was accepted.' if ok else
                  f'The test event was not accepted ({ev.last_error or "no answer"}); it stays queued for retry.')
        except ConnectError as e:
            check('Event delivery and webhook signature', False, e.message)
    report = {'ok': all(c['ok'] for c in checks), 'checks': checks, 'at': timezone.now().isoformat()}
    conn.last_test = report
    conn.save(update_fields=['last_test', 'updated_at'])
    audit_log.record('connection.test', 'ok' if report['ok'] else 'failed', connection=conn, user=user,
                     detail={'failed': [c['name'] for c in checks if not c['ok']]})
    return report
