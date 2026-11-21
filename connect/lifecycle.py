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
        from . import source_policy
        source_policy.remove_connection_rules(conn, reason)
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
    # A connection under test keeps no test window open (C3): its approval
    # stays, the window re-opens on a retest after the release.
    from . import activation
    for conn in Connection.objects.filter(state=Connection.TESTING):
        activation.back_to_awaiting_network(conn, 'kill_switch', user,
                                            message=activation.FRIENDLY['kill_switch'])
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

# Step ids of the commit-gate test (DESIGN.md §9.1; the first version of the
# diagnostics: the five application checks plus DNS, TCP, TLS, certificate
# and source address; all fifteen steps come with increment E).
NETWORK_STEPS = ('dns', 'destination', 'tcp', 'tls', 'certificate')


def _network_checks(conn, check):
    """DNS, approved destination, TCP, TLS and certificate, from a DNS + TLS
    handshake preview of the connection's address (no HTTP request). Returns
    False when a later step would be meaningless."""
    from . import destinations
    d = destinations.get(conn)
    try:
        pv = transport.probe(conn.base_url, allow_private=bool(d and d.has_private),
                             ca_pem=(d.ca_bundle if d else '') or conn.tls_ca_bundle)
    except Exception as e:   # the probe never raises by contract; a defect must not pass the gate
        logger.exception('connection test probe failed for %s', conn.pk)
        pv = destinations.Preview(host='', port=0, error=str(e)[:200], code='probe_error')
    code = getattr(pv, 'code', '') or ''
    host = pv.host or destinations.host_port(conn.base_url)[0]
    if not pv.addresses:
        check('DNS', False, pv.error or f'{host} did not resolve.', id='dns', code=code or 'dns_nxdomain',
              next_action='Check the other application\'s host name.')
        return False
    check('DNS', True, f'{host} resolves to {", ".join(pv.addresses)}.', id='dns')
    outside = [a for a in pv.addresses if not (d and destinations.contains(d.addresses, a))]
    if outside:
        check('Approved destination address', False,
              f'{", ".join(outside)} is not an approved address for this connection '
              f'(approved: {", ".join(d.nets) if d else "none"}).', id='destination', code='destination_changed',
              next_action='Confirm the new address with the other administrator, then approve it under Network.')
        return False
    check('Approved destination address', True, 'Every address is approved for this connection.', id='destination')
    if code.startswith('tcp_'):
        check('TCP', False, pv.error or 'The port did not answer.', id='tcp', code=code,
              next_action='The other side\'s firewall or port 443 forwarding has to let this server in.')
        return False
    check('TCP', True, f'Port {pv.port or destinations.host_port(conn.base_url)[1]} answers.', id='tcp')
    if code in ('tls_handshake', 'tls_version'):
        check('TLS', False, pv.error or 'TLS handshake failed.', id='tls', code=code)
        return False
    if pv.error and not code.startswith('certificate'):
        check('TLS', False, pv.error, id='tls', code=code or 'tls_handshake')
        return False
    check('TLS', True, 'TLS 1.2 or later negotiated.', id='tls')
    if code.startswith('certificate'):
        check('Certificate', False, pv.error or 'The certificate was not accepted.', id='certificate', code=code)
        return False
    if d and d.spki_pins and pv.spki and pv.spki not in d.spki_pins:
        check('Certificate', False, 'The certificate key does not match the pinned key.', id='certificate',
              code='spki_mismatch')
        return False
    check('Certificate', True, 'Valid for ' + host + '.', id='certificate')
    return True


