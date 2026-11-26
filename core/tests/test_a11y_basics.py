"""Accessibility basics, increment 113.4 part A.

Flash message tags and roles; skip link, current-page marker, focus ring and
top bar colours (CSS parsed, contrast computed with the design-token
validator's own function); 404 inside the shell for signed-in users only; 500
static, with no queries and no traceback.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import constants as msg
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import get_resolver

from core.error_pages import server_error
from core.tests._r681_fixture import TEST_MIDDLEWARE
from core.tests.test_theme_contrast import all_themes, theme_vars
from scripts.ux.check_design_tokens import contrast

CSS = Path(settings.BASE_DIR) / 'static' / 'css'
TEMPLATES = Path(settings.BASE_DIR) / 'templates'


def rule(css_text, selector_fragment):
    """Declarations (dict) of the first rule whose selector list contains the fragment."""
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', css_text, flags=re.S)):
        if selector_fragment in [s.strip() for s in m.group(1).split(',')]:
            return dict((k.strip(), v.strip().replace(' !important', ''))
                        for k, v in re.findall(r'([\w-]+)\s*:\s*([^;]+);', m.group(2)))
    raise AssertionError('no rule for ' + selector_fragment)


def blend(fg, bg, alpha):
    ch = lambda i: round(int(bg[i:i + 2], 16) * (1 - alpha) + int(fg[i:i + 2], 16) * alpha)
    return '#%02x%02x%02x' % (ch(1), ch(3), ch(5))


def focus_colour(v):
    return v.get('focus-ring', v.get('link-color', v['primary-color']))


class FlashMessageTests(SimpleTestCase):
    def render(self, level, **kw):
        return render_to_string('includes/_flash_messages.html',
                                {'messages': [Message(level, 'Something happened')], **kw})

    def test_error_maps_to_danger(self):
        self.assertEqual(settings.MESSAGE_TAGS[msg.ERROR], 'danger')
        self.assertEqual(Message(msg.ERROR, 'x').level_tag, 'danger')
        self.assertEqual(Message(msg.SUCCESS, 'x').level_tag, 'success')

    def test_error_and_warning_are_alerts(self):
        for level, cls in ((msg.ERROR, 'alert-danger'), (msg.WARNING, 'alert-warning')):
            html = self.render(level)
            self.assertIn(cls, html)
            self.assertIn('role="alert"', html)
            self.assertNotIn('alert-error', html)

    def test_info_and_success_are_status(self):
        for level, cls in ((msg.INFO, 'alert-info'), (msg.SUCCESS, 'alert-success')):
            html = self.render(level)
            self.assertIn(cls, html)
            self.assertIn('role="status"', html)
            self.assertNotIn('role="alert"', html)

    def test_close_button_has_a_name(self):
        html = self.render(msg.ERROR)
        self.assertRegex(html, r'<button[^>]*btn-close[^>]*aria-label="Close"')
        self.assertNotIn('btn-close', self.render(msg.ERROR, dismissible=0))

    def test_every_base_template_uses_the_shared_partial(self):
        for name in ('base.html', 'portal/base.html', 'portal/public_base.html',
                     'portal/auth/_base.html', 'two_factor/_base_focus.html', 'contracts/sign/base.html'):
            with self.subTest(template=name):
                text = (TEMPLATES / name).read_text()
                self.assertIn('includes/_flash_messages.html', text)
                self.assertNotIn('alert-{{ m.tags', text)
                self.assertNotIn('alert-{{ message.tags', text)

    def test_no_template_builds_alert_class_from_raw_tags(self):
        bad = [str(p.relative_to(TEMPLATES)) for p in TEMPLATES.rglob('*.html')
               if re.search(r'alert-\{\{\s*(m|msg|message)\.tags', p.read_text(errors='ignore'))]
        self.assertEqual(bad, [])

    def test_logo_link_has_a_name(self):
        text = (TEMPLATES / 'base.html').read_text()
        self.assertRegex(text, r'class="navbar-brand"[^>]*aria-label=')


class SkipLinkTests(SimpleTestCase):
    def test_focused_skip_link_is_readable(self):
        css = (CSS / 'mobile.css').read_text()
        focused = rule(css, 'html a.skip-to-main.skip-to-main.skip-to-main:focus')
        self.assertGreaterEqual(contrast(focused['color'], focused['background']), 4.5)
        self.assertIn('!important', re.search(r'html a\.skip-to-main\.skip-to-main\.skip-to-main:focus[^{]*\{[^}]*color[^;]*;', css, re.S).group(0))
        # The ring (outline) and the white edge both separate it from the bar behind it.
        self.assertIn('outline', focused)
        ring = re.search(r'#[0-9a-fA-F]{6}', focused['outline']).group(0)
        self.assertGreaterEqual(contrast(ring, focused['background']), 3)

    def test_skip_link_is_off_screen_until_focused(self):
        css = (CSS / 'mobile.css').read_text()
        self.assertTrue(rule(css, 'html a.skip-to-main.skip-to-main.skip-to-main')['top'].startswith('-'))
        self.assertEqual(rule(css, 'html a.skip-to-main.skip-to-main.skip-to-main:focus')['top'], '8px')


class PaginationTests(SimpleTestCase):
    def test_shared_rule_uses_the_link_pair(self):
        decl = rule((CSS / 'a11y.css').read_text(), 'html .pagination .page-item.active .page-link')
        self.assertIn('var(--link-color', decl['background-color'])
        self.assertIn('var(--surface', decl['color'])

    def test_current_page_in_every_theme(self):
        for name in all_themes():
            v = theme_vars(name)
            fill = v.get('link-color', v['primary-color'])
            text = v['surface']
            with self.subTest(theme=name):
                if name == 'professional':
                    # Keeps its own, older rule; check what it paints.
                    fill, text = v['primary-color'], '#ffffff'
                    self.assertIn('var(--primary-color)',
                                  rule((CSS / 'themes.css').read_text(),
                                       '[data-theme="professional"] .page-item.active .page-link')['background-color'])
                self.assertGreaterEqual(contrast(text, fill), 4.5)
                for neighbour in ('surface', 'surface-hover', 'background'):
                    self.assertGreaterEqual(contrast(fill, v[neighbour]), 3, neighbour)


class FocusAndTopBarTests(SimpleTestCase):
    def test_focus_colour_on_every_theme_surface(self):
        for name in all_themes():
            v = theme_vars(name)
            for surface in ('background', 'surface', 'surface-hover', 'card-bg'):
                with self.subTest(theme=name, surface=surface):
                    self.assertGreaterEqual(contrast(focus_colour(v), v[surface]), 3)

    def test_focus_rule_is_a_solid_outline_from_the_theme_colour(self):
        css = (CSS / 'a11y.css').read_text()
        decl = rule(css, 'html a:focus-visible')
        self.assertTrue(decl['outline'].startswith('2px solid var(--ui-focus'))
        self.assertIn('html .dropdown-item:focus-visible', css)
        self.assertIn('html .app-nav a:focus-visible', css)
        # ui.css feeds --ui-focus from the link colour, never the half-transparent ring.
        self.assertNotIn('rgba(13, 110, 253, 0.5)', (CSS / 'mobile.css').read_text())
        self.assertIn('var(--link-color', (CSS / 'ui.css').read_text().split('--ui-focus: var(--focus-ring')[1][:60])

    def test_top_bar_text_in_every_theme(self):
        for name in all_themes():
            v = theme_vars(name)
            if 'sidebar-bg' not in v:
                continue
            with self.subTest(theme=name):
                bar, text = v['sidebar-bg'], v['sidebar-text']
                self.assertGreaterEqual(contrast(text, bar), 4.5)
                # Active pill (20% white), hover (14%), key cap (12%) on the bar.
                for alpha in (.20, .14, .12):
                    self.assertGreaterEqual(contrast(text, blend('#ffffff', bar, alpha)), 4.5, alpha)
                # Focus ring on the bar is the bar's own text colour.
                self.assertGreaterEqual(contrast(text, bar), 3)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ErrorPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('a11y-admin', 'a@example.test', 'pw-a11y-test-1')

    def signed_in(self):
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_handlers_are_ours(self):
        self.assertEqual(get_resolver().resolve_error_handler(404).__module__, 'core.error_pages')
        self.assertEqual(get_resolver().resolve_error_handler(500).__module__, 'core.error_pages')

    def test_404_inside_shell_for_signed_in_user(self):
        r = self.signed_in().get('/psa/t/NOPE-does-not-exist/')
        self.assertEqual(r.status_code, 404)
        html = r.content.decode()
        self.assertIn('data-not-found', html)
        self.assertIn('app-topbar', html)          # the shell
        self.assertIn('role="search"', html)
        self.assertIn('/core/dashboard/', html)
        self.assertNotIn('Traceback', html)
        # The panel itself never echoes the address (the shell's own chrome may).
        panel = html.split('data-not-found', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('NOPE-does-not-exist', panel)

    def test_404_for_anonymous_has_no_shell(self):
        r = Client().get('/no-such-page-here/')
        self.assertEqual(r.status_code, 404)
        html = r.content.decode()
        self.assertIn('Page not found', html)
        for leak in ('app-topbar', 'app-nav', 'navbar', 'data-not-found', 'no-such-page-here'):
            self.assertNotIn(leak, html)

    def test_500_has_no_queries_and_no_internals(self):
        request = RequestFactory().get('/anything/')
        with self.assertNumQueries(0):
            r = server_error(request)
        self.assertEqual(r.status_code, 500)
        html = r.content.decode()
        self.assertIn('Something went wrong', html)
        self.assertIn('Go to the start page', html)
        for text in ('Traceback', 'File "', 'Exception', '/anything/', 'app-topbar'):
            self.assertNotIn(text, html)

    def test_500_survives_a_missing_template(self):
        r = server_error(RequestFactory().get('/'), template_name='nope.html')
        self.assertEqual(r.status_code, 500)
        self.assertIn('Something went wrong', r.content.decode())

    def test_500_template_extends_only_the_standalone_layout(self):
        text = (TEMPLATES / '500.html').read_text()
        self.assertIn('errors/_standalone.html', text)
        self.assertNotIn('base.html', text)
        self.assertNotRegex(text, r'\{%\s*(url|include|load)\b')
