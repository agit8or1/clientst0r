"""Interface components showcase (roadmap 113.11)."""
import importlib
import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest import skipUnless

from core import component_showcase as cs
from core.navigation import SECTIONS
from psa.tests._base import _make_msp_tech

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
SPEC = Path(django_settings.BASE_DIR) / cs.SPEC_FILE


def _spec_components():
    """The '###' headings of section 8 of the design specification."""
    text = SPEC.read_text()
    body = text.split('\n## 8. Components', 1)[1].split('\n## 9.', 1)[0]
    return re.findall(r'^### (.+)$', body, flags=re.M)


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.forms, self.resources, self.inline_handlers = [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids.append(a['id'])
        if tag == 'form':
            self.forms.append(a)
        if tag in ('script', 'img', 'iframe', 'source', 'video', 'audio', 'embed') and a.get('src'):
            self.resources.append((tag, a['src']))
        if tag == 'link' and a.get('href'):
            self.resources.append((tag, a['href']))
        for k in a:
            if k.startswith('on'):
                self.inline_handlers.append((tag, k))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ComponentShowcaseTests(TestCase):
    url = '/core/ui/components/'

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser('cs-super', 'a@example.com', 'pw')
        cls.staff = _make_msp_tech(User.objects.create_user('cs-tech', password='pw'))
        cls.customer = User.objects.create_user('cs-customer', password='pw')

    def _get(self, user):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        return self.client.get(self.url)

    def test_url_name(self):
        self.assertEqual(reverse('core:component_showcase'), self.url)

    def test_anonymous_is_redirected_to_login(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_customer_is_refused(self):
        self.assertIn(self._get(self.customer).status_code, (403, 404))

    def test_superuser_and_msp_staff_see_it(self):
        for u in (self.superuser, self.staff):
            r = self._get(u)
            self.assertEqual(r.status_code, 200, u.username)
            self.assertContains(r, 'Interface components')

    def test_post_is_not_accepted(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    def test_every_spec_component_has_a_registry_entry(self):
        spec = _spec_components()
        self.assertGreaterEqual(len(spec), 20, 'spec section 8 not parsed')
        self.assertEqual(sorted(spec), sorted(c.spec_heading for c in cs.COMPONENTS))

    def test_every_spec_component_has_a_section_with_details(self):
        r = self._get(self.superuser)
        html = r.content.decode()
        p = _Collect()
        p.feed(html)
        for c in cs.COMPONENTS:
            sid = 'cmp-' + c.key
            self.assertIn(sid, p.ids, 'missing section %s' % sid)
            self.assertIn('%s-title' % sid, p.ids)
            self.assertTrue(c.defined and c.note)
        self.assertEqual(len(p.ids), len(set(p.ids)), 'duplicate element ids')
        self.assertEqual(html.count('class="cs-sc"'), len(cs.COMPONENTS))
        self.assertIn(cs.SPEC_URL + '#buttons', html)

    def test_theme_and_density_switcher_present_and_client_side(self):
        html = self._get(self.superuser).content.decode()
        for ident in ('csTheme', 'csLight', 'csDark', 'csCompact', 'csComfortable', 'csReset'):
            self.assertIn('id="%s"' % ident, html)
        for key, _label, _dark in cs.THEMES:
            self.assertIn('value="%s"' % key, html)
        js = (Path(django_settings.BASE_DIR) / 'static/js/component_showcase.js').read_text()
        for needle in ('data-theme', 'data-bs-theme', 'data-density'):
            self.assertIn(needle, js)
        for forbidden in ('fetch(', 'XMLHttpRequest', 'localStorage', 'sendBeacon', '$.ajax'):
            self.assertNotIn(forbidden, js)

    def test_no_form_posts_anywhere(self):
        p = _Collect()
        p.feed(self._get(self.superuser).content.decode())
        demo = [f for f in p.forms if 'data-demo-form' in f]
        self.assertGreaterEqual(len(demo), 5)
        for f in p.forms:
            # Forms of the shell (sign-out, language, search) are not part of the
            # page content; every form the showcase draws is a marked demo form.
            if 'data-demo-form' not in f:
                continue
            self.assertFalse(f.get('action'), f)
            self.assertEqual(f.get('method'), 'dialog', f)

    def test_demo_content_has_no_forms_outside_demo_forms(self):
        html = self._get(self.superuser).content.decode()
        main = html.split('id="main-content"', 1)[1].split('</main>', 1)[0]
        p = _Collect()
        p.feed(main)
        for f in p.forms:
            self.assertIn('data-demo-form', f)

    def test_no_outbound_requests(self):
        html = self._get(self.superuser).content.decode()
        main = html.split('id="main-content"', 1)[1].split('</main>', 1)[0]
        p = _Collect()
        p.feed(main)
        for tag, url in p.resources:
            self.assertFalse(re.match(r'(?i)(https?:)?//', url), (tag, url))
        # and the page's own assets are local
        self.assertIn('/static/js/component_showcase.js', html)
        self.assertIn('/static/css/component_showcase.css', html)
        css = (Path(django_settings.BASE_DIR) / 'static/css/component_showcase.css').read_text()
        self.assertNotIn('url(', css)
        self.assertNotIn('@import', css)

    def test_view_module_makes_no_writes_or_calls(self):
        src = Path(importlib.import_module('core.showcase_views').__file__).read_text()
        for needle in ('.save(', '.create(', 'requests.', 'urllib', 'httpx', 'objects'):
            self.assertNotIn(needle, src)

    def test_navigation_entry_is_superuser_only(self):
        # The page itself opens for MSP staff; the menu entry is for
        # superusers so a technician's Administration section is unchanged.
        tab = None
        for s in SECTIONS:
            for t in s.tabs:
                if t.url_name == 'core:component_showcase':
                    tab, section = t, s
        self.assertIsNotNone(tab)
        self.assertEqual(section.key, 'settings_system')
        self.assertTrue(tab.gate({'user': self.superuser}))
        self.assertFalse(tab.gate({'user': self.customer, 'is_staff_user': True}))
        self.assertFalse(tab.gate({'user': self.customer, 'is_staff_user': False}))

    @skipUnless(importlib.util.find_spec('core.a11y_lint'),
                'core/a11y_lint.py (113.4) is not on this branch yet: accessibility check skipped')
    def test_passes_the_accessibility_checker(self):
        lint = importlib.import_module('core.a11y_lint')
        run = getattr(lint, 'check_html', None) or getattr(lint, 'lint_html', None)
        self.assertIsNotNone(run, 'a11y_lint exposes no check_html/lint_html; adapt this test')
        html = self._get(self.superuser).content.decode()
        findings = [f for f in run(html)
                    if 'cs-flag' not in str(f)]  # the one deliberate unnamed-button anti-pattern
        self.assertEqual(findings, [])
