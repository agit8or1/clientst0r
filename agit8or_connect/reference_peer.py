"""
An in-memory Agit8or Connect installation built only on this SDK.

It plays either role (responder: creates invitations, approves requests,
issues tokens, receives events; initiator: pairs with a code, polls, gets
tokens, calls APIs, sends events), with one key pair per connection,
DPoP-bound tokens, endorsed JWKS rotation and per-connection tenant grants.

Used by the SDK's own end-to-end tests (two reference peers pairing with each
other, and two "MSP" installations connecting to one responder) and by
Clientst0r's Django tests as the "other application" — no other app
implements Connect yet. It is also the most compact worked example of the
protocol for an implementer (IMPLEMENTING.md).

Protocol revision 1.1 (PROTOCOL-1.1.md): with `quick_connect=True` the peer
advertises qc-bootstrap/1, qc-source-binding/1 and qc-diagnostics/1 and can
pair through the browser-mediated flow (qc_start -> qc_review ->
qc_authorize -> qc_callback), then continues with the unchanged v1 poll,
result, tokens and events. Without it (the default) the peer is exactly the
v1-only peer it always was, which is how 1.0 <-> 1.1 interop is tested.

It is NOT production code: state lives in dicts, and requests are routed by a
`Network` object instead of sockets.
"""
from __future__ import annotations

import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from . import PROTOCOL_ID, discovery, keys, pairing, rotation, tokens, webhooks
from . import quick_connect as qc
from .canonical import sha256_hex
from .errors import (ConnectError, CONNECTION_INACTIVE, EXTENSION_NOT_NEGOTIATED, IDENTITY_MISMATCH, INVALID_CLIENT,
                     INVALID_PAIRING_CODE, INVALID_REQUEST, INVALID_SCOPE, PAIRING_LOCKED,
                     SOURCE_NOT_AUTHORISED)
from .http import Response
from .replay import MemoryReplayStore
from .scopes import HIGH_RISK, READ, WRITE, ADMIN, Catalog, Scope, parse_scope_string, require_subset
from .tenants import MemoryTenantResolver, TenantGrant, authorize

API = '/connect/v1'

REFERENCE_CATALOG = Catalog([
    Scope('connection:read', 'See this connection: granted permissions and customers', READ),
    Scope('customers:read', 'Read the names of granted customers', READ),
    Scope('devices:read', 'Read device inventory of granted customers', READ),
    Scope('events:publish', 'Deliver events (alerts, status changes) for granted customers', WRITE,
          events=('alert.raised', 'alert.resolved', 'connect.test')),
    Scope('tickets:write', 'Create tickets for granted customers', WRITE),
    Scope('remote_actions:execute', 'Run remote actions on customer devices (each action approved)', HIGH_RISK),
    Scope('connection:admin', 'Change this connection\'s settings remotely', ADMIN),
])


class Network:
    """Routes requests by origin to in-memory handlers. Also a Transport."""

    def __init__(self):
        self.handlers: Dict[str, Callable] = {}
        self.down: set = set()
        self.log: List[tuple] = []
        # Source address a handler sees (PROTOCOL-1.1.md qc-source-binding/1):
        # the `source` a sender passes, else `default_source`.
        self.default_source: Optional[str] = None
        self._sources: List[Optional[str]] = []

    def current_source(self) -> Optional[str]:
        return self._sources[-1] if self._sources else None

    def register(self, base_url: str, handler: Callable):
        self.handlers[discovery.origin(base_url)] = handler

    def request(self, method, url, headers=None, body=None, source=None) -> Response:
        o = discovery.origin(url)
        self.log.append((method, url))
        if o in self.down:
            raise ConnectError('transport_error', 'network unreachable', 502)
        h = self.handlers.get(o)
        if h is None:
            raise ConnectError('transport_error', 'host unreachable', 502)
        self._sources.append(source if source is not None else self.default_source)
        try:
            return h(method, url, dict(headers or {}), body or b'')
        finally:
            self._sources.pop()


@dataclass
class PeerConnection:
    id: str
    role: str                          # 'initiator' | 'responder'
    state: str                         # pending | awaiting_remote_approval | awaiting_local_approval | active | revoked
    keys: Dict[str, dict] = field(default_factory=dict)   # kid -> {'private', 'state', 'activated_at', 'retire_after'}
    remote_installation: str = ''
    remote_app: dict = field(default_factory=dict)
    remote_connection_id: str = ''
    remote_keys: Dict[str, object] = field(default_factory=dict)
    remote_endpoints: dict = field(default_factory=dict)
    inbound_scopes: List[str] = field(default_factory=list)    # what the peer may do on us
    outbound_scopes: List[str] = field(default_factory=list)   # what we may do on the peer
    peer_requested_scopes: List[str] = field(default_factory=list)
    proposed_tenants: List[dict] = field(default_factory=list)
    request_id: str = ''
    request_jti: str = ''
    request_jws: str = ''
    sas: str = ''
    result: dict = field(default_factory=dict)
    tokens_not_before: int = 0
    received_events: List[dict] = field(default_factory=list)
    token_cache: dict = field(default_factory=dict)

    def active_key(self):
        for kid, k in self.keys.items():
            if k['state'] == rotation.ACTIVE:
                return kid, k['private']
        raise ConnectError(CONNECTION_INACTIVE, 'no active key')

    def verifying_keys(self):
        return {kid: k['private'].public_key() for kid, k in self.keys.items()
                if k['state'] in rotation.VERIFYING_STATES}

    def published_keys(self):
        return [keys.public_jwk(k['private']) for k in self.keys.values() if k['state'] in rotation.PUBLISHED_STATES]


