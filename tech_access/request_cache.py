"""Per-request memo of the rows technician-access decisions read.

`resolver.decide` (and the RMM permission layer on top of it) is called once
per capability check, and one page makes dozens of checks for the same
technician at the same customer. Without a memo each check re-reads the
containment, the explicit denies, the customer policy, the assignments and the
customer's RMM pairings.

Semantics (113.7):

* The memo lives in the request's authorization context
  (accounts.authz_cache, bound by core.middleware.CurrentOrganizationMiddleware
  and released when the response leaves it), the same per-request memo the
  role-permission checks use. Management commands, the scheduler, queued
  jobs, the shell and threads started by a view have no such context and read
  the database on every call, exactly as before. Nothing is shared between
  requests, sessions or threads, so a change made anywhere is seen by the
  next request.
* What is memoised is the raw rows, never a decision. Every check still runs
  the full rule order in `resolver.decide` against those rows, with its own
  `now`, so expiry is evaluated per call and the allow/deny answers are the
  same as without the memo.
* Within a request, saving or deleting any technician-access row, an RMM
  connection or permission override, a user, profile or role (post_save /
  post_delete / m2m_changed), drops these rows from the memo, so a rule the request
  itself changes is re-read by the request's next check. Code that changes
  those rows with `QuerySet.update()` inside a request calls `invalidate()`
  (integrations.ticket_rmm._save does). A change committed by another
  process while this request runs is seen from the next request — the same
  as a change committed one moment after a check without the memo. No code
  path may rely on seeing another process's change part-way through a
  request.

`scope()` opens a memo outside a request (tests); production code paths
don't use it.

Clearing here drops only this request's rows and doesn't bump the
authorization generation: this module keeps nothing beyond the request, so
other workers have nothing to drop. (accounts.signals still bumps it for the
changes it already covered, and authz_cache.invalidate() clears this memo
too.)
"""
from __future__ import annotations

from contextlib import contextmanager

from django.db.models.signals import m2m_changed, post_delete, post_save

PREFIX = 'tech_access'

# App labels whose rows feed a technician-access or RMM-permission decision.
# Clearing more often than needed only costs a re-read; it is always safe.
_RULE_APPS = {'tech_access', 'rmm_permissions', 'integrations', 'psa', 'assets'}
_RULE_MODELS = {('auth', 'user'), ('accounts', 'userprofile'), ('accounts', 'roletemplate'),
                ('accounts', 'membership'), ('core', 'organization'),
                ('psa_ai', 'aibusinesspolicy'), ('core', 'systemsetting')}


def _ctx():
    from accounts import authz_cache
    return authz_cache.current_context()


def active() -> bool:
    return _ctx() is not None


def memo(key, compute):
    """`compute()`, memoised for the current request when one is open."""
    from accounts import authz_cache
    return authz_cache.memo((PREFIX,) + tuple(key), compute)


def invalidate():
    """Drop this request's technician-access rows (only those)."""
    memo = getattr(_ctx(), 'memo', None)   # no request, or a stand-in context without a memo
    if not memo:
        return
    for k in [k for k in memo if isinstance(k, tuple) and k and k[0] == PREFIX]:
        memo.pop(k, None)


@contextmanager
def scope():
    from accounts import authz_cache
    token = authz_cache._ctx.set(authz_cache.RequestContext())
    try:
        yield
    finally:
        authz_cache.unbind(token)


def _on_write(sender, **kwargs):
    meta = getattr(sender, '_meta', None)
    if meta is None or _ctx() is None:
        return
    if meta.app_label in _RULE_APPS or (meta.app_label, meta.model_name) in _RULE_MODELS:
        invalidate()


def _on_m2m(sender, **kwargs):
    # Group membership (TechnicianGroup.members) and any other relation
    # change: clear unconditionally, these are rare.
    invalidate()


post_save.connect(_on_write, dispatch_uid='tech_access_request_cache_save')
post_delete.connect(_on_write, dispatch_uid='tech_access_request_cache_delete')
m2m_changed.connect(_on_m2m, dispatch_uid='tech_access_request_cache_m2m')
