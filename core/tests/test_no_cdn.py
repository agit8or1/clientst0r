"""Nothing is loaded from a CDN or font host: every library is under static/vendor."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase, override_settings

CDN_HOSTS = re.compile(
    r'cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|unpkg\.com|fonts\.googleapis\.com|fonts\.gstatic\.com|'
    r'code\.jquery\.com|cdn\.datatables\.net|stackpath\.bootstrapcdn\.com|maxcdn\.bootstrapcdn\.com', re.I)
# Documented exceptions: none.
ALLOWED = {}
SKIP_DIRS = {'venv', 'node_modules', '.git', 'static_collected', 'staticfiles', 'htmlcov', 'vendor'}
STATIC_REF = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]\s*%\}""")


def project_files(suffixes):
    root = Path(settings.BASE_DIR)
    for path in root.rglob('*'):
        if path.suffix not in suffixes or not path.is_file():
            continue
        rel = path.relative_to(root)
        if SKIP_DIRS & set(rel.parts) or any(p.startswith('.') for p in rel.parts):
            continue
        if path.suffix == '.html' and 'templates' not in rel.parts:
            continue
        if path.suffix in ('.css', '.js') and rel.parts[0] != 'static' and 'static' not in rel.parts:
            continue
        yield rel, path


class NoCdnTests(SimpleTestCase):

    def test_no_template_or_static_file_references_a_cdn_host(self):
        offenders = []
        for rel, path in project_files({'.html', '.css', '.js'}):
            for n, line in enumerate(path.read_text(errors='ignore').splitlines(), 1):
                if CDN_HOSTS.search(line) and f'{rel}:{n}' not in ALLOWED:
                    offenders.append(f'{rel}:{n}')
        self.assertEqual(offenders, [], 'serve these from static/vendor')

    def test_csp_allows_no_cdn_host(self):
        for directive in ('script-src', 'style-src', 'font-src', 'connect-src', 'img-src'):
            for src in settings.CSP_POLICY.get(directive, []):
                self.assertFalse(CDN_HOSTS.search(str(src)), f'{directive}: {src}')

    def test_every_vendored_file_templates_reference_exists(self):
        missing = []
        for rel, path in project_files({'.html'}):
            for m in STATIC_REF.finditer(path.read_text(errors='ignore')):
                if m.group(1).startswith('vendor/') and not finders.find(m.group(1)):
                    missing.append(f'{rel}: {m.group(1)}')
        self.assertEqual(missing, [])

    def test_inter_is_self_hosted(self):
        css = Path(finders.find('vendor/inter/inter.css')).read_text()
        self.assertIn('font-display: swap', css)
        self.assertNotIn('http', css)
        for ref in re.findall(r'url\("([^"]+)"\)', css):
            self.assertTrue(finders.find('vendor/inter/' + ref), ref)
        self.assertTrue(finders.find('vendor/inter/LICENSE.txt'))

    def test_new_libraries_have_licences_and_are_documented(self):
        doc = Path(finders.find('vendor/VENDORED.md')).read_text()
        for lib in ('chartjs', 'sortablejs', 'jsvectormap', 'html5-qrcode', 'inter'):
            self.assertIn(lib + '/', doc)
            self.assertTrue(finders.find(f'vendor/{lib}/LICENSE') or finders.find(f'vendor/{lib}/LICENSE.txt'), lib)


from core.tests.test_navbar_grouping import TEST_MIDDLEWARE  # noqa: E402


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NoCdnSmokeTests(TestCase):
    """Rendered pages point at static/vendor and at no CDN host."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from core.models import Organization
        cls.user = get_user_model().objects.create_user(
            'nocdn_su', 'su@x.com', 'pw', is_staff=True, is_superuser=True)
        cls.org = Organization.objects.create(name='No CDN Co', slug='no-cdn-co')

    def setUp(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))

    def check(self, response, *vendored):
        self.assertEqual(response.status_code, 200, getattr(response, 'url', ''))
        html = response.content.decode()
        self.assertNotRegex(html, CDN_HOSTS)
        self.assertIn('vendor/inter/inter.css', html)
        for path in vendored:
            self.assertIn(path, html)

    def test_pages(self):
        from django.urls import reverse
        from monitoring.models import Rack
        from reports.models import Wallboard
        if True:
            self.check(self.client.get(reverse('reports:exec_scorecard')), 'vendor/chartjs/chart.umd.js')
            self.check(self.client.get(reverse('docs:document_create')), 'vendor/quill/2.0.3/quill.js',
                       'vendor/quill/2.0.3/quill.snow.css')
            rack = Rack.objects.create(organization=self.org, name='R1', units=42)
            self.check(self.client.get(reverse('monitoring:rack_detail', args=[rack.pk])),
                       'vendor/sortablejs/Sortable.min.js')
            wb = Wallboard.objects.create(organization=self.org, name='WB')
            # Chart.js loads only when the board has a chart widget; the include is a static ref.
            self.check(self.client.get(reverse('reports:wallboard_view', args=[wb.pk])))
            self.assertIn("vendor/chartjs/chart.umd.js",
                          (Path(settings.BASE_DIR) / 'templates/reports/wallboard_view.html').read_text())
            self.check(self.client.get(reverse('docs:global_kb_create')), 'vendor/quill/2.0.3/quill.js')
            self.check(self.client.get(reverse('accounts:quick_actions_edit')), 'vendor/sortablejs/Sortable.min.js')

    def test_standalone_pages(self):
        """Pages with their own <html>: checked on the source, they need request context to render."""
        root = Path(settings.BASE_DIR) / 'templates'
        for tpl in ('axes/lockout.html', 'firewall_blocked.html', 'two_factor/_base_focus.html',
                    'psa/csat_respond.html', 'psa/csat_thanks.html'):
            text = (root / tpl).read_text()
            self.assertNotRegex(text, CDN_HOSTS, tpl)
            self.assertIn("vendor/inter/inter.css", text, tpl)
            self.assertIn("'Inter'" if "'Inter'" in text else '"Inter"', text, tpl)
