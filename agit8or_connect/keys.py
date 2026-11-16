"""Ed25519 keys as JWKs (RFC 8037), thumbprints (RFC 7638) and JWKS.

Every connection has its own Ed25519 key pair on each side. The key id
(`kid`) of a key is its RFC 7638 thumbprint, so a kid can always be checked
against the key it names and two different keys can never share one.

An *endorsed* JWKS (PROTOCOL.md §9) carries a JWS signed by a key the peer
already trusts, over the SHA-256 of the canonical key list. A peer adds a new
key from a fetched JWKS only when that endorsement verifies with a key it
already holds — so rotation does not depend on TLS alone.
"""
from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import b64url, canonical_json, from_b64url, sha256_b64url, sha256_hex
from .errors import ConnectError, INVALID_REQUEST, INVALID_SIGNATURE

_RAW = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
JWKS_TYP = 'agit8or-jwks+jwt'
MAX_KEYS = 8


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_from_seed(seed: bytes) -> Ed25519PrivateKey:
    """For TEST VECTORS only: a key from a fixed 32-byte seed."""
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ConnectError(INVALID_REQUEST, 'an Ed25519 seed is 32 bytes')
    return Ed25519PrivateKey.from_private_bytes(bytes(seed))


def private_key_to_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode('ascii')


