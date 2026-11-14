"""Customer portal branding and layout, as set on Settings → General →
Customer portal (core/portal_settings_views.py) and applied by
portal/templatetags/portal_theme.py.

Every value read here is validated again before it reaches a page, so a row
edited outside the settings form (shell, fixture, old backup) still cannot
put anything but a hex colour into a <style> block or anything but an
http(s) / mailto / tel link into an href.
"""
from __future__ import annotations

import re

HEX6 = re.compile(r'^#[0-9a-fA-F]{6}$')
_HEX = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
# Digits, spaces and the usual separators; "ext" / "x" for an extension.
PHONE = re.compile(r'^\+?[0-9 ().\-/]{3,30}(?:\s*(?:ext\.?|x)\s*[0-9]{1,6})?$', re.I)

NAVIGATION = ('top', 'side')
WIDTHS = ('standard', 'wide')
THEMES = ('system', 'light', 'dark')
LOGIN_BACKGROUNDS = ('none', 'color', 'image')


def clean_hex(value) -> str:
    """A plain #rgb / #rrggbb colour, else ''."""
    value = (value or '').strip()
    return value if _HEX.match(value) else ''


def _channels(hex_colour):
    h = hex_colour.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _luminance(hex_colour) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _channels(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def text_on(hex_colour) -> str:
    """White or near-black, whichever reads better on `hex_colour`."""
    if not clean_hex(hex_colour):
        return '#ffffff'
    dark = '#111418'
    return '#ffffff' if contrast_ratio(hex_colour, '#ffffff') >= contrast_ratio(hex_colour, dark) else dark


def _mix(hex_colour, toward, amount):
    a, b = _channels(hex_colour), _channels(toward)
    return '#' + ''.join(f'{round((x + (y - x) * amount) * 255):02x}' for x, y in zip(a, b))


def readable_on(hex_colour, background, minimum=4.5) -> str:
    """`hex_colour`, mixed toward black or white (whichever the background is
    not) just enough to reach `minimum` contrast on `background`, so links
    and accent text in the chosen colour stay readable in light and dark."""
    hex_colour = clean_hex(hex_colour)
    if not hex_colour:
        return ''
    if contrast_ratio(hex_colour, background) >= minimum:
        return hex_colour.lower()
    toward = '#ffffff' if _luminance(background) < 0.5 else '#000000'
    for step in range(1, 21):
        candidate = _mix(hex_colour, toward, step / 20)
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return toward


# The portal's light and dark surfaces (static/css/portal.css).
LIGHT_SURFACE = '#ffffff'
DARK_SURFACE = '#1a1d20'


def tel_href(phone) -> str:
    """'tel:+15551234567' for a validated phone number, else ''."""
    phone = (phone or '').strip()
    if not phone or not PHONE.match(phone):
        return ''
    main = re.split(r'(?i)\s*(?:ext\.?|x)\s*', phone)[0]
    digits = re.sub(r'[^0-9+]', '', main)
    return f'tel:{digits}' if digits.strip('+') else ''


def safe_web_url(url) -> str:
    url = (url or '').strip()
    return url if re.match(r'^https?://', url, re.I) else ''


def brand_name(ss) -> str:
    """Portal name, else custom company name, else site name, else 'Support'."""
    if ss is None:
        return 'Support'
    for attr in ('portal_name', 'custom_company_name', 'site_name'):
        value = (getattr(ss, attr, '') or '').strip()
        if value:
            return value
    return 'Support'


def default_theme(ss) -> str:
    value = getattr(ss, 'portal_default_theme', '') if ss is not None else ''
    return value if value in ('light', 'dark') else ''


def _file_url(field):
    try:
        return field.url if field and field.name else ''
    except Exception:  # storage misconfigured / file field without storage
        return ''


class PortalLook:
    """What a portal page needs to draw itself: logo, accent, layout,
    sign-in background and message, and support contact."""

    def __init__(self, ss, organization=None):
        self.name = brand_name(ss)
        # Logo: the customer's own, the portal logo, the app's custom logo.
        self.logo_url, self.logo_alt = '', self.name
        org_logo = _file_url(getattr(organization, 'logo', None)) if organization is not None else ''
        if org_logo:
            self.logo_url, self.logo_alt = org_logo, organization.name
        else:
            for attr in ('portal_logo', 'custom_logo'):
                url = _file_url(getattr(ss, attr, None)) if ss is not None else ''
                if url:
                    self.logo_url = url
                    break

        # Accent: the customer's colour, else the portal default, else the
        # stylesheet's own (light/dark) teal.
        self.accent = clean_hex(getattr(organization, 'portal_primary_color', '')) \
            or clean_hex(getattr(ss, 'portal_accent_color', ''))
        # Light and dark variants keep 4.5:1 on the portal surfaces.
        self.accent_light = readable_on(self.accent, LIGHT_SURFACE) if self.accent else ''
        self.accent_dark = readable_on(self.accent, DARK_SURFACE) if self.accent else ''
        self.accent_contrast = text_on(self.accent_light) if self.accent else ''
        self.accent_dark_contrast = text_on(self.accent_dark) if self.accent else ''

        nav = getattr(ss, 'portal_navigation', 'top')
        width = getattr(ss, 'portal_content_width', 'standard')
        self.navigation = nav if nav in NAVIGATION else 'top'
        self.width = width if width in WIDTHS else 'standard'
        self.body_class = f'portal-nav-{self.navigation} portal-width-{self.width}'

        bg = getattr(ss, 'portal_login_background', 'none')
        self.login_bg_mode = 'none'
        self.login_bg_color = ''
        self.login_bg_image = ''
        if bg == 'color' and clean_hex(getattr(ss, 'portal_login_background_color', '')):
            self.login_bg_mode = 'color'
            self.login_bg_color = clean_hex(ss.portal_login_background_color)
        elif bg == 'image':
            url = _file_url(getattr(ss, 'portal_login_background_image', None))
            # Stored names are random hex (core.image_safety.sanitize_image);
            # anything that could close the url("…") is refused anyway.
            if url and not re.search(r'["\'()\\\s<>]', url):
                self.login_bg_mode = 'image'
                self.login_bg_image = url

        self.login_message = (getattr(ss, 'portal_login_message', '') or '').strip()

        self.support_email = (getattr(ss, 'portal_support_email', '') or '').strip()
        self.support_phone = (getattr(ss, 'portal_support_phone', '') or '').strip()
        self.support_tel = tel_href(self.support_phone)
        if not self.support_tel:
            self.support_phone = ''
        self.support_url = safe_web_url(getattr(ss, 'portal_support_url', ''))
        self.has_contact = bool(self.support_email or self.support_phone or self.support_url)
