"""
Request signing for the ticket-rmm-v1 integration, both directions.

Each paired RMM has two shared secrets (integrations/ticket_rmm.py):
ClientSt0r signs what it sends with the outbound secret, and the RMM signs
what it sends with the inbound secret. A leaked copy of one
direction's secret can't forge the other direction.

Headers on every request:

  X-Integration-Key-Id      the pairing's key ID
  X-Integration-Timestamp   Unix seconds; ±300 s accepted
  X-Integration-Nonce       16–64 chars [A-Za-z0-9_-]; never reused
  X-Integration-Signature   hex HMAC-SHA256(secret, canonical)

  canonical = METHOD \n PATH \n TIMESTAMP \n NONCE \n hex SHA-256(body)

PATH is the request path without the query string. Nonces are stored per
pairing in the database (IntegrationNonce), so a captured request can't be
replayed to any worker. Verification is constant-time.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

SKEW_SECONDS = 300
NONCE_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')
H_KEY, H_TS, H_NONCE, H_SIG = ('X-Integration-Key-Id', 'X-Integration-Timestamp', 'X-Integration-Nonce',
                               'X-Integration-Signature')


class AuthError(Exception):
    pass


def canonical(method, path, ts, nonce, body: bytes) -> bytes:
    return '\n'.join([method.upper(), path, str(ts), nonce, hashlib.sha256(body or b'').hexdigest()]).encode()


def sign(secret, method, path, body: bytes, key_id, ts=None, nonce=None) -> dict:
    ts = int(ts if ts is not None else time.time())
    nonce = nonce or secrets.token_urlsafe(24)
    sig = hmac.new(secret.encode(), canonical(method, path, ts, nonce, body), hashlib.sha256).hexdigest()
    return {H_KEY: key_id, H_TS: str(ts), H_NONCE: nonce, H_SIG: sig}


def _header(request, name):
    return request.headers.get(name, '') or ''


def find_connection(key_id):
    """The enabled pairing (any RMM provider) with this key ID, or None."""
    from integrations.ticket_rmm import find_by_key_id
    return find_by_key_id(key_id)


def verify_request(request):
    """The calling pairing, or AuthError. Records the nonce."""
    from integrations.ticket_rmm import secrets as integration_secrets
    from psa_ai.models import IntegrationNonce
    key_id, ts, nonce, sig = (_header(request, h) for h in (H_KEY, H_TS, H_NONCE, H_SIG))
    if not (key_id and ts and nonce and sig):
        raise AuthError('missing signature headers')
    if not NONCE_RE.match(nonce) or not ts.isdigit():
        raise AuthError('malformed signature headers')
    if abs(time.time() - int(ts)) > SKEW_SECONDS:
        raise AuthError('timestamp outside the allowed window')
    conn = find_connection(key_id)
    if conn is None or conn.provider_type == 'rem0te':
        # Rem0te never authenticates with HMAC (integrations/rem0te/inbound.py).
        raise AuthError('unknown or disabled pairing')
    secret = integration_secrets(conn)['inbound']
    want = hmac.new(secret.encode(), canonical(request.method, request.path, ts, nonce, request.body),
                    hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(want, sig):
        raise AuthError('bad signature')
    try:
        with transaction.atomic():
            IntegrationNonce.objects.create(connection_id=conn.pk, nonce=nonce)
    except IntegrityError:
        raise AuthError('nonce reused')
    IntegrationNonce.objects.filter(seen_at__lt=timezone.now() - timedelta(seconds=SKEW_SECONDS * 3)).delete()
    return conn
