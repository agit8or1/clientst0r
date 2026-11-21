"""
Agit8or Connect HTTP API (PROTOCOL.md §4–§10). Every view answers 404 while
AGIT8OR_CONNECT_ENABLED is off, so nothing new is exposed by default.

No session, cookie or API key is accepted here, and CSRF does not apply:
every request is authenticated by a signature, a client assertion, or a
DPoP-bound token. Responses never carry a private key, a pairing code, or
another connection's data.
"""
from __future__ import annotations

import functools
import json
import logging
import uuid

from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from agit8or_connect import PROTOCOL_ID
from agit8or_connect import keys as sdk_keys
from agit8or_connect.errors import ConnectError

from . import auth, catalog, events, identity, pairing, ratelimit, store

logger = logging.getLogger('connect')

MAX_BODY = 64 * 1024
MAX_EVENT_BODY = 1024 * 1024


def _json(status, data, headers=None):
    r = JsonResponse(data, status=status)
    r['Cache-Control'] = 'no-store'
    for k, v in (headers or {}).items():
        r[k] = v
    return r


def _error(e: ConnectError, correlation_id=''):
    headers = {}
    if e.status == 401 and e.code in ('invalid_token', 'invalid_dpop_proof', 'expired', 'replayed'):
        headers['WWW-Authenticate'] = f'DPoP error="{e.code}", algs="EdDSA"'
    if e.code == 'rate_limited':
        headers['Retry-After'] = '60'
    return _json(e.status, e.as_dict(correlation_id), headers)


def endpoint(methods, max_body=MAX_BODY, bucket='api_ip'):
    def deco(fn):
        @csrf_exempt
        @require_http_methods(methods)
        @functools.wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not identity.enabled():
                raise Http404
            cid = str(uuid.uuid4())
            try:
                # Buckets keyed by source address AND the connection the request
                # names (QC-13): one peer cannot use up another's budget.
                if not ratelimit.hit(bucket, ratelimit.request_key(request)):
                    raise ConnectError('rate_limited', 'too many requests', 429)
                length = int(request.META.get('CONTENT_LENGTH') or 0)
                if length > max_body or len(request.body or b'') > max_body:
                    raise ConnectError('too_large', 'request body too large', 413)
                return fn(request, *args, **kwargs)
            except ConnectError as e:
                logger.info('connect %s %s refused: %s', request.method, request.path, e.code)
                return _error(e, cid)
        return wrapper
    return deco


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        raise ConnectError('invalid_request', 'body must be JSON')
    if not isinstance(data, dict):
        raise ConnectError('invalid_request', 'body must be a JSON object')
    return data


@endpoint(['GET'])
def discovery(request):
    return _json(200, identity.document(request))


@endpoint(['GET'])
def health(request):
    out = {'status': 'stopped' if identity.kill_switch_engaged() else 'ok', 'protocol': PROTOCOL_ID,
           'installation_id': identity.installation_id()}
    if request.headers.get('Authorization'):
        a = auth.authenticate(request, testing_ok=True)
        out['connection'] = {'id': str(a.connection.pk), 'state': a.connection.state}
    import time
    out['time'] = int(time.time())
    return _json(200, out)


@endpoint(['POST'], bucket='pairing_ip')
def pairing_submit(request):
    if identity.kill_switch_engaged():
        raise ConnectError('kill_switch', 'connected applications are stopped', 503)
    if not ratelimit.hit('pairing_global'):
        raise ConnectError('rate_limited', 'too many pairing attempts', 429)
    token = _body(request).get('request')
    if not isinstance(token, str):
        raise ConnectError('invalid_request', 'request must be a compact JWS')
    return _json(202, pairing.receive_request(token, ratelimit.client_ip(request), request=request))


@endpoint(['POST'], bucket='poll_ip')
def pairing_status(request, request_id):
    try:
        uuid.UUID(str(request_id))
    except ValueError:
        raise ConnectError('not_found', 'unknown pairing request', 404)
    proof = _body(request).get('proof')
    if not isinstance(proof, str):
        raise ConnectError('invalid_request', 'proof must be a compact JWS')
    return _json(200, pairing.pairing_status(str(request_id), proof, request=request))


