"""Canonical JSON, base64url and digests.

Canonical JSON (PROTOCOL.md §3.1) is the same encoding Rem0te's contract
ticket-rmm-v1 already uses: object keys sorted by UTF-16 code units, no
insignificant whitespace, strings escaped exactly as ECMAScript's
JSON.stringify escapes them, numbers formatted as ECMAScript formats them;
non-finite numbers and integers beyond 2**53-1 are refused. It is what a
JavaScript implementation gets from a key-sorting JSON.stringify, so the
TypeScript SDK produces identical bytes.

Every JWS this SDK *produces* uses canonical JSON for its header and payload
segments so that test vectors are byte-exact across languages. Verifiers
accept any valid JSON in a JWS (they verify bytes, not re-encodings).
"""
from __future__ import annotations

import base64
import hashlib
import math
import re
from decimal import Decimal
from typing import Any

from .errors import ConnectError, INVALID_REQUEST

MAX_SAFE_INTEGER = 2 ** 53 - 1
_B64URL_RE = re.compile(r'^[A-Za-z0-9_-]*$')
_ESCAPES = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _js_string(s: str) -> str:
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
    if isinstance(n, bool):
        raise ConnectError(INVALID_REQUEST, 'canonical_json: bool is not a number')
    if isinstance(n, int):
        if abs(n) > MAX_SAFE_INTEGER:
            raise ConnectError(INVALID_REQUEST, 'canonical_json: number out of range')
        return str(n)
    if not math.isfinite(n):
        raise ConnectError(INVALID_REQUEST, 'canonical_json: number out of range')
    if n == int(n):
        if abs(n) > MAX_SAFE_INTEGER:
            raise ConnectError(INVALID_REQUEST, 'canonical_json: number out of range')
        return str(int(n))
    sign = '-' if n < 0 else ''
    d = Decimal(repr(abs(n)))
    t = d.as_tuple()
    digits = ''.join(map(str, t.digits)).rstrip('0') or '0'
    k = len(digits)
    point = len(t.digits) + t.exponent
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
                raise ConnectError(INVALID_REQUEST, 'canonical_json: object keys must be strings')
        keys = sorted(value, key=lambda k: k.encode('utf-16-be'))
        return '{' + ','.join(f'{_js_string(k)}:{canonical_json(value[k])}' for k in keys) + '}'
    raise ConnectError(INVALID_REQUEST, f'canonical_json: unsupported type {type(value).__name__}')


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode('utf-8')


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data or b'').hexdigest()


def sha256_b64url(data) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return b64url(hashlib.sha256(data or b'').digest())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def from_b64url(s: str) -> bytes:
    if not isinstance(s, str) or not _B64URL_RE.match(s) or len(s) % 4 == 1:
        raise ConnectError(INVALID_REQUEST, 'not base64url')
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
