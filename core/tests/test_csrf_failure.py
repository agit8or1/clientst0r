"""v3.17.624 — CSRF failures: a repeated sign-in submit after a successful
sign-in continues to `next`; everything else gets a "form expired" page."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CSRFFailureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('csrfu', password='pw')

    def _signed_in(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_signed_in_login_resubmit_continues_to_next(self):
        r = self._signed_in().post('/account/login/?next=/core/settings/updates/',
                                   {'login_view-current_step': 'token'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/core/settings/updates/')

    def test_offsite_next_ignored(self):
        r = self._signed_in().post('/account/login/?next=https://evil.example/',
                                   {'login_view-current_step': 'auth'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('evil.example', r['Location'])

    def test_anonymous_login_gets_expired_page(self):
        r = Client(enforce_csrf_checks=True).post('/account/login/?next=/core/', {'x': '1'})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'This form expired', status_code=403)
        self.assertContains(r, 'href="/account/login/?next=/core/"', status_code=403)

    def test_other_pages_link_back_only_to_same_site(self):
        c = self._signed_in()
        r = c.post('/core/favorites/', {}, HTTP_REFERER='https://evil.example/x')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'href="/"', status_code=403)
        r = c.post('/core/favorites/', {}, HTTP_REFERER='http://testserver/assets/')
        self.assertContains(r, 'href="http://testserver/assets/"', status_code=403)
