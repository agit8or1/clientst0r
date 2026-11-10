"""
Stable identifiers for the system prompts in psa_ai/prompts/.

A prompt version is `<file name>@<first 12 hex of the file's SHA-256>`, for
example `system_reply.md@3f9c0a1b2d4e`. It changes whenever the file's bytes
change and never otherwise, so two drafts with the same version were made
with the same instructions, whatever the release number says. The prompt
text itself is never stored with a draft or a run; only this identifier is.

Rows written before v3.17.660 carry the old hand-maintained value ("1"); the
ticket history shows those as "legacy (no content hash)".
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'
HASH_CHARS = 12


@lru_cache(maxsize=32)
def _version(name: str, mtime_ns: int, size: int) -> str:
    digest = hashlib.sha256((PROMPTS_DIR / name).read_bytes()).hexdigest()
    return f'{name}@{digest[:HASH_CHARS]}'


def prompt_version(name: str) -> str:
    """The version of psa_ai/prompts/<name>, or `<name>@missing` if the file
    is absent (the caller is about to fail reading it anyway)."""
    path = PROMPTS_DIR / name
    try:
        st = path.stat()
    except OSError:
        return f'{name}@missing'
    return _version(name, st.st_mtime_ns, st.st_size)


def is_hashed(value: str) -> bool:
    """True for a value this module produced (as opposed to a legacy "1")."""
    name, _, digest = (value or '').partition('@')
    return bool(name) and len(digest) == HASH_CHARS and all(c in '0123456789abcdef' for c in digest)
