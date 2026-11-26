"""The help pages' SVG illustrations draw the v3.17.680 layout.

They used to draw a horizontal top menu (Assets, Vault, Vehicles) that the
sidebar replaced. Each one now carries the app frame (top bar, sidebar,
breadcrumbs), an accessible name, and nothing the CSP would block.
"""
import re

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core import navigation

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

PAGES = ('getting-started', 'assets', 'vehicles', 'vault', 'security', 'workflows',
         'documentation', 'locations')
SVG_RE = re.compile(r'<svg[^>]*class="help-svg-screenshot"[^>]*>.*?</svg>', re.S)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class HelpSvgTests(TestCase):

    def setUp(self):
        user = User.objects.create_superuser('helpsvg', 'h@x.com', 'pw')
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def _svgs(self):
        found = {}
        for page in PAGES:
            r = self.client.get(f'/core/help/{page}/')
            self.assertEqual(r.status_code, 200, page)
            found[page] = SVG_RE.findall(r.content.decode())
        return found

    def test_every_diagram_draws_the_current_layout_accessibly(self):
        svgs = self._svgs()
        self.assertEqual(sum(len(v) for v in svgs.values()), 17)
        for page, items in svgs.items():
            for svg in items:
                head = svg.split('>', 1)[0]
                self.assertIn('role="img"', head, page)
                self.assertRegex(head, r'aria-label="[^"]{20,}"')
                self.assertRegex(svg, r'<title>[^<]{20,}</title>')
                self.assertIn('app frame: v3.17.680 layout', svg, page)
                self.assertIn('Ctrl K', svg, page)
                for banned in ('<script', '<image', 'href=', 'xlink:', 'url(http'):
                    self.assertNotIn(banned, svg, (page, banned))

    def test_the_layout_overview_uses_the_sidebar_labels(self):
        overview = self._svgs()['getting-started'][0]
        for group in navigation.PRIMARY:
            self.assertIn(str(group.label).replace('&', '&amp;'), overview)
        # The old drawing: a top menu of Assets / Vault / Vehicles and a
        # 'Switch organization' list.
        self.assertNotIn('SWITCH ORGANIZATION', overview)
        self.assertNotIn('>Vehicles<', overview)
        for text in ('Administration', 'Global View', 'View all customers', 'CURRENT CONTEXT',
                     'Customer operations'):
            self.assertIn(text, overview)
