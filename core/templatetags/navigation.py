"""`{% nav_state as nav %}` — the current page's place in the navigation.

See core/navigation.py for the registry behind it.
"""
import logging

from django import template

from core import navigation

register = template.Library()
logger = logging.getLogger(__name__)


@register.simple_tag(takes_context=True)
def nav_state(context):
    try:
        return navigation.nav_state(context)
    except Exception:  # pragma: no cover - decoration must never take a page down
        logger.exception('nav_state failed')
        return navigation._empty_state()


@register.simple_tag
def nav_matches(pnav, query, limit=8):
    """Sidebar pages whose label (or keywords) match every word of `query` —
    the server-side twin of the sidebar filter, for the search page. Only
    pages already in this user's sidebar can match, so nothing new leaks."""
    words = [w for w in (query or '').lower().split() if w]
    if not words or not pnav:
        return []
    groups = list(pnav.get('groups') or [])
    if pnav.get('settings'):
        groups.append(pnav['settings'])
    out, seen = [], set()
    for g in groups:
        for e in g['entries']:
            candidates = [(e['label'], e['href'], f"{e['label']} {e['keywords']} {g['label']}", g['label'])]
            candidates += [(c['label'], c['href'], f"{c['label']} {e['label']} {g['label']}",
                            f"{g['label']} › {e['label']}") for c in (e.get('tabs') or e['children'])]
            for label, href, text, where in candidates:
                text = str(text).lower()
                if href not in seen and all(w in text for w in words):
                    seen.add(href)
                    out.append({'label': label, 'href': href, 'where': where})
    # Pages that are not sidebar links (Configure pages, settings pages,
    # tabs): already gated the same way (core.navigation.destinations_for).
    for d in pnav.get('extra') or []:
        text = f"{d['label']} {d['keywords']} {d['section']} {d['group']}".lower()
        if d['href'] not in seen and all(w in text for w in words):
            seen.add(d['href'])
            where = d['group'] if d['section'] == d['group'] else f"{d['group']} › {d['section']}"
            out.append({'label': d['label'], 'href': d['href'], 'where': where})
    return out[:limit]


@register.simple_tag(takes_context=True)
def primary_nav(context):
    """`{% primary_nav as pnav %}` — the sidebar (core.navigation.primary_nav)."""
    try:
        return navigation.primary_nav(context)
    except Exception:  # pragma: no cover - decoration must never take a page down
        logger.exception('primary_nav failed')
        return navigation._empty_primary()


@register.simple_tag(takes_context=True)
def nav_notifications(context):
    """`{% nav_notifications as notes %}` — the top bar's bell
    (core.notifications.for_context)."""
    from core import notifications
    try:
        return notifications.for_context(context)
    except Exception:  # pragma: no cover - decoration must never take a page down
        logger.exception('nav_notifications failed')
        return {'items': [], 'total': 0}
