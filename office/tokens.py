"""Access tokens for edit sessions.

    raw = issue(session, ops=None, ttl_minutes=None, purpose='browser')
    token = validate(raw, op='write', session_id=None, target=None)  # AccessToken
    expires_at = renew(raw)
    revoke(raw); revoke_session_tokens(session)

A token is 43 random url-safe characters (256 bits). Only
``hash_token(raw, 'office.access')`` (HMAC-SHA256 keyed with API_KEY_SECRET)
is stored, so a database dump yields no usable token.

Scope: one session, therefore one organization, one user, one file and one
mode, plus an explicit list of operations:

    read    fetch the file / its metadata (CheckFileInfo, GetFile, download)
    write   store a new revision (PutFile, ONLYOFFICE save callback)
    lock    WOPI Lock / RefreshLock / Unlock / GetLock
    rename  WOPI RenameFile
    export  PDF / format conversion of the current revision

A view-mode session can only hold ``read`` (and ``export``).

``validate`` re-checks, on every call: the token (unknown / revoked /
expired), the operation, the session (live, not expired, the expected
session and file), the user (still active) and the user's permission on the
file right now (``can_view`` for read/export, ``can_edit`` for write, lock
and rename). A failed permission check revokes the whole session.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

PURPOSE = 'office.access'
WRITE_OPS = frozenset({'write', 'lock', 'rename'})
READ_OPS = frozenset({'read', 'export'})
DEFAULT_OPS = {'view': ('read',), 'edit': ('read', 'write', 'lock')}


class TokenError(Exception):
    """``reason``: unknown / revoked / expired / scope / session / permission."""

    def __init__(self, reason, message=''):
        super().__init__(message or reason)
        self.reason = reason


def _hash(raw):
    from vault.secret_fields import hash_token
    return hash_token(raw or '', PURPOSE)


def _ttl(ttl_minutes):
    if ttl_minutes:
        return int(ttl_minutes)
    from .models import OfficeSettings
    return OfficeSettings.get().token_ttl_minutes or 60


def issue(session, ops=None, *, ttl_minutes=None, purpose='browser') -> str:
    from .models import AccessToken, EditSession
    ops = list(ops or DEFAULT_OPS[session.mode])
    unknown = set(ops) - set(AccessToken.OPS)
    if unknown:
        raise ValueError(f'unknown token operations: {sorted(unknown)}')
    if session.mode != 'edit' and set(ops) & WRITE_OPS:
        raise ValueError('a view session cannot carry write operations')
    if session.state not in EditSession.LIVE_STATES:
        raise TokenError('session', 'The session is not open.')
    raw = secrets.token_urlsafe(32)
    now = timezone.now()
    AccessToken.objects.create(
        session=session, token_hash=_hash(raw), ops=sorted(set(ops)), purpose=purpose[:30],
        expires_at=min(now + timedelta(minutes=_ttl(ttl_minutes)), session.max_expires_at))
    return raw


def _lookup(raw):
    from .models import AccessToken
    if not raw or not isinstance(raw, str) or len(raw) > 200:
        raise TokenError('unknown')
    token = (AccessToken.objects.select_related('session', 'session__user', 'session__instance')
             .filter(token_hash=_hash(raw)).first())
    if token is None:
        raise TokenError('unknown')
    return token


def validate(raw, *, op, session_id=None, target=None):
    """The AccessToken for `raw` if it may perform `op` right now. Raises TokenError."""
    from .models import EditSession
    from .sessions import revoke, still_allowed
    from .targets import target_of
    token = _lookup(raw)
    now = timezone.now()
    if token.revoked_at is not None:
        raise TokenError('revoked')
    if token.expires_at <= now:
        raise TokenError('expired')
    if op not in token.ops:
        raise TokenError('scope', f'The token does not allow {op}.')
    session = token.session
    if session_id is not None and str(session.pk) != str(session_id):
        raise TokenError('scope', 'The token belongs to another session.')
    if session.state not in EditSession.LIVE_STATES:
        raise TokenError('session', f'The session is {session.state}.')
    if session.expires_at <= now:
        raise TokenError('expired', 'The session has expired.')
    session_target = target_of(session)
    if session_target is None:
        revoke(session, 'file deleted')
        raise TokenError('session', 'The file no longer exists.')
    if target is not None and session_target != target:
        raise TokenError('scope', 'The token belongs to another file.')
    user = session.user
    if not user.is_active:
        revoke(session, 'user deactivated')
        raise TokenError('permission')
    allowed = still_allowed(session) if op in WRITE_OPS else session_target.can_view(user)
    if not allowed:
        revoke(session, 'permission lost')
        raise TokenError('permission')
    if token.last_used_at is None or (now - token.last_used_at).total_seconds() > 60:
        type(token).objects.filter(pk=token.pk).update(last_used_at=now)
    token.target = session_target
    return token


def renew(raw, *, ttl_minutes=None):
    """Extend a still-valid token (and its session) for long editing sessions.
    Returns the new expiry. Never beyond the session's maximum length."""
    from .models import AccessToken
    from .sessions import renew as renew_session
    token = _lookup(raw)
    now = timezone.now()
    if token.revoked_at is not None:
        raise TokenError('revoked')
    if token.expires_at <= now:
        raise TokenError('expired')
    session = renew_session(token.session)
    expires = min(now + timedelta(minutes=_ttl(ttl_minutes)), session.max_expires_at)
    with transaction.atomic():
        AccessToken.objects.filter(pk=token.pk, revoked_at__isnull=True).update(expires_at=expires)
    return expires


def revoke(raw):
    from .models import AccessToken
    return AccessToken.objects.filter(token_hash=_hash(raw), revoked_at__isnull=True).update(
        revoked_at=timezone.now())


def revoke_session_tokens(session):
    from .models import AccessToken
    return AccessToken.objects.filter(session_id=session.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now())
