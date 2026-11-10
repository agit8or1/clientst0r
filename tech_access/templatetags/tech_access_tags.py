from django import template

from tech_access import catalog

register = template.Library()


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key) if hasattr(mapping, 'get') else mapping[key]
    except (KeyError, IndexError, TypeError):
        return None


@register.filter
def state_label(state):
    return {'locked': 'Locked', 'unavailable': 'Unavailable'}.get(state, catalog.STATE_LABELS.get(state, state))


@register.filter
def state_badge(state):
    return {'allowed': 'bg-success', 'request': 'bg-info text-dark', 'off': 'bg-secondary',
            'locked': 'bg-dark', 'unavailable': 'bg-light text-dark border'}.get(state, 'bg-secondary')


@register.filter
def cap_label(key):
    if key in catalog.OPTIONAL:
        return catalog.OPTIONAL[key][0]
    if key in catalog.LOCKED:
        return catalog.LOCKED[key][0]
    return key


@register.filter
def audit_changes(extra):
    """[(field, before, after)] from an audit entry's before/after, for the
    fields that differ. Empty when the entry carries no before/after."""
    if not isinstance(extra, dict) or ('before' not in extra and 'after' not in extra):
        return []
    before, after = extra.get('before'), extra.get('after')

    def show(v):
        if v is None:
            return '—'
        if isinstance(v, (list, tuple)):
            return ', '.join(str(x) for x in v) or '(none)'
        return str(v)

    if isinstance(before, dict) or isinstance(after, dict):
        b, a = before or {}, after or {}
        return [(k, show(b.get(k)), show(a.get(k))) for k in sorted(set(b) | set(a)) if b.get(k) != a.get(k)]
    return [('', show(before), show(after))]


@register.filter
def effect_badge(effect):
    return {'grants': 'bg-success', 'blocks': 'bg-danger', 'requires': 'bg-primary', 'info': 'bg-secondary',
            'not counted': 'bg-light text-dark border'}.get(effect, 'bg-secondary')
