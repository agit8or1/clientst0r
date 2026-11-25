"""docs/ux/design-tokens.json stays valid, accessible and in step with the CSS.

scripts/ux/check_design_tokens.py does the work; this runs it. Schema and contrast must pass.
CSS drift fails only when a --cs-* property exists with a different literal value; properties
that do not exist yet are "not yet implemented", not failures.
"""
import importlib.util
import json
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
