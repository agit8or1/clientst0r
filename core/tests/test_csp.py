"""Content-Security-Policy is sent on every HTML page.

The CSP settings existed for years but nothing sent them. Pinned here:
  * HTML responses carry a policy (Report-Only by default, enforcing when
    CSP_REPORT_ONLY=False), non-HTML responses don't;
  * every inline <script> in a rendered page carries the request's nonce and
    the header lists that same nonce; script-src has no 'unsafe-inline';
  * protected downloads keep their own stricter sandbox policy untouched;
  * same-origin framing (PDF preview) gets frame-ancestors 'self';
  * the violation report endpoint logs, is rate limited and size capped.
"""
import json
import re
import tempfile
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.csp_middleware import ContentSecurityPolicyMiddleware

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

RO = 'Content-Security-Policy-Report-Only'
ENFORCE = 'Content-Security-Policy'


def _directives(value):
    out = {}
    for part in value.split(';'):
        bits = part.strip().split()
        if bits:
            out[bits[0]] = bits[1:]
    return out


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CSPHeaderOnPagesTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'csp_su', 'csp@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _dashboard(self):
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        return r

    def test_report_only_header_by_default(self):
        r = self._dashboard()
        self.assertIn(RO, r)
        self.assertNotIn(ENFORCE, r)
        d = _directives(r[RO])
        self.assertEqual(d['default-src'], ["'self'"])
        self.assertEqual(d['object-src'], ["'none'"])
        self.assertEqual(d['frame-ancestors'], ["'none'"])
        self.assertNotIn("'unsafe-inline'", d['script-src'])
        self.assertEqual(d['report-uri'], ['/csp-report/'])

    @override_settings(CSP_REPORT_ONLY=False)
    def test_enforcing_when_report_only_off(self):
        r = self._dashboard()
        self.assertIn(ENFORCE, r)
        self.assertNotIn(RO, r)

    @override_settings(CSP_ENABLED=False)
    def test_disabled_sends_nothing(self):
        r = self._dashboard()
        self.assertNotIn(ENFORCE, r)
        self.assertNotIn(RO, r)

    def test_inline_scripts_carry_the_header_nonce(self):
        r = self._dashboard()
        html = r.content.decode()
        nonce = re.search(r"'nonce-([^']+)'", r[RO]).group(1)
        self.assertGreaterEqual(len(nonce), 16)

        inline = [tag for tag in re.findall(r'<script\b[^>]*>', html)
                  if 'src=' not in tag and 'application/json' not in tag]
        self.assertTrue(inline, 'dashboard should have inline scripts')
        for tag in inline:
            self.assertIn(f'nonce="{nonce}"', tag)

    def test_nonce_differs_per_request(self):
        n1 = re.search(r"'nonce-([^']+)'", self._dashboard()[RO]).group(1)
        n2 = re.search(r"'nonce-([^']+)'", self._dashboard()[RO]).group(1)
        self.assertNotEqual(n1, n2)

    def test_login_page_gets_header_too(self):
        self.client.logout()
        r = self.client.get('/account/login/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(RO, r)

    def test_json_responses_get_no_csp(self):
        r = self.client.get('/health/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(RO, r)
        self.assertNotIn(ENFORCE, r)


class CSPMiddlewareUnitTests(TestCase):

    def setUp(self):
        self.rf = RequestFactory()

    def _run(self, response):
        return ContentSecurityPolicyMiddleware(lambda request: response)(self.rf.get('/x/'))

    def test_existing_strict_policy_left_alone(self):
        strict = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        resp = HttpResponse('<html></html>', content_type='text/html')
        resp[ENFORCE] = strict
        out = self._run(resp)
        self.assertEqual(out[ENFORCE], strict)
        self.assertNotIn(RO, out)

    def test_download_keeps_sandbox_policy(self):
        from core.media_views import stream_file
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evil.html'
            path.write_text('<script>alert(1)</script>')
            mw = ContentSecurityPolicyMiddleware(
                lambda request: stream_file(request, path, 'files/evil.html'))
            out = mw(self.rf.get('/media/files/evil.html'))
            out.close()
        self.assertIn('sandbox', out[ENFORCE])
        self.assertIn("default-src 'none'", out[ENFORCE])
        self.assertNotIn(RO, out)

    def test_sameorigin_framing_gets_frame_ancestors_self(self):
        resp = HttpResponse('<html></html>', content_type='text/html')
        resp['X-Frame-Options'] = 'SAMEORIGIN'
        out = self._run(resp)
        self.assertEqual(_directives(out[RO])['frame-ancestors'], ["'self'"])

    def test_no_nonce_in_header_when_page_has_no_inline_script(self):
        out = self._run(HttpResponse('<html></html>', content_type='text/html'))
        self.assertNotIn("'nonce-", out[RO])

    def test_non_html_untouched(self):
        out = self._run(JsonResponse({'ok': True}))
        self.assertNotIn(RO, out)

    @override_settings(CSP_REPORT_URI='')
    def test_report_uri_optional(self):
        out = self._run(HttpResponse('<html></html>', content_type='text/html'))
        self.assertNotIn('report-uri', out[RO])

    def test_security_headers_keep_sameorigin(self):
        from core.security_headers_middleware import SecurityHeadersMiddleware

        def view(request):
            resp = HttpResponse('x')
            resp['X-Frame-Options'] = 'SAMEORIGIN'
            return resp
        out = SecurityHeadersMiddleware(view)(self.rf.get('/'))
        self.assertEqual(out['X-Frame-Options'], 'SAMEORIGIN')
        out = SecurityHeadersMiddleware(lambda r: HttpResponse('x'))(self.rf.get('/'))
        self.assertEqual(out['X-Frame-Options'], 'DENY')


@override_settings(SECURE_SSL_REDIRECT=False, CSP_REPORT_RATE_LIMIT=3)
class CSPReportEndpointTests(TestCase):

    def setUp(self):
        cache.clear()

    def _post(self, payload, content_type='application/csp-report'):
        return self.client.post('/csp-report/', data=json.dumps(payload), content_type=content_type)

    def test_logs_legacy_report(self):
        with self.assertLogs('security.csp', level='WARNING') as logs:
            r = self._post({'csp-report': {
                'document-uri': 'https://app/x/', 'violated-directive': 'script-src-elem',
                'blocked-uri': 'inline', 'line-number': 12}})
        self.assertEqual(r.status_code, 204)
        self.assertIn("blocked-uri='inline'", logs.output[0])

    def test_logs_reporting_api_report(self):
        with self.assertLogs('security.csp', level='WARNING') as logs:
            r = self._post([{'type': 'csp-violation', 'body': {
                'documentURL': 'https://app/y/', 'effectiveDirective': 'img-src',
                'blockedURL': 'http://evil/'}}], content_type='application/reports+json')
        self.assertEqual(r.status_code, 204)
        self.assertIn("effective-directive='img-src'", logs.output[0])

    def test_rate_limited(self):
        body = {'csp-report': {'blocked-uri': 'inline'}}
        with self.assertLogs('security.csp', level='WARNING'):
            codes = [self._post(body).status_code for _ in range(5)]
        self.assertEqual(codes[:3], [204, 204, 204])
        self.assertEqual(codes[3:], [429, 429])

    def test_rejects_garbage_and_large_bodies(self):
        self.assertEqual(self.client.post('/csp-report/', data='nope', content_type='application/json').status_code, 400)
        big = {'csp-report': {'blocked-uri': 'x' * 20000}}
        self.assertEqual(self._post(big).status_code, 413)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get('/csp-report/').status_code, 405)
