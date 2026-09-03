"""
Canonical preset-background table (v3.17.527).

The twelve abstract backgrounds were defined twice: the labels as inline
`choices` on `accounts.UserProfile.preset_background`, and the URLs as a dict
inside `accounts.context_processors.user_theme`. Nothing tied the two together,
so a key could exist in one and not the other and the only symptom would be a
silently missing background. The system-wide background policy added in
v3.17.527 needs the same list a third time, which made consolidating it the
cheaper option.

Kept free of model imports so both `core.models` and `accounts.models` can use
it without an import cycle.
"""
from __future__ import annotations

# key -> (human label, image URL)
PRESET_BACKGROUNDS: dict[str, tuple[str, str]] = {
    'abstract-1':  ('Purple Gradient', 'https://images.unsplash.com/photo-1618005198919-d3d4b5a92ead?w=1920&q=80'),
    'abstract-2':  ('Blue Gradient',   'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=1920&q=80'),
    'abstract-3':  ('Orange Coral',    'https://images.unsplash.com/photo-1553356084-58ef4a67b2a7?w=1920&q=80'),
    'abstract-4':  ('Teal Wave',       'https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=1920&q=80'),
    'abstract-5':  ('Pink Nebula',     'https://images.unsplash.com/photo-1550859492-d5da9d8e45f3?w=1920&q=80'),
    'abstract-6':  ('Cyan Fluid',      'https://images.unsplash.com/photo-1620121692029-d088224ddc74?w=1920&q=80'),
    'abstract-7':  ('Red Geometric',   'https://images.unsplash.com/photo-1557682224-5b8590cd9ec5?w=1920&q=80'),
    'abstract-8':  ('Blue Teal',       'https://images.unsplash.com/photo-1542281286-9e0a16bb7366?w=1920&q=80'),
    'abstract-9':  ('Yellow Gold',     'https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=1920&q=80'),
    'abstract-10': ('Indigo Dark',     'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=1920&q=80'),
    'abstract-11': ('Magenta Flow',    'https://images.unsplash.com/photo-1557672172-298e090bd0f1?w=1920&q=80'),
    'abstract-12': ('Navy Space',      'https://images.unsplash.com/photo-1419242902214-272b3f66ee7a?w=1920&q=80'),
}

DEFAULT_PRESET = 'abstract-1'
DEFAULT_COLOR = '#1a1a2e'

# Django `choices` for any field selecting a preset.
PRESET_CHOICES = [(key, label) for key, (label, _url) in PRESET_BACKGROUNDS.items()]


def preset_url(key: str | None) -> str:
    """URL for a preset key, falling back to the default rather than blank.

    An unknown key means a stale profile row or a hand-edited setting; a
    missing background reads as a bug to the user, so return something.
    """
    entry = PRESET_BACKGROUNDS.get(key or '') or PRESET_BACKGROUNDS[DEFAULT_PRESET]
    return entry[1]


def random_url() -> str:
    """A different image per page load, via Lorem Picsum."""
    import time
    return f'https://picsum.photos/1920/1080?random={int(time.time() * 1000)}'
