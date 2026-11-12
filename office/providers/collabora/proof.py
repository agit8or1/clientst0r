"""WOPI proof-key verification.

Collabora signs WOPI requests only when ``/etc/coolwsd/proof_key`` exists
(``sudo coolconfig generate-proof-key``); discovery then carries a
``<proof-key>`` element. Each signed request has:

    X-WOPI-TimeStamp   .NET ticks (100 ns units since 0001-01-01 UTC)
    X-WOPI-Proof       base64 RSA-SHA256 (PKCS#1 v1.5) signature, current key
    X-WOPI-ProofOld    the same with the old key (Collabora 26.04 currently
                       sends a copy of X-WOPI-Proof)

over the bytes

    [4-byte big-endian len][access_token, UTF-8]
    [4-byte big-endian len][the full request URL, upper-cased, UTF-8]
    [4-byte big-endian len = 8][ticks, 8-byte big-endian]

(Collabora wsd/ProofKey.cpp; Microsoft "Verifying that requests originate
from Office for the web by using proof keys"). A request is accepted when
X-WOPI-Proof verifies with the current or old key, or X-WOPI-ProofOld
verifies with the current key, and the timestamp is no more than 20 minutes
old. Using the ``cryptography`` package for this is our implementation
choice; no vendor helper exists for Python.
"""
from __future__ import annotations

import base64
import struct
from datetime import datetime, timedelta, timezone as dt_timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

MAX_AGE = timedelta(minutes=20)
MAX_SKEW = timedelta(minutes=5)
_EPOCH_TICKS = 621355968000000000   # ticks at 1970-01-01T00:00:00Z


class ProofError(Exception):
    pass


def ticks_from_datetime(when) -> int:
    when = when.astimezone(dt_timezone.utc)
    delta = when - datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
    return _EPOCH_TICKS + (delta.days * 86400 + delta.seconds) * 10**7 + delta.microseconds * 10


def datetime_from_ticks(ticks: int):
    micro = (int(ticks) - _EPOCH_TICKS) // 10
    return datetime(1970, 1, 1, tzinfo=dt_timezone.utc) + timedelta(microseconds=micro)


def expected_bytes(access_token: str, url: str, ticks: int) -> bytes:
    token = (access_token or '').encode('utf-8')
    upper = (url or '').upper().encode('utf-8')
    return (struct.pack('>i', len(token)) + token
            + struct.pack('>i', len(upper)) + upper
            + struct.pack('>i', 8) + struct.pack('>q', int(ticks)))


def _b64int(value):
    raw = base64.b64decode(value)
    return int.from_bytes(raw, 'big')


def public_key(modulus_b64, exponent_b64):
    if not modulus_b64 or not exponent_b64:
        return None
    try:
        return rsa.RSAPublicNumbers(_b64int(exponent_b64), _b64int(modulus_b64)).public_key()
    except Exception:
        return None


def _verifies(key, signature_b64, data):
    if key is None or not signature_b64:
        return False
    try:
        sig = base64.b64decode(signature_b64, validate=False)
    except Exception:
        return False
    try:
        key.verify(sig, data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify(proof_key, *, access_token, urls, timestamp, proof, proof_old, now=None):
    """Raise ProofError unless the request is signed by `proof_key`
    (discovery.ProofKey). `urls` lists candidate spellings of the request URL
    (the one Collabora used is not known exactly behind a proxy)."""
    if not timestamp or not proof:
        raise ProofError('The request carries no WOPI proof.')
    try:
        ticks = int(str(timestamp).strip())
        sent = datetime_from_ticks(ticks)
    except (ValueError, OverflowError):
        raise ProofError('The WOPI proof timestamp is not a number.')
    now = now or datetime.now(dt_timezone.utc)
    if now - sent > MAX_AGE:
        raise ProofError('The WOPI proof timestamp is older than 20 minutes.')
    if sent - now > MAX_SKEW:
        raise ProofError('The WOPI proof timestamp is in the future.')
    current = public_key(proof_key.modulus, proof_key.exponent)
    old = public_key(proof_key.old_modulus, proof_key.old_exponent)
    if current is None:
        raise ProofError('The published proof key could not be read.')
    for url in dict.fromkeys(u for u in urls if u):
        data = expected_bytes(access_token, url, ticks)
        if (_verifies(current, proof, data) or _verifies(current, proof_old, data)
                or _verifies(old, proof, data)):
            return True
    raise ProofError('The WOPI proof signature does not verify.')


# -- test / fake-server helper -------------------------------------------------

def sign(private_key, access_token, url, ticks) -> str:
    sig = private_key.sign(expected_bytes(access_token, url, ticks), padding.PKCS1v15(),
                           hashes.SHA256())
    return base64.b64encode(sig).decode('ascii')


def public_numbers_b64(private_key):
    nums = private_key.public_key().public_numbers()
    n = nums.n.to_bytes((nums.n.bit_length() + 7) // 8, 'big')
    e = nums.e.to_bytes((nums.e.bit_length() + 7) // 8, 'big')
    return base64.b64encode(n).decode('ascii'), base64.b64encode(e).decode('ascii')
