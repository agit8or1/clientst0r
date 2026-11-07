"""Link text in every dark colour theme stays readable — v3.17.634.

The dark themes' primary colours are tuned for button fills; used as link text
they fell to ~2:1 on cards. themes.css now gives those themes a --link-color.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

THEMES_CSS = Path(settings.BASE_DIR) / 'static' / 'css' / 'themes.css'
DARK_THEMES = ('dark', 'dracula', 'monokai')


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


class DarkThemeLinkContrastTests(SimpleTestCase):
    def test_links_meet_aa_on_page_and_cards(self):
        for name in DARK_THEMES:
            v = theme_vars(name)
            for surface in ('background', 'surface', 'card-bg', 'surface-hover'):
                with self.subTest(theme=name, surface=surface):
                    self.assertGreaterEqual(contrast(v['link-color'], v[surface]), 4.5)
                    self.assertGreaterEqual(contrast(v['link-hover'], v[surface]), 4.5)

    def test_hover_gets_lighter_on_dark_themes(self):
        for name in DARK_THEMES:
            v = theme_vars(name)
            with self.subTest(theme=name):
                self.assertGreater(_luminance(v['link-hover']), _luminance(v['link-color']))

    def test_link_rules_use_the_link_colour(self):
        css = THEMES_CSS.read_text()
        rule = re.search(r'a:not\(\.btn\):not\(\.nav-link\):not\(\.dropdown-item\) \{(.*?)\}', css, re.S).group(1)
        self.assertIn('var(--link-color, var(--primary-color))', rule)
