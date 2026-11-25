"""Is an RMM connected? One cheap, cached answer for presentation code.

Standalone installations (no RMM at all) must not show RMM-only navigation,
dashboard widgets, workspace tabs or empty RMM lines (CLAUDE.md "Standalone
operation", docs/ux/STANDALONE_REQUIREMENTS.md P0-3). Every such place asks
here instead of running its own query.

* ``rmm_configured()`` — any enabled RMM connection (any provider; Rem0te
  counts through its provider row like every other RMM).
* ``rmm_configured(org)`` — for one customer: an enabled connection the
  customer owns, or devices of this customer (or its sites) synced by an
  enabled connection. A platform connection that brought in nothing for the
  customer does not count, so the customer's workspace shows no empty RMM tab.

Answers are kept per worker process, keyed on the access generations
(``accounts.authz_cache.local_generation`` / ``shared_generation``): saving a
connection with a changed enabled flag or owner, creating or deleting one
bumps both (``integrations.signals``), so the next request in any worker sees
the change; the navigation's own decision cache (core.nav_cache) is dropped
by the same bump. Entries also expire after TTL seconds, which covers what no
save announces (the first devices of a customer arriving with a sync).

Hiding is presentation only: every RMM page keeps its own checks and its own
empty state.
"""
from __future__ import annotations

import threading
import time

TTL = 30
MAX_ENTRIES = 2000

_store: dict = {}
_lock = threading.Lock()


def clear():
    with _lock:
        _store.clear()


def _compute(org_id):
    from integrations.models import RMMConnection, RMMDevice
    active = RMMConnection.objects.filter(is_active=True)
    if org_id is None:
        return active.exists()
    if active.filter(organization_id=org_id).exists():
        return True
    from core.models import Organization
    org = Organization.objects.filter(pk=org_id).first()
    if org is None:
        return False
    return RMMDevice.objects.for_organization(org).filter(connection__is_active=True).exists()


def _generation_key(request):
    from accounts import authz_cache
    if request is None:
        request = authz_cache.current_request()
    shared = authz_cache.shared_generation(request)
    if shared is None:
        return None
    return (authz_cache.local_generation(), shared)


def rmm_configured(organization=None, request=None) -> bool:
    """True when an enabled RMM connection exists (for `organization`: one
    that serves this customer, see the module docstring)."""
    org_id = getattr(organization, 'pk', organization)
    # Once per request and customer.
    memo = getattr(request, '_rmm_presence', None) if request is not None else None
    if memo is not None and org_id in memo:
        return memo[org_id]
    try:
        gen = _generation_key(request)
    except Exception:
        gen = None
    value = None
    now = time.monotonic()
    if gen is not None:
        key = gen + (org_id,)
        with _lock:
            hit = _store.get(key)
        if hit is not None and hit[0] > now:
            value = hit[1]
    if value is None:
        try:
            value = bool(_compute(org_id))
        except Exception:
            return False  # not kept: a missing table before migrate, a broken connection
        if gen is not None:
            with _lock:
                if len(_store) >= MAX_ENTRIES:
                    _store.clear()
                _store[gen + (org_id,)] = (now + TTL, value)
    if request is not None:
        if memo is None:
            memo = {}
            try:
                request._rmm_presence = memo
            except Exception:  # pragma: no cover - read-only request object
                return value
        memo[org_id] = value
    return value
