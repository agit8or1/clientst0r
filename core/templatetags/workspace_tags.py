"""Template hooks for core/workspace.py: the open-in-context trail and the
saved-views bar. Both are decoration and must never take a page down."""
import logging

from django import template

register = template.Library()
logger = logging.getLogger(__name__)


@register.simple_tag(takes_context=True)
def work_context_trail(context):
    request = context.get('request')
    if request is None or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return None
    try:
        from core.workspace import context_trail
        return context_trail(request)
    except Exception:  # pragma: no cover
        logger.exception('work_context_trail failed')
        return None


@register.simple_tag(takes_context=True)
def saved_view_bar(context):
    request = context.get('request')
    if request is None or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return None
    try:
        from core.workspace import saved_view_bar as build
        return build(request)
    except Exception:  # pragma: no cover
        logger.exception('saved_view_bar failed')
        return None
