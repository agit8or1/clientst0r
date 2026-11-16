"""Client assertions, access tokens and DPoP proofs.

Token request (PROTOCOL.md §6): OAuth 2.1 client_credentials, client
authentication private_key_jwt (RFC 7523 / RFC 7521), plus a DPoP proof
(RFC 9449) made with the same per-connection key.

  client assertion   typ client-authentication+jwt, iss = sub = client_id,
                     aud = the exact token endpoint URL, jti single-use,
                     exp - iat <= 60 s
  access token       typ at+jwt (RFC 9068 profile), iss = aud = the
                     issuing installation id, sub = client_id, scope,
                     exp - iat <= 300 s, cnf.jkt = thumbprint of the
                     connection key (RFC 9449 §6)
  DPoP proof         typ dpop+jwt, jwk header, htm, htu, iat, jti single-use,
                     ath = base64url(SHA-256(access token)) on resource calls

A stolen access token alone is useless: every call needs a fresh proof
signed by the private key whose thumbprint the token is bound to, and that
key never leaves its owner.
"""
from __future__ import annotations

import secrets
import time
from typing import Callable, Dict, Iterable, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import keys as _keys
from .canonical import sha256_b64url
from .errors import (ConnectError, INVALID_CLIENT, INVALID_DPOP, INVALID_REQUEST, INVALID_TOKEN, REPLAYED)
from .jws import sign_compact, unverified_header, unverified_payload, verify_compact
from .replay import ReplayStore
from .scopes import parse_scope_string

CLIENT_ASSERTION_TYPE = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
TYP_ASSERTION = 'client-authentication+jwt'
TYP_ACCESS_TOKEN = 'at+jwt'
TYP_DPOP = 'dpop+jwt'
ASSERTION_MAX_LIFETIME = 60
ACCESS_TOKEN_LIFETIME = 300
DPOP_MAX_AGE = 120
SKEW = 120

KeySource = Union[Mapping[str, Ed25519PublicKey], Callable[[str], Optional[Ed25519PublicKey]]]


def _lookup(source: KeySource, kid: str) -> Optional[Ed25519PublicKey]:
    if callable(source):
        return source(kid)
    return source.get(kid)


def new_jti() -> str:
    return secrets.token_urlsafe(24)


def _now(now) -> int:
    return int(time.time() if now is None else now)


# --- client assertion -------------------------------------------------------------

def build_client_assertion(private_key: Ed25519PrivateKey, client_id: str, token_endpoint: str,
                           now: Optional[int] = None, jti: Optional[str] = None, lifetime: int = 60) -> str:
    if not 0 < lifetime <= ASSERTION_MAX_LIFETIME:
        raise ConnectError(INVALID_REQUEST, 'assertion lifetime must be 1..60 s')
    iat = _now(now)
    return sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_ASSERTION, 'kid': _keys.thumbprint(private_key)},
                        {'iss': client_id, 'sub': client_id, 'aud': token_endpoint, 'iat': iat,
                         'exp': iat + lifetime, 'jti': jti or new_jti()})


def verify_client_assertion(assertion: str, keys: KeySource, *, client_id: str, token_endpoint: str,
                            replay: ReplayStore, now: Optional[int] = None) -> Tuple[dict, str]:
    """(claims, kid). Refuses unknown kid, wrong iss/sub/aud, a lifetime over
    60 s, expiry, and a jti seen before (recorded only after the signature)."""
    try:
        header = unverified_header(assertion)
    except ConnectError as e:
        raise ConnectError(INVALID_CLIENT, e.message, 401) from e
    kid = str(header.get('kid') or '')
    key = _lookup(keys, kid)
    if key is None:
        raise ConnectError(INVALID_CLIENT, 'unknown client key', 401)
    try:
        claims = verify_compact(assertion, key, typ=TYP_ASSERTION, audience=token_endpoint, issuer=client_id,
                                now=now, max_lifetime=ASSERTION_MAX_LIFETIME, skew=SKEW,
                                required=('iss', 'sub', 'aud', 'iat', 'exp', 'jti'))
    except ConnectError as e:
        raise ConnectError(INVALID_CLIENT, e.message, 401) from e
    if claims.get('sub') != client_id or not isinstance(claims.get('jti'), str) or not claims['jti']:
        raise ConnectError(INVALID_CLIENT, 'assertion subject or jti invalid', 401)
    if not replay.add('assertion', f'{client_id}:{claims["jti"]}', claims['exp'] + SKEW):
        raise ConnectError(REPLAYED, 'client assertion already used', 401)
    return claims, kid


