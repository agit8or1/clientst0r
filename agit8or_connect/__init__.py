"""
Agit8or Connect — reference Python SDK for the app-to-app protocol
"agit8or-connect/1" (docs/agit8or-connect/PROTOCOL.md).

Framework-agnostic: no Django import anywhere in this package. Runtime
dependencies are `cryptography` and `PyJWT` only. Persistence (replay store,
tenant grants, keys) is behind small interfaces the host application
implements; in-memory versions are provided for tests and the reference peer.

Modules
-------
canonical   canonical JSON, base64url, SHA-256 helpers
keys        Ed25519 keys, JWK / JWKS, RFC 7638 thumbprints, endorsed JWKS
jws         compact JWS (EdDSA) build and strict verify (PyJWT)
tokens      client assertions (RFC 7523), access tokens (RFC 9068 profile),
            DPoP proofs (RFC 9449)
pairing     invitation codes, short authentication string, pairing messages
webhooks    signed event delivery, envelopes, backoff
replay      replay / idempotency store interface
rotation    key rotation state machine
audit       tamper-evident hash chain
scopes      scope names, risk tiers, catalogs
tenants     tenant-grant resolution interface
discovery   /.well-known/agit8or-connect document build / parse / fetch
http        transport interface and a minimal SSRF-guarded stdlib transport
reference_peer  an in-memory implementation of both roles, for tests
"""

PROTOCOL = 'agit8or-connect'
PROTOCOL_VERSION = '1'
PROTOCOL_ID = f'{PROTOCOL}/{PROTOCOL_VERSION}'
SUPPORTED_VERSIONS = ('1',)
__version__ = '1.0.0'

from .errors import ConnectError  # noqa: E402,F401
