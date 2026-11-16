"""The RP's own key pair for private_key_jwt client authentication.

An RSA-2048 key is generated here; the private key is stored encrypted
(EncryptedTextField) and only the public JWK is ever shown or served. The
key id is the RFC 7638 thumbprint of the public key.
"""
import base64
import hashlib
import json
import secrets
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone

ASSERTION_ALG = 'RS256'
ASSERTION_LIFETIME = 60


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _thumbprint(e: str, n: str) -> str:
    canonical = json.dumps({'e': e, 'kty': 'RSA', 'n': n}, separators=(',', ':'), sort_keys=True)
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b'=').decode()


def generate_keypair(provider):
    """Create (or replace) the provider's key pair. Caller saves."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode('ascii')
    numbers = key.public_key().public_numbers()
    provider.private_key_pem = pem
    provider.key_id = _thumbprint(_b64(numbers.e), _b64(numbers.n))
    provider.key_created_at = timezone.now()
    return provider


def _private_key(provider):
    pem = provider.private_key_pem or ''
    if not pem.startswith('-----BEGIN'):
        return None
    return serialization.load_pem_private_key(pem.encode('ascii'), password=None)


def public_jwk(provider):
    """The public JWK (dict) to register at the OP, or None."""
    key = _private_key(provider)
    if key is None:
        return None
    numbers = key.public_key().public_numbers()
    return {'kty': 'RSA', 'use': 'sig', 'alg': ASSERTION_ALG, 'kid': provider.key_id,
            'e': _b64(numbers.e), 'n': _b64(numbers.n)}


def public_jwks(provider):
    jwk = public_jwk(provider)
    return {'keys': [jwk] if jwk else []}


def client_assertion(provider, audience):
    """A signed client assertion (RFC 7523) for the token endpoint."""
    key = _private_key(provider)
    if key is None:
        raise ValueError('No key pair: generate one on the provider settings page.')
    now = int(time.time())
    claims = {'iss': provider.client_id, 'sub': provider.client_id, 'aud': audience,
              'jti': secrets.token_urlsafe(24), 'iat': now, 'nbf': now - 5, 'exp': now + ASSERTION_LIFETIME}
    return jwt.encode(claims, key, algorithm=ASSERTION_ALG, headers={'kid': provider.key_id})
