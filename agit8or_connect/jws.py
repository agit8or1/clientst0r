"""Compact JWS with EdDSA (Ed25519) only.

Producing: header and payload are canonical JSON (byte-exact across SDKs),
signed with `cryptography`'s Ed25519.

Verifying: PyJWT checks the signature, the algorithm allow-list (EdDSA only:
no `none`, no HMAC/RSA confusion), `aud` (strict single string) and `iss`;
this module adds the `typ` check, the required-claims check and the time
checks against an injectable clock (so test vectors verify at a fixed time).
"""
from __future__ import annotations

import json
import time
from typing import Iterable, Optional

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import b64url, canonical_bytes, from_b64url
from .errors import ConnectError, EXPIRED, INVALID_REQUEST, INVALID_SIGNATURE

MAX_TOKEN_LENGTH = 8192
DEFAULT_SKEW = 120


def sign_compact(private_key: Ed25519PrivateKey, header: dict, payload: dict) -> str:
    if header.get('alg') != 'EdDSA':
        raise ConnectError(INVALID_REQUEST, 'only EdDSA is produced')
    h = b64url(canonical_bytes(header))
    p = b64url(canonical_bytes(payload))
    sig = private_key.sign(f'{h}.{p}'.encode('ascii'))
    return f'{h}.{p}.{b64url(sig)}'


def _parts(token: str):
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        raise ConnectError(INVALID_REQUEST, 'token missing or too long')
    parts = token.split('.')
    if len(parts) != 3 or not all(parts[:2]) or not parts[2]:
        raise ConnectError(INVALID_REQUEST, 'not a compact JWS')
    return parts


def unverified_header(token: str) -> dict:
    parts = _parts(token)
    try:
        header = json.loads(from_b64url(parts[0]))
    except ValueError as e:
        raise ConnectError(INVALID_REQUEST, 'malformed JWS header') from e
    if not isinstance(header, dict):
        raise ConnectError(INVALID_REQUEST, 'malformed JWS header')
    if header.get('alg') != 'EdDSA':
        raise ConnectError(INVALID_SIGNATURE, 'unsupported JWS algorithm')
    if 'crit' in header:
        raise ConnectError(INVALID_REQUEST, 'critical JWS header parameters are not supported')
    return header


def unverified_payload(token: str) -> dict:
    parts = _parts(token)
    try:
        payload = json.loads(from_b64url(parts[1]))
    except ValueError as e:
        raise ConnectError(INVALID_REQUEST, 'malformed JWS payload') from e
    if not isinstance(payload, dict):
        raise ConnectError(INVALID_REQUEST, 'malformed JWS payload')
    return payload


def check_times(claims: dict, now: Optional[float] = None, *, max_lifetime: Optional[int] = None,
                skew: int = DEFAULT_SKEW, require_iat: bool = True) -> None:
    """exp in the future, nbf/iat not in the future (± skew), lifetime cap."""
    now = time.time() if now is None else now
    for name in ('exp', 'iat', 'nbf'):
        v = claims.get(name)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise ConnectError(INVALID_REQUEST, f'{name} must be an integer')
    exp, iat, nbf = claims.get('exp'), claims.get('iat'), claims.get('nbf')
    if exp is None or (require_iat and iat is None):
        raise ConnectError(INVALID_REQUEST, 'exp and iat are required')
    if now >= exp + skew:
        raise ConnectError(EXPIRED, 'token expired', 401)
    if iat is not None and iat > now + skew:
        raise ConnectError(INVALID_REQUEST, 'token issued in the future', 401)
    if nbf is not None and nbf > now + skew:
        raise ConnectError(INVALID_REQUEST, 'token not yet valid', 401)
    if max_lifetime is not None and iat is not None and exp - iat > max_lifetime:
        raise ConnectError(INVALID_REQUEST, 'token lifetime exceeds the maximum', 401)
    if iat is not None and exp <= iat:
        raise ConnectError(INVALID_REQUEST, 'exp must be after iat', 401)


def verify_compact(token: str, key: Ed25519PublicKey, *, typ: str, audience: Optional[str] = None,
                   issuer: Optional[str] = None, now: Optional[float] = None, max_lifetime: Optional[int] = None,
                   skew: int = DEFAULT_SKEW, required: Iterable[str] = ('iat', 'exp')) -> dict:
    """Verify signature + typ + aud + iss + times. Returns the claims."""
    header = unverified_header(token)
    if header.get('typ') != typ:
        raise ConnectError(INVALID_REQUEST, f'expected a {typ} token', 401)
    if not isinstance(key, Ed25519PublicKey):
        raise ConnectError(INVALID_SIGNATURE, 'no usable verification key', 401)
    options = {'verify_signature': True, 'verify_exp': False, 'verify_nbf': False, 'verify_iat': False,
               'verify_aud': audience is not None, 'verify_iss': issuer is not None, 'strict_aud': True,
               'require': list(required)}
    try:
        claims = jwt.decode(token, key=key, algorithms=['EdDSA'], audience=audience, issuer=issuer,
                            options=options)
    except jwt.InvalidSignatureError as e:
        raise ConnectError(INVALID_SIGNATURE, 'signature does not verify', 401) from e
    except jwt.InvalidAudienceError as e:
        raise ConnectError(INVALID_SIGNATURE, 'wrong audience', 401) from e
    except jwt.InvalidIssuerError as e:
        raise ConnectError(INVALID_SIGNATURE, 'wrong issuer', 401) from e
    except jwt.MissingRequiredClaimError as e:
        raise ConnectError(INVALID_REQUEST, f'missing claim {e.claim}', 401) from e
    except jwt.PyJWTError as e:
        raise ConnectError(INVALID_SIGNATURE, 'token rejected', 401) from e
    if audience is not None and claims.get('aud') != audience:
        raise ConnectError(INVALID_SIGNATURE, 'wrong audience', 401)
    if issuer is not None and claims.get('iss') != issuer:
        raise ConnectError(INVALID_SIGNATURE, 'wrong issuer', 401)
    if 'exp' in tuple(required):
        check_times(claims, now, max_lifetime=max_lifetime, skew=skew, require_iat='iat' in tuple(required))
    return claims