def _source_check(conn, check, peer_refused):
    """Both directions of the source policy: the other application accepted
    this installation's source (no ``source_not_authorised``), and this
    connection's own rules let the other application in."""
    from .models import SourceRule as SR
    from . import source_policy
    if peer_refused:
        check('Source address', False, 'The other application refused this server\'s source address.',
              id='source', code='source_not_authorised', status='fail',
              next_action='The other administrator approves this installation\'s egress address (Connected '
                          'Applications → Network shows it).')
        return
    now = timezone.now()
    rules = [r for r in SR.objects.filter(connection=conn, layer=SR.CONNECTION, action=SR.ALLOW,
                                          status__in=(SR.TEMPORARY, SR.ACTIVE),
                                          purpose__in=(SR.ALL, SR.DISCOVERY))
             if not r.expires_at or r.expires_at > now]
    if not rules:
        check('Source address', False, 'No approved address of the other application is allowed here for this '
                                       'connection.', id='source', code='source_not_authorised_here',
              next_action='Approve the other application\'s address for this connection.')
        return
    missing = [r.network for r in rules if not source_policy.installation_allows(r.network)]
    if len(missing) == len(rules):
        check('Source address', False, 'The installation layer (Network) refuses ' + ', '.join(missing) + '.',
              id='source', code='source_not_authorised_here',
              next_action='Add the address to the installation layer under Network.')
        return
    check('Source address', True, 'This server is accepted by the other application; '
          + ', '.join(r.network for r in rules) + ' may reach this connection here.', id='source')