class ReferencePeer:
    def __init__(self, base_url: str, network: Network, *, app_type: str = 'reference-peer',
                 display_name: str = 'Reference peer', catalog: Catalog = REFERENCE_CATALOG,
                 clock: Callable[[], float] = time.time, tenants: Optional[Dict[str, str]] = None,
                 quick_connect: bool = False, egress: Optional[List[str]] = None,
                 source_address: Optional[str] = None):
        self.base = base_url.rstrip('/')
        self.network = network
        self.installation_id = str(uuid.uuid4())
        self.app = {'type': app_type, 'version': '1.0.0', 'display_name': display_name,
                    'installation_id': self.installation_id}
        self.catalog = catalog
        self.clock = clock
        self.replay = MemoryReplayStore(clock)
        self.grants = MemoryTenantResolver()
        self.tenants = dict(tenants or {'cust-1': 'Customer One', 'cust-2': 'Customer Two'})
        self.pepper = secrets.token_bytes(32)
        self.invitations: List[dict] = []
        self.connections: Dict[str, PeerConnection] = {}
        self.requests: Dict[str, str] = {}   # request id -> connection id
        self.event_handlers: Dict[str, Callable] = {}
        # Protocol 1.1 (Quick Connect). `egress` is what this installation
        # declares (signed); `source_address` is where its requests come from.
        self.quick_connect = quick_connect
        self.qc_advertise = quick_connect        # tests flip it to simulate a stripped discovery document
        self.egress = list(egress or [])
        self.source_address = source_address
        self.qc_attempts: Dict[str, dict] = {}   # initiator: state -> attempt
        self.qc_reviews: Dict[str, dict] = {}    # responder: review id -> verified invitation
        self.qc_grants: Dict[str, dict] = {}     # responder: sha256(code) -> grant + temporary rule
        self.qc_last_reached: Dict[str, int] = {}
        network.register(self.base, self.handle)

    # --- helpers --------------------------------------------------------------------
    def now(self) -> int:
        return int(self.clock())

    def url(self, path: str) -> str:
        return self.base + path

    def endpoints(self) -> dict:
        return {'pairing': self.url(f'{API}/pairing/requests'),
                'pairing_status': self.url(f'{API}/pairing/requests/{{request_id}}/status'),
                'token': self.url(f'{API}/token'),
                'jwks': self.url(f'{API}/connections/{{connection_id}}/jwks'),
                'health': self.url(f'{API}/health'), 'capabilities': self.url(f'{API}/capabilities'),
                'events': self.url(f'{API}/events'), 'test': self.url(f'{API}/test'),
                'api_base': self.url(API)}

    def document(self) -> dict:
        doc = discovery.build_document(app=self.app, endpoints=self.endpoints(), catalog=self.catalog,
                                       events=['alert.raised', 'alert.resolved', 'connect.test'],
                                       tenant_model={'name': 'customer', 'description': 'A business the '
                                                     'operator serves'})
        if self.qc_advertise:
            doc = qc.extend_discovery_document(doc, self.base)
        return doc

    def _send(self, method, url, headers=None, body=None) -> Response:
        """Outbound request from this installation's source address."""
        return self.network.request(method, url, headers, body, source=self.source_address)

    def _new_key(self, conn: PeerConnection, state=rotation.ACTIVE):
        k = keys.generate_private_key()
        conn.keys[keys.thumbprint(k)] = {'private': k, 'state': state, 'activated_at': self.now(),
                                         'retire_after': None}
        return k

    @staticmethod
    def _json(status, obj, headers=None):
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        return Response(status, h, json.dumps(obj).encode())

    def _err(self, e: ConnectError):
        return self._json(e.status, e.as_dict())

    # --- server side -----------------------------------------------------------------
    def handle(self, method, url, headers, body) -> Response:
        path = urlsplit(url).path
        try:
            if method == 'GET' and path == discovery.WELL_KNOWN:
                return self._json(200, self.document())
            if method == 'GET' and path == f'{API}/health':
                return self._json(200, {'status': 'ok', 'protocol': PROTOCOL_ID, 'time': self.now()})
            if method == 'POST' and path == f'{API}/pairing/requests':
                return self._pairing_submit(json.loads(body or b'{}'))
            if method == 'POST' and path.startswith(f'{API}/pairing/requests/') and path.endswith('/status'):
                return self._pairing_status(path.split('/')[-2], json.loads(body or b'{}'))
            if method == 'POST' and path == f'{API}/token':
                return self._token(headers, body)
            if method == 'GET' and path.startswith(f'{API}/connections/') and path.endswith('/jwks'):
                conn = self.connections.get(path.split('/')[-2])
                if conn is None or conn.state == 'revoked':
                    return self._json(404, {'error': {'code': 'not_found', 'message': 'not found'}})
                _, active = conn.active_key()
                return self._json(200, keys.endorsed_jwks(active, conn.published_keys(), self.installation_id,
                                                          conn.id, now=self.now()))
            if method == 'POST' and path == f'{API}/events':
                return self._events(headers, body)
            if path in (f'{API}/capabilities', f'{API}/test', f'{API}/customers/current'):
                return self._resource(method, url, path, headers)
            if self.quick_connect and method == 'POST' and path == qc.EXCHANGE_PATH:
                return self._qc_exchange(url, headers, body)
            if self.quick_connect and method == 'POST' and path == qc.PROBE_PATH:
                return self._qc_probe(method, url, headers, body)
            return self._json(404, {'error': {'code': 'not_found', 'message': 'not found'}})
        except ConnectError as e:
            return self._err(e)

    def create_invitation(self) -> str:
        code = pairing.generate_code()
        self.invitations.append({'hash': pairing.hash_code(code, self.pepper), 'expires': self.now() + pairing.CODE_TTL,
                                 'attempts': 0, 'used': False, 'burned': False})
        return code

    def _pairing_submit(self, data) -> Response:
        token = data.get('request') if isinstance(data, dict) else None
        claims, jwk = pairing.verify_request(token, responder_installation=self.installation_id,
                                             replay=self.replay, now=self.now())
        open_inv = [i for i in self.invitations if not i['used'] and not i['burned'] and i['expires'] > self.now()]
        inv = next((i for i in open_inv if pairing.code_matches(claims['pairing_code'], i['hash'], self.pepper)),
                   None)
        if inv is None:
            for i in open_inv:
                i['attempts'] += 1
                if i['attempts'] >= pairing.MAX_ATTEMPTS:
                    i['burned'] = True
            if open_inv and all(i['burned'] for i in open_inv):
                raise ConnectError(PAIRING_LOCKED, 'too many wrong codes: ask for a new invitation', 403)
            raise ConnectError(INVALID_PAIRING_CODE, 'pairing code invalid or expired', 400)
        inv['used'] = True
        conn = PeerConnection(id=str(uuid.uuid4()), role='responder', state='awaiting_local_approval',
                              remote_installation=claims['iss'], remote_app=claims['app'],
                              remote_connection_id=claims['connection_id'],
                              remote_keys={jwk['kid']: keys.public_key_from_jwk(jwk)},
                              peer_requested_scopes=list(claims.get('requested_scopes') or []),
                              proposed_tenants=pairing.tenant_list(claims.get('proposed_tenants')),
                              request_id=str(uuid.uuid4()), request_jti=claims['jti'], request_jws=token)
        # Our discovery of THEM (callback / their endpoints), fetched now.
        info = discovery.fetch(self.network, claims['discovery_url'])
        if info.installation_id != claims['iss']:
            raise ConnectError(INVALID_REQUEST, 'initiator discovery identity mismatch')
        conn.remote_endpoints = info.endpoints
        my = self._new_key(conn)
        conn.sas = pairing.short_authentication_string(pairing.transcript_hash(
            request_jws=token, request_jti=claims['jti'], initiator_installation=claims['iss'],
            initiator_jkt=jwk['kid'], responder_installation=self.installation_id, responder_jkt=keys.thumbprint(my)))
        self.connections[conn.id] = conn
        self.requests[conn.request_id] = conn.id
        ack = pairing.build_ack(my, responder_app=self.app, initiator_installation=claims['iss'],
                                request_id=conn.request_id, request_jti=claims['jti'], connection_id=conn.id,
                                now=self.now())
        return self._json(202, {'status': 'pending_approval', 'request_id': conn.request_id, 'ack': ack})

    def approve(self, request_id: str, *, scopes: List[str], tenant_grants: List[dict],
                requested_scopes: List[str] = (), reject: bool = False):
        """tenant_grants: [{'remote_tenant': initiator tenant id, 'local_tenant': ours, 'scopes': [...]}]"""
        conn = self.connections[self.requests[request_id]]
        require_subset(scopes, conn.peer_requested_scopes)
        conn.inbound_scopes = sorted(set(scopes))
        conn.state = 'revoked' if reject else 'active'
        grants_out = []
        for g in tenant_grants:
            self.grants.add(TenantGrant(conn.id, g['remote_tenant'], g['local_tenant'],
                                        tuple(require_subset(g['scopes'], conn.inbound_scopes))))
            grants_out.append({'tenant': g['local_tenant'], 'label': self.tenants.get(g['local_tenant'], ''),
                               'remote_tenant': g['remote_tenant'], 'scopes': sorted(g['scopes'])})
        _, my = conn.active_key()
        conn.result = {'jws': pairing.build_result(
            my, responder_installation=self.installation_id, initiator_installation=conn.remote_installation,
            request_id=request_id, request_jti=conn.request_jti, status='rejected' if reject else 'approved',
            connection_id=conn.id, granted_scopes=conn.inbound_scopes, tenant_grants=grants_out,
            requested_scopes=requested_scopes, endpoints=self.endpoints(), now=self.now())}
        conn.outbound_scopes = sorted(set(requested_scopes))  # granted only once the initiator approves
        return conn

    def _pairing_status(self, request_id, data) -> Response:
        conn = self.connections.get(self.requests.get(request_id, ''))
        if conn is None:
            raise ConnectError('not_found', 'unknown pairing request', 404)
        (_, key), = conn.remote_keys.items()
        pairing.verify_poll(data.get('proof'), key, initiator_installation=conn.remote_installation,
                            responder_installation=self.installation_id, request_id=request_id,
                            replay=self.replay, now=self.now())
        if not conn.result:
            return self._json(200, {'status': 'pending_approval'})
        return self._json(200, {'status': 'decided', 'result': conn.result['jws']})

    def _token(self, headers, body) -> Response:
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs(body.decode('ascii', 'replace')).items()}
        try:
            if form.get('grant_type') != 'client_credentials' or \
                    form.get('client_assertion_type') != tokens.CLIENT_ASSERTION_TYPE:
                raise ConnectError('unsupported_grant_type', 'client_credentials with private_key_jwt only')
            conn = self.connections.get(form.get('client_id', ''))
            if conn is None:
                raise ConnectError(INVALID_CLIENT, 'unknown client', 401)
            if conn.state != 'active':
                raise ConnectError(INVALID_CLIENT, 'connection is not active', 401)
            endpoint = self.url(f'{API}/token')

            def key_for(kid):
                if kid not in conn.remote_keys:
                    self._refresh_remote_keys(conn)
                return conn.remote_keys.get(kid)
            claims, kid = tokens.verify_client_assertion(form.get('client_assertion', ''), key_for,
                                                         client_id=conn.id, token_endpoint=endpoint,
                                                         replay=self.replay, now=self.now())
            jkt, _ = tokens.verify_dpop_proof(headers.get('DPoP', ''), method='POST', url=endpoint,
                                              replay=self.replay, now=self.now(), allowed_jkts=[kid])
            requested = parse_scope_string(form.get('scope', '')) or list(conn.inbound_scopes)
            granted = require_subset(requested, conn.inbound_scopes)
            _, my = conn.active_key()
            at, _ = tokens.issue_access_token(my, issuer=self.installation_id, client_id=conn.id, scopes=granted,
                                              jkt=jkt, now=self.now())
            return self._json(200, {'access_token': at, 'token_type': 'DPoP', 'expires_in': 300,
                                    'scope': ' '.join(granted)}, {'Cache-Control': 'no-store'})
        except ConnectError as e:
            return self._json(e.status if e.status != 403 else 400,
                              {'error': e.code, 'error_description': e.message})

    def _refresh_remote_keys(self, conn: PeerConnection):
        url = conn.remote_endpoints['jwks'].replace('{connection_id}', conn.remote_connection_id)
        r = self.network.request('GET', url)
        if r.status == 200:
            ring = keys.verify_endorsed_jwks(json.loads(r.body), conn.remote_keys, conn.remote_installation,
                                             conn.remote_connection_id, now=self.now())
            conn.remote_keys.update(ring)

    def _authenticate(self, method, url, headers):
        def keys_for(client_id):
            c = self.connections.get(client_id)
            return c.verifying_keys() if c and c.state == 'active' else {}
        claims, client_id = tokens.authenticate_resource_request(
            authorization=headers.get('Authorization', ''), dpop=headers.get('DPoP', ''), method=method, url=url,
            issuer=self.installation_id, token_keys_for=keys_for, replay=self.replay, now=self.now())
        conn = self.connections[client_id]
        if claims['iat'] < conn.tokens_not_before:
            raise ConnectError('invalid_token', 'token issued before the connection was re-keyed', 401)
        scopes = sorted(set(claims['scopes']) & set(conn.inbound_scopes))
        return conn, scopes

    def _resource(self, method, url, path, headers) -> Response:
        conn, scopes = self._authenticate(method, url, headers)
        if path.endswith('/capabilities'):
            grants = [{'tenant': g.remote_tenant_id, 'scopes': list(g.scopes)}
                      for g in self.grants.grants.values() if g.connection_id == conn.id and g.active]
            return self._json(200, {'connection_id': conn.id, 'scopes': scopes, 'tenants': grants})
        if path.endswith('/test'):
            return self._json(200, {'ok': True, 'connection_id': conn.id, 'scopes': scopes, 'time': self.now()})
        grant = authorize(self.grants, conn.id, headers.get('Agit8or-Tenant', ''), 'customers:read', scopes)
        return self._json(200, {'tenant': grant.remote_tenant_id, 'name': self.tenants.get(grant.local_tenant)})

    def _events(self, headers, body) -> Response:
        conn = self.connections.get(headers.get(webhooks.H_CONNECTION, ''))
        if conn is None or conn.state != 'active':
            raise ConnectError('invalid_signature', 'unknown connection', 401)
        eid, _ = webhooks.verify(headers, body, conn.remote_keys, sender=conn.remote_installation,
                                 receiver=self.installation_id, connection_id=conn.id, now=self.now())
        env = webhooks.validate_envelope(json.loads(body), event_id=eid, sender=conn.remote_installation,
                                         receiver=self.installation_id)
        if not self.replay.add('event', f'{conn.id}:{eid}', self.now() + 7 * 86400):
            return self._json(200, {'status': 'duplicate', 'id': eid})
        if env['loop']:
            return self._json(200, {'status': 'ignored_loop', 'id': eid})
        if webhooks.is_connection_event(env):
            if env['type'] == 'connect.connection.revoked':
                conn.state = 'revoked'
        else:
            authorize(self.grants, conn.id, env.get('tenant', ''), 'events:publish', conn.inbound_scopes)
        conn.received_events.append(env)
        return self._json(200, {'status': 'accepted', 'id': eid})

    # --- client side ----------------------------------------------------------------
    def start_pairing(self, base_url: str, code: str, *, requested_scopes: List[str],
                      proposed_tenants: List[dict] = ()) -> PeerConnection:
        info = discovery.fetch(self.network, base_url)
        conn = PeerConnection(id=str(uuid.uuid4()), role='initiator', state='pending',
                              remote_installation=info.installation_id, remote_endpoints=info.endpoints,
                              remote_app={'type': info.app_type, 'display_name': info.display_name})
        my = self._new_key(conn)
        self.connections[conn.id] = conn
        req, claims = pairing.build_request(
            my, initiator_app=self.app, responder_installation=info.installation_id, pairing_code=code,
            connection_id=conn.id, discovery_url=self.url(discovery.WELL_KNOWN), requested_scopes=requested_scopes,
            proposed_tenants=proposed_tenants, now=self.now())
        r = self.network.request('POST', info.endpoints['pairing'], {'Content-Type': 'application/json'},
                                 json.dumps({'request': req}).encode())
        data = json.loads(r.body or b'{}')
        if r.status != 202:
            conn.state = 'failed'
            raise ConnectError(data.get('error', {}).get('code', 'pairing_failed'),
                               data.get('error', {}).get('message', ''), r.status)
        ack, rjwk = pairing.verify_ack(data['ack'], initiator_installation=self.installation_id,
                                       responder_installation=info.installation_id, request_jti=claims['jti'],
                                       now=self.now())
        conn.remote_keys = {rjwk['kid']: keys.public_key_from_jwk(rjwk)}
        conn.remote_connection_id = ack['connection_id']
        conn.request_id, conn.request_jti, conn.request_jws = data['request_id'], claims['jti'], req
        conn.sas = pairing.short_authentication_string(pairing.transcript_hash(
            request_jws=req, request_jti=claims['jti'], initiator_installation=self.installation_id,
            initiator_jkt=keys.thumbprint(my), responder_installation=info.installation_id,
            responder_jkt=rjwk['kid']))
        conn.state = 'awaiting_remote_approval'
        return conn

    def poll(self, conn_id: str) -> str:
        conn = self.connections[conn_id]
        _, my = conn.active_key()
        proof = pairing.build_poll(my, initiator_installation=self.installation_id,
                                   responder_installation=conn.remote_installation, request_id=conn.request_id,
                                   now=self.now())
        url = conn.remote_endpoints['pairing_status'].replace('{request_id}', conn.request_id)
        r = self.network.request('POST', url, {'Content-Type': 'application/json'},
                                 json.dumps({'proof': proof}).encode())
        data = json.loads(r.body or b'{}')
        if r.status != 200:
            raise ConnectError(data.get('error', {}).get('code', 'poll_failed'), '', r.status)
        if data.get('status') != 'decided':
            return 'pending'
        (_, rkey), = conn.remote_keys.items()
        res = pairing.verify_result(data['result'], rkey, initiator_installation=self.installation_id,
                                    responder_installation=conn.remote_installation, request_jti=conn.request_jti,
                                    now=self.now())
        conn.result = res
        if res['status'] == 'rejected':
            conn.state = 'revoked'
            return 'rejected'
        conn.outbound_scopes = list(res['granted_scopes'])
        conn.peer_requested_scopes = list(res['requested_scopes'])
        conn.state = 'awaiting_local_approval'
        return 'approved'

    def accept(self, conn_id: str, *, scopes: List[str] = (), tenant_grants: List[dict] = ()):
        conn = self.connections[conn_id]
        conn.inbound_scopes = require_subset(scopes, conn.peer_requested_scopes)
        for g in tenant_grants:
            self.grants.add(TenantGrant(conn.id, g['remote_tenant'], g['local_tenant'],
                                        tuple(require_subset(g['scopes'], conn.inbound_scopes))))
        conn.state = 'active'
        return conn

    def get_token(self, conn_id: str, scopes: List[str] = (), key=None) -> dict:
        conn = self.connections[conn_id]
        if key is None:
            _, key = conn.active_key()
        endpoint = conn.remote_endpoints['token']
        assertion = tokens.build_client_assertion(key, conn.remote_connection_id, endpoint, now=self.now())
        proof = tokens.build_dpop_proof(key, 'POST', endpoint, now=self.now())
        from urllib.parse import urlencode
        form = {'grant_type': 'client_credentials', 'client_id': conn.remote_connection_id,
                'client_assertion_type': tokens.CLIENT_ASSERTION_TYPE, 'client_assertion': assertion}
        if scopes:
            form['scope'] = ' '.join(scopes)
        r = self.network.request('POST', endpoint, {'Content-Type': 'application/x-www-form-urlencoded',
                                                    'DPoP': proof}, urlencode(form).encode())
        data = json.loads(r.body or b'{}')
        if r.status != 200:
            raise ConnectError(data.get('error', 'token_failed'), data.get('error_description', ''), r.status)
        conn.token_cache = {'token': data['access_token'], 'key': key}
        return data

    def call(self, conn_id: str, method: str, url: str, *, tenant: Optional[str] = None, body: bytes = b'',
             token: Optional[str] = None, key=None) -> Response:
        conn = self.connections[conn_id]
        if token is None:
            token = self.get_token(conn_id)['access_token']
        if key is None:
            _, key = conn.active_key()
        h = {'Authorization': f'DPoP {token}',
             'DPoP': tokens.build_dpop_proof(key, method, url, now=self.now(), access_token=token)}
        if tenant is not None:
            h['Agit8or-Tenant'] = tenant
        return self.network.request(method, url, h, body)

    def send_event(self, conn_id: str, event_type: str, tenant: str, data: dict, event_id=None,
                   origin=None) -> Response:
        conn = self.connections[conn_id]
        _, key = conn.active_key()
        env = webhooks.envelope(event_type=event_type, tenant=tenant, data=data, sender=self.installation_id,
                                origin=origin, event_id=event_id, occurred_at=self.now())
        body = webhooks.body_of(env)
        h = webhooks.sign(key, connection_id=conn.remote_connection_id, event_id=env['id'],
                          sender=self.installation_id, receiver=conn.remote_installation, body=body,
                          timestamp=self.now())
        return self.network.request('POST', conn.remote_endpoints['events'], h, body)

    def rotate(self, conn_id: str, overlap: int = 3600) -> bool:
        """Stage a new key, prove the peer accepts it, then promote; on
        failure the new key is marked failed and the old one stays active."""
        conn = self.connections[conn_id]
        old_kid, _ = conn.active_key()
        new = self._new_key(conn, state=rotation.STAGED)
        new_kid = keys.thumbprint(new)
        try:
            self.get_token(conn_id, key=new)
        except ConnectError:
            conn.keys[new_kid]['state'] = rotation.transition(rotation.STAGED, 'validation_failed')
            return False
        conn.keys[new_kid]['state'] = rotation.transition(rotation.STAGED, 'validated')
        conn.keys[old_kid]['state'] = rotation.transition(rotation.ACTIVE, 'superseded')
        conn.keys[old_kid]['retire_after'] = self.now() + overlap
        return True

    def revoke(self, conn_id: str):
        conn = self.connections[conn_id]
        conn.state = 'revoked'
        conn.tokens_not_before = self.now() + 1
        for k in conn.keys.values():
            k['state'] = rotation.RETIRED
        for g in self.grants.grants.values():
            if g.connection_id == conn_id:
                g.active = False

    # --- protocol 1.1: Quick Connect (qc-bootstrap/1) ----------------------------------
    # Initiator (A) ------------------------------------------------------------------------
    def qc_start(self, responder_base: str, *, requested_scopes: List[str],
                 authorize_url: Optional[str] = None) -> str:
        """Start an attempt; returns the URL the administrator's browser opens
        at the responder. Raises extension_not_negotiated when the responder's
        discovery is readable and does not offer qc-bootstrap/1 (use the v1
        code flow instead)."""
        if not self.quick_connect:
            raise ConnectError(EXTENSION_NOT_NEGOTIATED, 'this installation does not speak qc-bootstrap/1')
        if authorize_url is None:
            try:
                r = self._send('GET', discovery.discovery_url(responder_base), {'Accept': 'application/json'})
                doc = json.loads(r.body) if r.status == 200 else None
            except (ConnectError, ValueError):
                doc = None
            if doc is None:       # not readable (e.g. source policy): the conventional entry point
                authorize_url = responder_base + qc.AUTHORIZE_ENTRY_PATH
            else:
                negotiated = qc.negotiate_extensions(
                    qc.advertised_extensions(doc, discovery.discovery_url(responder_base)))
                if qc.pairing_flow(negotiated) != qc.BOOTSTRAP_ID:
                    raise ConnectError(EXTENSION_NOT_NEGOTIATED, 'the other application does not offer Quick '
                                                                 'Connect: use a pairing code')
                authorize_url = doc['endpoints']['qc_authorize']
        conn = PeerConnection(id=str(uuid.uuid4()), role='initiator', state='pending')
        my = self._new_key(conn)
        self.connections[conn.id] = conn
        verifier, state = qc.generate_pkce_verifier(), qc.generate_state()
        inv, claims = qc.build_invitation(
            my, initiator_app=self.app, responder_origin=qc.origin_of(responder_base), attempt=conn.id,
            base=self.base, redirect_uri=self.base + '/agit8or-connect/qc-callback', egress=self.egress,
            requested_scopes=requested_scopes, code_challenge=qc.pkce_challenge(verifier),
            nonce=qc.generate_nonce(), now=self.now())
        self.qc_attempts[state] = {'conn': conn.id, 'invitation': inv, 'claims': claims, 'verifier': verifier,
                                   'scopes': list(requested_scopes), 'used': False}
        return qc.authorization_url(authorize_url, inv, state)

    def qc_callback(self, url: str, *, proposed_tenants: List[dict] = ()) -> PeerConnection:
        """The browser arrives back with code + accept: verify, read the
        responder's discovery, exchange, verify the v1 ack, compute the SAS."""
        att = self.qc_attempts.get(qc.parse_query(url).get('state', ''))
        if att is None or att['used']:
            raise ConnectError('state_mismatch', 'unknown or finished attempt')
        att['used'] = True
        resp = qc.parse_authorization_response(url, expected_state=qc.parse_query(url)['state'])
        conn = self.connections[att['conn']]
        accept, bjwk = qc.verify_accept(resp['accept'], invitation=att['claims'], invitation_jws=att['invitation'],
                                        code=resp['code'], now=self.now())
        info = discovery.fetch(_Sourced(self), accept['base'])
        qc.check_discovered_identity(accept, info.raw, info.url)
        _, my = conn.active_key()
        exch, eclaims = qc.build_exchange(
            my, invitation=att['claims'], accept=accept, accept_jws=resp['accept'], code=resp['code'],
            code_verifier=att['verifier'], initiator_app=self.app, discovery_url=self.url(discovery.WELL_KNOWN),
            requested_scopes=att['scopes'], proposed_tenants=proposed_tenants, now=self.now())
        ep = info.raw['endpoints']['qc_exchange']
        r = self._send('POST', ep, {'Content-Type': 'application/json',
                                    'DPoP': tokens.build_dpop_proof(my, 'POST', ep, now=self.now())},
                       json.dumps({'exchange': exch}).encode())
        data = json.loads(r.body or b'{}')
        if r.status != 202:
            conn.state = 'failed'
            raise ConnectError(data.get('error', {}).get('code', 'pairing_failed'),
                               data.get('error', {}).get('message', ''), r.status)
        ack, ack_jwk = pairing.verify_ack(data['ack'], initiator_installation=self.installation_id,
                                          responder_installation=accept['iss'], request_jti=eclaims['jti'],
                                          now=self.now())
        qc.check_ack_key(ack_jwk, bjwk)
        conn.remote_installation = accept['iss']
        conn.remote_app = dict(accept['app'])
        conn.remote_endpoints = info.endpoints
        conn.remote_keys = {ack_jwk['kid']: keys.public_key_from_jwk(ack_jwk)}
        conn.remote_connection_id = ack['connection_id']
        conn.request_id, conn.request_jti, conn.request_jws = data['request_id'], eclaims['jti'], exch
        conn.sas = qc.sas(qc.transcript_from_messages(att['invitation'], resp['accept'], exch))
        conn.state = 'awaiting_remote_approval'
        att.update(accept=resp['accept'], code=resp['code'], exchange_url=ep)
        return conn

    # Responder (B) ------------------------------------------------------------------------
    def qc_review(self, authorize_url: str) -> str:
        """The administrator, signed in to B's own UI, opens the browser URL.
        Returns a review id; nothing is reachable yet."""
        if not self.quick_connect:
            raise ConnectError('not_found', 'no such page', 404)
        q = qc.parse_query(authorize_url)
        claims, jwk = qc.verify_invitation(q.get('invitation', ''), responder_origin=qc.origin_of(self.base),
                                           responder_installation=self.installation_id, replay=self.replay,
                                           now=self.now())
        rid = str(uuid.uuid4())
        self.qc_reviews[rid] = {'claims': claims, 'jwk': jwk, 'jws': q['invitation'], 'state': q.get('state', '')}
        return rid

    def qc_authorize(self, review_id: str, *, approve: bool = True) -> str:
        """Approve (temporary pairing rule for egress_A, one-time code, signed
        accept) or deny. Returns the redirect back to the initiator."""
        rv = self.qc_reviews.pop(review_id)
        claims = rv['claims']
        if not approve:
            return qc.authorization_response_url(claims['redirect_uri'], state=rv['state'], error='access_denied')
        conn = PeerConnection(id=str(uuid.uuid4()), role='responder', state='pending_pairing')
        my = self._new_key(conn)
        self.connections[conn.id] = conn
        code = qc.generate_code()
        accept = qc.build_accept(my, responder_app=self.app, invitation=claims, invitation_jws=rv['jws'],
                                 connection_id=conn.id, base=self.base, egress=self.egress, code=code,
                                 now=self.now())
        self.qc_grants[sha256_hex(code)] = {
            'conn': conn.id, 'invitation': claims, 'invitation_jws': rv['jws'], 'jwk': rv['jwk'], 'accept': accept,
            'code_expires_at': self.now() + qc.CODE_TTL,
            'rule': {'nets': qc.egress_nets(claims['egress']), 'expires_at': self.now() + qc.TEMPORARY_RULE_TTL,
                     'purpose': 'pairing'}}
        return qc.authorization_response_url(claims['redirect_uri'], state=rv['state'], code=code, accept=accept)

    def _qc_exchange(self, url, headers, body) -> Response:
        data = json.loads(body or b'{}')
        token = data.get('exchange') if isinstance(data, dict) else None
        grant = self.qc_grants.get(qc.exchange_code_sha256(token or ''))
        source = self.network.current_source()
        # Source layer first: only this attempt's temporary rule admits the exchange.
        if grant is None or source is None or self.now() >= grant['rule']['expires_at'] or \
                not qc.source_in_egress(source, [{'net': n} for n in grant['rule']['nets']]):
            return self._json(403, {'error': {'code': SOURCE_NOT_AUTHORISED,
                                              'message': 'This address is not authorised for Agit8or Connect.'}})
        claims = qc.verify_exchange(token, dpop=headers.get('DPoP', ''), url=url, invitation=grant['invitation'],
                                    invitation_jwk=grant['jwk'], accept_jws=grant['accept'],
                                    code_sha256=qc.exchange_code_sha256(token),
                                    code_expires_at=grant['code_expires_at'],
                                    responder_installation=self.installation_id, replay=self.replay,
                                    now=self.now())
        conn = self.connections[grant['conn']]
        info = discovery.fetch(_Sourced(self), grant['invitation']['base'])
        if info.installation_id != claims['iss']:
            raise ConnectError(IDENTITY_MISMATCH, 'initiator discovery identity mismatch', 403)
        conn.remote_installation = claims['iss']
        conn.remote_app = claims['app']
        conn.remote_connection_id = claims['connection_id']
        conn.remote_keys = {grant['jwk']['kid']: keys.public_key_from_jwk(grant['jwk'])}
        conn.remote_endpoints = info.endpoints
        conn.peer_requested_scopes = list(claims.get('requested_scopes') or [])
        conn.proposed_tenants = pairing.tenant_list(claims.get('proposed_tenants'))
        conn.request_id, conn.request_jti, conn.request_jws = str(uuid.uuid4()), claims['jti'], token
        conn.sas = qc.sas(qc.transcript_from_messages(grant['invitation_jws'], grant['accept'], token))
        conn.state = 'awaiting_local_approval'
        self.requests[conn.request_id] = conn.id
        _, my = conn.active_key()
        ack = pairing.build_ack(my, responder_app=self.app, initiator_installation=claims['iss'],
                                request_id=conn.request_id, request_jti=claims['jti'], connection_id=conn.id,
                                now=self.now())
        return self._json(202, {'status': 'pending_approval', 'request_id': conn.request_id, 'ack': ack})

    # qc-diagnostics/1 ---------------------------------------------------------------------
    def _qc_probe(self, method, url, headers, body) -> Response:
        conn, _ = self._authenticate(method, url, headers)
        data = json.loads(body or b'{}') if body else {}
        source = self.network.current_source()
        return self._json(200, qc.build_probe_response(
            observed_source=source or '0.0.0.0', server_time=self.now(), connection_state=conn.state,
            source_check='not_enforced', peer_reached_at=self.qc_last_reached.get(conn.id),
            nonce=data.get('nonce') if isinstance(data, dict) else None))

    def qc_probe(self, conn_id: str, nonce: Optional[str] = None) -> dict:
        conn = self.connections[conn_id]
        url = conn.remote_endpoints.get('api_base', '').rsplit('/connect/v1', 1)[0] + qc.PROBE_PATH
        token = self.get_token(conn_id)['access_token']
        _, key = conn.active_key()
        h = {'Authorization': f'DPoP {token}', 'Content-Type': 'application/json',
             'DPoP': tokens.build_dpop_proof(key, 'POST', url, now=self.now(), access_token=token)}
        r = self._send('POST', url, h, json.dumps(qc.probe_request_body(nonce)).encode())
        data = json.loads(r.body or b'{}')
        if r.status != 200:
            raise ConnectError(data.get('error', {}).get('code', 'probe_failed'), '', r.status)
        self.qc_last_reached[conn_id] = self.now()
        return qc.validate_probe_response(data, nonce=nonce)


class _Sourced:
    """A Transport that sends from a peer's source address."""

    def __init__(self, peer: ReferencePeer):
        self.peer = peer

    def request(self, method, url, headers=None, body=None) -> Response:
        return self.peer._send(method, url, headers, body)
