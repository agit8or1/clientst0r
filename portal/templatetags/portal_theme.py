"""Template helpers for the customer portal theme (static/css/portal.css)."""
import re

from django import template

register = template.Library()

_HEX = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
DARK_THEMES = frozenset({'dark', 'dracula', 'monokai'})


@register.filter
def portal_accent(value):
    """The customer's portal colour when it is a plain hex colour, else ''.
    It goes into a <style> block, so nothing else is let through."""
    value = (value or '').strip()
    return value if _HEX.match(value) else ''


@register.simple_tag(takes_context=True)
def portal_theme_mode(context):
    """'dark' or 'light' for a signed-in user (from their theme), '' to
    follow the visitor's system preference."""
    request = context.get('request')
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return ''
    profile = getattr(user, 'profile', None)
    theme = getattr(profile, 'theme', '') or ''
    if not theme or theme == 'default':
        return ''
    return 'dark' if theme in DARK_THEMES else 'light'


@register.simple_tag(takes_context=True)
def portal_brand_name(context):
    """The MSP's name for portal pages: custom company name, else site name."""
    ss = context.get('system_settings')
    name = ''
    if ss is not None:
        name = (getattr(ss, 'custom_company_name', '') or getattr(ss, 'site_name', '') or '').strip()
    return name or 'Support'


@register.simple_tag(takes_context=True)
def portal_accent_color(context):
    """Validated portal colour of the customer being shown: the view's
    `organization`, else the signed-in user's active portal customer."""
    org = context.get('organization')
    if org is None:
        request = context.get('request')
        membership = getattr(request, 'portal_membership', None)
        org = getattr(membership, 'organization', None)
    return portal_accent(getattr(org, 'portal_primary_color', ''))
