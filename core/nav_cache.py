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
    clear_html()


try:
    from django.core.signals import setting_changed
    setting_changed.connect(_on_setting_changed, dispatch_uid='core_nav_cache_settings')
except Exception:  # pragma: no cover
    pass


# --- Rendered sidebar sections ---------------------------------------------
#
# Drawing the sidebar's sections (core/_primary_nav_group.html) cost about
# half of a typical page's render. A section's HTML depends only on the
# section data core.navigation.primary_nav built for this request (labels,
# links, icons, active flags, children), on whether the current path is one
# of its links (aria-current), on the active language and, for the
# Overview section, on its "Edit pinned pages" link and the current URL.
# `group_html` keys the rendered HTML on exactly those values, so a hit is
# the HTML the template would draw for this request, never another user's
# or another page's. Decisions about who may see what are not made here:
# they are already in the section data.

HTML_MAX_ENTRIES = 512
_html_store: "OrderedDict[tuple, str]" = OrderedDict()
_html_lock = threading.Lock()


# The fields core/_primary_nav_group.html reads from a section (g), its
# entries (e) and their nested pages (c). core.tests.test_page_budgets checks
# the template against these lists, so a field added to the template without
# adding it here fails a test instead of drawing stale HTML.
GROUP_FIELDS = ('key', 'label', 'icon', 'shortcut', 'href', 'active')
ENTRY_FIELDS = ('pin', 'label', 'keywords', 'shortcut', 'active', 'href', 'icon', 'children')
CHILD_FIELDS = ('label', 'keywords', 'href', 'active')


def html_enabled():
    return getattr(settings, 'NAV_HTML_CACHE', True)


def clear_html():
    with _html_lock:
        _html_store.clear()


def _v(value):
    # Type and text: the template prints str(value) and tests truthiness, and
    # two values with the same type and text draw the same.
    return (type(value).__name__, str(value))


def group_key(group, pnav, request):
    """The cache key for one sidebar section: every value the template reads
    for it, or None when it cannot be keyed (the section is then drawn
    normally)."""
    from django.utils import translation
    path = getattr(request, 'path', None)
    try:
        entries = []
        hrefs = set()
        for e in group.get('entries') or ():
            hrefs.add(e.get('href'))
            children = tuple(tuple(_v(c.get(f)) for f in CHILD_FIELDS) for c in e.get('children') or ())
            entries.append(tuple(_v(e.get(f)) for f in ENTRY_FIELDS[:-1]) + (children,))
        overview = None
        if group.get('key') == 'dashboard':
            pin_edit = (pnav or {}).get('pin_edit') or ''
            overview = (str(pin_edit), request.get_full_path() if pin_edit else None)
        return (tuple(_v(group.get(f)) for f in GROUP_FIELDS), tuple(entries),
                path if path in hrefs else None, translation.get_language(), overview)
    except (AttributeError, TypeError):
        return None


def _cached_html(key, render):
    if key is None:
        return render()
    with _html_lock:
        hit = _html_store.get(key)
        if hit is not None:
            _html_store.move_to_end(key)
            return hit
    html = render()
    with _html_lock:
        _html_store[key] = html
        _html_store.move_to_end(key)
        while len(_html_store) > HTML_MAX_ENTRIES:
            _html_store.popitem(last=False)
    return html


def group_html(group, pnav, request, render):
    """The section's HTML: from the per-process cache when this exact key was
    drawn before, else `render()` (and kept)."""
    if not html_enabled() or request is None:
        return render()
    return _cached_html(group_key(group, pnav, request), render)


# The fields core/_settings_menu.html reads from the settings workspace: its
# categories (c, and `cur`, the current one) and their pages (t).
CATEGORY_FIELDS = ('key', 'label', 'icon', 'href', 'active', 'tabs')
TAB_FIELDS = ('label', 'keywords', 'href', 'active', 'icon')


def settings_menu_key(workspace):
    """The cache key for the settings workspace header: every value
    core/_settings_menu.html reads, or None when it cannot be keyed."""
    from django.utils import translation
    try:
        cats = []
        current = None
        for i, c in enumerate(workspace.get('categories') or ()):
            tabs = tuple(tuple(_v(t.get(f)) for f in TAB_FIELDS) for t in c.get('tabs') or ())
            cats.append(tuple(_v(c.get(f)) for f in CATEGORY_FIELDS[:-1]) + (tabs,))
            if c is workspace.get('current'):
                current = i
        if workspace.get('current') is not None and current is None:
            return None   # a current category that is not one of the list: draw it normally
        return ('settings_menu', tuple(cats), current, translation.get_language())
    except (AttributeError, TypeError):
        return None


def settings_menu_html(workspace, render):
    if not html_enabled() or not workspace:
        return render()
    return _cached_html(settings_menu_key(workspace), render)
