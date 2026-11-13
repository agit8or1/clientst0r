"""Link text in every colour theme stays readable — v3.17.634, v3.17.635.

The themes' primary colours are tuned for button fills; used as link text they
fell to ~2:1 on cards (Dark, Sunset, Gruvbox). themes.css now gives the themes
a --link-color; a theme without one falls back to its primary colour.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

THEMES_CSS = Path(settings.BASE_DIR) / 'static' / 'css' / 'themes.css'
DARK_THEMES = ('professional', 'dark', 'dracula', 'monokai')


def all_themes():
    return re.findall(r'^\[data-theme="([\w-]+)"\]\s*\{', THEMES_CSS.read_text(), re.M)


def _luminance(hex_colour):
    channels = [int(hex_colour.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def theme_vars(name):
    css = THEMES_CSS.read_text()
    block = re.search(r'\[data-theme="%s"\]\s*\{(.*?)\}' % name, css, re.S).group(1)
    return dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})', block))


def link_colours(v):
    return v.get('link-color', v['primary-color']), v.get('link-hover', v['primary-hover'])


class ThemeLinkContrastTests(SimpleTestCase):
    def test_every_theme_is_checked(self):
        self.assertGreaterEqual(len(all_themes()), 11)

    def test_links_meet_aa_on_page_and_cards(self):
        for name in all_themes():
            v = theme_vars(name)
            link, hover = link_colours(v)
            for surface in ('background', 'surface', 'card-bg', 'surface-hover'):
                with self.subTest(theme=name, surface=surface):
                    self.assertGreaterEqual(contrast(link, v[surface]), 4.5)
                    self.assertGreaterEqual(contrast(hover, v[surface]), 4.5)

    def test_hover_moves_away_from_the_background(self):
        for name in all_themes():
            link, hover = link_colours(theme_vars(name))
            with self.subTest(theme=name):
                if name in DARK_THEMES:
                    self.assertGreater(_luminance(hover), _luminance(link))
                else:
                    self.assertLess(_luminance(hover), _luminance(link))

    def test_link_rules_use_the_link_colour(self):
        css = THEMES_CSS.read_text()
        rule = re.search(r'a:not\(\.btn\):not\(\.nav-link\):not\(\.dropdown-item\) \{(.*?)\}', css, re.S).group(1)
        self.assertIn('var(--link-color, var(--primary-color))', rule)
