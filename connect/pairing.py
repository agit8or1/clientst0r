"""
Pairing, both directions (PROTOCOL.md §5).

Outbound — Clientst0r connects to another app ("we are the initiator"):
    discover() → start_outbound() → poll() → approve_local()

Inbound — another app connects to Clientst0r ("we are the responder"):
    create_invitation() → receive_request() [API] → approve_inbound() / reject_inbound()
    pairing_status() [API] answers the other app's signed polls.

Granting a high_risk or admin scope is a protected change: it is applied only
when a second administrator approves it (tech_access.protected, kind
"app_connection"; applier in connect/approvals.py).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.utils import timezone

from agit8or_connect import discovery as sdk_discovery
from agit8or_connect import keys as sdk_keys
from agit8or_connect import pairing as sdk_pairing
from agit8or_connect.errors import ConnectError
from agit8or_connect.scopes import Catalog

from . import audit_log, catalog, identity, store, transport

logger = logging.getLogger('connect')

REQUEST_LIFETIME = timedelta(hours=24)


class PairingFailed(Exception):
    """Shown to the administrator; `message` is plain language, no secrets."""

    def __init__(self, message, code=''):
        super().__init__(message)
        self.message, self.code = message, code


FRIENDLY = {
    'invalid_pairing_code': 'The other application did not accept the pairing code. Check it, or ask for a new '
                            'one: codes are valid for 10 minutes and can be used once.',
    'pairing_locked': 'Too many wrong codes were tried, so the other application locked its open invitations. '
                      'Ask its administrator for a new invitation code.',
    'rate_limited': 'The other application is limiting pairing attempts. Wait a few minutes and try again.',
    'blocked_destination': 'This address is not allowed. For an internal address (private IP, VPN or private '
                           'DNS) open Advanced settings and allow private networks for this connection. Cloud '
                           'metadata addresses are always blocked.',
    'transport_error': 'The other application could not be reached. Check the address, that it is reachable '
                       'from this server, and its TLS certificate (for a private CA, add the CA bundle under '
                       'Advanced settings).',
    'unsupported_version': 'The other application does not speak a protocol version this Clientst0r supports. '
                           'Update the older side.',
    'invalid_request': 'The other application answered with something that is not valid Agit8or Connect.',
    'invalid_signature': 'A signature from the other application did not verify. Do not continue: the address '
                         'may not lead to the application you expect.',
    'kill_switch': 'Connected applications are stopped by the emergency kill switch.',
}


def friendly(e: ConnectError) -> str:
    return FRIENDLY.get(e.code, e.message)


def _refuse_if_stopped():
    """Nothing becomes (or moves towards) active while the kill switch is
    engaged (PROTOCOL.md §12). Checked in every approval and activation path,
    not only in the UI."""
    if identity.kill_switch_engaged():
        raise PairingFailed(FRIENDLY['kill_switch'], 'kill_switch')


def _require_public_url():
    """Pairing messages carry our absolute URLs; never send relative ones."""
    problem = identity.public_url_problem()
    if problem:
        raise PairingFailed(problem, identity.NOT_CONFIGURED)


def duplicate_connections(conn):
    """Other connections here to the installation id `conn` claims: connected,
    suspended, or approved here and waiting on the other side / a second
    administrator. Other unreviewed inbound requests do not count."""
    from django.db.models import Q
    from .models import Connection
    connected = (Connection.ACTIVE, Connection.SUSPENDED, Connection.AWAITING_REMOTE, Connection.AWAITING_SECOND)
    return Connection.objects.filter(
        Q(state__in=connected) | Q(state=Connection.AWAITING_LOCAL, direction=Connection.OUTBOUND),
        remote_installation_id=conn.remote_installation_id).exclude(pk=conn.pk)


def _err(data, fallback):
    err = data.get('error') if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get('code') or fallback)[:40]
    if isinstance(err, str):
        return err[:40]
    return fallback


def _json(resp):
    try:
        return json.loads(resp.body or b'{}')
    except ValueError:
        return {}


def org_tenant(org) -> dict:
    return {'id': catalog.tenant_id(org), 'label': org.name[:200]}


def scope_fingerprint(connection, scopes, grants) -> str:
    raw = json.dumps([str(connection.pk), sorted(store.remote_keyring(connection)), sorted(scopes),
                      sorted([int(o), str(t), sorted(s)] for o, t, s in grants)])
    return hashlib.sha256(raw.encode()).hexdigest()


# --- outbound ----------------------------------------------------------------------

def discover(base_url: str, *, allow_private=False, ca_pem='') -> sdk_discovery.DiscoveryInfo:
    try:
        info = sdk_discovery.fetch(transport.for_settings(allow_private=allow_private, ca_pem=ca_pem,
                                                          base_url=base_url), base_url)
    except ConnectError as e:
        raise PairingFailed(friendly(e), e.code) from e
    if info.installation_id == identity.installation_id():
        raise PairingFailed('That address is this Clientst0r installation itself.', 'self')
    return info


def start_outbound(info: sdk_discovery.DiscoveryInfo, code: str, *, requested_scopes: Sequence[str],
                   organizations: Iterable = (), user=None, allow_private=False, ca_pem='',
                   rotation_interval_days=90):
    from .models import Connection
    _refuse_if_stopped()
    _require_public_url()
    try:
        sdk_pairing.normalize_code(code)
    except ConnectError as e:
        raise PairingFailed('A pairing code is 10 letters and digits, like 7K3QM-9XD2P.', e.code) from e
    unknown = [s for s in requested_scopes if s not in info.catalog.by_name]
    if unknown or not requested_scopes:
        raise PairingFailed('Choose at least one permission the other application offers.', 'invalid_scope')
    if Connection.objects.filter(remote_installation_id=info.installation_id,
                                 state__in=(Connection.ACTIVE, Connection.AWAITING_REMOTE,
                                            Connection.AWAITING_LOCAL, Connection.AWAITING_SECOND)).exists():
        raise PairingFailed('This Clientst0r already has a connection to that installation. Disconnect it '
                            'first to pair again.', 'duplicate')
    orgs = list(organizations)
    conn = Connection.objects.create(
        direction=Connection.OUTBOUND, state=Connection.PENDING_PAIRING, remote_app_type=info.app_type[:64],
        remote_installation_id=info.installation_id, remote_display_name=info.display_name,
        remote_app_version=info.app_version, remote_protocol_version=info.version, base_url=info.url,
        remote_endpoints=info.endpoints, remote_catalog=info.catalog.as_list(),
        requested_outbound_scopes=sorted(set(requested_scopes)), allow_private_network=allow_private,
        tls_ca_bundle=ca_pem or '', proposed_tenants=[org_tenant(o) for o in orgs],
        rotation_interval_days=rotation_interval_days, created_by=user)
    row, priv = store.new_key(conn)
    req, claims = sdk_pairing.build_request(
        priv, initiator_app=identity.app_info(), responder_installation=info.installation_id, pairing_code=code,
        connection_id=str(conn.pk), discovery_url=identity.public_base() + sdk_discovery.WELL_KNOWN,
        requested_scopes=requested_scopes, proposed_tenants=conn.proposed_tenants)
    try:
        r = transport.for_connection(conn).request(
            'POST', info.endpoints['pairing'], headers={'Content-Type': 'application/json',
                                                        'Accept': 'application/json'},
            body=json.dumps({'request': req}).encode())
        data = _json(r)
        if r.status != 202:
            raise ConnectError(_err(data, f'http_{r.status}'), f'pairing answered HTTP {r.status}', r.status)
        ack, rjwk = sdk_pairing.verify_ack(data.get('ack', ''), initiator_installation=identity.installation_id(),
                                           responder_installation=info.installation_id, request_jti=claims['jti'])
    except ConnectError as e:
        conn.state, conn.last_error, conn.last_failure_at = Connection.FAILED, friendly(e)[:500], timezone.now()
        conn.save(update_fields=['state', 'last_error', 'last_failure_at', 'updated_at'])
        audit_log.record('pairing.outbound_submitted', e.code, connection=conn, user=user,
                         app=info.installation_id, scopes=requested_scopes)
        raise PairingFailed(friendly(e), e.code) from e
    conn.remote_connection_id = str(ack['connection_id'])[:128]
    conn.remote_jwks = {'keys': [rjwk]}
    conn.pairing_request_id = str(data.get('request_id') or ack['request_id'])[:128]
    conn.pairing_request_jti, conn.pairing_request_jws = claims['jti'], req
    conn.sas = sdk_pairing.short_authentication_string(sdk_pairing.transcript_hash(
        request_jws=req, request_jti=claims['jti'], initiator_installation=identity.installation_id(),
        initiator_jkt=row.kid, responder_installation=info.installation_id, responder_jkt=rjwk['kid']))
    conn.state = Connection.AWAITING_REMOTE
    conn.save()
    audit_log.record('pairing.outbound_submitted', 'ok', connection=conn, user=user, app=info.installation_id,
                     scopes=requested_scopes, detail={'tenants_proposed': len(orgs)})
    return conn


def poll(conn) -> str:
    """'pending' | 'approved' | 'rejected'. Signed with our connection key."""
    from .models import Connection
    if conn.state != Connection.AWAITING_REMOTE:
        return conn.state
    _, priv = store.active_key(conn)
    proof = sdk_pairing.build_poll(priv, initiator_installation=identity.installation_id(),
                                   responder_installation=conn.remote_installation_id,
                                   request_id=conn.pairing_request_id)
    try:
        r = transport.for_connection(conn).request(
            'POST', conn.endpoint('pairing_status', request_id=conn.pairing_request_id),
            headers={'Content-Type': 'application/json'}, body=json.dumps({'proof': proof}).encode())
        data = _json(r)
        if r.status != 200:
            raise ConnectError(_err(data, f'http_{r.status}'), f'status answered HTTP {r.status}', r.status)
        if data.get('status') != 'decided':
            return 'pending'
        (rkey,) = store.remote_keyring(conn).values()
        res = sdk_pairing.verify_result(data.get('result', ''), rkey, initiator_installation=identity.installation_id(),
                                        responder_installation=conn.remote_installation_id,
                                        request_jti=conn.pairing_request_jti)
    except ConnectError as e:
        conn.last_error, conn.last_failure_at = friendly(e)[:500], timezone.now()
        conn.save(update_fields=['last_error', 'last_failure_at', 'updated_at'])
        raise PairingFailed(friendly(e), e.code) from e
    if res['status'] == 'rejected':
        conn.state, conn.last_error = Connection.FAILED, 'The other application\'s administrator rejected the pairing.'
        conn.save()
        audit_log.record('pairing.outbound_result', 'rejected', connection=conn, app=conn.remote_installation_id)
        return 'rejected'
    if res.get('connection_id') != conn.remote_connection_id:
        raise PairingFailed(FRIENDLY['invalid_signature'], 'invalid_signature')
    conn.outbound_scopes = sorted(s for s in res.get('granted_scopes', []) if isinstance(s, str))
    conn.peer_requested_scopes = sorted(s for s in res.get('requested_scopes', []) if isinstance(s, str))
    conn.remote_tenant_grants = sdk_pairing.tenant_list(
        [{'id': g.get('tenant'), **g} for g in res.get('tenant_grants', []) if isinstance(g, dict)])
    conn.state = Connection.AWAITING_LOCAL
    conn.last_success_at = timezone.now()
    conn.save()
    audit_log.record('pairing.outbound_result', 'approved', connection=conn, app=conn.remote_installation_id,
                     scopes=conn.outbound_scopes)
    return 'approved'


def _validate_grants(scopes, grants) -> List[Tuple[int, str, List[str]]]:
    from agit8or_connect.tenants import TENANT_ID_RE
    from core.models import Organization
    out, seen_org, seen_remote = [], set(), set()
    for org_id, remote, gscopes in grants:
        remote = str(remote or '').strip()
        if not TENANT_ID_RE.match(remote):
            raise PairingFailed(f'"{remote[:40]}" is not a valid tenant id of the other application.')
        if not Organization.objects.filter(pk=org_id).exists():
            raise PairingFailed('A selected customer does not exist.')
        if int(org_id) in seen_org or remote in seen_remote:
            raise PairingFailed('Each customer and each remote tenant can be mapped only once per connection.')
        bad = sorted(set(gscopes) - set(scopes))
        if bad:
            raise PairingFailed(f'A customer was given "{bad[0]}", which the connection itself is not granted.')
        seen_org.add(int(org_id))
        seen_remote.add(remote)
        out.append((int(org_id), remote, sorted(set(gscopes))))
    return out


def _check_grantable(scopes, peer_requested):
    for s in scopes:
        sc = catalog.CATALOG.get(s)
        if sc is None:
            raise PairingFailed(f'"{s}" is not a permission Clientst0r offers.', 'invalid_scope')
        if not sc.available:
            raise PairingFailed(f'"{sc.description}" is not available in this release yet.', 'invalid_scope')
        if s not in set(peer_requested):
            raise PairingFailed(f'The other application did not ask for "{s}".', 'invalid_scope')


def _apply_grants(conn, grants, user):
    from .models import TenantGrant
    for org_id, remote, gscopes in grants:
        g, created = TenantGrant.objects.get_or_create(
            connection=conn, organization_id=org_id,
            defaults={'remote_tenant_id': remote, 'scopes': gscopes, 'created_by': user})
        if not created:
            g.remote_tenant_id, g.scopes, g.active, g.revoked_at, g.revoked_by = remote, gscopes, True, None, None
            g.save()
        audit_log.record('tenant_grant.created', 'ok', connection=conn, user=user, tenant=remote, scopes=gscopes,
                         detail={'organization_id': org_id})


def _needs_second_admin(scopes) -> bool:
    return bool(catalog.CATALOG.elevated(scopes))


def _propose(conn, mode, scopes, grants, user, request, requested_scopes=(), duplicate_of=()):
    from tech_access.protected import propose
    elevated = catalog.CATALOG.elevated(scopes)
    name = conn.remote_display_name or conn.remote_app_type
    parts = []
    widening = [f'App permission {s}' for s in elevated]
    if duplicate_of:
        parts.append(f'second connection for installation {conn.remote_installation_id}, which is already '
                     'connected here')
        widening.insert(0, f'Another connection claiming installation {conn.remote_installation_id} '
                           '(already connected)')
    if elevated:
        parts.append('grant ' + ', '.join(elevated))
    change = propose('app_connection', f'Connected application "{name}": ' + '; '.join(parts),
                     {'connection': str(conn.pk), 'mode': mode, 'scopes': sorted(scopes),
                      'grants': [[o, t, s] for o, t, s in grants], 'requested_scopes': sorted(requested_scopes),
                      'duplicate_of': sorted(str(c) for c in duplicate_of),
                      'fingerprint': scope_fingerprint(conn, scopes, grants)},
                     widening, user, request=request)
    return change


def approve_local(conn, *, scopes: Sequence[str], grants, user, request=None):
    """Outbound connection: approve what the other app asked of us."""
    from .models import Connection
    _refuse_if_stopped()
    if conn.state != Connection.AWAITING_LOCAL or conn.direction != Connection.OUTBOUND:
        raise PairingFailed('This connection is not waiting for approval here.')
    scopes = sorted(set(scopes))
    _check_grantable(scopes, conn.peer_requested_scopes)
    grants = _validate_grants(scopes, grants)
    if _needs_second_admin(scopes):
        change = _propose(conn, 'local', scopes, grants, user, request)
        conn.state = Connection.AWAITING_SECOND
        conn.save(update_fields=['state', 'updated_at'])
        audit_log.record('pairing.second_approval_requested', 'pending', connection=conn, user=user, scopes=scopes,
                         detail={'protected_change': change.pk})
        return change
    finalize_local(conn, scopes, grants, user)
    return None


def finalize_local(conn, scopes, grants, user):
    from .models import Connection
    _refuse_if_stopped()
    with transaction.atomic():
        conn.inbound_scopes = sorted(set(scopes))
        conn.inbound_event_types = _event_types(scopes)
        _apply_grants(conn, grants, user)
        _activate(conn)
    audit_log.record('pairing.activated', 'ok', connection=conn, user=user, scopes=conn.inbound_scopes,
                     detail={'direction': Connection.OUTBOUND, 'grants': len(grants)})


def _event_types(scopes) -> List[str]:
    out = set()
    for s in scopes:
        sc = catalog.CATALOG.get(s)
        if sc:
            out.update(e for e in sc.events if e in catalog.INBOUND_EVENT_TYPES)
    return sorted(out)


def _activate(conn):
    from .models import Connection
    _refuse_if_stopped()   # inside the caller's transaction: raising rolls the approval back
    conn.state = Connection.ACTIVE
    conn.next_rotation_at = timezone.now() + timedelta(days=conn.rotation_interval_days or 90)
    conn.save()


# --- inbound ----------------------------------------------------------------------

def create_invitation(user, label='', ttl_seconds=sdk_pairing.CODE_TTL):
    from .models import PairingInvitation
    _refuse_if_stopped()
    _require_public_url()
    code = sdk_pairing.generate_code()
    inv = PairingInvitation.objects.create(code_hash=sdk_pairing.hash_code(code, identity.pairing_pepper()),
                                           label=label[:200], expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
                                           created_by=user)
    audit_log.record('pairing.invitation_created', 'ok', user=user, detail={'invitation': str(inv.pk)})
    return inv, code


def _burn_attempt():
    """A wrong code counts against EVERY open invitation; at five they burn."""
    from .models import PairingInvitation
    now = timezone.now()
    with transaction.atomic():
        open_qs = PairingInvitation.objects.select_for_update().filter(used_at=None, burned_at=None,
                                                                       expires_at__gt=now)
        rows = list(open_qs)
        for inv in rows:
            inv.attempts += 1
            if inv.attempts >= inv.max_attempts:
                inv.burned_at = now
            inv.save(update_fields=['attempts', 'burned_at'])
    return rows and all(r.burned_at for r in rows)


def receive_request(token: str, source_ip: str = '') -> dict:
    """API: verify an inbound pairing request, consume the code, create the
    pending connection, answer with our signed ack."""
    from .models import Connection, PairingInvitation, PairingRequest
    claims, jwk = sdk_pairing.verify_request(token, responder_installation=identity.installation_id(),
                                             replay=store.replay_store)
    try:
        code_hash = sdk_pairing.hash_code(claims['pairing_code'], identity.pairing_pepper())
    except ConnectError:
        code_hash = ''
    with transaction.atomic():
        inv = PairingInvitation.objects.select_for_update().filter(
            code_hash=code_hash, used_at=None, burned_at=None, expires_at__gt=timezone.now()).first() \
            if code_hash else None
        if inv is not None:
            inv.used_at = timezone.now()
            inv.save(update_fields=['used_at'])
    if inv is None:
        locked = _burn_attempt()
        if locked:   # once per burn of the open invitations: kept in the chain
            audit_log.record('pairing.code_rejected', 'locked', app=str(claims['iss'])[:128],
                             detail={'source_ip': source_ip})
        else:        # repeatable by anyone: folded refusal log, summarised into the chain (QC-03)
            from . import denials
            denials.note(denials.CODE_REJECTED, source_ip=source_ip, path=denials.PAIRING_PATH)
        if locked:
            raise ConnectError('pairing_locked', 'too many wrong codes: ask for a new invitation', 403)
        raise ConnectError('invalid_pairing_code', 'pairing code invalid or expired', 400)
    app = claims['app']
    requested = sorted({s for s in claims.get('requested_scopes') or [] if isinstance(s, str)})[:64]
    with transaction.atomic():
        conn = Connection.objects.create(
            direction=Connection.INBOUND, state=Connection.AWAITING_LOCAL,
            remote_app_type=str(app.get('type') or '')[:64] or 'unknown',
            remote_installation_id=str(claims['iss'])[:128], remote_display_name=str(app.get('display_name') or '')[:200],
            remote_app_version=str(app.get('version') or '')[:64],
            base_url=str(claims.get('discovery_url') or '')[:500], remote_connection_id=str(claims['connection_id'])[:128],
            remote_jwks={'keys': [jwk]}, peer_requested_scopes=requested,
            proposed_tenants=sdk_pairing.tenant_list(claims.get('proposed_tenants'))[:200],
            pairing_request_jti=claims['jti'], pairing_request_jws=token, created_by=inv.created_by)
        row, priv = store.new_key(conn)
        conn.sas = sdk_pairing.short_authentication_string(sdk_pairing.transcript_hash(
            request_jws=token, request_jti=claims['jti'], initiator_installation=claims['iss'],
            initiator_jkt=jwk['kid'], responder_installation=identity.installation_id(), responder_jkt=row.kid))
        conn.save()
        preq = PairingRequest.objects.create(invitation=inv, connection=conn, initiator_jwk=jwk,
                                             source_ip=source_ip or None,
                                             expires_at=timezone.now() + REQUEST_LIFETIME)
        conn.pairing_request_id = str(preq.pk)
        conn.save(update_fields=['pairing_request_id'])
    ack = sdk_pairing.build_ack(priv, responder_app=identity.app_info(), initiator_installation=claims['iss'],
                                request_id=str(preq.pk), request_jti=claims['jti'], connection_id=str(conn.pk))
    audit_log.record('pairing.inbound_received', 'pending', connection=conn, app=conn.remote_installation_id,
                     scopes=requested, detail={'source_ip': source_ip, 'app_type': conn.remote_app_type})
    return {'status': 'pending_approval', 'request_id': str(preq.pk), 'ack': ack}


def pairing_status(request_id: str, proof: str) -> dict:
    from .models import PairingRequest
    preq = PairingRequest.objects.select_related('connection').filter(pk=request_id).first()
    if preq is None:
        raise ConnectError('not_found', 'unknown pairing request', 404)
    conn = preq.connection
    sdk_pairing.verify_poll(proof, sdk_keys.public_key_from_jwk(preq.initiator_jwk),
                            initiator_installation=conn.remote_installation_id,
                            responder_installation=identity.installation_id(), request_id=str(preq.pk),
                            replay=store.replay_store)
    if preq.status in (PairingRequest.PENDING, PairingRequest.AWAITING_SECOND) and preq.expires_at <= timezone.now():
        _reject(preq, None, expired=True)
    if preq.result_jws:
        return {'status': 'decided', 'result': preq.result_jws}
    return {'status': 'pending_approval'}


def refresh_remote_discovery(conn):
    info = sdk_discovery.fetch(transport.for_connection(conn), conn.base_url)
    if info.installation_id != conn.remote_installation_id:
        raise ConnectError('invalid_signature', 'the other application\'s address now leads to a different '
                                                'installation')
    conn.remote_endpoints = info.endpoints
    conn.remote_catalog = info.catalog.as_list()
    conn.remote_protocol_version = info.version
    conn.remote_app_version = info.app_version or conn.remote_app_version
    return info


def approve_inbound(preq, *, scopes, grants, requested_scopes=(), user, request=None, allow_private=False,
                    ca_pem=''):
    from .models import Connection, PairingRequest
    conn = preq.connection
    _refuse_if_stopped()
    _require_public_url()
    if preq.status != PairingRequest.PENDING or preq.expires_at <= timezone.now():
        raise PairingFailed('This pairing request is no longer waiting for a decision.')
    scopes = sorted(set(scopes))
    _check_grantable(scopes, conn.peer_requested_scopes)
    grants = _validate_grants(scopes, grants)
    conn.allow_private_network, conn.tls_ca_bundle = bool(allow_private), ca_pem or ''
    try:
        info = refresh_remote_discovery(conn)
    except ConnectError as e:
        raise PairingFailed('Clientst0r could not verify the other application\'s address: ' + friendly(e),
                            e.code) from e
    unknown = [s for s in requested_scopes if s not in info.catalog.by_name]
    if unknown:
        raise PairingFailed(f'The other application does not offer "{unknown[0]}".', 'invalid_scope')
    conn.requested_outbound_scopes = sorted(set(requested_scopes))
    conn.save()
    duplicates = list(duplicate_connections(conn).values_list('pk', flat=True))
    if _needs_second_admin(scopes) or duplicates:
        change = _propose(conn, 'inbound', scopes, grants, user, request, requested_scopes, duplicate_of=duplicates)
        preq.status, preq.protected_change_id = PairingRequest.AWAITING_SECOND, change.pk
        preq.save(update_fields=['status', 'protected_change_id'])
        conn.state = Connection.AWAITING_SECOND
        conn.save(update_fields=['state', 'updated_at'])
        audit_log.record('pairing.second_approval_requested', 'pending', connection=conn, user=user, scopes=scopes,
                         detail={'protected_change': change.pk, 'duplicate_installation': bool(duplicates)})
        return change
    finalize_inbound(preq, scopes, grants, conn.requested_outbound_scopes, user)
    return None


def finalize_inbound(preq, scopes, grants, requested_scopes, user):
    from core.models import Organization
    from .models import PairingRequest
    conn = preq.connection
    _refuse_if_stopped()
    _, priv = store.active_key(conn)
    with transaction.atomic():
        conn.inbound_scopes = sorted(set(scopes))
        conn.inbound_event_types = _event_types(scopes)
        _apply_grants(conn, grants, user)
        names = dict(Organization.objects.filter(pk__in=[g[0] for g in grants]).values_list('pk', 'name'))
        preq.result_jws = sdk_pairing.build_result(
            priv, responder_installation=identity.installation_id(), initiator_installation=conn.remote_installation_id,
            request_id=str(preq.pk), request_jti=conn.pairing_request_jti, status='approved',
            connection_id=str(conn.pk), granted_scopes=conn.inbound_scopes,
            tenant_grants=[{'tenant': catalog.tenant_id(o), 'label': names.get(o, '')[:200], 'remote_tenant': t,
                            'scopes': s} for o, t, s in grants],
            requested_scopes=requested_scopes, endpoints=identity.endpoints())
        preq.status, preq.decided_at, preq.decided_by = PairingRequest.APPROVED, timezone.now(), user
        preq.save()
        _activate(conn)
    audit_log.record('pairing.activated', 'ok', connection=conn, user=user, scopes=conn.inbound_scopes,
                     detail={'direction': 'inbound', 'grants': len(grants)})


def _reject(preq, user, expired=False):
    from .models import Connection, PairingRequest
    conn = preq.connection
    _, priv = store.active_key(conn)
    preq.result_jws = sdk_pairing.build_result(
        priv, responder_installation=identity.installation_id(), initiator_installation=conn.remote_installation_id,
        request_id=str(preq.pk), request_jti=conn.pairing_request_jti, status='rejected', connection_id=str(conn.pk))
    preq.status = PairingRequest.EXPIRED if expired else PairingRequest.REJECTED
    preq.decided_at, preq.decided_by = timezone.now(), user
    preq.save()
    conn.state = Connection.FAILED
    conn.last_error = 'Pairing request expired.' if expired else 'Pairing rejected here.'
    conn.save()
    from . import lifecycle
    lifecycle.retire_keys(conn)
    audit_log.record('pairing.rejected', 'expired' if expired else 'rejected', connection=conn, user=user,
                     app=conn.remote_installation_id)


def reject_inbound(preq, user):
    from .models import PairingRequest
    if preq.status not in (PairingRequest.PENDING, PairingRequest.AWAITING_SECOND):
        raise PairingFailed('This pairing request is no longer waiting for a decision.')
    _reject(preq, user)


def catalog_for(conn) -> Catalog:
    return Catalog.from_list(conn.remote_catalog)
