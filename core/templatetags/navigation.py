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
        return {'menu': '', 'section': '', 'section_label': '', 'tabs': []}
