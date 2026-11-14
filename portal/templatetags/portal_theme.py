"""Template helpers for the customer portal theme (static/css/portal.css)."""
import re

from django import template

from core.portal_branding import PortalLook, brand_name, default_theme

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
    """'dark' or 'light' for a signed-in user who picked a theme; otherwise
    the portal's default theme, '' meaning follow the visitor's system
    preference."""
    request = context.get('request')
    user = getattr(request, 'user', None)
    fallback = default_theme(context.get('system_settings'))
    if user is None or not user.is_authenticated:
        return fallback
    profile = getattr(user, 'profile', None)
    theme = getattr(profile, 'theme', '') or ''
    # 'professional' is the starting theme of every new profile (v3.17.677),
    # so like 'default' before it, it says nothing about what this customer
    # wants: the portal uses its default theme (Settings → Customer portal),
    # which by default follows their system preference.
    if not theme or theme in ('default', 'professional'):
        return fallback
    return 'dark' if theme in DARK_THEMES else 'light'


@register.simple_tag(takes_context=True)
def portal_brand_name(context):
    """The MSP's name for portal pages: portal name, else custom company
    name, else site name."""
    return brand_name(context.get('system_settings'))


@register.simple_tag(takes_context=True)
def portal_accent_color(context):
    """Validated portal colour of the customer being shown (the view's
    `organization`, else the signed-in user's active portal customer), else
    the portal's default accent colour."""
    return PortalLook(context.get('system_settings'), _shown_org(context)).accent


def _shown_org(context):
    org = context.get('organization')
    if org is None:
        request = context.get('request')
        membership = getattr(request, 'portal_membership', None)
        org = getattr(membership, 'organization', None)
    return org


@register.simple_tag(takes_context=True)
def portal_look(context, with_org=True):
    """core.portal_branding.PortalLook for this page: logo, accent, layout
    classes, sign-in background and message, support contact. The sign-in
    pages pass with_org=False (no customer is known there)."""
    return PortalLook(context.get('system_settings'), _shown_org(context) if with_org else None)
