"""ID token and back-channel logout token validation (PyJWT, no custom crypto).

ID token (OIDC Core §3.1.3.7):
  * alg in the provider's allowlist (subset of RS256/PS256/ES256/EdDSA) —
    never "none", never HS* (no shared-secret signatures), no "crit" header;
  * signature with a key from the OP's JWKS: kid match, key type matching
    the alg, use=sig; an unknown kid refetches the JWKS once (rotation);
  * iss exact, aud contains client_id, azp == client_id when present (and
    required when there are several audiences);
  * exp / iat / nbf with LEEWAY seconds; iat not older than MAX_TOKEN_AGE;
  * nonce equals the one stored for this flow;
  * auth_time present and within max_age when max_age was requested;
  * at_hash checked when present and an access token was returned.

Logout token (OIDC Back-Channel Logout §2.6): same signature / iss / aud /
iat checks, a jti, the back-channel logout event, no nonce, sid or sub.
"""
import base64
import hashlib
import hmac
import time

import jwt
from jwt import PyJWK

from . import discovery
from .http import OPError
from .models import ALLOWED_ALGORITHMS

LEEWAY = 60
MAX_TOKEN_AGE = 600
LOGOUT_EVENT = 'http://schemas.openid.net/event/backchannel-logout'

_KTY = {'RS256': 'RSA', 'PS256': 'RSA', 'ES256': 'EC', 'EdDSA': 'OKP'}
_HASH = {'RS256': hashlib.sha256, 'PS256': hashlib.sha256, 'ES256': hashlib.sha256, 'EdDSA': hashlib.sha512}


class TokenError(Exception):
    """A token was refused. `reason` is a short machine code for the audit log."""

    def __init__(self, reason, message=''):
        super().__init__(message or reason)
        self.reason = reason


def _header(token):
    if not isinstance(token, str) or token.count('.') != 2 or len(token) > 16384:
        raise TokenError('malformed', 'Not a signed JWT')
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise TokenError('malformed', 'Unreadable JWT header') from None
    alg = header.get('alg')
    if alg not in ALLOWED_ALGORITHMS:
        raise TokenError('bad_alg', f'Algorithm {str(alg)[:20]!r} is not allowed')
    if 'crit' in header:
        raise TokenError('bad_header', 'Unsupported critical header')
    return header


def _candidates(jwks, alg, kid):
    out = []
    for k in jwks.get('keys', []):
        if k.get('kty') != _KTY[alg]:
            continue
        if k.get('use') not in (None, 'sig'):
            continue
        if k.get('alg') not in (None, alg):
            continue
        if kid is not None and k.get('kid') != kid:
            continue
        out.append(k)
    return out


def _signing_key(provider, header):
    alg, kid = header['alg'], header.get('kid')
    try:
        jwks = discovery.get_jwks(provider)
        found = _candidates(jwks, alg, kid)
        if not found:
            refreshed = discovery.refetch_jwks_once(provider)
            if refreshed is not None:
                found = _candidates(refreshed, alg, kid)
    except OPError as exc:
        raise TokenError('jwks_unavailable', str(exc)) from None
    if len(found) != 1:
        raise TokenError('unknown_key', 'No single matching signing key in the OP\'s JWKS')
    try:
        return PyJWK(found[0], algorithm=alg).key
    except jwt.PyJWTError:
        raise TokenError('unknown_key', 'Signing key could not be used') from None


