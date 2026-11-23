"""Client St0r Docs: docs/*.md read in the app (core/guides.py)."""
import subprocess
import sys
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core import guides
from core.models import Organization

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class GuideRegistryTests(SimpleTestCase):

    def test_every_listed_guide_exists(self):
        root = Path(django_settings.BASE_DIR)
        missing = [g.path for g in guides.GUIDES if not (root / g.path).is_file()]
        self.assertEqual(missing, [])

    def test_slugs_are_unique_and_categories_known(self):
        slugs = [g.slug for g in guides.GUIDES]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(g.category in guides.CATEGORIES for g in guides.GUIDES))

    def test_asset_path_stays_inside_the_image_folders(self):
        self.assertIsNotNone(guides.asset_path('images/guides/guide-dashboard.png'))
        for bad in ('../config/settings.py', 'images/../../db.sqlite3', 'images/../ROADMAP.md',
                    '/etc/passwd', 'images/guides/../../../.env', 'images/github', ''):
            self.assertIsNone(guides.asset_path(bad), bad)

    def test_github_style_anchors_and_nested_lists(self):
        html, toc = guides._markdown_html('# T\n\n## Off-host: setup & keys\n\n1. one\n   - nested\n2. two\n\n## Off-host: setup & keys\n')
        self.assertIn('id="off-host-setup--keys"', html)
        self.assertIn('id="off-host-setup--keys-1"', html)
        self.assertIn('<ul>', html)  # the 3-space nested list is a list, not a paragraph
        self.assertEqual([t['id'] for t in toc], ['off-host-setup--keys', 'off-host-setup--keys-1'])

    def test_links_and_images_point_into_the_app(self):
        data = guides.load(guides.GUIDES_BY_SLUG['billing'])
        self.assertIn('src="/core/docs/assets/images/guides/guide-billing-ready.png"', data['html'])
        self.assertIn('<figcaption>', data['html'])
        data = guides.load(guides.GUIDES_BY_SLUG['getting-started'])
        self.assertIn(f'href="{reverse("core:guide", args=["organizations"])}"', data['html'])

    def test_search_finds_sections_and_escapes(self):
        hits = guides.search('prepaid hours')
        self.assertTrue(hits)
        self.assertTrue(any(h['url'].startswith('/core/docs/billing/') for h in hits))
        self.assertTrue(all('<mark>' in h['heading_hl'] or '<mark>' in h['snippet'] or h['score'] for h in hits))
        self.assertEqual(guides.search('<script>alert(1)</script> zzqqxx'), [])
        self.assertEqual(guides.search(''), [])
        self.assertEqual(guides.highlight('<b>x</b>', ['x']), '&lt;b&gt;<mark>x</mark>&lt;/b&gt;')

    def test_figure_blocks_match_the_manifest(self):
        root = Path(django_settings.BASE_DIR)
        proc = subprocess.run([sys.executable, str(root / 'scripts' / 'guide_figures.py'), '--check'],
                              capture_output=True, text=True, cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GuideViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Alpha', slug='alpha')
        cls.user = User.objects.create_superuser('docsreader', 'd@example.com', 'pw')

    def setUp(self):
        self.client.force_login(self.user)

    def test_sign_in_required(self):
        self.client.logout()
        for url in (reverse('core:guides'), reverse('core:guide', args=['billing']),
                    reverse('core:guide_asset', args=['images/guides/guide-dashboard.png'])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)

    def test_index_lists_guides(self):
        r = self.client.get(reverse('core:guides'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Getting started: finding your way')
        self.assertContains(r, reverse('core:guide', args=['billing']))

    def test_index_search(self):
        r = self.client.get(reverse('core:guides'), {'q': 'off-host backup'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '/core/docs/backup-and-restore/')
        self.assertContains(r, '<mark>')
        r = self.client.get(reverse('core:guides'), {'q': '<img src=x onerror=alert(1)>'})
        self.assertNotContains(r, '<img src=x onerror')

    def test_guide_page(self):
        r = self.client.get(reverse('core:guide', args=['getting-started']), {'q': 'ticket'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Getting started: finding your way')
        self.assertContains(r, 'On this page')
        self.assertContains(r, 'Back to results')
        self.assertEqual(self.client.get(reverse('core:guide', args=['no-such-guide'])).status_code, 404)

    def test_assets(self):
        r = self.client.get(reverse('core:guide_asset', args=['images/guides/guide-dashboard.png']))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertIn('sandbox', r['Content-Security-Policy'])
        r.close()
        for bad in ('../config/settings.py', 'images/../../manage.py', 'images/guides/nope.png'):
            self.assertEqual(self.client.get(reverse('core:guide_asset', args=[bad])).status_code, 404, bad)

    def test_help_search_includes_guides(self):
        r = self.client.get(reverse('core:help_search'), {'q': 'prepaid'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'In the Client St0r Docs')

    def test_sidebar_foot_links_to_the_docs(self):
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'app-nav__docs')
        self.assertContains(r, f'href="{reverse("core:guides")}"')
