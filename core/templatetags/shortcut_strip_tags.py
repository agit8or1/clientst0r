"""`{% shortcut_pins as pins %}` for templates/core/_shortcut_strip.html.

Resolved per request (cached on the request) so a revoked permission, a
disabled module or a removed route hides the pin on the very next page.
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def shortcut_pins(context):
    request = context.get('request')
    user = getattr(request, 'user', None) or context.get('user')
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    cached = getattr(request, '_shortcut_pins', None) if request is not None else None
    if cached is not None:
        return cached
    try:
        from core.shortcut_strip import resolve_pins
        pins = resolve_pins(user)
    except Exception:
        pins = []
    if request is not None:
        request._shortcut_pins = pins
    return pins


@register.simple_tag(takes_context=True)
def shortcut_strip_eligible(context):
    request = context.get('request')
    user = getattr(request, 'user', None) or context.get('user')
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    try:
        from core.shortcut_strip import strip_eligible
        return strip_eligible(user)
    except Exception:
        return False
