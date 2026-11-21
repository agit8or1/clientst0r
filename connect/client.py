"""Calling the other app: token (private_key_jwt + DPoP) and API calls."""
from __future__ import annotations

import contextlib
import json
import threading
import time
from typing import Optional
from urllib.parse import urlencode

from django.utils import timezone

from agit8or_connect import tokens as sdk_tokens
from agit8or_connect.errors import ConnectError
from agit8or_connect.scopes import parse_scope_string

from . import catalog, identity, store, transport

_cache = {}   # (connection id, kid) -> (token, expires_at); in-process only
_retest = threading.local()


@contextlib.contextmanager
def retesting(conn):
    """Inside this block a Security Blocked connection may be called, for
    the retest after an administrator approved a new destination (B2), and
    a connection in ``testing`` for its commit-gate test (C3). Nowhere else."""
    prev = getattr(_retest, 'pk', None)
    _retest.pk = str(conn.pk)
    try:
        yield
    finally:
        _retest.pk = prev


def diagnosing(conn) -> bool:
    """True inside a diagnostics run for ``conn`` (connect/diagnostics.py):
    a security failure is reported there, not acted on, because
    diagnostics never change a connection (the monitor acts on it)."""
    return conn is not None and getattr(_retest, 'diag', None) == str(getattr(conn, 'pk', conn))


@contextlib.contextmanager
def diagnostics_run(conn):
    prev = getattr(_retest, 'diag', None)
    _retest.diag = str(conn.pk)
    try:
        yield
    finally:
        _retest.diag = prev


def usable_state(conn, state) -> bool:
    from .models import Connection
    return state == Connection.ACTIVE or (state in (Connection.SECURITY_BLOCKED, Connection.TESTING)
                                          and getattr(_retest, 'pk', None) == str(conn.pk))


def require_active(conn):
    """Refuse unless the connection is active NOW. The state is re-read from
    the database, so a suspend or revoke done in another worker applies here
    at once, whatever this process cached (QC-14)."""
    from .models import Connection
    state = Connection.objects.filter(pk=conn.pk).values_list('state', flat=True).first()
    if not usable_state(conn, state):
        clear_cache(conn)
        raise ConnectError('connection_inactive', f'the connection is {state or "gone"}, not active', 409)


def get_token(conn, scopes=(), *, key_row=None, use_cache=True) -> dict:
    if identity.kill_switch_engaged():
        raise ConnectError('kill_switch', 'connected applications are stopped', 503)
    require_active(conn)
    if key_row is None:
        key_row, priv = store.active_key(conn)
    else:
        priv = store.private_key(key_row)
    ck = (str(conn.pk), key_row.kid, ' '.join(sorted(scopes)))
    hit = _cache.get(ck)
    if use_cache and hit and hit[1] > time.time() + 30:
        return {'access_token': hit[0], 'scope': hit[2], 'cached': True}
    endpoint = conn.endpoint('token')
    form = {'grant_type': 'client_credentials', 'client_id': conn.remote_connection_id,
            'client_assertion_type': sdk_tokens.CLIENT_ASSERTION_TYPE,
            'client_assertion': sdk_tokens.build_client_assertion(priv, conn.remote_connection_id, endpoint)}
    if scopes:
        form['scope'] = ' '.join(sorted(scopes))
    r = transport.for_connection(conn).request(
        'POST', endpoint, headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
                                   'DPoP': sdk_tokens.build_dpop_proof(priv, 'POST', endpoint)},
        body=urlencode(form).encode())
    try:
        data = json.loads(r.body or b'{}')
    except ValueError:
        data = {}
    if r.status != 200 or data.get('token_type') != 'DPoP' or not data.get('access_token'):
        err = data.get('error')
        if isinstance(err, dict) and isinstance(err.get('code'), str):   # v1 error body (source policy refusal)
            err = err['code']
        code = err if isinstance(err, str) and err else f'http_{r.status}'
        raise ConnectError(code[:40], str(data.get('error_description') or 'token request refused')[:200],
                           r.status or 502)
    granted = parse_scope_string(str(data.get('scope') or ''))
    if not scopes and sorted(granted) != sorted(conn.outbound_scopes or []):
        from .models import Connection
        missing = sorted(set(conn.outbound_scopes or []) - set(granted))
        if missing and conn.state == Connection.ACTIVE:
            # DESIGN §7.3 scope_withdrawn: a committed permission is gone. Never
            # narrowed silently; Security Blocked until an administrator retests.
            if not diagnosing(conn):
                from . import destinations
                destinations.security_block(conn, 'scope_withdrawn', {'missing_scopes': missing})
            raise ConnectError('scope_withdrawn', 'the other application granted fewer permissions than were '
                                                  'committed: ' + ', '.join(missing), 403)
        conn.outbound_scopes = granted
        conn.save(update_fields=['outbound_scopes', 'updated_at'])
    _cache[ck] = (data['access_token'], time.time() + int(data.get('expires_in') or 60), data.get('scope', ''))
    return data


def call(conn, method: str, url: str, *, tenant_org=None, body: Optional[bytes] = None, scopes=()):
    data = get_token(conn, scopes)   # checks the kill switch and that the connection is active
    _, priv = store.active_key(conn)
    headers = {'Authorization': f'DPoP {data["access_token"]}', 'Accept': 'application/json',
               'DPoP': sdk_tokens.build_dpop_proof(priv, method, url, access_token=data['access_token'])}
    if tenant_org is not None:
        headers['Agit8or-Tenant'] = catalog.tenant_id(tenant_org)
    if body is not None:
        headers['Content-Type'] = 'application/json'
    r = transport.for_connection(conn).request(method, url, headers=headers, body=body)
    from .models import Connection
    if 200 <= r.status < 300:
        now = timezone.now()
        Connection.objects.filter(pk=conn.pk).update(last_success_at=now, last_outbound_ok_at=now)
    return r


def clear_cache(conn=None):
    for k in list(_cache):
        if conn is None or k[0] == str(conn.pk):
            _cache.pop(k, None)