def test_connection(conn, user=None, *, full=False) -> dict:
    """A pass/fail report: discovery + identity + compatibility, auth,
    permissions, tenant mapping, event delivery (signature accepted).

    ``full`` (the commit gate, connect/activation.py): first DNS, approved
    destination, TCP, TLS and certificate, then the application checks, plus
    the source-address step. Each check has an id, a status (pass / fail /
    skipped / not_tested), a code and, when it failed, the next action."""
    import uuid
    from .models import Connection
    checks = []

    def check(name, ok, message, *, id='', code='', status=None, next_action=''):
        st = status or ('pass' if ok else 'fail')
        checks.append({'id': id or name.lower().replace(' ', '_'), 'name': name, 'ok': st in ('pass', 'not_tested'),
                       'status': st, 'code': code if st == 'fail' else '', 'message': message,
                       'next_action': next_action if st == 'fail' else ''})
        return ok

    def skip(name, id, because):
        check(name, False, f'Skipped because {because} failed.', id=id, status='skipped')

    one_way = full and not (conn.requested_outbound_scopes or conn.outbound_scopes)
    peer_refused = False
    if not client.usable_state(conn, conn.state):
        check('State', False, f'The connection is {conn.get_state_display().lower()}.', id='state',
              code='connection_inactive')
    elif full and not _network_checks(conn, check):
        first = next(c for c in checks if c['status'] == 'fail')['name'].lower()
        for name, sid in (('Connectivity and identity', 'identity'), ('Source address', 'source'),
                          ('Authentication', 'token')):
            skip(name, sid, first)
    else:
        identity_ok = False
        try:
            t = transport.for_connection(conn)
            r = t.request('GET', sdk_discovery.discovery_url(conn.base_url), headers={'Accept': 'application/json'})
            if r.status == 403 and b'source_not_authorised' in (r.body or b''):
                peer_refused = True
                raise ConnectError('source_not_authorised', 'the other application refused this source', 403)
            if r.status != 200:
                raise ConnectError('transport_error', f'discovery answered HTTP {r.status}', 502)
            info = sdk_discovery.parse_document(json.loads(r.body), sdk_discovery.discovery_url(conn.base_url))
            identity_ok = info.installation_id == conn.remote_installation_id
            check('Connectivity and identity', identity_ok, f'Reached {info.display_name or info.app_type} '
                  f'(installation {info.installation_id[:8]}…).' if identity_ok else
                  'The address now leads to a different installation. Disconnect and pair again.',
                  id='identity', code='identity_changed')
            check('Compatibility', True, f'Protocol agit8or-connect/{info.version}; '
                                         f'{info.app_type} {info.app_version or ""}'.strip(), id='protocol')
        except (ConnectError, ValueError) as e:
            from .pairing import friendly
            if isinstance(e, ConnectError):
                msg, code = friendly(e), e.code
            else:
                msg, code = 'The discovery document is not JSON.', 'invalid_request'
            check('Connectivity and identity', False, msg, id='identity', code=code)
        if full:
            _source_check(conn, check, peer_refused)
        token = None
        if one_way:
            for name, sid in (('Authentication', 'token'), ('Permissions', 'permissions'),
                              ('Customer mapping', 'tenants'), ('Event delivery and webhook signature', 'event')):
                check(name, True, 'Not tested: this installation was granted nothing at the other application '
                                  '(one-directional connection).', id=sid, status='not_tested')
        elif full and not identity_ok:
            for name, sid in (('Authentication', 'token'), ('Permissions', 'permissions')):
                skip(name, sid, 'connectivity and identity')
        else:
            at_pairing = set(conn.outbound_scopes or [])     # get_token() records the token's scopes
            try:
                token = client.get_token(conn, use_cache=False)
                check('Authentication', True, 'The other application issued a short-lived, key-bound access token.',
                      id='token')
            except ConnectError as e:
                if full and not peer_refused and (e.code in ('source_not_authorised', 'http_403') or e.status == 403):
                    peer_refused = True
                    checks[:] = [c for c in checks if c['id'] != 'source']
                    _source_check(conn, check, True)
                check('Authentication', False, f'Token refused ({e.code}): {e.message}', id='token', code=e.code,
                      next_action='The other administrator completes the approval on their side, then run the '
                                  'test again.' if e.code == 'invalid_client' else '')
            if token is not None:
                granted = set(str(token.get('scope', '')).split())
                want = set(conn.requested_outbound_scopes or [])
                if full:
                    # The commit gate checks what the other side granted at
                    # pairing; a request it declined is its decision, shown
                    # but not a failure (no automatic escalation either way).
                    declined = sorted(want - at_pairing) if at_pairing else []
                    want = at_pairing
                else:
                    declined = []
                missing = sorted(want - granted)
                check('Permissions', not missing, ('All granted permissions are in the token.' +
                                                   (f' Declined by the other application: {", ".join(declined)}.'
                                                    if declined else '')) if full else
                      'All requested permissions are granted.' if not missing else
                      'Not granted by the other application: ' + ', '.join(missing), id='permissions',
                      code='scope_withdrawn')
                if full and missing:
                    checks[-1]['message'] = 'Granted at pairing but missing from the token: ' + ', '.join(missing)
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
                              f'Capabilities answered HTTP {r.status}.', id='tenants', code='insufficient_scope')
                    except ConnectError as e:
                        check('Customer mapping', False, e.message, id='tenants', code=e.code)
            elif full:
                for name, sid in (('Permissions', 'permissions'), ('Customer mapping', 'tenants')):
                    skip(name, sid, 'authentication')
        if not one_way:
            try:
                ev = events.enqueue(conn, 'connect.test', {'requested_by': 'connection test'})
                ok = events.deliver(ev)
                check('Event delivery and webhook signature', ok, 'A signed test event was accepted.' if ok else
                      f'The test event was not accepted ({ev.last_error or "no answer"}); it stays queued for retry.',
                      id='event', code='event_rejected')
            except ConnectError as e:
                check('Event delivery and webhook signature', False, e.message, id='event', code=e.code)
    report = {'ok': bool(checks) and all(c['ok'] for c in checks), 'checks': checks,
              'at': timezone.now().isoformat(), 'run_id': str(uuid.uuid4()), 'full': bool(full)}
    conn.last_test = report
    Connection.objects.filter(pk=conn.pk).update(last_test=report, updated_at=timezone.now())
    audit_log.record('connection.test', 'ok' if report['ok'] else 'failed', connection=conn, user=user,
                     detail={'failed': [c['name'] for c in checks if c['status'] == 'fail'], 'run_id': report['run_id'],
                             'full': bool(full)})
    return report
