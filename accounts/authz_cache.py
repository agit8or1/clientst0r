"""
Authorization memo and its invalidation.

Permission checks may be asked dozens of times while one page renders, so
their results are memoized - for the current request only. Nothing is kept
between requests, so a change made by one request is seen by the next one
without any cache to expire. Within a request the memo is dropped the
moment a role template, membership (or its additional roles), profile
(user type, global role, client scope), account (is_active / superuser),
organization (parent / active) or technician access assignment changes
(accounts.signals), so a request that demotes someone and then checks
their access sees the demotion.

`generation()` is a process-wide counter bumped on every such change, for
code that keeps longer-lived derived state (for example a per-session or
per-token snapshot) and needs to know when to re-derive it.
`shared_generation()` is its cross-process twin: a database row
(accounts.AuthzGeneration) bumped by the same changes, so state one worker
keeps between requests is dropped by a change made in another worker. Background jobs
run outside any request and are never memoized: every check reads the
current rows.

The request context (selected organization, acting user) is set by
core.middleware.CurrentOrganizationMiddleware via `bind_request` and is
also what accounts.signals reads to name the actor in the audit trail.
"""
from __future__ import annotations

import contextvars
import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_ctx: contextvars.ContextVar = contextvars.ContextVar('clientst0r_authz_ctx', default=None)
_generation = itertools.count(1)
_current_generation = [0]

_UNSET = object()


@dataclass
class RequestContext:
    organization_id: Optional[int] = None
    user_id: Optional[int] = None
    request: Any = None
    memo: Dict[Any, Any] = field(default_factory=dict)


def bind_request(request):
    """Start a request context; returns a token for `unbind`."""
    org = getattr(request, 'current_organization', None)
    user = getattr(request, 'user', None)
    ctx = RequestContext(organization_id=getattr(org, 'pk', None),
                         user_id=getattr(user, 'pk', None) if getattr(user, 'is_authenticated', False) else None,
                         request=request)
    return _ctx.set(ctx)


def unbind(token):
    try:
        _ctx.reset(token)
    except (ValueError, LookupError):  # pragma: no cover - token from another context
        _ctx.set(None)


def current_context() -> Optional[RequestContext]:
    return _ctx.get()


def current_request():
    ctx = _ctx.get()
    return ctx.request if ctx is not None else None


def memo(key, compute):
    ctx = _ctx.get()
    if ctx is None:
        return compute()
    value = ctx.memo.get(key, _UNSET)
    if value is _UNSET:
        value = compute()
        ctx.memo[key] = value
    return value


def forget(key):
    """Drop one memoized value of the current request (after a queryset
    update that sends no signal)."""
    ctx = _ctx.get()
    if ctx is not None:
        ctx.memo.pop(key, None)


def invalidate(reason: str = ''):
    """Drop every memoized decision and bump the generation."""
    ctx = _ctx.get()
    if ctx is not None:
        ctx.memo.clear()
    _current_generation[0] = next(_generation)
    try:
        from django.core.cache import cache
        cache.set('authz:generation', _current_generation[0], None)
    except Exception:  # pragma: no cover - cache backend down never blocks a change
        pass
    _bump_shared()


def _bump_shared():
    """Advance the database row every worker reads (shared_generation). It
    runs inside the caller's transaction, so a change that rolls back takes
    its bump with it; a missing table (before migrate) is skipped."""
    try:
        from django.db import transaction
        from django.db.models import F

        from .models import AuthzGeneration
        with transaction.atomic():
            if not AuthzGeneration.objects.filter(pk=1).update(value=F('value') + 1):
                AuthzGeneration.objects.create(pk=1, value=1)
    except Exception:  # pragma: no cover - never block the change itself
        pass


_SHARED_SQL = 'SELECT value FROM accounts_authz_generation WHERE id = 1'


def shared_generation(request=None):
    """The cross-process generation (accounts.AuthzGeneration), or None when
    it cannot be read. With `request`, read once per request; a change made
    later in the same request still shows through generation(), which this
    process bumps at once."""
    if request is not None:
        value = getattr(request, '_authz_shared_generation', _UNSET)
        if value is not _UNSET:
            return value
    try:
        from django.db import connection, transaction

        def read():
            with connection.cursor() as cursor:
                cursor.execute(_SHARED_SQL)
                return cursor.fetchone()
        if connection.in_atomic_block:
            # A failed read must not poison the caller's transaction.
            with transaction.atomic():
                row = read()
        else:
            row = read()
        value = int(row[0]) if row else 0
    except Exception:
        value = None
    if request is not None:
        try:
            request._authz_shared_generation = value
        except Exception:  # pragma: no cover - read-only request object
            pass
    return value


def local_generation() -> int:
    """This process's counter, bumped by invalidate() here (no cache read)."""
    return _current_generation[0]


def generation() -> int:
    try:
        from django.core.cache import cache
        value = cache.get('authz:generation')
        if value is not None:
            return int(value)
    except Exception:  # pragma: no cover
        pass
    return _current_generation[0]