@endpoint(['POST'], bucket='token_ip')
def token(request):
    if not ratelimit.hit('token_global'):
        raise ConnectError('rate_limited', 'too many token requests', 429)
    if not (request.content_type or '').startswith('application/x-www-form-urlencoded'):
        return _json(400, {'error': 'invalid_request', 'error_description': 'form-encoded body required'})
    status, data, headers = auth.token_request(request)
    return _json(status, data, headers)


@endpoint(['GET'], bucket='jwks_ip')
def jwks(request, connection_id):
    from .models import Connection
    conn = Connection.objects.filter(pk=connection_id).exclude(
        state__in=(Connection.REVOKED, Connection.FAILED)).first()
    if conn is None:
        raise ConnectError('not_found', 'not found', 404)
    # Unauthenticated, but the source must be one this connection allows
    # (checked before the view; this keeps a union match from reaching it).
    if str(conn.pk) not in getattr(getattr(request, 'connect_source', None), 'matched', ()) and not getattr(
            getattr(request, 'connect_source', None), 'lenient', False):
        raise ConnectError('source_not_authorised', 'This source address is not authorised for Agit8or Connect.',
                           403)
    row, priv = store.active_key(conn)
    doc = sdk_keys.endorsed_jwks(priv, store.published_jwks(conn), identity.installation_id(), str(conn.pk))
    r = _json(200, doc)
    r['Content-Type'] = 'application/jwk-set+json'
    return r


@endpoint(['GET'])
def capabilities(request):
    a = auth.authenticate(request, require_scope='connection:read', testing_ok=True)
    grants = [{'tenant': g.remote_tenant_id, 'scopes': g.scopes}
              for g in a.connection.tenant_grants.filter(active=True)]
    return _json(200, {'connection_id': str(a.connection.pk), 'scopes': a.scopes,
                       'event_types': a.connection.inbound_event_types, 'tenants': grants,
                       'catalog': catalog.CATALOG.as_list()})


@endpoint(['POST'])
def test(request):
    a = auth.authenticate(request, testing_ok=True)
    import time
    out = {'ok': True, 'connection_id': str(a.connection.pk), 'scopes': a.scopes, 'protocol': PROTOCOL_ID,
           'time': int(time.time())}
    if request.headers.get('Agit8or-Tenant'):
        try:
            a.tenant(request, 'connection:read')
            out['tenant'] = 'granted'
        except ConnectError as e:
            out['tenant'] = e.code
    return _json(200, out)


@endpoint(['GET'])
def customers(request):
    a = auth.authenticate(request, require_scope='customers:read')
    rows = a.connection.tenant_grants.filter(active=True).select_related('organization')
    return _json(200, {'tenants': [{'tenant': g.remote_tenant_id, 'name': g.organization.name,
                                    'scopes': g.scopes} for g in rows if 'customers:read' in (g.scopes or [])]})


@endpoint(['GET'])
def customer_current(request):
    """Tenant-scoped sample resource: the one customer the Agit8or-Tenant
    header resolves to through THIS connection's grants."""
    a = auth.authenticate(request, require_scope='customers:read')
    grant = a.tenant(request, 'customers:read')
    return _json(200, {'tenant': grant.remote_tenant_id, 'name': grant.organization.name})


@endpoint(['POST'], max_body=MAX_EVENT_BODY, bucket='events_ip')
def events_inbound(request):
    status, data = events.receive(request)
    return _json(status, data)


@endpoint(['POST'], bucket='pairing_ip')
def qc_exchange(request):
    """PROTOCOL-1.1.md §5.6. The source layer (middleware) already admitted
    the request from the temporary rule of the attempt whose one-time code
    it carries; everything else is checked in quick_connect.receive_exchange."""
    from . import quick_connect
    if not quick_connect.available():
        raise Http404
    if identity.kill_switch_engaged():
        raise ConnectError('kill_switch', 'connected applications are stopped', 503)
    if not ratelimit.hit('pairing_global'):
        raise ConnectError('rate_limited', 'too many pairing attempts', 429)
    token = _body(request).get('exchange')
    if not isinstance(token, str) or not token:
        raise ConnectError('invalid_request', 'exchange must be a compact JWS')
    return _json(202, quick_connect.receive_exchange(request, token, request.headers.get('DPoP', '')))
