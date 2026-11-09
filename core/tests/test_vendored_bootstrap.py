"""Bootstrap is served from static/vendor, never from a CDN.

A README screenshot once shipped unstyled because the CDN copy of
bootstrap.min.css failed to load; any user whose network blocks or loses the
CDN saw the same broken page. The files under static/vendor/bootstrap/5.3.0
are the unmodified npm release (dist/), with their source maps so the
manifest storage can rewrite the sourceMappingURL comments.
"""
import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

CDN_BOOTSTRAP = re.compile(r'(cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com)\S*/bootstrap(@|/)\d')
SKIP = {'venv', 'node_modules', '.git', 'static_collected', 'staticfiles', 'htmlcov', 'mobile', 'mobile-app'}

# sha256 of the files in the bootstrap-5.3.0 npm tarball (registry integrity
# sha512-UnBV3E3v4STVNQdms6jSGO2CvOkjUMdDAVR2V5N4uCMdaIkaQjbcEAMqRimDHIs4uqBYzDAKCQwCB+97tJgHQw==)
VENDORED = {
    'vendor/bootstrap/5.3.0/css/bootstrap.min.css': '7f1d37f0d90b6385354c2ac10e2bb91563c46bd7a266ed351222ebcac8496c2a',
    'vendor/bootstrap/5.3.0/js/bootstrap.bundle.min.js': 'aa53d582f97eb594c2a5cc5824574707f9ba9837bce3046bfa5f3556860f4e04',
}


class VendoredBootstrapTests(SimpleTestCase):
    def test_vendored_files_are_the_upstream_release(self):
        for path, digest in VENDORED.items():
            found = finders.find(path)
            self.assertIsNotNone(found, path)
            self.assertEqual(hashlib.sha256(Path(found).read_bytes()).hexdigest(), digest, path)
            self.assertIsNotNone(finders.find(path + '.map'), f'{path}.map (needed by the manifest storage)')

    def test_no_template_or_view_loads_bootstrap_from_a_cdn(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in root.rglob('*'):
            if path.suffix not in ('.html', '.py') or not path.is_file():
                continue
            rel = path.relative_to(root)
            if SKIP.intersection(rel.parts) or 'site-packages' in rel.parts or rel == Path(__file__).relative_to(root):
                continue
            for n, line in enumerate(path.read_text(errors='ignore').splitlines(), 1):
                if CDN_BOOTSTRAP.search(line):
                    offenders.append(f'{rel}:{n}')
        self.assertEqual(offenders, [], 'Bootstrap must come from static/vendor/bootstrap')
