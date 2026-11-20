"""Token endpoint and API request authentication (we are the resource
server / authorization server for the connections other apps hold here).

Every API call: DPoP-bound access token issued here (signed by our key for
that connection), a fresh DPoP proof by the connection key the token is
bound to, connection ACTIVE, token not older than tokens_not_before, kill
switch off, and the scopes used = token scopes ∩ what is granted NOW (so a
revocation or narrowing applies to tokens already issued). Tenant-scoped
calls then resolve Agit8or-Tenant through THIS connection's grants only.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone as dt_tz
from urllib.parse import parse_qs

from django.utils import timezone

from agit8or_connect import keys as sdk_keys
from agit8or_connect import tokens as sdk_tokens
from agit8or_connect.errors import ConnectError
from agit8or_connect.scopes import parse_scope_string, require_subset
from agit8or_connect.tenants import authorize

from . import audit_log, identity, store, transport

logger = logging.getLogger('connect')

JWKS_REFRESH_INTERVAL = 60


def _connection(client_id: str):
    from .models import Connection
    import uuid
    try:
        uuid.UUID(str(client_id))
    except ValueError:
        return None
    return Connection.objects.filter(pk=client_id).first()


def refresh_remote_jwks(conn) -> bool:
    """Fetch the other app's endorsed JWKS for this connection; add keys only
    if the endorsement verifies with a key we already trust. At most once a
    minute per connection."""
    now = timezone.now()
    if conn.remote_jwks_fetched_at and (now - conn.remote_jwks_fetched_at).total_seconds() < JWKS_REFRESH_INTERVAL:
        return False
    conn.remote_jwks_fetched_at = now
    conn.save(update_fields=['remote_jwks_fetched_at'])
    url = conn.endpoint('jwks', connection_id=conn.remote_connection_id)
    if not url:
        return False
    try:
        r = transport.for_connection(conn).request('GET', url, headers={'Accept': 'application/json'})
        if r.status != 200:
            return False
        ring = sdk_keys.verify_endorsed_jwks(json.loads(r.body), store.remote_keyring(conn),
                                             conn.remote_installation_id, conn.remote_connection_id)
    except (ConnectError, ValueError):
        return False
    store.set_remote_keys(conn, ring)
    conn.save(update_fields=['remote_jwks', 'remote_jwks_fetched_at'])
    return True


def _note_auth_failure(conn, code):
    from django.db.models import F
    from .models import Connection
    Connection.objects.filter(pk=conn.pk).update(auth_failure_count=F('auth_failure_count') + 1,
                                                 last_failure_at=timezone.now())


def token_request(request):
    """OAuth 2.1 client_credentials + private_key_jwt + DPoP. Returns
    (status, body dict, headers)."""
    from .models import Connection
    form = {k: v[0] for k, v in parse_qs(request.body.decode('ascii', 'replace'), max_num_fields=10).items()}
    conn = None
    try:
        if identity.kill_switch_engaged():
            raise ConnectError('kill_switch', 'connected applications are stopped', 503)
        if form.get('grant_type') != 'client_credentials':
            raise ConnectError('unsupported_grant_type', 'only client_credentials is supported')
        if form.get('client_assertion_type') != sdk_tokens.CLIENT_ASSERTION_TYPE or not form.get('client_assertion'):
            raise ConnectError('invalid_client', 'private_key_jwt client authentication is required', 401)
        conn = _connection(form.get('client_id', ''))
        if conn is None:
            raise ConnectError('invalid_client', 'unknown client', 401)
        if conn.state != Connection.ACTIVE:
            raise ConnectError('invalid_client', 'this connection is not active', 401)
        endpoint = identity.token_endpoint(request)

        def key_for(kid):
            ring = store.remote_keyring(conn)
            if kid not in ring and refresh_remote_jwks(conn):
                ring = store.remote_keyring(conn)
            return ring.get(kid)

        claims, kid = sdk_tokens.verify_client_assertion(form['client_assertion'], key_for, client_id=str(conn.pk),
                                                         token_endpoint=endpoint, replay=store.replay_store)
        jkt, _ = sdk_tokens.verify_dpop_proof(request.headers.get('DPoP', ''), method='POST', url=endpoint,
                                              replay=store.replay_store, allowed_jkts=[kid])
        requested = parse_scope_string(form.get('scope', '')) or list(conn.inbound_scopes)
        granted = require_subset(requested, conn.inbound_scopes)
        _, priv = store.active_key(conn)
        token, tclaims = sdk_tokens.issue_access_token(priv, issuer=identity.installation_id(), client_id=str(conn.pk),
                                                       scopes=granted, jkt=jkt)
    except ConnectError as e:
        if conn is not None:
            _note_auth_failure(conn, e.code)
            audit_log.record('token.issue', e.code, connection=conn, app=conn.remote_installation_id, scopes=[])
        else:
            # No (known) connection: anyone can cause this, so it is counted in
            # the folded refusal log and summarised into the chain (QC-03).
            from . import denials, ratelimit
            denials.note(denials.token_reason(e.code), source_ip=ratelimit.client_ip(request),
                         path=request.path, method=request.method)
        status = e.status if e.status in (400, 401, 503) else 400
        return status, {'error': e.code, 'error_description': e.message}, {'Cache-Control': 'no-store'}
    audit_log.record('token.issue', 'ok', connection=conn, app=conn.remote_installation_id, scopes=granted,
                     correlation_id=tclaims['jti'])
    return 200, {'access_token': token, 'token_type': 'DPoP', 'expires_in': tclaims['exp'] - tclaims['iat'],
                 'scope': ' '.join(granted)}, {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}


class Authenticated:
    def __init__(self, connection, scopes, claims):
        self.connection, self.scopes, self.claims = connection, scopes, claims

    def tenant(self, request, scope):
        """The TenantGrant for the Agit8or-Tenant header, under `scope`."""
        g = authorize(store.tenant_resolver, str(self.connection.pk), request.headers.get('Agit8or-Tenant', ''),
                      scope, self.scopes)
        return g.local_tenant


def authenticate(request, *, require_scope=None) -> Authenticated:
    from .models import Connection
    if identity.kill_switch_engaged():
        raise ConnectError('kill_switch', 'connected applications are stopped', 503)
    url = identity.public_base(request) + request.path

    def keys_for(client_id):
        c = _connection(client_id)
        return store.verifying_keys(c) if c and c.state == Connection.ACTIVE else {}

    claims, client_id = sdk_tokens.authenticate_resource_request(
        authorization=request.headers.get('Authorization', ''), dpop=request.headers.get('DPoP', ''),
        method=request.method, url=url, issuer=identity.installation_id(), token_keys_for=keys_for,
        replay=store.replay_store)
    conn = _connection(client_id)
    if conn is None or conn.state != Connection.ACTIVE:
        raise ConnectError('invalid_token', 'connection is not active', 401)
    if conn.tokens_not_before and datetime.fromtimestamp(claims['iat'], tz=dt_tz.utc) < conn.tokens_not_before:
        raise ConnectError('invalid_token', 'token issued before the connection was re-keyed', 401)
    scopes = sorted(set(claims['scopes']) & set(conn.inbound_scopes))
    if require_scope and require_scope not in scopes:
        raise ConnectError('insufficient_scope', f'requires {require_scope}', 403)
    from .models import Connection as C
    C.objects.filter(pk=conn.pk).update(last_success_at=timezone.now())
    return Authenticated(conn, scopes, claims)