# --- access tokens ------------------------------------------------------------------

def issue_access_token(private_key: Ed25519PrivateKey, *, issuer: str, client_id: str, scopes: Iterable[str],
                       jkt: str, now: Optional[int] = None, lifetime: int = ACCESS_TOKEN_LIFETIME,
                       jti: Optional[str] = None, extra: Optional[dict] = None) -> Tuple[str, dict]:
    if not 0 < lifetime <= ACCESS_TOKEN_LIFETIME:
        raise ConnectError(INVALID_REQUEST, 'access token lifetime must be 1..300 s')
    iat = _now(now)
    claims = dict(extra or {})
    claims.update({'iss': issuer, 'aud': issuer, 'sub': client_id, 'client_id': client_id,
                   'scope': ' '.join(sorted(set(scopes))), 'iat': iat, 'nbf': iat, 'exp': iat + lifetime,
                   'jti': jti or new_jti(), 'cnf': {'jkt': jkt}})
    token = sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_ACCESS_TOKEN,
                                       'kid': _keys.thumbprint(private_key)}, claims)
    return token, claims


def verify_access_token(token: str, keys: KeySource, *, issuer: str, now: Optional[int] = None) -> dict:
    """Signature, typ, iss = aud = this installation, exp/nbf (no leeway on
    expiry: we issued it with our own clock), lifetime cap, cnf.jkt."""
    try:
        header = unverified_header(token)
    except ConnectError as e:
        raise ConnectError(INVALID_TOKEN, e.message, 401) from e
    key = _lookup(keys, str(header.get('kid') or ''))
    if key is None:
        raise ConnectError(INVALID_TOKEN, 'token signed by an unknown key', 401)
    try:
        claims = verify_compact(token, key, typ=TYP_ACCESS_TOKEN, audience=issuer, issuer=issuer, now=now,
                                max_lifetime=ACCESS_TOKEN_LIFETIME, skew=0,
                                required=('iss', 'aud', 'sub', 'client_id', 'scope', 'iat', 'exp', 'jti', 'cnf'))
    except ConnectError as e:
        raise ConnectError(INVALID_TOKEN, e.message, 401) from e
    cnf = claims.get('cnf')
    if not isinstance(cnf, dict) or not isinstance(cnf.get('jkt'), str) or not cnf['jkt']:
        raise ConnectError(INVALID_TOKEN, 'token is not sender-constrained', 401)
    if claims.get('sub') != claims.get('client_id'):
        raise ConnectError(INVALID_TOKEN, 'token subject mismatch', 401)
    claims['scopes'] = parse_scope_string(claims.get('scope', ''))
    return claims


def token_client_id(token: str) -> str:
    """client_id of a token WITHOUT verification — only to pick the
    connection whose keys then verify it."""
    try:
        return str(unverified_payload(token).get('client_id') or '')
    except ConnectError:
        return ''


# --- DPoP ---------------------------------------------------------------------------

def normalize_htu(url: str) -> str:
    """RFC 9449 §4.3: scheme and host lower-cased, default port dropped, no
    query or fragment."""
    p = urlsplit(url)
    scheme = p.scheme.lower()
    host = (p.hostname or '').lower()
    if ':' in host:
        host = f'[{host}]'
    port = p.port
    netloc = host if port is None or (scheme, port) in (('https', 443), ('http', 80)) else f'{host}:{port}'
    return urlunsplit((scheme, netloc, p.path or '/', '', ''))


def access_token_hash(access_token: str) -> str:
    return sha256_b64url(access_token.encode('ascii'))


def build_dpop_proof(private_key: Ed25519PrivateKey, method: str, url: str, *, now: Optional[int] = None,
                     jti: Optional[str] = None, access_token: Optional[str] = None) -> str:
    claims = {'jti': jti or new_jti(), 'htm': method.upper(), 'htu': normalize_htu(url), 'iat': _now(now)}
    if access_token:
        claims['ath'] = access_token_hash(access_token)
    jwk = _keys.public_jwk(private_key)
    header = {'alg': 'EdDSA', 'typ': TYP_DPOP, 'jwk': {k: jwk[k] for k in ('kty', 'crv', 'x')}}
    return sign_compact(private_key, header, claims)


