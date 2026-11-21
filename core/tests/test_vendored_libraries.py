"""The libraries every page loads are served from static/vendor.

base.html used to pull Font Awesome, DataTables, Select2 (and its Bootstrap 5
theme), Leaflet and jQuery from five CDN hosts: a DNS lookup and TLS
handshake per host on a first visit, render-blocking stylesheets from
another origin, and a broken page whenever a network blocks a CDN. The
files below are byte-for-byte the CDN copies of the same versions (checked
against the Subresource Integrity hashes base.html carried, where it had
one), with their licences.
"""
import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

VENDORED = {
    'vendor/datatables/1.13.7/css/dataTables.bootstrap5.min.css': 'f34c8a0861b8143557d6a3fb835fedfa8896c896b645af8da700ed8827d8b114',
    'vendor/datatables/1.13.7/js/dataTables.bootstrap5.min.js': 'de25c7adf49de31cc8d58caba281748c6e0e5701a2480a14d7e59d6301306199',
    'vendor/datatables/1.13.7/js/jquery.dataTables.min.js': 'ec42765021641e0f094cc8309d3f4f998afbd68683c008012ac11a4139842ee6',
    'vendor/fontawesome/6.5.1/css/all.min.css': 'c22cfb6520a7fdbb738632834019acf47c78b1279462c0eb4cb83bae83ecb5a7',
    'vendor/fontawesome/6.5.1/webfonts/fa-brands-400.ttf': '5656d596bc597165a42182f67b2b9f17d2ae47a9e3ef1b042b9a729739730705',
    'vendor/fontawesome/6.5.1/webfonts/fa-brands-400.woff2': '3a8924cd5203a28628716aedb5cef0943da4c3b44e3ffcee90ab06387b41c490',
    'vendor/fontawesome/6.5.1/webfonts/fa-regular-400.ttf': '5d02dc9b858e3c85a794f87e379857f4fedc4e26cf15001714a9a0e0b1d2294d',
    'vendor/fontawesome/6.5.1/webfonts/fa-regular-400.woff2': '2bccecf0bc7e96cd5ce4003abeb3ae9ee4a3d19158c4e6edfd2df32d2f0d5721',
    'vendor/fontawesome/6.5.1/webfonts/fa-solid-900.ttf': 'fbbf06d7437aa30f3cd44c968380193545a8fc3eadfb7ad897bbb101eefec5a2',
    'vendor/fontawesome/6.5.1/webfonts/fa-solid-900.woff2': '9fc85f3a4544ab0d570c7f8f9bbb88db8d92c359b2707580ea8b07c75673eae2',
    'vendor/fontawesome/6.5.1/webfonts/fa-v4compatibility.ttf': '09663a36fc05e7190af8324b855105c5bb511ad94f94b81b34afee503279eca2',
    'vendor/fontawesome/6.5.1/webfonts/fa-v4compatibility.woff2': '4d4a2d7fd1c6684845cb174fdd7fc073bd64cb741286fb247f8b76c2b7b852c4',
    'vendor/jquery/3.7.0/jquery-3.7.0.min.js': 'd8f9afbf492e4c139e9d2bcb9ba6ef7c14921eb509fb703bc7a3f911b774eff8',
    'vendor/leaflet/1.9.4/images/layers-2x.png': '066daca850d8ffbef007af00b06eac0015728dee279c51f3cb6c716df7c42edf',
    'vendor/leaflet/1.9.4/images/layers.png': '1dbbe9d028e292f36fcba8f8b3a28d5e8932754fc2215b9ac69e4cdecf5107c6',
    'vendor/leaflet/1.9.4/images/marker-icon-2x.png': '00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528',
    'vendor/leaflet/1.9.4/images/marker-icon.png': '574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437',
    'vendor/leaflet/1.9.4/images/marker-shadow.png': '264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da',
    'vendor/leaflet/1.9.4/leaflet.css': 'a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6',
    'vendor/leaflet/1.9.4/leaflet.js': 'db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a',
    'vendor/leaflet/1.9.4/leaflet.js.map': '600a10dc5cd110de0699510d322afcbe01c7ca90b4c5f48adc20314c70aac753',
    'vendor/select2-bootstrap-5-theme/1.3.0/select2-bootstrap-5-theme.min.css': '5cb35411fccf18705e4ad112d836cb514459ddeefddc169b970cc99588fa5b64',
    'vendor/select2/4.1.0-rc.0/css/select2.min.css': 'cda4a81c187015d95ed2c71f1841540b08203cdec5fa2a7d5d1825a3c2166f8c',
    'vendor/select2/4.1.0-rc.0/js/select2.min.js': 'f7244fff610595b944f76bf3080d74e3af42b5dd234f8f079e698cc39ac966b0',
}

