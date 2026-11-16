"""OP metadata (discovery) and signing keys (JWKS), cached per worker.

Discovery is read from <issuer>/.well-known/openid-configuration. The
document's "issuer" must equal the configured issuer exactly (OIDC Discovery
§4.3), and every endpoint passes the outbound request guard.

JWKS: cached; a token whose kid is not in the cached set triggers one
refetch (key rotation), at most once per REFETCH_COOLDOWN seconds per
provider, so a flood of tokens with random kids cannot hammer the OP.
"""
import hashlib
import time

from django.core.cache import cache

from .http import OPError, check_url, request_json
from .models import ALLOWED_ALGORITHMS

METADATA_TTL = 3600
JWKS_TTL = 3600
REFETCH_COOLDOWN = 30

REQUIRED_ENDPOINTS = ('authorization_endpoint', 'token_endpoint', 'jwks_uri')
OPTIONAL_ENDPOINTS = ('userinfo_endpoint', 'end_session_endpoint')


def _key(provider, what):
    digest = hashlib.sha256(provider.issuer_normalized.encode()).hexdigest()[:16]
    return f'oidc_sso:{what}:{provider.pk}:{digest}'


def discovery_url(provider):
    return provider.issuer_normalized.rstrip('/') + '/.well-known/openid-configuration'


def fetch_metadata(provider):
    """Fetch and validate the discovery document (no cache)."""
    _status, doc = request_json(provider, 'GET', check_url(provider, discovery_url(provider)))
    if not isinstance(doc, dict):
        raise OPError('Discovery document is not a JSON object')
    if doc.get('issuer') != provider.issuer_normalized:
        raise OPError('Discovery "issuer" does not exactly match the configured issuer '
                      f'({str(doc.get("issuer"))[:200]!r})')
    meta = {'issuer': doc['issuer']}
    for name in REQUIRED_ENDPOINTS:
        if not isinstance(doc.get(name), str) or not doc.get(name):
            raise OPError(f'Discovery document has no {name}')
        meta[name] = check_url(provider, doc[name])
    for name in OPTIONAL_ENDPOINTS:
        if isinstance(doc.get(name), str) and doc.get(name):
            meta[name] = check_url(provider, doc[name])
    algs = doc.get('id_token_signing_alg_values_supported')
    if isinstance(algs, list):
        usable = [a for a in algs if a in ALLOWED_ALGORITHMS and a in provider.algorithm_list()]
        if not usable:
            raise OPError('The OP signs ID tokens with none of the allowed algorithms')
        meta['id_token_algs'] = usable
    if 'S256' not in (doc.get('code_challenge_methods_supported') or ['S256']):
        raise OPError('The OP does not support PKCE S256')
    for flag in ('backchannel_logout_supported', 'backchannel_logout_session_supported'):
        meta[flag] = bool(doc.get(flag))
    auth_methods = doc.get('token_endpoint_auth_methods_supported')
    if isinstance(auth_methods, list):
        meta['token_endpoint_auth_methods'] = [str(m) for m in auth_methods][:20]
    return meta


def get_metadata(provider, force=False):
    key = _key(provider, 'meta')
    if not force:
        cached = cache.get(key)
        if cached:
            return cached
    meta = fetch_metadata(provider)
    cache.set(key, meta, METADATA_TTL)
    return meta


def cached_metadata(provider):
    """Metadata only if already cached (no network), else None."""
    return cache.get(_key(provider, 'meta'))


def _fetch_jwks(provider):
    meta = get_metadata(provider)
    _status, jwks = request_json(provider, 'GET', meta['jwks_uri'])
    if not isinstance(jwks, dict) or not isinstance(jwks.get('keys'), list):
        raise OPError('JWKS document has no "keys" list')
    keys = [k for k in jwks['keys'] if isinstance(k, dict)]
    return {'keys': keys}


def get_jwks(provider, force=False):
    key = _key(provider, 'jwks')
    if not force:
        cached = cache.get(key)
        if cached:
            return cached
    jwks = _fetch_jwks(provider)
    cache.set(key, jwks, JWKS_TTL)
    return jwks


def refetch_jwks_once(provider):
    """Refetch after an unknown kid, unless one happened very recently.
    Returns the new JWKS or None when throttled."""
    if not cache.add(_key(provider, 'jwks_refetch'), time.time(), REFETCH_COOLDOWN):
        return None
    return get_jwks(provider, force=True)


def forget(provider):
    for what in ('meta', 'jwks', 'jwks_refetch'):
        cache.delete(_key(provider, what))
