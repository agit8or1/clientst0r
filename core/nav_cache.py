"""Gate decisions for the navigation, kept between requests.

core.navigation draws every page's sidebar, top bar, account menu and
settings workspace by asking a few hundred questions: does this gate admit
this user, would the server open this URL for them. The answers depend on
who is asking (the account, its MSP-staff profile, the selected client, the
feature switches in the context) and on the access rows behind them (roles,
memberships, access groups, technician assignments, RMM overrides), not on
the page being drawn. They used to be recomputed on every request, which
cost most of the time a page took to render.

This module keeps them, per worker process, in a small LRU keyed on
everything the answers read:

* the context fingerprint (`fingerprint`): user id and join time, the
  account flags, the MSP-staff profile type and global role, the selected
  client (request, session and context), and every feature switch the gates
  read;
* accounts.authz_cache.local_generation(): bumped in this process by every
  access change (accounts.signals), so a change is seen by the very next
  render here;
* accounts.authz_cache.shared_generation(): the same bump written to a
  database row, read once per request, so a change made in another worker
  is seen by the next request here.

Entries also expire after TTL seconds, which bounds the one thing no save
announces: a time-limited grant or override passing its expiry.

Only decisions are kept (booleans). Links, labels and the current page's
active state are still worked out on every request, so the HTML is exactly
what the uncached code draws. Hiding a link is presentation; every page
keeps its own permission check.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from django.conf import settings

# Seconds an entry lives at most (time-limited grants expire without a save).
TTL = 30
# Fingerprints kept per process (one per user × selected client, roughly).
MAX_ENTRIES = 1000

_store: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
_lock = threading.Lock()

# Context keys the gates read (core.navigation: _flag gates, the shortcut
# strip's flags, request_context()).
_FLAG_KEYS = ('monitoring_enabled', 'global_kb_enabled', 'workflows_enabled', 'vehicles_enabled',
              'inventory_enabled', 'scheduling_enabled', 'psa_enabled', 'crm_enabled',
              'reports_enabled', 'secure_notes_enabled', 'pulse_enabled')


def enabled():
    return getattr(settings, 'NAV_DECISION_CACHE', True)


def clear():
    with _lock:
        _store.clear()


def _pk(obj):
    return getattr(obj, 'pk', None)


def fingerprint(ctx):
    """Everything a gate decision reads from the context, or None when the
    context has no signed-in user or no request (those are not cached)."""
    request = ctx.get('request')
    user = ctx.get('user')
    if request is None or user is None or not getattr(user, 'is_authenticated', False):
        return None
    profile = getattr(getattr(user, '_state', None), 'fields_cache', {}).get('profile')
    session = getattr(request, 'session', None)
    try:
        session_org = session.get('current_organization_id') if session is not None else None
    except Exception:
        session_org = None
    system_settings = ctx.get('system_settings')
    return (
        user.pk, str(getattr(user, 'date_joined', '')),
        bool(user.is_superuser), bool(user.is_staff), bool(user.is_active),
        getattr(profile, 'user_type', None), getattr(profile, 'global_role_template_id', None),
        bool(ctx.get('is_staff_user')),
        _pk(getattr(request, 'current_organization', None)), _pk(ctx.get('current_organization')),
        session_org,
        tuple(bool(ctx.get(k)) for k in _FLAG_KEYS),
        bool(getattr(system_settings, 'psa_ai_enabled', False)),
        bool(getattr(settings, 'AGIT8OR_CONNECT_ENABLED', False)),
    )


def decisions(ctx):
    """The decision dict for this context (shared by every render with the
    same fingerprint and generations), or None when nothing may be kept.

    The lookup is done once per context object: the result is pinned on the
    request next to the context it was made for."""
    if not enabled():
        return None
    request = ctx.get('request')
    if request is None:
        return None
    pinned = getattr(request, '_nav_decisions', None)
    if pinned is not None:
        for held_ctx, memo in pinned:
            if held_ctx is ctx:
                return memo
    else:
        pinned = []
        try:
            request._nav_decisions = pinned
        except Exception:  # pragma: no cover - read-only request object
            return None
    fp = fingerprint(ctx)
    if fp is None:
        memo = None
    else:
        from accounts import authz_cache
        shared = authz_cache.shared_generation(request)
        if shared is None:
            memo = None  # cannot tell whether another worker changed access
        else:
            memo = _entry(fp + (authz_cache.local_generation(), shared))
    pinned.append((ctx, memo))
    return memo


def _entry(key):
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            _store.move_to_end(key)
            return hit[1]
        memo = {}
        _store[key] = (now + TTL, memo)
        _store.move_to_end(key)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)
        return memo


def _on_setting_changed(**_kw):
    # override_settings in tests, or anything else that swaps settings at
    # run time: gates read django settings too.
    clear()


try:
    from django.core.signals import setting_changed
    setting_changed.connect(_on_setting_changed, dispatch_uid='core_nav_cache_settings')
except Exception:  # pragma: no cover
    pass
