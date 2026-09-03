"""
Context helpers for the GeoIP click-to-select world map (v3.17.522).

Both the global firewall country rules and the vault access-rule form render the
same `core/_geoip_map.html` component, so the backdrop resolution and the
list payload live here rather than being duplicated in two views.
"""
from __future__ import annotations

import json
import random

from .iso3166 import COUNTRY_NAMES, is_valid_code

# Colours for the selectable lists. Deliberately not red/green alone — the
# firewall's single list uses amber, and allow/block use blue/red, so the pair
# is still distinguishable without relying on colour vision.
COLOR_BLOCK = '#dc3545'
COLOR_ALLOW = '#0d6efd'
COLOR_SINGLE = '#fd7e14'


def map_background_context(settings_obj) -> dict:
    """Resolve the backdrop for the map component.

    `random` picks a pattern per render on purpose: the user asked for a
    backdrop that varies, and choosing server-side keeps it stable for the
    lifetime of the page instead of flickering on every client repaint.
    """
    patterns = [key for key, _label in getattr(
        settings_obj.__class__, 'GEOIP_MAP_PATTERNS', [('slate', 'Slate')])]
    mode = getattr(settings_obj, 'geoip_map_background_mode', 'pattern') or 'pattern'
    pattern = getattr(settings_obj, 'geoip_map_background_pattern', 'slate') or 'slate'
    image_url = ''

    if mode == 'random':
        pattern = random.choice(patterns) if patterns else 'slate'
    elif mode == 'image':
        image = getattr(settings_obj, 'geoip_map_background_image', None)
        if image:
            try:
                image_url = image.url
            except Exception:      # noqa: BLE001 — a missing file must not break the page
                image_url = ''
        if not image_url:
            # Fall back to the chosen pattern rather than rendering a blank box.
            mode = 'pattern'

    if pattern not in patterns:
        pattern = patterns[0] if patterns else 'slate'

    return {
        'geoip_map_mode': mode,
        'geoip_map_pattern': pattern,
        'geoip_map_image_url': image_url,
    }


def build_lists(*specs) -> str:
    """Serialise list specs for the component's `data-lists` attribute.

    Each spec is (key, label, color, input_id, codes).
    """
    payload = []
    for key, label, color, input_id, codes in specs:
        payload.append({
            'key': key,
            'label': label,
            'color': color,
            'input_id': input_id,
            'codes': normalise_codes(codes),
        })
    return json.dumps(payload)


def normalise_codes(value) -> list[str]:
    """Accept a list or a comma-separated string; return valid upper-case codes.

    Unknown codes are dropped rather than stored: these drive a firewall, and a
    typo silently becoming a rule that matches nothing is worse than losing it
    at the door.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.split(',')
    else:
        raw = list(value)
    seen: list[str] = []
    for item in raw:
        code = str(item).strip().upper()
        if code and is_valid_code(code) and code not in seen:
            seen.append(code)
    return seen


def name_for(code: str) -> str:
    """Trusted display name for a code — never taken from the browser."""
    return COUNTRY_NAMES.get(str(code).strip().upper(), '')
