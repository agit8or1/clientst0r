"""Redact credentials from Office log records.

``RedactSecretsFilter`` rewrites a record's message (after %-formatting) so
that none of these survive:

* ``access_token=...`` / ``token=...`` / ``access_token_ttl`` values in query
  strings and form bodies (WOPI passes the token in the URL by protocol);
* ``"token": "..."`` in JSON;
* ``Authorization: Bearer ...`` headers;
* anything shaped like a JWT (three base64url segments starting ``eyJ``).

It is attached to the ``office`` logger and every ``office.*`` child logger
at startup (``install_office_log_filter``), so the provider connectors get it
by logging under ``office.<provider>``.
"""
from __future__ import annotations

import logging
import re

REDACTED = '[redacted]'

_PATTERNS = (
    (re.compile(r'(?i)\b((?:access_)?token(?:_ttl)?)=([^&\s"\'<>]+)'), r'\1=' + REDACTED),
    (re.compile(r'(?i)("(?:access_)?token"\s*:\s*")[^"]*(")'), r'\1' + REDACTED + r'\2'),
    (re.compile(r'(?i)\b(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,"\']+'), r'\1' + REDACTED),
    (re.compile(r'(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}'), r'\1' + REDACTED),
    (re.compile(r'eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*'), REDACTED),
)


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactSecretsFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message or record.args:
            record.msg = cleaned
            record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install_office_log_filter():
    """Attach the filter to the ``office`` logger and existing ``office.*`` loggers.

    Loggers created later under ``office.`` get it from ``get_logger``.
    """
    names = ['office'] + [n for n in logging.root.manager.loggerDict if n.startswith('office.')]
    for name in names:
        _attach(logging.getLogger(name))


def _attach(logger):
    if any(isinstance(f, RedactSecretsFilter) for f in logger.filters):
        return
    logger.addFilter(RedactSecretsFilter())


def get_logger(name: str) -> logging.Logger:
    """``logging.getLogger`` for office modules, with redaction attached.
    Provider connectors: ``log = get_logger('office.onlyoffice')``."""
    if name != 'office' and not name.startswith('office.'):
        name = 'office.' + name
    logger = logging.getLogger(name)
    _attach(logger)
    return logger