LICENCES = (
    'vendor/fontawesome/6.5.1/LICENSE.txt',
    'vendor/datatables/1.13.7/LICENSE.txt',
    'vendor/select2/4.1.0-rc.0/LICENSE.md',
    'vendor/select2-bootstrap-5-theme/1.3.0/LICENSE',
    'vendor/leaflet/1.9.4/LICENSE',
    'vendor/jquery/3.7.0/LICENSE.txt',
)

# The CDN copies these replace, anywhere in a template.
CDN_COPY = re.compile(
    r'font-awesome/6\.5\.1/|cdn\.datatables\.net/1\.13\.7/|select2@4\.1\.0-rc\.0/|'
    r'select2-bootstrap-5-theme@1\.3\.0/|leaflet@1\.9\.4/|code\.jquery\.com/jquery-3\.7\.0')
CDN_HOST = re.compile(r'(?:src|href)="(https://[a-z0-9.-]+)/', re.I)


def templates():
    root = Path(settings.BASE_DIR)
    for path in root.rglob('*.html'):
        rel = path.relative_to(root)
        if {'venv', 'node_modules', '.git', 'static_collected', 'staticfiles', 'htmlcov'} & set(rel.parts):
            continue
        if 'templates' in rel.parts:
            yield rel, path.read_text(errors='ignore')


class VendoredLibraryTests(SimpleTestCase):

    def test_files_are_the_upstream_release(self):
        for path, digest in VENDORED.items():
            found = finders.find(path)
            self.assertIsNotNone(found, path)
            self.assertEqual(hashlib.sha256(Path(found).read_bytes()).hexdigest(), digest, path)
        for path in LICENCES:
            self.assertIsNotNone(finders.find(path), path)

    def test_stylesheet_references_resolve(self):
        """url(...) in the vendored CSS (webfonts, Leaflet's images) points at
        files that exist, or the manifest storage fails collectstatic."""
        for path in VENDORED:
            if not path.endswith('.css'):
                continue
            base = Path(finders.find(path)).parent
            for ref in re.findall(r'url\(([^)]+)\)', Path(finders.find(path)).read_text()):
                ref = ref.strip('\'"').split('?')[0].split('#')[0]
                if not ref or ref.startswith('data:'):
                    continue
                self.assertTrue((base / ref).is_file(), f'{path} -> {ref}')

    def test_source_maps_are_present(self):
        for path in VENDORED:
            found = Path(finders.find(path))
            if found.suffix not in ('.js', '.css'):
                continue
            m = re.search(r'sourceMappingURL=(\S+?)(?:\s|\*/|$)', found.read_text(errors='ignore'))
            if m:
                self.assertTrue((found.parent / m.group(1)).is_file(), f'{path}: {m.group(1)}')

    def test_no_template_loads_these_from_a_cdn(self):
        offenders = [f'{rel}:{n}' for rel, text in templates()
                     for n, line in enumerate(text.splitlines(), 1) if CDN_COPY.search(line)]
        self.assertEqual(offenders, [], 'serve these from static/vendor')

    def test_csp_lists_every_cdn_a_template_still_uses_and_no_other(self):
        used = {m.group(1).lower() for _rel, text in templates() for m in CDN_HOST.finditer(text)
                if re.search(r'<(script|link)\b[^>]*' + re.escape(m.group(0)), text)}
        allowed = set(settings.CSP_POLICY['script-src']) | set(settings.CSP_POLICY['style-src'])
        cdns = {h for h in used if h in ('https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com',
                                         'https://unpkg.com', 'https://code.jquery.com',
                                         'https://cdn.datatables.net')}
        self.assertTrue(cdns <= allowed, cdns - allowed)
        for host in ('https://code.jquery.com', 'https://cdn.datatables.net'):
            self.assertNotIn(host, used)
            self.assertNotIn(host, settings.CSP_POLICY['script-src'])