def private_key_from_pem(pem: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key((pem or '').encode('ascii'), password=None)
    except (ValueError, TypeError) as e:
        raise ConnectError(INVALID_REQUEST, 'not a PEM private key') from e
    if not isinstance(key, Ed25519PrivateKey):
        raise ConnectError(INVALID_REQUEST, 'key is not Ed25519')
    return key


def _public(key) -> Ed25519PublicKey:
    if isinstance(key, Ed25519PrivateKey):
        return key.public_key()
    if isinstance(key, Ed25519PublicKey):
        return key
    if isinstance(key, dict):
        return public_key_from_jwk(key)
    raise ConnectError(INVALID_REQUEST, 'not an Ed25519 key')


def raw_public(key) -> bytes:
    return _public(key).public_bytes(*_RAW)


def thumbprint(key) -> str:
    """RFC 7638 JWK thumbprint (SHA-256, base64url) of an Ed25519 key:
    the hash of {"crv":"Ed25519","kty":"OKP","x":...} — canonical JSON of
    exactly the required members, which is the RFC's serialization."""
    x = b64url(raw_public(key))
    return sha256_b64url(canonical_json({'crv': 'Ed25519', 'kty': 'OKP', 'x': x}))


def public_jwk(key, kid: Optional[str] = None) -> dict:
    """The public JWK. `kid` defaults to (and must equal) the thumbprint."""
    tp = thumbprint(key)
    if kid is not None and kid != tp:
        raise ConnectError(INVALID_REQUEST, 'kid must be the key thumbprint')
    return {'kty': 'OKP', 'crv': 'Ed25519', 'x': b64url(raw_public(key)), 'kid': tp, 'alg': 'EdDSA', 'use': 'sig'}


def public_key_from_jwk(jwk: dict) -> Ed25519PublicKey:
    """Strict: OKP / Ed25519 / 32-byte x, never a private member, and a kid
    (when present) that equals the thumbprint. Unknown members are ignored."""
    if not isinstance(jwk, dict):
        raise ConnectError(INVALID_REQUEST, 'JWK must be an object')
    if jwk.get('kty') != 'OKP' or jwk.get('crv') != 'Ed25519':
        raise ConnectError(INVALID_REQUEST, 'only OKP / Ed25519 keys are accepted')
    if 'd' in jwk:
        raise ConnectError(INVALID_REQUEST, 'a private key must never be sent')
    if jwk.get('alg') not in (None, 'EdDSA'):
        raise ConnectError(INVALID_REQUEST, 'JWK alg must be EdDSA')
    raw = from_b64url(jwk.get('x') or '')
    if len(raw) != 32:
        raise ConnectError(INVALID_REQUEST, 'Ed25519 public key must be 32 bytes')
    key = Ed25519PublicKey.from_public_bytes(raw)
    kid = jwk.get('kid')
    if kid is not None and kid != thumbprint(key):
        raise ConnectError(INVALID_REQUEST, 'JWK kid does not match its thumbprint')
    return key


def fingerprint(key) -> str:
    """Human-comparable form: the thumbprint grouped in fours."""
    tp = thumbprint(key)
    return ' '.join(tp[i:i + 4] for i in range(0, len(tp), 4))


def keyring(jwks) -> Dict[str, Ed25519PublicKey]:
    """{kid: key} from a JWKS dict or a list of JWKs; invalid entries skipped."""
    entries = jwks.get('keys', []) if isinstance(jwks, dict) else (jwks or [])
    out = {}
    for jwk in list(entries)[:MAX_KEYS]:
        try:
            key = public_key_from_jwk(jwk)
        except ConnectError:
            continue
        out[thumbprint(key)] = key
    return out


def keys_digest(jwks_keys: Iterable[dict]) -> str:
    """SHA-256 hex of the canonical list of public JWKs (sorted by kid)."""
    norm = sorted(({'crv': 'Ed25519', 'kid': thumbprint(k), 'kty': 'OKP', 'x': k['x']} for k in jwks_keys),
                  key=lambda k: k['kid'])
    return sha256_hex(canonical_json(norm))


def endorsed_jwks(signing_key: Ed25519PrivateKey, public_keys: List[dict], issuer: str, connection_id: str,
                  now: Optional[int] = None, lifetime: int = 3600) -> dict:
    """A JWKS for one connection, endorsed by `signing_key` (which must be one
    the peer already trusts — the current active key)."""
    from .jws import sign_compact
    iat = int(now if now is not None else time.time())
    keys = [public_jwk(k) if not isinstance(k, dict) else dict(k) for k in public_keys]
    endorsement = sign_compact(signing_key, {'alg': 'EdDSA', 'typ': JWKS_TYP, 'kid': thumbprint(signing_key)},
                               {'iss': issuer, 'sub': connection_id, 'keys_sha256': keys_digest(keys),
                                'iat': iat, 'exp': iat + lifetime})
    return {'keys': keys, 'endorsement': endorsement}


def verify_endorsed_jwks(document: dict, trusted: Dict[str, Ed25519PublicKey], issuer: str, connection_id: str,
                         now: Optional[int] = None) -> Dict[str, Ed25519PublicKey]:
    """The keyring of a fetched JWKS, only if its endorsement verifies with a
    key in `trusted`. A JWKS whose endorsement is missing, signed by an
    unknown key, stale, or for another connection is refused as a whole."""
    from .jws import verify_compact, unverified_header
    if not isinstance(document, dict) or not isinstance(document.get('keys'), list):
        raise ConnectError(INVALID_REQUEST, 'JWKS must be an object with a keys array')
    if len(document['keys']) > MAX_KEYS:
        raise ConnectError(INVALID_REQUEST, 'too many keys in JWKS')
    token = document.get('endorsement')
    if not isinstance(token, str):
        raise ConnectError(INVALID_SIGNATURE, 'JWKS is not endorsed')
    header = unverified_header(token)
    key = trusted.get(str(header.get('kid') or ''))
    if key is None:
        raise ConnectError(INVALID_SIGNATURE, 'JWKS endorsed by a key that is not trusted')
    claims = verify_compact(token, key, typ=JWKS_TYP, issuer=issuer, now=now, max_lifetime=86400,
                            required=('iss', 'sub', 'keys_sha256', 'iat', 'exp'))
    if claims.get('sub') != connection_id:
        raise ConnectError(INVALID_SIGNATURE, 'JWKS endorsement is for another connection')
    ring = keyring(document['keys'])
    if claims.get('keys_sha256') != keys_digest([public_jwk(k) for k in ring.values()]) or \
            len(ring) != len(document['keys']):
        raise ConnectError(INVALID_SIGNATURE, 'JWKS keys do not match the endorsement')
    return ring
