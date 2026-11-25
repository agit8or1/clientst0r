"""`{% app_switcher as sw %}` — entries for templates/core/_app_switcher.html.

Reads stored state only (core.app_switcher); never calls another
application. Returns None when there is nothing to show, so the partial
renders no markup at all.
"""
import logging

from django import template

register = template.Library()
logger = logging.getLogger(__name__)


@register.simple_tag(takes_context=True)
def app_switcher(context):
    try:
        from core.app_switcher import switcher_context
        request = context.get('request')
        user = context.get('user') or getattr(request, 'user', None)
        org = context.get('current_organization')
        if org is None and request is not None:
            org = getattr(request, 'current_organization', None)
        return switcher_context(user, org)
    except Exception:  # pragma: no cover - decoration must never take a page down
        logger.exception('app_switcher failed')
        return None
