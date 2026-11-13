"""Redaction for everything the harness writes (results, report, logs).

Two layers:

* by key: any mapping key that names a secret (token, secret, password,
  cookie, jwt, authorization, session key ...) has its value replaced;
* by value: JWTs, ``token=`` / ``access_token=`` / ``md5=`` / ``signature=``
  query values, bearer headers, and every literal secret the run registered
  (``Redactor.add``: the test users' passwords, the browser session keys,
  the editor's JWT secret if it was ever read) are replaced in every string.

Redaction is applied when the run state, the results and the report are
written, so nothing unredacted reaches disk through the harness.
"""
from __future__ import annotations

import re

MASK = '[redacted]'

SECRET_KEY_RE = re.compile(
    r'(secret|token|passw|cookie|jwt|authori[sz]ation|session_?key|sessionid|csrf|'
    r'api_?key|private|credential|signature)', re.I)
# Keys that look secret-ish but hold ids we want to keep (session UUIDs,
# token counts). Exact names only.
SAFE_KEYS = {'session_id', 'sessions', 'session_ids', 'token_count', 'secrets_present',
             'edit_session', 'real_sessions', 'test_sessions', 'session_state',
             'frame_cookie_names', 'cookie_jar', 'jar', 'frame_detail', 'csrf_cookie_name'}

VALUE_PATTERNS = [
    # JWT: header.payload.signature (base64url, header starts with eyJ).
    (re.compile(r'eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*'), MASK),
    # Query-string credentials.
    (re.compile(r'(?i)\b(access_token|token|md5|signature|sig|jwt|key|secret|password|'
                r'access_token_ttl|expires)=([^&\s"\'<>]+)'), r'\1=' + MASK),
    # Authorization headers.
    (re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}'), r'\1 ' + MASK),
    # sessionid=... in cookie strings.
    (re.compile(r'(?i)\b(sessionid|csrftoken|clientstor_sessionid)=([^;\s]+)'), r'\1=' + MASK),
]


class Redactor:
    def __init__(self, literals=()):
        self._literals = set()
        for value in literals:
            self.add(value)

    def add(self, value):
        """Register a literal secret (ignored when too short to be one)."""
        if isinstance(value, str) and len(value) >= 6:
            self._literals.add(value)

    def text(self, s: str) -> str:
        if not isinstance(s, str):
            return s
        for lit in sorted(self._literals, key=len, reverse=True):
            if lit in s:
                s = s.replace(lit, MASK)
        for pattern, repl in VALUE_PATTERNS:
            s = pattern.sub(repl, s)
        return s

    def obj(self, value, key=None):
        """Deep copy of `value` with secrets removed."""
        if key is not None and isinstance(key, str) and key not in SAFE_KEYS \
                and SECRET_KEY_RE.search(key):
            if value in (None, '', [], {}, False, True, 0):
                return value
            return MASK
        if isinstance(value, dict):
            return {k: self.obj(v, k) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.obj(v) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value


DEFAULT = Redactor()


def redact(value):
    return DEFAULT.obj(value)
