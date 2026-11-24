"""Readable text on the Executive Scorecard, the Reports pages and the shared
components the contrast sweep (scripts/contrast_check.py) found under 4.5:1."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core import navigation
from core.models import badge_style_for
from core.tests.test_theme_contrast import contrast

ROOT = Path(settings.BASE_DIR)


def theme_block(name):
    css = (ROOT / 'static' / 'css' / 'themes.css').read_text()
    m = re.search(r'^\[data-theme="%s"\]\s*\{(.*?)^\}' % re.escape(name), css, re.M | re.S)
    return dict(re.findall(r'(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;', m.group(1)))


class LightThemeTextTests(SimpleTestCase):

    def test_secondary_and_muted_text_read_on_every_light_ground(self):
        palette = theme_block('default')
        for var in ('--text-secondary', '--text-muted'):
            for ground in ('#ffffff', '#f8f9fa', '#f0f1f3', '#e9ecef'):
                self.assertGreaterEqual(contrast(palette[var], ground), 4.5, f'{var} on {ground}')

    def test_status_ink_reads_on_white(self):
        palette = theme_block('default')
        for var in ('--success-ink', '--warning-ink', '--danger-ink', '--info-ink'):
            self.assertGreaterEqual(contrast(palette[var], '#ffffff'), 4.5, var)
            self.assertGreaterEqual(contrast(palette[var], '#f8f9fa'), 4.5, var)


class TagBadgeTests(SimpleTestCase):

    def test_text_colour_follows_the_fill(self):
        self.assertEqual(badge_style_for('#fd7e14'), 'background-color:#fd7e14;color:#000;')
        self.assertEqual(badge_style_for('#ffc107'), 'background-color:#ffc107;color:#000;')
        self.assertEqual(badge_style_for('#0d47a1'), 'background-color:#0d47a1;color:#fff;')
        self.assertEqual(badge_style_for('#6c757d'), 'background-color:#6c757d;color:#fff;')

    def test_anything_but_a_hex_colour_uses_the_fallback(self):
        for bad in ('red', '#fff', 'url(x)', '#12345g', '', None, '#000000;color:red'):
            self.assertTrue(badge_style_for(bad).startswith('background-color:#6c757d;'), bad)

    def test_picked_colour_always_clears_4_5(self):
        for colour in ('#fd7e14', '#ffc107', '#0dcaf0', '#198754', '#dc3545', '#6f42c1', '#20c997', '#777777'):
            text = '#000000' if 'color:#000' in badge_style_for(colour) else '#ffffff'
            self.assertGreaterEqual(contrast(text, colour), 4.5, colour)


class ExecutiveScorecardTests(SimpleTestCase):

    def test_cards_use_the_theme_not_white(self):
        html = (ROOT / 'templates' / 'reports' / 'exec_scorecard.html').read_text()
        self.assertNotIn('background: #fff', html)
        self.assertNotIn('bg-white', html)
        self.assertNotIn('table-light', html)
        # Charts sit in a fixed-height box; a bare responsive canvas grew without end.
        self.assertEqual(html.count('class="es-chart'), 2)

    def test_scorecard_has_a_menu_entry_and_reports_light_reports_home(self):
        section = next(s for s in navigation.SECTIONS if s.key == 'mod_reports')
        tabs = {t.url_name: t for t in section.tabs}
        self.assertIn('reports:exec_scorecard', tabs)
        self.assertIn('reports:psa_profitability_by_client', tabs['reports:home'].also)
