"""JWT handling for ONLYOFFICE Docs (HS256 only).

ONLYOFFICE Docs signs and checks three kinds of token with the secrets in
its ``local.json`` (``services.CoAuthoring.secret.{browser,inbox,outbox}``).
clientst0r stores one shared secret per instance; the setup guide tells the
administrator to set all three to it.

* **Editor config** (browser): the whole ``DocsAPI.DocEditor`` config is
  signed and put in its ``token`` field. ``token.browser.secretFromInbox``
  is ``true`` by default, so the inbox secret checks it.
* **Inbox** (clientst0r -> Docs: command service, conversion service): a
  ``Authorization: Bearer`` header whose claims wrap the request in
  ``payload``, and the same parameters signed again in the body ``token``
  (the command service documents the body form). Since 10.0 an editor-config
  token is no longer accepted here and the token carries an ``operation``
  field. Where exactly Docs expects ``operation`` in the claims is not
  spelled out in the changelog (unverified); it is sent at the top level of
  both tokens.
* **Outbox** (Docs -> clientst0r: save callbacks, document downloads): a
  ``Authorization: Bearer`` header, HS256, claims wrapped in ``payload``,
  expiring after 5 minutes, carrying ``operation`` = ``callback`` /
  ``download`` since 10.0. With ``token.outbox.inBody`` on, callbacks also
  carry ``{"token": ...}`` in the body; that form is only accepted for an
  instance configured for it (``OFFICE_ONLYOFFICE_INSTANCE_OPTIONS``).

Nothing here logs a token. ``decode`` refuses every algorithm except HS256
(including ``none``), a missing or past ``exp``, a bad signature, and an
``operation`` other than the expected one.
"""
from __future__ import annotations

import jwt

ALGORITHM = 'HS256'
DEFAULT_HEADER = 'Authorization'
# Leeway for clock skew between clientst0r and the editor host.
LEEWAY_SECONDS = 30
# Inbox tokens clientst0r issues are short-lived.
INBOX_TTL_SECONDS = 300


class InvalidToken(Exception):
    """``reason``: missing / malformed / algorithm / signature / expired /
    operation / payload."""

    def __init__(self, reason, message=''):
        super().__init__(message or reason)
        self.reason = reason


def encode(claims: dict, secret: str) -> str:
    if not secret:
        raise InvalidToken('secret', 'No shared secret is configured.')
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def _now():
    import time
    return int(time.time())


def sign_config(config: dict, secret: str) -> str:
    """Token for the editor config. Signs the config exactly as sent (the
    vendor requires 'the same structure as the config')."""
    return encode(dict(config), secret)


def inbox_request(params: dict, secret: str, operation: str):
    """(headers, body) for a signed request to the command or conversion
    service. ``params`` is the documented request body without ``token``."""
    now = _now()
    claims = dict(params)
    claims.update({'operation': operation, 'iat': now, 'exp': now + INBOX_TTL_SECONDS})
    header_claims = {'payload': dict(params), 'operation': operation, 'iat': now,
                     'exp': now + INBOX_TTL_SECONDS}
    body = dict(params)
    body['token'] = encode(claims, secret)
    headers = {DEFAULT_HEADER: 'Bearer ' + encode(header_claims, secret),
               'Content-Type': 'application/json', 'Accept': 'application/json'}
    return headers, body


def decode(token: str, secret: str, *, operation: str | None = None) -> dict:
    """Verified claims of `token`. Raises InvalidToken."""
    if not token or not isinstance(token, str) or len(token) > 64 * 1024:
        raise InvalidToken('missing')
    if not secret:
        raise InvalidToken('signature', 'No shared secret is configured.')
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise InvalidToken('malformed')
    if header.get('alg') != ALGORITHM:
        raise InvalidToken('algorithm', 'Only HS256 tokens are accepted.')
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM], leeway=LEEWAY_SECONDS,
                            options={'require': ['exp'], 'verify_aud': False})
    except jwt.ExpiredSignatureError:
        raise InvalidToken('expired')
    except jwt.InvalidSignatureError:
        raise InvalidToken('signature')
    except jwt.MissingRequiredClaimError:
        raise InvalidToken('expired', 'The token has no expiry.')
    except jwt.PyJWTError:
        raise InvalidToken('malformed')
    if not isinstance(claims, dict):
        raise InvalidToken('payload')
    if operation is not None:
        found = [c.get('operation') for c in (claims, claims.get('payload'))
                 if isinstance(c, dict) and 'operation' in c]
        if any(op != operation for op in found):
            raise InvalidToken('operation', 'The token was issued for another operation.')
    return claims


def bearer(value: str) -> str:
    """The token in an ``Authorization: Bearer <jwt>`` header value, or ''."""
    value = (value or '').strip()
    if value[:7].lower() == 'bearer ':
        return value[7:].strip()
    return ''


def header_name(instance) -> str:
    return instance_option(instance, 'header', DEFAULT_HEADER) or DEFAULT_HEADER


def instance_option(instance, name, default=None):
    """Per-instance connector option from settings.OFFICE_ONLYOFFICE_INSTANCE_OPTIONS,
    keyed by instance name or primary key:

        OFFICE_ONLYOFFICE_INSTANCE_OPTIONS = {
            'Docs LAN': {'body_token': True, 'header': 'Authorization'},
        }

    ``body_token``: also accept the callback token in the request body
    (needs ``token.outbox.inBody: true`` on the editor). ``header``: the
    editor's ``token.outbox.header`` if it was changed from Authorization.
    """
    from django.conf import settings
    options = getattr(settings, 'OFFICE_ONLYOFFICE_INSTANCE_OPTIONS', {}) or {}
    entry = options.get(getattr(instance, 'name', None)) or options.get(getattr(instance, 'pk', None)) \
        or options.get(str(getattr(instance, 'pk', ''))) or {}
    return entry.get(name, default)
