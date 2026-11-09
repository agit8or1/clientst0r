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
