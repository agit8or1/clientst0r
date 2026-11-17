"""core.safe_redirect: redirect targets taken from the request stay on this site
(code-scanning py/url-redirection and Semgrep open-redirect, v3.17.694)."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.safe_redirect import safe_next, safe_post_next, safe_referer

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

OFFSITE = [
    'https://evil.example/',
    'http://evil.example/x',
    '//evil.example/',
    '/\\evil.example/',
    '\\\\evil.example/',
    '/\\/evil.example/',
    'javascript:alert(1)',
    'data:text/html,x',
    ' //evil.example/',
    '/ok/\n',
    '/ok/\x00',
    'https://testserver.evil.example/',
    'https:evil.example',
    'https:///evil.example',
]


@override_settings(ALLOWED_HOSTS=['testserver'])
class SafeNextTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_same_site_targets_are_kept(self):
        req = self.rf.get('/')
        for url in ['/core/dashboard/', '/psa/tickets/?status=open&q=a%20b', '/x/#frag',
                    'http://testserver/psa/', 'relative/path']:
            self.assertEqual(safe_next(req, url, '/fallback/'), url, url)

    def test_offsite_and_malformed_targets_get_the_fallback(self):
        req = self.rf.get('/')
        for url in OFFSITE:
            self.assertEqual(safe_next(req, url, '/fallback/'), '/fallback/', repr(url))

    def test_non_strings_and_empty_get_the_fallback(self):
        req = self.rf.get('/')
        for value in (None, '', 0, ['/x/'], b'/x/'):
            self.assertEqual(safe_next(req, value, 'app:name'), 'app:name')

    def test_https_request_refuses_a_plain_http_absolute_url(self):
        req = self.rf.get('/', secure=True)
        self.assertEqual(safe_next(req, 'http://testserver/x/', '/f/'), '/f/')
        self.assertEqual(safe_next(req, 'https://testserver/x/', '/f/'), 'https://testserver/x/')

    def test_referer_and_post_next(self):
        req = self.rf.post('/', {'next': '//evil.example/'}, HTTP_REFERER='https://evil.example/')
        self.assertEqual(safe_post_next(req, '/f/'), '/f/')
        self.assertEqual(safe_referer(req, '/f/'), '/f/')
        req = self.rf.post('/', {'next': '/psa/'}, HTTP_REFERER='http://testserver/docs/')
        self.assertEqual(safe_post_next(req, '/f/'), '/psa/')
        self.assertEqual(safe_referer(req, '/f/'), 'http://testserver/docs/')
        self.assertEqual(safe_referer(self.rf.get('/'), '/f/'), '/f/')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SwitchGlobalViewRedirectTests(TestCase):
    """accounts.views.switch_to_global_view honours ?next= and the Referer
    only for this site."""

    def setUp(self):
        self.user = User.objects.create_superuser('redir', 'r@example.com', 'pw')
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def test_same_site_next_is_followed(self):
        r = self.client.get('/accounts/switch-global/', {'next': '/core/settings/'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/core/settings/')

    def test_offsite_next_is_ignored(self):
        for url in ('//evil.example/', '/\\evil.example/', 'https://evil.example/'):
            r = self.client.get('/accounts/switch-global/', {'next': url})
            self.assertEqual(r.status_code, 302)
            self.assertNotIn('evil.example', r['Location'], url)

    def test_offsite_referer_is_ignored(self):
        from core.models import SystemSetting
        st = SystemSetting.get_settings()
        st.stay_on_page_after_org_switch = True
        st.save()
        for ref in ('https://evil.example/core/settings/', 'http://testserver//evil.example/'):
            r = self.client.get('/accounts/switch-global/', HTTP_REFERER=ref)
            self.assertEqual(r.status_code, 302)
            self.assertNotIn('evil.example', r['Location'], ref)
