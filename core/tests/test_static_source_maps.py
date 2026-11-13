"""Every sourceMappingURL in our static files must point at a file we ship.

The production static storage (whitenoise CompressedManifestStaticFilesStorage)
rewrites these references during collectstatic and fails the whole run when the
map is missing. v3.17.669 vendored Quill with references to .map files it did
not include, and the upgrade stopped at collectstatic on prod. The test
settings use plain StaticFilesStorage, so only a check like this catches it.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

MAP_REF = re.compile(r'sourceMappingURL=([^\s*]+)')


def _static_dirs():
    base = Path(settings.BASE_DIR)
    yield base / 'static'
    for app_static in base.glob('*/static'):
        if app_static.parent.name != 'venv':
            yield app_static


class StaticSourceMapTests(SimpleTestCase):
    def test_every_source_map_reference_exists(self):
        missing = []
        for root in _static_dirs():
            if not root.is_dir():
                continue
            for path in list(root.rglob('*.css')) + list(root.rglob('*.js')):
                try:
                    text = path.read_text(encoding='utf-8', errors='ignore')
                except OSError:
                    continue
                for ref in MAP_REF.findall(text):
                    if ref.startswith(('data:', 'http://', 'https://', '/')):
                        continue
                    if not (path.parent / ref).is_file():
                        missing.append(f'{path.relative_to(settings.BASE_DIR)} -> {ref}')
        self.assertEqual(missing, [], 'source maps referenced but not shipped')
