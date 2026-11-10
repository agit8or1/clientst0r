"""
Signing primitives for Rem0te's contract ticket-rmm-v1 — a byte-for-byte
port of Rem0te's apps/api/src/integration/crypto.ts (pinned revision in
contract/PIN.json).

Ed25519 only, through the `cryptography` package. There is no algorithm
negotiation: no `alg: none`, no HMAC/RSA confusion, no key-type downgrade.
Every signature covers a domain-separated string, so a signature made for
one purpose (a request, an inference response, a job event, an alert event)
never verifies as another.

  rem0te-http-req-v1\\n{audience}\\n{METHOD}\\n{path?query}\\n{ts}\\n{nonce}\\n{sha256(body)}
  rem0te-http-resp-v1\\n{the request's nonce}\\n{sha256(body)}
  rem0te-event-v1\\n{canonical JSON of the event}
  rem0te-alert-event-v1\\n{canonical JSON of the alert event}

Canonical JSON (Rem0te's canonicalJson): object keys sorted, no whitespace,
arrays in order, strings escaped exactly as JavaScript's JSON.stringify
escapes them, numbers formatted as JavaScript formats them. Non-finite and
unsafe integers are refused, as Rem0te refuses them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import secrets as _secrets
import time
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

CONTRACT = 'ticket-rmm-v1'

MAX_CLOCK_SKEW_S = 120
MAX_DELEGATION_TTL_S = 300
DELEGATION_TTL_S = 120
DELEGATION_TYP = 'rem0te-delegation+jwt'

H_KEY_ID = 'rem0te-key-id'
H_TIMESTAMP = 'rem0te-timestamp'
H_NONCE = 'rem0te-nonce'
H_SIGNATURE = 'rem0te-signature'
H_RESPONSE_SIGNATURE = 'rem0te-response-signature'
H_DELEGATION = 'rem0te-delegation'

KEY_ID_RE = re.compile(r'^([A-Za-z0-9._-]{1,64})/([A-Za-z0-9._-]{1,64})$')
KID_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
TIMESTAMP_RE = re.compile(r'^\d{9,11}$')
NONCE_RE = re.compile(r'^[A-Za-z0-9_-]{16,128}$')
B64URL_RE = re.compile(r'^[A-Za-z0-9_-]*$')
EXT_ID_RE = re.compile(r'^[A-Za-z0-9._:@-]{1,128}$')
PROFILE_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')

SCOPES = ('ticket_analysis:submit', 'ticket_analysis:read', 'actions:propose', 'actions:read')

MAX_SAFE_INTEGER = 2 ** 53 - 1


class ProtocolError(ValueError):
    """A message that cannot be produced or verified under the contract."""


# --- canonical JSON ------------------------------------------------------------

_ESCAPES = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _js_string(s: str) -> str:
    """JSON.stringify(string): ", \\ and C0 controls escaped (short forms for
    \\b \\f \\n \\r \\t, \\u00xx lowercase otherwise), lone surrogates as \\udxxx,
    everything else — including non-ASCII, U+2028/9 and DEL — verbatim."""
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif o < 0x20 or 0xD800 <= o <= 0xDFFF:
            out.append(f'\\u{o:04x}')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _js_number(n) -> str:
    """Number.prototype.toString for the values JSON.stringify emits."""
    if isinstance(n, bool):
        raise ProtocolError('canonical_json: bool is not a number')
    if isinstance(n, int):
        if abs(n) > MAX_SAFE_INTEGER:
            raise ProtocolError('canonical_json: number out of range')
        return str(n)
    if not math.isfinite(n):
        raise ProtocolError('canonical_json: number out of range')
    if n == int(n):
        if abs(n) > MAX_SAFE_INTEGER:
            raise ProtocolError('canonical_json: number out of range')
        return str(int(n))
    # Shortest round-trip digits (Python's repr agrees with ECMAScript on the
    # digits), then ECMAScript's choice between plain and exponent notation.
    sign = '-' if n < 0 else ''
    d = Decimal(repr(abs(n)))
    t = d.as_tuple()
    digits = ''.join(map(str, t.digits)).rstrip('0') or '0'
    k = len(digits)
    point = len(t.digits) + t.exponent  # the decimal point's position (ECMAScript "n")
    if k <= point <= 21:
        return sign + digits + '0' * (point - k)
    if 0 < point <= 21:
        return sign + digits[:point] + '.' + digits[point:]
    if -6 < point <= 0:
        return sign + '0.' + '0' * (-point) + digits
    e = point - 1
    mant = digits[0] + ('.' + digits[1:] if k > 1 else '')
    return f'{sign}{mant}e{"+" if e >= 0 else "-"}{abs(e)}'


def canonical_json(value: Any) -> str:
    """Rem0te's canonicalJson(): sorted keys (UTF-16 code unit order), no
    whitespace, `None` members of objects dropped only when they are
    JavaScript `undefined` — which JSON cannot carry, so nothing is dropped."""
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, str):
        return _js_string(value)
    if isinstance(value, (int, float)):
        return _js_number(value)
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(canonical_json(v) for v in value) + ']'
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise ProtocolError('canonical_json: object keys must be strings')
        keys = sorted(value, key=lambda k: k.encode('utf-16-be'))
        return '{' + ','.join(f'{_js_string(k)}:{canonical_json(value[k])}' for k in keys) + '}'
    raise ProtocolError(f'canonical_json: unsupported type {type(value).__name__}')


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data or b'').hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def from_b64url(s: str) -> bytes:
    if not isinstance(s, str) or not B64URL_RE.match(s):
        raise ProtocolError('not base64url')
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


# --- keys --------------------------------------------------------------------

def generate_private_key_pem() -> str:
    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def load_private_key(pem: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key((pem or '').encode(), password=None)
    except (ValueError, TypeError) as e:
        raise ProtocolError('not a PEM private key') from e
    if not isinstance(key, Ed25519PrivateKey):
        raise ProtocolError('key is not Ed25519')
    return key


def load_public_key(pem: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key((pem or '').strip().encode())
    except (ValueError, TypeError) as e:
        raise ProtocolError('not a PEM public key') from e
    if not isinstance(key, Ed25519PublicKey):
        raise ProtocolError('key is not Ed25519')
    return key


def public_pem(private_key) -> str:
    """PEM (SPKI) public key of a private key, or of a public key itself."""
    if isinstance(private_key, str):
        private_key = load_private_key(private_key)
    key = private_key if isinstance(private_key, Ed25519PublicKey) else private_key.public_key()
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def fingerprint(public_key) -> str:
    """SHA-256 of the raw 32-byte public key, hex, grouped for reading aloud."""
    if isinstance(public_key, str):
        public_key = load_public_key(public_key)
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    h = hashlib.sha256(raw).hexdigest()
    return ':'.join(h[i:i + 4] for i in range(0, 32, 4))


def same_public_key(pem_a: str, pem_b: str) -> bool:
    try:
        a, b = load_public_key(pem_a), load_public_key(pem_b)
    except ProtocolError:
        return False
    raw = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return a.public_bytes(*raw) == b.public_bytes(*raw)


def sign(private_key, message) -> str:
    if isinstance(private_key, str):
        private_key = load_private_key(private_key)
    if isinstance(message, str):
        message = message.encode('utf-8')
    return b64url(private_key.sign(message))


def verify(public_key, message, signature: str) -> bool:
    """True only for a valid 64-byte Ed25519 signature. Never raises."""
    try:
        if isinstance(public_key, str):
            public_key = load_public_key(public_key)
        sig = from_b64url(signature)
        if len(sig) != 64:
            return False
        if isinstance(message, str):
            message = message.encode('utf-8')
        public_key.verify(sig, message)
        return True
    except (InvalidSignature, ProtocolError, ValueError, TypeError):
        return False


# --- signing strings -----------------------------------------------------------

def request_signing_string(audience, method, path_with_query, timestamp, nonce, body_sha256) -> str:
    return '\n'.join(['rem0te-http-req-v1', audience, method.upper(), path_with_query, str(timestamp), nonce,
                      body_sha256])


def response_signing_string(request_nonce, body_sha256) -> str:
    return '\n'.join(['rem0te-http-resp-v1', request_nonce, body_sha256])


def event_signing_string(event) -> str:
    return 'rem0te-event-v1\n' + canonical_json(event)


def alert_event_signing_string(event) -> str:
    return 'rem0te-alert-event-v1\n' + canonical_json(event)


def new_nonce() -> str:
    return _secrets.token_urlsafe(18)  # 24 base64url chars, like Rem0te's randomBytes(18)


def request_headers(private_key, key_id: str, audience: str, method: str, path_with_query: str, body: bytes,
                    timestamp: Optional[int] = None, nonce: Optional[str] = None) -> Dict[str, str]:
    """The four signature headers for one request. `key_id` is
    "{peer id}/{kid}" — what the receiver looks the key up by."""
    ts = str(int(timestamp if timestamp is not None else time.time()))
    nonce = nonce or new_nonce()
    sig = sign(private_key, request_signing_string(audience, method, path_with_query, ts, nonce,
                                                   sha256_hex(body or b'')))
    return {H_KEY_ID: key_id, H_TIMESTAMP: ts, H_NONCE: nonce, H_SIGNATURE: sig}


def sign_response(private_key, request_nonce: str, body: bytes) -> str:
    return sign(private_key, response_signing_string(request_nonce, sha256_hex(body or b'')))


# --- delegation JWS (EdDSA only) ------------------------------------------------

def _jws_part(obj) -> str:
    # Rem0te signs JSON.stringify output; any JSON works on the way in, it
    # verifies the bytes. Compact separators keep the token short.
    return b64url(json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def sign_jws(private_key, kid: str, payload: dict, typ: str = DELEGATION_TYP) -> str:
    h = _jws_part({'alg': 'EdDSA', 'kid': kid, 'typ': typ})
    p = _jws_part(payload)
    return f'{h}.{p}.{sign(private_key, f"{h}.{p}")}'


def parse_jws(token: str) -> Tuple[dict, dict, str, str]:
    """(header, payload, signing input, signature). Structure only — the
    caller verifies."""
    if not isinstance(token, str) or len(token) > 4096:
        raise ProtocolError('token too long')
    parts = token.split('.')
    if len(parts) != 3:
        raise ProtocolError('not a compact JWS')
    try:
        header = json.loads(from_b64url(parts[0]))
        payload = json.loads(from_b64url(parts[1]))
    except ValueError as e:
        raise ProtocolError('malformed JWS') from e
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ProtocolError('malformed JWS')
    return header, payload, f'{parts[0]}.{parts[1]}', parts[2]


def delegation_claims(*, peer_id: str, audience: str, technician_id: str, organization_id: str, scope: str,
                      req_sha256: Optional[str] = None, now: Optional[int] = None,
                      ttl: int = DELEGATION_TTL_S, jti: Optional[str] = None) -> dict:
    """The claim set Rem0te's DelegationService accepts: iss = peer id,
    aud = Rem0te's audience, sub/org must equal the body's technician_id /
    organization_id, exp − iat ≤ 300, jti single-use, and req_sha256 (submit
    and propose) = sha256 of the canonical request after defaults."""
    if scope not in SCOPES:
        raise ProtocolError(f'unknown delegation scope {scope}')
    if not (0 < ttl <= MAX_DELEGATION_TTL_S):
        raise ProtocolError('delegation lifetime out of range')
    for name, v in (('peer_id', peer_id), ('technician_id', technician_id), ('organization_id', organization_id)):
        if not EXT_ID_RE.match(v or ''):
            raise ProtocolError(f'{name} has characters the contract does not allow')
    iat = int(now if now is not None else time.time())
    claims = {'iss': peer_id, 'aud': audience, 'sub': technician_id, 'org': organization_id, 'scope': scope,
              'iat': iat, 'exp': iat + ttl, 'jti': jti or _secrets.token_hex(16)}
    if req_sha256 is not None:
        if not re.match(r'^[a-f0-9]{64}$', req_sha256):
            raise ProtocolError('req_sha256 must be 64 lowercase hex')
        claims['req_sha256'] = req_sha256
    return claims


def verify_jws(token: str, keys: Dict[str, Any], typ: str = DELEGATION_TYP) -> dict:
    """Verify a compact EdDSA JWS against {kid: public key}. Returns the
    payload. (ClientSt0r mints delegations; this exists for tests and for the
    lab harness, which plays both sides.)"""
    header, payload, signing_input, sig = parse_jws(token)
    if header.get('alg') != 'EdDSA' or header.get('typ') != typ:
        raise ProtocolError('unsupported token type')
    key = keys.get(str(header.get('kid') or ''))
    if key is None or not verify(key, signing_input, sig):
        raise ProtocolError('token signature invalid')
    return payload


# --- signed events -------------------------------------------------------------

def verify_event_signature(event: dict, signature: dict, keys: Dict[str, Any], alert: bool = False) -> str:
    """Check a {event|alert_event, signature} pair against Rem0te's keys
    ({kid: public key}). Returns '' when valid, else why not (no secrets)."""
    if not isinstance(signature, dict) or set(signature) != {'alg', 'kid', 'sig'}:
        return 'malformed signature object'
    if signature.get('alg') != 'Ed25519':
        return 'unsupported signature algorithm'
    kid = str(signature.get('kid') or '')
    key = keys.get(kid)
    if key is None:
        return f'unknown event signing key id "{kid[:64]}"'
    try:
        message = (alert_event_signing_string if alert else event_signing_string)(event)
    except ProtocolError as e:
        return f'event cannot be canonicalised ({e})'
    if not verify(key, message, str(signature.get('sig') or '')):
        return 'event signature does not verify'
    return ''


def keyring(entries: Iterable[dict]) -> Dict[str, Ed25519PublicKey]:
    """[{kid, public_key_pem}] → {kid: key}, skipping anything unusable."""
    out = {}
    for e in entries or []:
        try:
            kid = str(e.get('kid') or '')
            if KID_RE.match(kid):
                out[kid] = load_public_key(e.get('public_key_pem') or '')
        except (ProtocolError, AttributeError):
            continue
    return out
