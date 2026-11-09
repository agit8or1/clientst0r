"""Template helpers for the grouped Settings sidebar and the Admin navbar menu."""
from django import template

from core import settings_groups

register = template.Library()


def _user(context):
    request = context.get('request')
    return getattr(request, 'user', None) or context.get('user')


@register.simple_tag
def settings_open_group(active_page):
    """Group key to expand in the sidebar: the one containing ``active_page``."""
    return settings_groups.group_for_active_page(active_page) or ''


@register.simple_tag(takes_context=True)
def settings_group_count(context, group_key):
    """How many entries of ``group_key`` the viewer can see."""
    return len(settings_groups.visible_entries(
        group_key, _user(context), bool(context.get('psa_enabled')),
    ))


@register.simple_tag(takes_context=True)
def settings_group_url(context, group_key):
    """Landing URL for ``group_key``: its first page the viewer may open.

    Usage: ``{% load settings_menu %}<a href="{% settings_group_url 'security' %}">``
    """
    return settings_groups.landing_url(
        group_key, _user(context), bool(context.get('psa_enabled')),
    )