def verify_dpop_proof(proof: str, *, method: str, url: str, replay: ReplayStore, now: Optional[int] = None,
                      access_token: Optional[str] = None, expected_jkt: Optional[str] = None,
                      allowed_jkts: Optional[Iterable[str]] = None) -> Tuple[str, dict]:
    """(jkt, claims). The key is the proof's own `jwk` header; it must match
    `expected_jkt` (the token's cnf.jkt) or be one of `allowed_jkts` (the
    connection's keys, at the token endpoint). iat within ±120 s, jti
    single-use, htm/htu exact, ath = hash of the presented token."""
    if not isinstance(proof, str) or not proof:
        raise ConnectError(INVALID_DPOP, 'DPoP proof missing', 401)
    try:
        header = unverified_header(proof)
    except ConnectError as e:
        raise ConnectError(INVALID_DPOP, e.message, 401) from e
    jwk = header.get('jwk')
    try:
        key = _keys.public_key_from_jwk(jwk)
    except ConnectError as e:
        raise ConnectError(INVALID_DPOP, e.message, 401) from e
    jkt = _keys.thumbprint(key)
    if expected_jkt is not None and jkt != expected_jkt:
        raise ConnectError(INVALID_DPOP, 'proof key does not match the token binding', 401)
    if allowed_jkts is not None and jkt not in set(allowed_jkts):
        raise ConnectError(INVALID_DPOP, 'proof key is not a key of this connection', 401)
    now_i = _now(now)
    try:
        # DPoP proofs carry no exp: signature + typ here, iat checked below.
        claims = verify_compact(proof, key, typ=TYP_DPOP, now=now_i, skew=SKEW,
                                required=('jti', 'htm', 'htu', 'iat'))
    except ConnectError as e:
        raise ConnectError(INVALID_DPOP, e.message, 401) from e
    iat = claims.get('iat')
    if isinstance(iat, bool) or not isinstance(iat, int) or abs(now_i - iat) > DPOP_MAX_AGE:
        raise ConnectError(INVALID_DPOP, 'proof too old or from the future', 401)
    if claims.get('htm') != method.upper() or claims.get('htu') != normalize_htu(url):
        raise ConnectError(INVALID_DPOP, 'proof is for another request', 401)
    if access_token is not None:
        if claims.get('ath') != access_token_hash(access_token):
            raise ConnectError(INVALID_DPOP, 'proof is for another access token', 401)
    if not isinstance(claims.get('jti'), str) or not 8 <= len(claims['jti']) <= 128:
        raise ConnectError(INVALID_DPOP, 'proof jti invalid', 401)
    if not replay.add('dpop', f'{jkt}:{claims["jti"]}', iat + DPOP_MAX_AGE + SKEW):
        raise ConnectError(REPLAYED, 'DPoP proof already used', 401)
    return jkt, claims


def keys_by_kid(jwks) -> Dict[str, Ed25519PublicKey]:
    return _keys.keyring(jwks)


def authenticate_resource_request(*, authorization: str, dpop: str, method: str, url: str, issuer: str,
                                  token_keys_for: Callable[[str], KeySource], replay: ReplayStore,
                                  now: Optional[int] = None) -> Tuple[dict, str]:
    """Authenticate one API call: `Authorization: DPoP <token>` + `DPoP: <proof>`.

    `token_keys_for(client_id)` returns OUR keys that may have signed tokens
    for that connection (active + retiring), or {} for an unknown / inactive
    connection. Returns (token claims, client_id). The caller then checks the
    connection is active, the token is not older than the connection's
    tokens_not_before, and intersects the scopes with what is granted NOW.
    """
    scheme, _, token = (authorization or '').partition(' ')
    if scheme != 'DPoP' or not token:
        if scheme == 'Bearer':
            raise ConnectError(INVALID_TOKEN, 'bearer tokens are not accepted; use DPoP', 401)
        raise ConnectError(INVALID_TOKEN, 'missing access token', 401)
    client_id = token_client_id(token)
    if not client_id:
        raise ConnectError(INVALID_TOKEN, 'malformed access token', 401)
    claims = verify_access_token(token, token_keys_for(client_id) or {}, issuer=issuer, now=now)
    verify_dpop_proof(dpop, method=method, url=url, replay=replay, now=now, access_token=token,
                      expected_jkt=claims['cnf']['jkt'])
    return claims, client_id
