"""Pairing (PROTOCOL.md §5).

Roles: the RESPONDER's administrator creates an invitation and reads the
code (or shows the QR) to the INITIATOR's administrator, who enters it.

  1. responder: invitation code, 10 Crockford base32 characters (50 bits),
     shown as XXXXX-XXXXX, valid 10 minutes, single use, stored only as
     HMAC-SHA256(pepper, code). Five wrong codes in total burn every open
     invitation; pairing submissions are rate limited per IP and globally.
  2. initiator: generates a fresh Ed25519 key for this connection and POSTs a
     pairing request JWS signed with it (proof of possession) carrying the
     code, its identity, the scopes it asks for and the tenants it proposes.
  3. responder: verifies, consumes the code, generates ITS per-connection
     key, answers 202 with a signed ack (its key + connection id). Both sides
     now compute the same transcript hash and short authentication string
     (SAS) from both public keys and both installation ids; both UIs show it
     and the administrators compare it (a man-in-the-middle who learned the
     code cannot make the SAS match).
  4. responder administrator approves scopes + tenant grants. The initiator
     polls with a signed proof and receives a signed result.
  5. initiator verifies the result with the key from the ack, its
     administrator approves what the responder asks in return; both active.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import PROTOCOL_ID
from . import keys as _keys
from .canonical import canonical_json, sha256_hex
from .errors import ConnectError, INVALID_PAIRING_CODE, INVALID_REQUEST, INVALID_SIGNATURE, REPLAYED
from .jws import sign_compact, unverified_header, verify_compact
from .replay import ReplayStore

CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'  # Crockford base32: no I, L, O, U
CODE_LENGTH = 10
CODE_TTL = 600
MAX_ATTEMPTS = 5
REQUEST_MAX_LIFETIME = 600
POLL_MAX_LIFETIME = 120
RESULT_MAX_LIFETIME = 3600

TYP_REQUEST = 'agit8or-pairing-request+jwt'
TYP_ACK = 'agit8or-pairing-ack+jwt'
TYP_RESULT = 'agit8or-pairing-result+jwt'
TYP_POLL = 'agit8or-pairing-poll+jwt'

_CODE_MAP = {'O': '0', 'I': '1', 'L': '1'}


# --- codes ----------------------------------------------------------------------

def generate_code() -> str:
    raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f'{raw[:5]}-{raw[5:]}'


def normalize_code(code: str) -> str:
    """Upper-case, drop separators and spaces, map O->0 and I/L->1.
    Raises invalid_pairing_code for anything that cannot be a code."""
    if not isinstance(code, str) or len(code) > 32:
        raise ConnectError(INVALID_PAIRING_CODE, 'pairing code malformed')
    s = ''.join(_CODE_MAP.get(c, c) for c in code.upper() if c not in '- \t')
    if len(s) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in s):
        raise ConnectError(INVALID_PAIRING_CODE, 'pairing code malformed')
    return s


def hash_code(code: str, pepper: bytes) -> str:
    """HMAC-SHA256(pepper, "agit8or-connect/1 pairing-code\\n" + normalized)."""
    if not pepper:
        raise ValueError('a pairing code pepper is required')
    return hmac.new(pepper, b'agit8or-connect/1 pairing-code\n' + normalize_code(code).encode('ascii'),
                    hashlib.sha256).hexdigest()


def code_matches(code: str, stored_hash: str, pepper: bytes) -> bool:
    try:
        return hmac.compare_digest(hash_code(code, pepper), stored_hash or '')
    except ConnectError:
        return False


def qr_payload(discovery_url: str, code: str, installation_id: str) -> str:
    """What the QR code encodes. Only an initiator's own UI reads it; it
    prefills the address and code, and the identity is still verified."""
    return (f'agit8or-connect:pair?v=1&url={quote(discovery_url, safe="")}&code={quote(code)}'
            f'&id={quote(installation_id)}')


def parse_qr_payload(text: str) -> dict:
    p = urlsplit(text or '')
    if p.scheme != 'agit8or-connect' or not p.path.startswith('pair'):
        raise ConnectError(INVALID_REQUEST, 'not an Agit8or Connect pairing QR code')
    q = {k: v[0] for k, v in parse_qs(p.query).items()}
    return {'url': q.get('url', ''), 'code': q.get('code', ''), 'installation_id': q.get('id', '')}


# --- transcript and SAS ----------------------------------------------------------

def transcript_hash(*, request_jws: str, request_jti: str, initiator_installation: str, initiator_jkt: str,
                    responder_installation: str, responder_jkt: str) -> str:
    return sha256_hex(canonical_json({
        'v': f'{PROTOCOL_ID} pairing-transcript',
        'request_sha256': sha256_hex(request_jws),
        'request_jti': request_jti,
        'initiator': {'installation_id': initiator_installation, 'jkt': initiator_jkt},
        'responder': {'installation_id': responder_installation, 'jkt': responder_jkt},
    }))


def short_authentication_string(transcript: str) -> str:
    """8 decimal digits shown as NNNN-NNNN (about 26.6 bits)."""
    d = hashlib.sha256(f'{PROTOCOL_ID} sas\n{transcript}'.encode('ascii')).digest()
    n = int.from_bytes(d[:8], 'big') % 100_000_000
    s = f'{n:08d}'
    return f'{s[:4]}-{s[4:]}'


# --- messages ----------------------------------------------------------------------

def _now(now):
    return int(time.time() if now is None else now)


def _app(app: dict) -> dict:
    return {k: str(app.get(k) or '') for k in ('type', 'version', 'display_name', 'installation_id')}


def build_request(private_key: Ed25519PrivateKey, *, initiator_app: dict, responder_installation: str,
                  pairing_code: str, connection_id: str, discovery_url: str, requested_scopes: Iterable[str],
                  proposed_tenants: Iterable[dict] = (), now=None, jti=None, lifetime=300) -> Tuple[str, dict]:
    iat = _now(now)
    jwk = _keys.public_jwk(private_key)
    claims = {
        'protocol': PROTOCOL_ID, 'iss': initiator_app['installation_id'], 'aud': responder_installation,
        'iat': iat, 'exp': iat + lifetime, 'jti': jti or secrets.token_urlsafe(24),
        'pairing_code': pairing_code, 'app': _app(initiator_app), 'connection_id': connection_id,
        'discovery_url': discovery_url, 'connection_key': jwk,
        'requested_scopes': sorted(set(requested_scopes)),
        'proposed_tenants': [{'id': str(t['id']), 'label': str(t.get('label') or '')[:200]}
                             for t in proposed_tenants],
    }
    header = {'alg': 'EdDSA', 'typ': TYP_REQUEST, 'kid': jwk['kid'], 'jwk': jwk}
    return sign_compact(private_key, header, claims), claims


def verify_request(token: str, *, responder_installation: str, replay: ReplayStore, now=None) -> Tuple[dict, dict]:
    """(claims, initiator public JWK). The signature is made with the key in
    the header (proof of possession of the connection key it announces);
    payload connection_key must be that same key."""
    header = unverified_header(token)
    try:
        key = _keys.public_key_from_jwk(header.get('jwk'))
    except ConnectError as e:
        raise ConnectError(INVALID_SIGNATURE, e.message, 401) from e
    claims = verify_compact(token, key, typ=TYP_REQUEST, audience=responder_installation, now=now,
                            max_lifetime=REQUEST_MAX_LIFETIME,
                            required=('protocol', 'iss', 'aud', 'iat', 'exp', 'jti', 'pairing_code',
                                      'app', 'connection_id', 'connection_key'))
    if claims.get('protocol') != PROTOCOL_ID:
        raise ConnectError('unsupported_version', 'pairing request protocol not supported')
    try:
        announced = _keys.public_key_from_jwk(claims.get('connection_key'))
    except ConnectError as e:
        raise ConnectError(INVALID_REQUEST, e.message) from e
    if _keys.thumbprint(announced) != _keys.thumbprint(key):
        raise ConnectError(INVALID_SIGNATURE, 'request not signed by the announced connection key', 401)
    app = claims.get('app')
    if not isinstance(app, dict) or app.get('installation_id') != claims['iss']:
        raise ConnectError(INVALID_REQUEST, 'app identity does not match the issuer')
    if not isinstance(claims.get('requested_scopes', []), list):
        raise ConnectError(INVALID_REQUEST, 'requested_scopes must be a list')
    if not replay.add('pairing', f'{claims["iss"]}:{claims["jti"]}', claims['exp'] + 120):
        raise ConnectError(REPLAYED, 'pairing request already submitted', 401)
    return claims, _keys.public_jwk(key)


def build_ack(private_key, *, responder_app: dict, initiator_installation: str, request_id: str, request_jti: str,
              connection_id: str, now=None, lifetime=RESULT_MAX_LIFETIME) -> str:
    iat = _now(now)
    jwk = _keys.public_jwk(private_key)
    return sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_ACK, 'kid': jwk['kid'], 'jwk': jwk}, {
        'protocol': PROTOCOL_ID, 'iss': responder_app['installation_id'], 'aud': initiator_installation,
        'iat': iat, 'exp': iat + lifetime, 'request_id': request_id, 'request_jti': request_jti,
        'connection_id': connection_id, 'app': _app(responder_app), 'connection_key': jwk,
        'status': 'pending_approval'})


def verify_ack(token: str, *, initiator_installation: str, responder_installation: str, request_jti: str,
               now=None) -> Tuple[dict, dict]:
    header = unverified_header(token)
    key = _keys.public_key_from_jwk(header.get('jwk'))
    claims = verify_compact(token, key, typ=TYP_ACK, audience=initiator_installation,
                            issuer=responder_installation, now=now, max_lifetime=RESULT_MAX_LIFETIME,
                            required=('iss', 'aud', 'iat', 'exp', 'request_id', 'request_jti', 'connection_id',
                                      'connection_key'))
    if claims.get('request_jti') != request_jti:
        raise ConnectError(INVALID_SIGNATURE, 'ack is for another pairing request', 401)
    if _keys.thumbprint(_keys.public_key_from_jwk(claims['connection_key'])) != _keys.thumbprint(key):
        raise ConnectError(INVALID_SIGNATURE, 'ack not signed by the announced key', 401)
    return claims, _keys.public_jwk(key)


def build_poll(private_key, *, initiator_installation: str, responder_installation: str, request_id: str,
               now=None, jti=None) -> str:
    iat = _now(now)
    return sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_POLL, 'kid': _keys.thumbprint(private_key)}, {
        'iss': initiator_installation, 'aud': responder_installation, 'iat': iat, 'exp': iat + 60,
        'jti': jti or secrets.token_urlsafe(18), 'request_id': request_id})


def verify_poll(token: str, initiator_key, *, initiator_installation: str, responder_installation: str,
                request_id: str, replay: ReplayStore, now=None) -> dict:
    claims = verify_compact(token, initiator_key, typ=TYP_POLL, audience=responder_installation,
                            issuer=initiator_installation, now=now, max_lifetime=POLL_MAX_LIFETIME,
                            required=('iss', 'aud', 'iat', 'exp', 'jti', 'request_id'))
    if claims.get('request_id') != request_id:
        raise ConnectError(INVALID_SIGNATURE, 'proof is for another pairing request', 401)
    if not replay.add('poll', f'{request_id}:{claims["jti"]}', claims['exp'] + 120):
        raise ConnectError(REPLAYED, 'status proof already used', 401)
    return claims


def build_result(private_key, *, responder_installation: str, initiator_installation: str, request_id: str,
                 request_jti: str, status: str, connection_id: str, granted_scopes: Iterable[str] = (),
                 tenant_grants: Iterable[dict] = (), requested_scopes: Iterable[str] = (),
                 endpoints: Optional[dict] = None, now=None, lifetime=RESULT_MAX_LIFETIME) -> str:
    if status not in ('approved', 'rejected'):
        raise ValueError('status must be approved or rejected')
    iat = _now(now)
    return sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_RESULT, 'kid': _keys.thumbprint(private_key)}, {
        'protocol': PROTOCOL_ID, 'iss': responder_installation, 'aud': initiator_installation, 'iat': iat,
        'exp': iat + lifetime, 'request_id': request_id, 'request_jti': request_jti, 'status': status,
        'connection_id': connection_id, 'granted_scopes': sorted(set(granted_scopes)),
        'tenant_grants': [dict(t) for t in tenant_grants], 'requested_scopes': sorted(set(requested_scopes)),
        'endpoints': dict(endpoints or {})})


def verify_result(token: str, responder_key, *, initiator_installation: str, responder_installation: str,
                  request_jti: str, now=None) -> dict:
    claims = verify_compact(token, responder_key, typ=TYP_RESULT, audience=initiator_installation,
                            issuer=responder_installation, now=now, max_lifetime=RESULT_MAX_LIFETIME,
                            required=('iss', 'aud', 'iat', 'exp', 'request_id', 'request_jti', 'status',
                                      'connection_id'))
    if claims.get('request_jti') != request_jti:
        raise ConnectError(INVALID_SIGNATURE, 'result is for another pairing request', 401)
    if claims.get('status') not in ('approved', 'rejected'):
        raise ConnectError(INVALID_REQUEST, 'unknown pairing status')
    for name in ('granted_scopes', 'requested_scopes', 'tenant_grants'):
        if not isinstance(claims.get(name, []), list):
            raise ConnectError(INVALID_REQUEST, f'{name} must be a list')
    return claims


def tenant_list(items) -> List[dict]:
    """Tolerant parse of proposed_tenants / tenant_grants lists."""
    out = []
    for it in items or []:
        if isinstance(it, dict) and isinstance(it.get('id', it.get('tenant')), str):
            out.append(it)
    return out[:500]
