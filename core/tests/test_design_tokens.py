"""docs/ux/design-tokens.json stays valid, accessible and in step with the CSS.

scripts/ux/check_design_tokens.py does the work; this runs it. Schema and contrast must pass.
CSS drift fails only when a --cs-* property exists with a different literal value; properties
that do not exist yet are "not yet implemented", not failures.
"""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
SCRIPT = ROOT / 'scripts' / 'ux' / 'check_design_tokens.py'
TOKENS = ROOT / 'docs' / 'ux' / 'design-tokens.json'


def _load():
    spec = importlib.util.spec_from_file_location('check_design_tokens', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cdt = _load()


class DesignTokenTests(SimpleTestCase):
    def test_validator_passes(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_schema_and_contrast(self):
        res = cdt.run()
        self.assertEqual(res['schema'], [])
        self.assertEqual(res['contrast'], [])
        self.assertEqual(res['drift']['errors'], [])

    def test_versioned_and_both_themes(self):
        doc = json.loads(TOKENS.read_text())
        self.assertRegex(doc['meta']['version'], r'^\d+\.\d+\.\d+$')
        self.assertEqual(set(doc['theme']), {'light', 'dark'})
        self.assertGreaterEqual(len(doc['contrast-pairs']['pairs']), 200)

    def test_every_status_role_has_text_and_fill_pairs(self):
        doc = json.loads(TOKENS.read_text())
        pairs = {(p['theme'], p['fg'], p['bg']) for p in doc['contrast-pairs']['pairs']}
        for theme in ('light', 'dark'):
            for role in ('success', 'warning', 'danger', 'info', 'pending'):
                with self.subTest(theme=theme, role=role):
                    self.assertIn((theme, f'status.{role}.on-solid', f'status.{role}.solid'), pairs)
                    self.assertIn((theme, f'status.{role}.text', 'bg.surface'), pairs)
                    self.assertIn((theme, f'status.{role}.graphic', 'bg.surface'), pairs)

    def test_failing_pair_is_reported(self):
        doc = json.loads(TOKENS.read_text())
        doc['contrast-pairs']['pairs'].append(
            {'theme': 'light', 'fg': 'bg.page', 'bg': 'bg.surface', 'min': 4.5, 'use': 'test'})
        errors = cdt.check_contrast(doc)
        self.assertEqual(len(errors), 1)
        self.assertIn('bg.page on bg.surface', errors[0])

    def test_schema_catches_bad_values_and_theme_gaps(self):
        doc = json.loads(TOKENS.read_text())
        doc['space']['1']['$value'] = 'four'
        del doc['theme']['dark']['color']['text']['muted']
        doc['icon']['concepts']['ticket']['fa'] = 'no-such-icon-anywhere'
        fa = (ROOT / 'static' / 'vendor' / 'fontawesome' / '6.5.1' / 'css' / 'all.min.css').read_text()
        errors = '\n'.join(cdt.check_schema(doc, fa))
        self.assertIn('space.1', errors)
        self.assertIn('theme.dark is missing color.text.muted', errors)
        self.assertIn('fa-no-such-icon-anywhere', errors)

    def test_drift_detects_mismatch_only_for_existing_variables(self):
        doc = json.loads(TOKENS.read_text())
        light_text = cdt.resolve(doc, doc['theme']['light']['color']['text']['primary'])
        dark_text = cdt.resolve(doc, doc['theme']['dark']['color']['text']['primary'])
        css = (
            ':root { --cs-color-text-primary: %s; --cs-space-2: 9px; --cs-radius-md: var(--x); }\n'
            '[data-cs-theme="dark"] { --cs-color-text-primary: %s; }\n'
            '[data-density="comfortable"] { --cs-control-height: 40px; }\n'
            '@media (prefers-reduced-motion: reduce) { :root { --cs-motion-duration-fast: 0ms; } }\n'
            ':root { --cs-not-a-token: 1px; }\n'
        ) % (light_text.upper(), dark_text)
        with tempfile.NamedTemporaryFile('w', suffix='.css', delete=False) as fh:
            fh.write(css)
        try:
            drift = cdt.check_drift(doc, [fh.name])
        finally:
            Path(fh.name).unlink()
        self.assertEqual(len(drift['errors']), 1, drift['errors'])
        self.assertIn('--cs-space-2', drift['errors'][0])
        self.assertEqual(len(drift['indirect']), 1)
        self.assertIn('--cs-not-a-token', drift['unknown'])
        implemented = {name for _ctx, name in drift['implemented']}
        self.assertTrue({'--cs-color-text-primary', '--cs-control-height', '--cs-motion-duration-fast'} <= implemented)
        self.assertGreater(len(drift['missing']), 200)

    def test_emitted_css_round_trips_without_drift(self):
        doc = json.loads(TOKENS.read_text())
        with tempfile.NamedTemporaryFile('w', suffix='.css', delete=False) as fh:
            fh.write(cdt.emit_css(doc))
        try:
            drift = cdt.check_drift(doc, [fh.name])
        finally:
            Path(fh.name).unlink()
        self.assertEqual(drift['errors'], [])
        self.assertEqual(drift['missing'], [])


# --------------------------------------------------------------------------- 113.5 generated CSS
BUILD = ROOT / 'scripts' / 'ux' / 'build_token_css.py'
TOKENS_CSS = ROOT / 'static' / 'css' / 'tokens.css'
THEMES_CSS = ROOT / 'static' / 'css' / 'themes.css'
NAV_CSS = ROOT / 'static' / 'css' / 'navigation.css'


def _load_build():
    spec = importlib.util.spec_from_file_location('build_token_css', BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


btc = _load_build()


def _region(text):
    start = text.index(btc.REGION_START)
    return text[start:text.index(btc.REGION_END, start)]


class GeneratedTokenCssTests(SimpleTestCase):
    def test_tokens_css_is_up_to_date(self):
        self.assertEqual(TOKENS_CSS.read_text(), btc.build(),
                         'static/css/tokens.css is stale: run venv/bin/python scripts/ux/build_token_css.py')

    def test_themes_css_region_is_up_to_date(self):
        current = THEMES_CSS.read_text()
        self.assertEqual(current, btc.build_themes(current),
                         'themes.css theme-token region is stale: run scripts/ux/build_token_css.py')

    def test_check_mode_passes_and_detects_staleness(self):
        r = subprocess.run([sys.executable, str(BUILD), '--check'], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = json.loads(TOKENS.read_text())
        doc['space']['4']['$value'] = '17px'
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / 'tokens.json'
            changed.write_text(json.dumps(doc))
            r = subprocess.run([sys.executable, str(BUILD), '--check', '--no-themes', '--tokens', str(changed)],
                               capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('out of date', r.stderr)

    def test_output_is_deterministic(self):
        self.assertEqual(btc.build(), btc.build())
        text = THEMES_CSS.read_text()
        self.assertEqual(btc.build_themes(text), btc.build_themes(btc.build_themes(text)))

    def test_tokens_css_has_every_token_and_the_system_theme(self):
        css = TOKENS_CSS.read_text()
        drift = cdt.check_drift(json.loads(TOKENS.read_text()), [TOKENS_CSS])
        self.assertEqual(drift['errors'], [])
        self.assertEqual(drift['missing'], [])
        self.assertIn('@media (prefers-color-scheme: dark) {\n  :root[data-cs-theme="system"] {', css)
        self.assertIn('[data-cs-theme="dark"] {', css)

    def test_generated_css_only_declares_custom_properties(self):
        """Loading tokens.css and the theme-token region cannot change how a page looks: they
        declare --cs-* custom properties and nothing else."""
        for label, text in (('tokens.css', TOKENS_CSS.read_text()), ('themes region', _region(THEMES_CSS.read_text()))):
            for prelude, name, _value in cdt.css_declarations(text):
                with self.subTest(source=label, name=name):
                    self.assertTrue(name.startswith('--cs-'))
            body = cdt._strip_comments(text)
            for decl in re.findall(r'[{;]\s*([a-z][a-z-]*)\s*:', body):
                with self.subTest(source=label, property=decl):
                    self.fail(f'{label} declares a real property {decl!r}')


class LegacyThemeTokenTests(SimpleTestCase):
    """Every colour theme in themes.css sets the semantic tokens from its own palette, and the
    values a page would see meet every contrast pair of the spec (WCAG 2.2 AA)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = json.loads(TOKENS.read_text())
        cls.themes_text = THEMES_CSS.read_text()
        cls.palettes = btc.legacy_palettes(cls.themes_text)
        cls.nav = btc.nav_palette(NAV_CSS.read_text())
        cls.blocks = {name: (mode, body) for name, mode, body in re.findall(
            r':root\[data-theme="([\w-]+)"\] \{ /\* (light|dark) \*/\n(.*?)^\}', _region(cls.themes_text), re.S | re.M)}

    def _resolved(self, name):
        mode, body = self.blocks[name]
        values = {'.'.join(p): cdt.resolve(self.doc, t) for p, t in cdt.walk(self.doc['theme'][mode]['color'])}
        prefix = '--cs-color-'
        lookup = dict(self.palettes[name], **self.nav)
        for css_name, value in re.findall(r'(--cs-color-[\w-]+):\s*([^;]+);', body):
            path = css_name[len(prefix):]
            key = next(k for k in values if k.replace('.', '-') == path)
            m = re.match(r'var\(--([\w-]+)\)$', value.strip())
            values[key] = lookup[m.group(1)] if m else value.strip()
        return mode, values

    def test_every_theme_is_mapped_in_the_right_mode(self):
        from accounts.context_processors import DARK_THEMES
        self.assertEqual(set(self.blocks), set(self.palettes))
        self.assertGreaterEqual(len(self.blocks), 12)
        for name, (mode, _body) in self.blocks.items():
            with self.subTest(theme=name):
                self.assertEqual(mode == 'dark', name in DARK_THEMES)

    def test_main_roles_come_from_the_theme_palette(self):
        for name in self.blocks:
            body = self.blocks[name][1]
            with self.subTest(theme=name):
                for line in ('--cs-color-bg-page: var(--background);', '--cs-color-bg-surface: var(--surface);',
                             '--cs-color-text-primary: var(--text-primary);',
                             '--cs-color-border-subtle: var(--border-color);'):
                    self.assertIn(line, body)

    def test_every_contrast_pair_passes_in_every_theme(self):
        for name in self.blocks:
            mode, values = self._resolved(name)
            for pair in self.doc['contrast-pairs']['pairs']:
                if pair['theme'] != mode:
                    continue
                fg, bg = values[pair['fg']], values[pair['bg']]
                if len(fg) != 7 or len(bg) != 7:
                    continue  # translucent spec overlay, not a text pair
                with self.subTest(theme=name, fg=pair['fg'], bg=pair['bg']):
                    self.assertGreaterEqual(cdt.contrast(fg, bg) + 1e-9, pair['min'])

    def test_mapping_is_more_specific_than_the_system_block(self):
        # tokens.css: :root[data-cs-theme="system"] (0,2,0) under the media query. The theme blocks
        # use :root[data-theme="x"] (0,2,0) and themes.css loads later, so the theme wins.
        self.assertNotIn('\n[data-theme=', _region(self.themes_text))
