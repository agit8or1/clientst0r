"""Tamper-evident audit hash chain (PROTOCOL.md §11).

    hash_n = SHA-256( canonical_json({"prev": hash_{n-1}, "record": record_n}) )

hash_0's prev is GENESIS (64 zeros). Changing, removing or reordering any
record changes every later hash; `verify_chain` returns the index of the
first record that does not match. Records must not contain secrets or
customer content: identifiers, operation names, scopes and results only.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from .canonical import canonical_json, sha256_hex

GENESIS = '0' * 64


def entry_hash(prev_hash: str, record: dict) -> str:
    return sha256_hex(canonical_json({'prev': prev_hash, 'record': record}))


def verify_chain(entries: Iterable[Tuple[dict, str, str]], start_prev: str = GENESIS) -> Optional[int]:
    """entries: (record, stored prev_hash, stored hash) in order. None when
    intact, else the index of the first broken entry."""
    prev = start_prev
    for i, (record, stored_prev, stored_hash) in enumerate(entries):
        if stored_prev != prev or entry_hash(prev, record) != stored_hash:
            return i
        prev = stored_hash
    return None
