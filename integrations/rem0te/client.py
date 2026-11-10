"""
Signed requests from ClientSt0r to Rem0te (contract ticket-rmm-v1).

Every request carries the four rem0te-* signature headers over
rem0te-http-req-v1 with Rem0te's audience, signed by ClientSt0r's request
key; delegated routes add a fresh, single-use EdDSA delegation token minted
with the separate delegation key. Redirects are never followed (a 3xx could
carry a signed body elsewhere), proxies from the environment are ignored,
the destination goes through core.safe_http, and responses are read to a
hard cap.

Nothing here ever signs with an HMAC secret. If the Ed25519 identity or the
connection's Rem0te settings are incomplete, the request is not sent.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests

from core.safe_http import BlockedDestinationError, OutboundPolicy, configured_service_policy, guard_session

from . import identity, protocol

logger = logging.getLogger('integrations.rem0te')

API = '/api/integration/v1'
TIMEOUT = (5, 20)
MAX_RESPONSE = 4 * 1024 * 1024
_PRINTABLE = re.compile(r'[^\x20-\x7e]')


class NotSent(Exception):
    """The request was not sent: ClientSt0r's own configuration is incomplete."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Result:
    ok: bool
    status: int = 0
    data: Any = None
    code: str = ''              # Rem0te's error code, or a transport code ClientSt0r assigns
    message: str = ''           # safe to show: no secrets, no request content
    transport: str = ''         # '' | 'unreachable' | 'timeout' | 'blocked' | 'too_large' | 'invalid'
    clock_skew_s: Optional[int] = None
    headers: dict = field(default_factory=dict)

    @property
    def maybe_delivered(self) -> bool:
        """Could Rem0te have acted on it? (A timeout or a 5xx might have.)"""
        return self.transport in ('timeout', 'read') or self.status >= 500


def safe_text(value, limit=200) -> str:
    return _PRINTABLE.sub(' ', str(value or ''))[:limit].strip()


def _policy(settings_):
    base = configured_service_policy()
    if settings_['location'] == 'local':
        return OutboundPolicy(allow_lan=True, allow_local=base.allow_local, allowed_ports=None)
    return base


def request(connection, method, path, body=None, query=None, delegation=None) -> Result:
    """Send one signed request. `path` is under /api/integration/v1.
    `delegation` = (scope, technician_id, req_sha256 or None)."""
    from .pairing import settings as rem0te_settings, organization_id
    s = rem0te_settings(connection)
    problem = s['incomplete']
    if problem:
        raise NotSent('NOT_CONFIGURED_LOCAL', problem)
    ident = identity.get(create=False)
    missing = identity.configured(ident)
    if missing:
        raise NotSent('NOT_CONFIGURED_LOCAL', missing)

    site = s['site']
    url = site + API + path
    if query:
        url += '?' + urlencode(query)
    parts = urlsplit(url)
    path_with_query = parts.path + (f'?{parts.query}' if parts.query else '')
    raw = protocol.canonical_json(body).encode('utf-8') if body is not None else b''
    headers = protocol.request_headers(identity.request_signer(ident), identity.request_key_id(ident),
                                       s['rem0te_audience'], method, path_with_query, raw)
    headers['Accept'] = 'application/json'
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if delegation is not None:
        scope, technician_id, req_sha256 = delegation
        claims = protocol.delegation_claims(
            peer_id=ident.peer_id, audience=s['rem0te_audience'], technician_id=technician_id,
            organization_id=organization_id(connection), scope=scope, req_sha256=req_sha256)
        headers[protocol.H_DELEGATION] = protocol.sign_jws(identity.delegation_signer(ident), ident.delegation_kid,
                                                           claims)
    session = requests.Session()
    session.trust_env = False
    guard_session(session, _policy(s))
    sent_at = time.time()
    try:
        r = session.request(method, url, data=raw or None, headers=headers, timeout=TIMEOUT,
                            allow_redirects=False, stream=True)
        content = b''
        for chunk in r.iter_content(65536):
            content += chunk
            if len(content) > MAX_RESPONSE:
                r.close()
                return Result(False, r.status_code, code='TOO_LARGE_RESPONSE', transport='too_large',
                              message='Rem0te answered with more data than ClientSt0r accepts.')
    except BlockedDestinationError:
        return Result(False, code='BLOCKED', transport='blocked',
                      message=f'{parts.hostname} is not an allowed destination for this connection '
                              '(check "Where this RMM runs" and the private-address setting).')
    except requests.Timeout as e:
        kind = 'timeout' if isinstance(e, requests.ReadTimeout) else 'unreachable'
        return Result(False, code='UNREACHABLE', transport=kind,
                      message=f'Rem0te at {parts.hostname} did not answer in time ({e.__class__.__name__}).')
    except requests.ConnectionError as e:
        return Result(False, code='UNREACHABLE', transport='unreachable',
                      message=f'Rem0te at {parts.hostname}:{parts.port or (443 if parts.scheme == "https" else 80)} '
                              f'could not be reached ({e.__class__.__name__}).')
    except requests.RequestException as e:
        return Result(False, code='UNREACHABLE', transport='read',
                      message=f'The request to Rem0te failed ({e.__class__.__name__}).')
    skew = None
    date = r.headers.get('Date')
    if date:
        try:
            skew = int(parsedate_to_datetime(date).timestamp() - (sent_at + time.time()) / 2)
        except (TypeError, ValueError, OverflowError):
            skew = None
    hdrs = {k.lower(): v for k, v in r.headers.items() if k.lower() in ('idempotent-replayed', 'content-type')}
    if 300 <= r.status_code < 400:
        return Result(False, r.status_code, code='REDIRECT', transport='invalid', clock_skew_s=skew, headers=hdrs,
                      message=f'Rem0te answered with a redirect (HTTP {r.status_code}); ClientSt0r does not follow '
                              'redirects. Check the integration address.')
    data = None
    if content:
        try:
            data = json.loads(content)
        except ValueError:
            data = None
    if r.status_code >= 400 or not (200 <= r.status_code < 300):
        err = data.get('error') if isinstance(data, dict) else None
        code = safe_text(err.get('code'), 40) if isinstance(err, dict) else ''
        message = safe_text(err.get('message'), 200) if isinstance(err, dict) else ''
        if not code:
            code = 'RATE_LIMITED' if r.status_code == 429 else f'HTTP_{r.status_code}'
        return Result(False, r.status_code, data=None, code=code, clock_skew_s=skew, headers=hdrs,
                      message=message or f'Rem0te answered HTTP {r.status_code}.')
    if data is None and content:
        return Result(False, r.status_code, code='INVALID_RESPONSE', transport='invalid', clock_skew_s=skew,
                      message='Rem0te returned something other than JSON.')
    return Result(True, r.status_code, data=data, clock_skew_s=skew, headers=hdrs)
