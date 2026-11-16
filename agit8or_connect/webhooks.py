"""Signed events (PROTOCOL.md §8).

Delivery: POST {events endpoint} with the JSON envelope as the body and

  Agit8or-Connection   the receiver's connection id for the sender (client id)
  Agit8or-Event-Id     the envelope id (UUID)
  Agit8or-Timestamp    unix seconds of THIS attempt
  Agit8or-Key-Id       sender's connection key thumbprint
  Agit8or-Signature    base64url Ed25519 signature over

    agit8or-connect-event-v1\\n{connection}\\n{event id}\\n{timestamp}\\n
    {sender installation}\\n{receiver installation}\\n{sha256 hex of body}

Receiver: timestamp within ±120 s, signature with a key of that connection,
then the event id is recorded (dedup) — a duplicate is answered 200
`duplicate` and not processed again; a replay outside the window fails the
timestamp check. The envelope's origin / causation / hop count stop loops.
"""
from __future__ import annotations

import random
import re
import time
import uuid
from typing import Dict, Mapping, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import keys as _keys
from .canonical import b64url, canonical_bytes, from_b64url, sha256_hex
from .errors import ConnectError, EXPIRED, INVALID_REQUEST, INVALID_SIGNATURE

PREFIX = 'agit8or-connect-event-v1'
SKEW = 120
MAX_HOPS = 4
MAX_BODY = 1024 * 1024
H_CONNECTION, H_EVENT_ID, H_TIMESTAMP, H_KEY_ID, H_SIGNATURE = (
    'Agit8or-Connection', 'Agit8or-Event-Id', 'Agit8or-Timestamp', 'Agit8or-Key-Id', 'Agit8or-Signature')
EVENT_TYPE_RE = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,4}$')
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def signing_string(*, connection_id: str, event_id: str, timestamp: int, sender: str, receiver: str,
                   body: bytes) -> str:
    return '\n'.join([PREFIX, connection_id, event_id, str(int(timestamp)), sender, receiver, sha256_hex(body)])


def sign(private_key: Ed25519PrivateKey, *, connection_id: str, event_id: str, sender: str, receiver: str,
         body: bytes, timestamp: Optional[int] = None) -> Dict[str, str]:
    ts = int(time.time() if timestamp is None else timestamp)
    msg = signing_string(connection_id=connection_id, event_id=event_id, timestamp=ts, sender=sender,
                         receiver=receiver, body=body)
    return {H_CONNECTION: connection_id, H_EVENT_ID: event_id, H_TIMESTAMP: str(ts),
            H_KEY_ID: _keys.thumbprint(private_key), H_SIGNATURE: b64url(private_key.sign(msg.encode('utf-8'))),
            'Content-Type': 'application/json'}


def _h(headers: Mapping[str, str], name: str) -> str:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v or ''
    return ''


def verify(headers: Mapping[str, str], body: bytes, keys: Mapping[str, Ed25519PublicKey], *, sender: str,
           receiver: str, connection_id: str, now: Optional[int] = None) -> Tuple[str, str]:
    """(event id, kid) when the delivery is authentic and fresh."""
    if len(body or b'') > MAX_BODY:
        raise ConnectError('too_large', 'event body too large', 413)
    conn, eid, ts, kid, sig = (_h(headers, n) for n in (H_CONNECTION, H_EVENT_ID, H_TIMESTAMP, H_KEY_ID,
                                                       H_SIGNATURE))
    if conn != connection_id or not UUID_RE.match(eid) or not ts.isdigit() or len(ts) > 11:
        raise ConnectError(INVALID_REQUEST, 'missing or malformed event headers', 401)
    now = int(time.time() if now is None else now)
    if abs(now - int(ts)) > SKEW:
        raise ConnectError(EXPIRED, 'event timestamp outside the allowed window', 401)
    key = keys.get(kid)
    if key is None:
        raise ConnectError(INVALID_SIGNATURE, 'event signed by an unknown key', 401)
    try:
        raw = from_b64url(sig)
        if len(raw) != 64:
            raise ValueError
        key.verify(raw, signing_string(connection_id=conn, event_id=eid, timestamp=int(ts), sender=sender,
                                       receiver=receiver, body=body).encode('utf-8'))
    except Exception as e:  # InvalidSignature, ValueError, ConnectError
        raise ConnectError(INVALID_SIGNATURE, 'event signature does not verify', 401) from e
    return eid, kid


def envelope(*, event_type: str, tenant: str, data: dict, sender: str, origin: Optional[str] = None,
             correlation_id: Optional[str] = None, causation_id: Optional[str] = None, hops: int = 0,
             event_id: Optional[str] = None, occurred_at: Optional[int] = None, version: int = 1,
             idempotency_key: Optional[str] = None) -> dict:
    if not EVENT_TYPE_RE.match(event_type):
        raise ConnectError(INVALID_REQUEST, 'bad event type')
    eid = event_id or str(uuid.uuid4())
    return {'id': eid, 'type': event_type, 'version': version, 'tenant': tenant, 'data': data,
            'sender': sender, 'origin': origin or sender, 'correlation_id': correlation_id or eid,
            'causation_id': causation_id or '', 'hops': hops, 'idempotency_key': idempotency_key or eid,
            'occurred_at': int(time.time() if occurred_at is None else occurred_at)}


def body_of(env: dict) -> bytes:
    return canonical_bytes(env)


# Connection-level events: no tenant, accepted from any active connection
# (no events:publish needed). Any other type needs a granted tenant.
CONNECTION_EVENTS = ('connect.test', 'connect.connection.revoked')


def is_connection_event(env: dict) -> bool:
    return env.get('type') in CONNECTION_EVENTS and not env.get('tenant')


def validate_envelope(env, *, event_id: str, sender: str, receiver: str) -> dict:
    """Checks the members the protocol needs; unknown members are ignored
    (forward compatibility). Returns {'loop': bool, ...env}."""
    if not isinstance(env, dict):
        raise ConnectError(INVALID_REQUEST, 'event must be a JSON object')
    if env.get('id') != event_id:
        raise ConnectError(INVALID_REQUEST, 'event id does not match the signed header')
    if env.get('sender') != sender:
        raise ConnectError(INVALID_REQUEST, 'event sender does not match the connection')
    if not isinstance(env.get('type'), str) or not EVENT_TYPE_RE.match(env['type']):
        raise ConnectError(INVALID_REQUEST, 'bad event type')
    if not isinstance(env.get('tenant', ''), str):
        raise ConnectError(INVALID_REQUEST, 'tenant must be a string')
    if not isinstance(env.get('data', {}), dict):
        raise ConnectError(INVALID_REQUEST, 'data must be an object')
    hops = env.get('hops', 0)
    if isinstance(hops, bool) or not isinstance(hops, int) or hops < 0:
        raise ConnectError(INVALID_REQUEST, 'hops must be a non-negative integer')
    loop = env.get('origin') == receiver or hops >= MAX_HOPS
    return dict(env, loop=loop)


def backoff_seconds(attempt: int, *, base: int = 30, cap: int = 3600, rng=random.random) -> int:
    """Exponential backoff with full jitter in [50%, 100%] of min(cap, base*2^n)."""
    ceiling = min(cap, base * (2 ** max(0, min(attempt, 20))))
    return max(1, int(ceiling * (0.5 + 0.5 * rng())))


MAX_ATTEMPTS = 12  # ~ 1+2+4+…+60 min capped: about 7-8 hours before dead letter
