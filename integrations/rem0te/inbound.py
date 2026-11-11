"""
Requests Rem0te signs to ClientSt0r: POST /api/integration/v1/inference and
POST /api/integration/v1/events.

Rem0te signs with its own Ed25519 key (`rem0te-key-id: rem0te/{kid}`) over
rem0te-http-req-v1 with ClientSt0r's audience (Rem0teIdentity.audience —
the peers file's peerAudience). A request is accepted only when:

  * all four headers are present and well-formed;
  * the timestamp is within ±120 s;
  * the signature verifies with a signing key configured on an active Rem0te
    connection (Rem0te's public key, entered by an administrator and
    compared with Rem0te's capabilities at Check pairing);
  * the nonce has not been seen — recorded in the database only after the
    signature verifies, so an unauthenticated caller cannot fill the table,
    and kept past the skew window, so a replay fails after a restart too.

The handler then binds the request to the one connection serving the
organization named in the (now authenticated) body. There is no HMAC path
here and no fallback to one: a failure is a 401.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import List, Tuple

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import identity, pairing, protocol

logger = logging.getLogger('integrations.rem0te')

NONCE_TTL = timedelta(seconds=2 * (protocol.MAX_CLOCK_SKEW_S + 60))
MAX_BODY = 1024 * 1024


class InboundRefused(Exception):
    def __init__(self, reason, status=401, code='UNAUTHENTICATED'):
        super().__init__(reason)
        self.reason, self.status, self.code = reason, status, code


def is_rem0te_request(request) -> bool:
    return any(request.headers.get(h) for h in (protocol.H_KEY_ID, protocol.H_SIGNATURE))


def authenticate(request) -> Tuple[List, str, str]:
    """(connections whose Rem0te key verified the request, kid, nonce)."""
    from integrations.models import RMMConnection, Rem0teReplayGuard
    body = request.body or b''
    if len(body) > MAX_BODY:
        raise InboundRefused('body too large', 413, 'TOO_LARGE')
    key_id = request.headers.get(protocol.H_KEY_ID, '')
    ts = request.headers.get(protocol.H_TIMESTAMP, '')
    nonce = request.headers.get(protocol.H_NONCE, '')
    sig = request.headers.get(protocol.H_SIGNATURE, '')
    m = protocol.KEY_ID_RE.match(key_id)
    if not m or not protocol.TIMESTAMP_RE.match(ts) or not protocol.NONCE_RE.match(nonce) or not sig:
        raise InboundRefused('missing or malformed signature headers')
    if m.group(1) != 'rem0te':
        raise InboundRefused('key id is not a Rem0te key id')
    kid = m.group(2)
    if abs(time.time() - int(ts)) > protocol.MAX_CLOCK_SKEW_S:
        raise InboundRefused('timestamp outside the allowed window')
    ident = identity.get(create=False)
    if ident is None or not ident.audience:
        raise InboundRefused('ClientSt0r has no Rem0te identity configured', 404, 'NOT_CONFIGURED')
    message = protocol.request_signing_string(ident.audience, request.method, request.get_full_path(), ts, nonce,
                                              protocol.sha256_hex(body))
    verified, known = [], []
    for conn in RMMConnection.objects.filter(provider_type='rem0te', is_active=True).order_by('pk'):
        key = pairing.keyring(conn).get(kid)
        if key is None:
            continue
        known.append(conn)
        if protocol.verify(key, message, sig):
            verified.append(conn)
    from . import health
    if not verified:
        # Unauthenticated: nothing is stored for an unknown key id (anyone can
        # send one). A known key id whose signature fails is shown on those
        # connections — Rem0te's audience for ClientSt0r or its key changed.
        for conn in known[:20]:
            health.note(conn, 'inbound_auth', f'Rem0te\'s request signed with key "{kid}" did not verify '
                                              f'({request.method} {request.path}).', code='INBOUND_SIGNATURE',
                        action="Check ClientSt0r's audience (peerAudience in the peers file) and Rem0te's "
                               'signing key on this connection.')
        raise InboundRefused('signature invalid' if known else f'unknown key id "{kid}"')
    for conn in verified:
        health.clear(conn, 'inbound_auth')
    try:
        with transaction.atomic():
            Rem0teReplayGuard.objects.create(key=f'in:{kid}:{nonce}', expires_at=timezone.now() + NONCE_TTL)
    except IntegrityError:
        raise InboundRefused('nonce already used', 401, 'REPLAYED')
    if int(ts) % 20 == 0:
        Rem0teReplayGuard.objects.filter(expires_at__lt=timezone.now()).delete()
    return verified, kid, nonce


def connection_for(verified, organization_id):
    for conn in verified:
        if pairing.organization_id(conn) == organization_id:
            return conn
    return None


def response_headers(nonce: str, body: bytes) -> dict:
    """The inference response signature: rem0te-http-resp-v1 over the
    request's nonce and the exact response bytes, with ClientSt0r's request
    key (Rem0te looks it up as `{peer id}/{kid}` among requestKeys)."""
    ident = identity.get(create=False)
    return {protocol.H_KEY_ID: identity.request_key_id(ident),
            protocol.H_RESPONSE_SIGNATURE: protocol.sign_response(identity.request_signer(ident), nonce, body)}
