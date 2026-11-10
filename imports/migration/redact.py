"""Secret handling for the migration rehearsal.

* Source secrets (passwords, OTP seeds, confidential fields) are moved out of
  the raw payload at staging time into ``StagedRecord.secret_data`` (encrypted
  at rest). ``raw`` never holds them.
* Change detection uses keyed fingerprints (HMAC-SHA256 under a key derived
  from SECRET_KEY), never plain hashes, so a fingerprint cannot be brute-forced
  offline without the key.
* Everything the operator sees or downloads goes through ``redact_text`` /
  ``scrub`` as a second line of defence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from django.conf import settings

REDACTED = '[redacted]'
SECRET_PLACEHOLDER = '[secret]'

# Keys whose values are secrets wherever they appear in a source payload.
SECRET_KEY_RE = re.compile(
    r'(^|[-_])(password|passwd|secret|token|api[-_]?key|otp|totp|private[-_]?key|'
    r'client[-_]?secret|passphrase|pin)($|[-_])',
    re.IGNORECASE)
# Keys that look secret but only carry metadata.
SAFE_KEYS = {
    'password-category-id', 'password-category-name', 'password_category_id',
    'password_category_name', 'passwordable_type', 'passwordable_id', 'password-updated-at',
    'password_updated_at', 'password_folder_id', 'password_folder_name', 'password-folder-id',
    'otp_enabled', 'otp-enabled', 'password_type', 'password-type',
}
# Hudu asset field types holding secrets.
CONFIDENTIAL_FIELD_TYPES = {'password', 'confidentialtext', 'confidential_text', 'confidential'}


def is_secret_key(key) -> bool:
    key = str(key)
    return key.lower() not in SAFE_KEYS and bool(SECRET_KEY_RE.search(key))


def fingerprint(value) -> str:
    """Keyed fingerprint of a secret, safe to store and compare."""
    key = hashlib.sha256(('imports.migration.fp:' + settings.SECRET_KEY).encode()).digest()
    data = value if isinstance(value, bytes) else str(value or '').encode()
    return 'fp:' + hmac.new(key, data, hashlib.sha256).hexdigest()


def scrub(obj):
    """Deep copy of ``obj`` with secret-looking keys' values replaced."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if is_secret_key(k) and v not in (None, '', [], {}):
                out[k] = REDACTED
            else:
                out[k] = scrub(v)
        return out
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def redact_text(text, secrets=()) -> str:
    """Remove known secret values and ``key=value`` style secrets from text."""
    text = str(text or '')
    for s in secrets:
        s = str(s or '')
        if len(s) >= 4:
            text = text.replace(s, REDACTED)
    return re.sub(
        r'((?:password|passwd|secret|token|api[-_ ]?key|otp)\s*[=:]\s*)([^\s,;\'"]+)',
        r'\1' + REDACTED, text, flags=re.IGNORECASE)


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