def _decode(provider, token, require):
    header = _header(token)
    if header['alg'] not in provider.algorithm_list():
        raise TokenError('bad_alg', f'Algorithm {header["alg"]} is not enabled for this provider')
    key = _signing_key(provider, header)
    try:
        claims = jwt.decode(
            token, key=key, algorithms=[header['alg']],
            audience=provider.client_id, issuer=provider.issuer_normalized, leeway=LEEWAY,
            options={'require': require, 'verify_signature': True, 'verify_exp': True,
                     'verify_iat': True, 'verify_nbf': True, 'verify_aud': True, 'verify_iss': True},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError('expired', 'Token has expired') from None
    except jwt.InvalidAudienceError:
        raise TokenError('bad_aud', 'Token is not for this client') from None
    except jwt.InvalidIssuerError:
        raise TokenError('bad_iss', 'Token issuer does not match') from None
    except jwt.InvalidSignatureError:
        raise TokenError('bad_signature', 'Signature does not verify') from None
    except (jwt.ImmatureSignatureError, jwt.InvalidIssuedAtError):
        raise TokenError('not_yet_valid', 'Token issued in the future') from None
    except jwt.MissingRequiredClaimError as exc:
        raise TokenError('missing_claim', f'Missing claim {exc.claim}') from None
    except jwt.PyJWTError as exc:
        raise TokenError('invalid', type(exc).__name__) from None
    # PyJWT allows a str issuer to match; insist on the exact string.
    if claims.get('iss') != provider.issuer_normalized:
        raise TokenError('bad_iss', 'Token issuer does not match')
    aud = claims.get('aud')
    audiences = aud if isinstance(aud, list) else [aud]
    azp = claims.get('azp')
    if azp is not None and azp != provider.client_id:
        raise TokenError('bad_azp', 'Token azp is not this client')
    if len(audiences) > 1 and azp is None:
        raise TokenError('bad_azp', 'Token has several audiences and no azp')
    iat = claims.get('iat')
    if not isinstance(iat, (int, float)) or time.time() - iat > MAX_TOKEN_AGE + LEEWAY:
        raise TokenError('stale', 'Token was issued too long ago')
    return header, claims


def _at_hash_ok(alg, access_token, at_hash):
    digest = _HASH[alg](access_token.encode('ascii')).digest()
    expected = base64.urlsafe_b64encode(digest[:len(digest) // 2]).rstrip(b'=').decode()
    return hmac.compare_digest(expected, str(at_hash))


def validate_id_token(provider, token, *, nonce, max_age=None, access_token=None):
    header, claims = _decode(provider, token, ['iss', 'sub', 'aud', 'exp', 'iat'])
    sub = claims.get('sub')
    if not isinstance(sub, str) or not sub or len(sub) > 255:
        raise TokenError('bad_sub', 'Token has no usable sub')
    got = claims.get('nonce')
    if not isinstance(got, str) or not nonce or not hmac.compare_digest(got, nonce):
        raise TokenError('bad_nonce', 'Nonce does not match this sign-in')
    if max_age is not None:
        auth_time = claims.get('auth_time')
        if not isinstance(auth_time, (int, float)):
            raise TokenError('no_auth_time', 'Token has no auth_time')
        if time.time() - auth_time > max_age + LEEWAY:
            raise TokenError('stale_auth', 'The sign-in at the OP is not recent enough')
    if access_token and claims.get('at_hash') is not None:
        if not _at_hash_ok(header['alg'], access_token, claims['at_hash']):
            raise TokenError('bad_at_hash', 'at_hash does not match the access token')
    return claims


def validate_logout_token(provider, token):
    _header_, claims = _decode(provider, token, ['iss', 'aud', 'iat', 'jti'])
    if 'nonce' in claims:
        raise TokenError('nonce_present', 'Logout token must not carry a nonce')
    events = claims.get('events')
    if not isinstance(events, dict) or not isinstance(events.get(LOGOUT_EVENT), dict):
        raise TokenError('bad_events', 'Not a back-channel logout token')
    sid, sub = claims.get('sid'), claims.get('sub')
    if not (isinstance(sid, str) and sid) and not (isinstance(sub, str) and sub):
        raise TokenError('no_subject', 'Logout token has neither sid nor sub')
    jti = claims.get('jti')
    if not isinstance(jti, str) or not jti or len(jti) > 255:
        raise TokenError('bad_jti', 'Logout token has no usable jti')
    return claims
