"""
Separate customer portal sign-in (/portal/login/), surface classification,
the optional portal host name, and customer-facing links.
"""
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core import portal_surface

# Real middleware stack except the HTTPS redirect (and, where noted, 2FA).
NO_2FA_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m
]
STAFF_LOGIN = '/account/login/'
PORTAL_LOGIN = '/portal/login/'
PASSWORD = 'Correct-Horse-Battery-42'


def _setup_world(test):
    from accounts.models import Membership, Role
    from core.models import Organization, SystemSetting
    from psa.models import ClientPSASettings
    from psa.tests._base import _make_msp_tech

    s = SystemSetting.get_settings()
    s.psa_enabled = True
    s.require_2fa = False
    s.save()
    from core import security_policy
    security_policy.invalidate()
    test.org = Organization.objects.create(name='PortalCo', slug='portalco-login')
    ClientPSASettings.objects.update_or_create(organization=test.org, defaults={'portal_enabled': True})
    test.customer = User.objects.create_user('customer@example.com', 'customer@example.com', PASSWORD)
    Membership.objects.create(user=test.customer, organization=test.org,
                              role=Role.READONLY, is_active=True)
    test.tech = User.objects.create_user('tech', 'tech@msp.example', PASSWORD)
    _make_msp_tech(test.tech)
    test.admin = User.objects.create_superuser('root', 'root@msp.example', PASSWORD)
    # A customer user of a customer without the portal: keeps the staff sign-in.
    test.backend_customer = User.objects.create_user('docs-only', 'd@example.com', PASSWORD)
    other = Organization.objects.create(name='NoPortalCo', slug='noportal-login')
    Membership.objects.create(user=test.backend_customer, organization=other,
                              role=Role.READONLY, is_active=True)


def _post_login(client, url, username, password, prefix):
    return client.post(url, {
        f'{prefix}-current_step': 'auth',
        'auth-username': username,
        'auth-password': password,
    })


@override_settings(MIDDLEWARE=NO_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SignInSurfaceTests(TestCase):

    def setUp(self):
        cache.clear()
        _setup_world(self)

    def test_portal_login_page_renders_with_portal_theme(self):
        r = self.client.get(PORTAL_LOGIN)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'css/portal.css')
        self.assertContains(r, 'Sign in to your support portal')
        self.assertNotContains(r, 'Secure, Self-Hosted IT Documentation')

    def test_portal_login_accepts_customer(self):
        r = _post_login(self.client, PORTAL_LOGIN, 'customer@example.com', PASSWORD, 'portal_login')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/portal/')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.customer.pk)
        self.assertEqual(self.client.session['_auth_surface'], 'portal')

    def test_portal_login_refuses_staff_and_superuser_like_a_wrong_password(self):
        wrong = _post_login(self.client, PORTAL_LOGIN, 'tech', 'nope-nope-nope', 'portal_login')
        for user in ('tech', 'root'):
            r = _post_login(self.client, PORTAL_LOGIN, user, PASSWORD, 'portal_login')
            self.assertEqual(r.status_code, 200, user)
            self.assertNotIn('_auth_user_id', self.client.session)
            self.assertContains(r, 'staff accounts use the staff sign-in page')
            # Same error text as a wrong password: no "right password" oracle.
            self.assertEqual(r.context['form'].errors, wrong.context['form'].errors)

    def test_portal_login_ignores_next_to_backend(self):
        r = self.client.post(PORTAL_LOGIN + '?next=/core/dashboard/', {
            'portal_login-current_step': 'auth',
            'auth-username': 'customer@example.com', 'auth-password': PASSWORD,
        })
        self.assertEqual(r['Location'], '/portal/')
        r2 = self.client.get(PORTAL_LOGIN + '?next=/portal/kb/')
        self.assertEqual(r2.status_code, 302)  # already signed in
        self.assertEqual(r2['Location'], '/portal/kb/')

    def test_staff_login_refuses_customer_with_pointer_to_portal(self):
        r = _post_login(self.client, STAFF_LOGIN, 'customer@example.com', PASSWORD, 'login_view')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(r, 'Customer accounts sign in at the customer portal')
        self.assertContains(r, 'http://testserver/portal/login/')

    def test_staff_login_still_accepts_staff_and_backend_customers(self):
        for user in ('tech', 'root', 'docs-only'):
            self.client.logout()
            r = _post_login(self.client, STAFF_LOGIN, user, PASSWORD, 'login_view')
            self.assertEqual(r.status_code, 302, user)
            self.assertIn('_auth_user_id', self.client.session, user)

    def test_staff_login_page_links_to_portal(self):
        self.assertContains(self.client.get(STAFF_LOGIN), PORTAL_LOGIN)

    def test_customer_on_backend_is_sent_to_portal(self):
        self.client.force_login(self.customer)
        for path in ('/core/dashboard/', '/psa/tickets/', '/admin/', '/account/two_factor/setup/'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertEqual(r['Location'], '/portal/', path)
        # Portal pages still work.
        self.assertEqual(self.client.get('/portal/kb/').status_code, 200)

    def test_backend_customer_without_portal_is_not_redirected(self):
        self.client.force_login(self.backend_customer)
        r = self.client.get('/core/dashboard/')
        self.assertNotEqual(r.get('Location'), '/portal/')

    def test_anonymous_portal_page_goes_to_portal_login(self):
        r = self.client.get('/portal/kb/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(PORTAL_LOGIN), r['Location'])
        # Agreements use login_required: rewritten to the portal sign-in too.
        r = self.client.get('/portal/agreements/')
        self.assertTrue(r['Location'].startswith(PORTAL_LOGIN), r['Location'])
        # A backend page still goes to the staff sign-in.
        r = self.client.get('/core/dashboard/')
        self.assertTrue(r['Location'].startswith(STAFF_LOGIN), r['Location'])

    def test_portal_logout(self):
        self.client.force_login(self.customer)
        r = self.client.post('/portal/logout/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], PORTAL_LOGIN)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_portal_2fa_pages_refuse_staff(self):
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get('/portal/account/two-factor/setup/').status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorAndLockoutTests(TestCase):
    """Full middleware stack, including 2FA enforcement and axes."""

    def setUp(self):
        cache.clear()
        _setup_world(self)

    def test_required_2fa_sends_portal_user_to_portal_enrolment(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.require_2fa = True
        s.save()
        from core import security_policy
        security_policy.invalidate()
        self.client.force_login(self.customer)
        r = self.client.get('/portal/kb/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/portal/account/two-factor/setup/')
        r = self.client.get('/portal/account/two-factor/setup/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'css/portal.css')
        r = self.client.post('/portal/account/two-factor/setup/', {'portal_setup-current_step': 'welcome'})
        if r.context['wizard']['steps'].current == 'method':
            r = self.client.post('/portal/account/two-factor/setup/', {
                'portal_setup-current_step': 'method', 'method-method': 'generator'})
        self.assertEqual(r.context['wizard']['steps'].current, 'generator')
        self.assertContains(r, '/portal/account/two-factor/qrcode/')
        self.assertEqual(self.client.get('/portal/account/two-factor/qrcode/').status_code, 200)

    def test_portal_user_with_device_must_pass_token_step(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.create(user=self.customer, name='default', confirmed=True)
        r = _post_login(self.client, PORTAL_LOGIN, 'customer@example.com', PASSWORD, 'portal_login')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['wizard']['steps'].current, 'token')
        self.assertNotIn('_auth_user_id', self.client.session)
        # An unverified session (password only) is ended and sent to the
        # portal sign-in, not the staff one.
        self.client.force_login(self.customer)
        r = self.client.get('/portal/kb/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(PORTAL_LOGIN), r['Location'])

    def test_staff_2fa_still_enforced_on_staff_login(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.create(user=self.tech, name='default', confirmed=True)
        r = _post_login(self.client, STAFF_LOGIN, 'tech', PASSWORD, 'login_view')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['wizard']['steps'].current, 'token')

    def test_lockout_on_portal_login(self):
        from core import security_policy
        limit = security_policy.lockout_failure_limit()
        r = None
        for _ in range(limit + 1):
            r = _post_login(self.client, PORTAL_LOGIN, 'customer@example.com', 'wrong-password', 'portal_login')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/portal/locked/')
        # Locked even with the right password now.
        r = _post_login(self.client, PORTAL_LOGIN, 'customer@example.com', PASSWORD, 'portal_login')
        self.assertEqual(r['Location'], '/portal/locked/')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(self.client.get('/portal/locked/'), 'Too many sign-in attempts', status_code=403)

    def test_lockout_on_staff_login_unchanged(self):
        from core import security_policy
        limit = security_policy.lockout_failure_limit()
        r = None
        for _ in range(limit + 1):
            r = _post_login(self.client, STAFF_LOGIN, 'tech', 'wrong-password', 'login_view')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('/accounts/locked/'), r['Location'])


class SurfaceClassificationTests(TestCase):

    def test_portal_paths(self):
        for path in ('/portal/', '/portal/login/', '/portal/kb/', '/portal/t/T-1/',
                     '/portal/password-reset/', '/portal/account/two-factor/setup/',
                     '/portal/quote/abc/sign/', '/portal/agreements/reminders/unsubscribe/x/'):
            self.assertEqual(portal_surface.classify_path(path), 'portal', path)

    def test_public_customer_links(self):
        for path in ('/core/secret/tok123/', '/psa/secure-reply/tok/', '/psa/csat/tok/',
                     '/status/p/tok/', '/security/digest/unsubscribe/tok/',
                     '/accounts/portal/set-password/MQ/abc-123/'):
            self.assertEqual(portal_surface.classify_path(path), 'portal', path)

    def test_backend_paths(self):
        for path in ('/', '/account/login/', '/core/dashboard/', '/psa/tickets/', '/admin/',
                     '/api/mobile/v1/version/', '/core/secure-notes/', '/status/',
                     '/accounts/locked/', '/account/two_factor/setup/'):
            self.assertEqual(portal_surface.classify_path(path), 'staff', path)

    def test_unknown_paths_are_staff(self):
        for path in ('/nope/', '/portalx/', '/wp-login.php', '/core/secretx/'):
            self.assertEqual(portal_surface.classify_path(path), 'staff', path)

    def test_shared_paths(self):
        for path in ('/static/css/portal.css', '/media/branding/logo.png', '/csp-report/', '/favicon.ico'):
            self.assertEqual(portal_surface.classify_path(path), 'shared', path)

    def test_shared_paths_judged_by_user(self):
        from django.contrib.auth.models import AnonymousUser
        rf = RequestFactory()
        req = rf.get('/media/x.png')
        req.user = AnonymousUser()
        self.assertEqual(portal_surface.request_surface(req), 'portal')
        req.user = User.objects.create_superuser('su', 'su@x.com', 'pw')
        self.assertEqual(portal_surface.request_surface(req), 'staff')

    def test_client_input_does_not_change_surface(self):
        rf = RequestFactory()
        from django.contrib.auth.models import AnonymousUser
        req = rf.get('/core/dashboard/?surface=portal', HTTP_X_SURFACE='portal',
                     HTTP_REFERER='https://x/portal/')
        req.user = AnonymousUser()
        self.assertEqual(portal_surface.request_surface(req), 'staff')


@override_settings(MIDDLEWARE=NO_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['staff.example.com', 'portal.example.com', 'testserver'])
class PortalHostnameTests(TestCase):

    def setUp(self):
        cache.clear()
        _setup_world(self)
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.portal_hostname = 'portal.example.com'
        s.site_url = 'https://staff.example.com'
        s.save()

    def get(self, path, host, **kw):
        return self.client.get(path, HTTP_HOST=host, **kw)

    def test_staff_paths_404_on_portal_host(self):
        for path in ('/account/login/', '/core/dashboard/', '/admin/', '/api/mobile/v1/version/', '/nope/'):
            self.assertEqual(self.get(path, 'portal.example.com').status_code, 404, path)

    def test_portal_host_serves_portal(self):
        self.assertEqual(self.get('/portal/login/', 'portal.example.com').status_code, 200)
        r = self.get('/', 'portal.example.com')
        self.assertEqual(r['Location'], '/portal/')
        self.assertEqual(self.get('/portal/password-reset/', 'portal.example.com').status_code, 200)
        # Customer links are served there (this token is unknown, so the
        # view's own answer, not the host's "not part of the portal" page).
        self.assertNotContains(self.get('/core/secret/unknown-token/', 'portal.example.com'),
                               'not part of the customer portal', status_code=404)

    def test_portal_paths_on_staff_host_redirect(self):
        r = self.get('/portal/login/?next=/portal/kb/', 'staff.example.com')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://portal.example.com/portal/login/?next=/portal/kb/')
        r = self.get('/psa/csat/abc/', 'staff.example.com')
        self.assertEqual(r['Location'], 'https://portal.example.com/psa/csat/abc/')

    def test_staff_host_keeps_backend(self):
        self.assertEqual(self.get('/account/login/', 'staff.example.com').status_code, 200)

    def test_customer_on_staff_host_sent_to_portal_host(self):
        self.client.force_login(self.customer)
        r = self.get('/core/dashboard/', 'staff.example.com')
        self.assertEqual(r['Location'], 'https://portal.example.com/portal/')

    def test_staff_login_points_to_portal_host(self):
        r = self.client.post(STAFF_LOGIN, {
            'login_view-current_step': 'auth',
            'auth-username': 'customer@example.com', 'auth-password': PASSWORD,
        }, HTTP_HOST='staff.example.com')
        self.assertContains(r, 'https://portal.example.com/portal/login/')

    def test_unset_hostname_changes_nothing(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.portal_hostname = ''
        s.save()
        self.assertEqual(self.get('/portal/login/', 'staff.example.com').status_code, 200)
        self.assertEqual(self.get('/account/login/', 'staff.example.com').status_code, 200)

    def test_hostname_validation(self):
        rf = RequestFactory()
        req = rf.get('/', HTTP_HOST='staff.example.com')
        self.assertEqual(portal_surface.validate_portal_hostname('', req), ('', ''))
        self.assertEqual(portal_surface.validate_portal_hostname('Portal.Example.com', req)[1], '')
        self.assertTrue(portal_surface.validate_portal_hostname('staff.example.com', req)[1])
        self.assertTrue(portal_surface.validate_portal_hostname('not a host', req)[1])
        self.assertIn('ALLOWED_HOSTS', portal_surface.validate_portal_hostname('other.example.org', req)[1])

    @override_settings(PORTAL_HOSTNAME='env-portal.example.com',
                       ALLOWED_HOSTS=['env-portal.example.com', 'staff.example.com'])
    def test_env_overrides_setting(self):
        self.assertEqual(portal_surface.portal_hostname(), 'env-portal.example.com')
        self.assertEqual(self.get('/core/dashboard/', 'env-portal.example.com').status_code, 404)

    def _portal_settings_post(self, host_name):
        # The host name is edited on Settings → Customer portal (it moved
        # off Settings → General); the other fields are that form's defaults.
        return self.client.post('/core/settings/portal/', {
            'portal_hostname': host_name, 'portal_login_background': 'none',
            'portal_navigation': 'top', 'portal_content_width': 'standard',
            'portal_default_theme': 'system',
        }, HTTP_HOST='staff.example.com')

    def test_settings_page_saves_hostname(self):
        self.client.force_login(self.admin)
        r = self._portal_settings_post('staff.example.com')
        self.assertEqual(r.status_code, 200)  # form shown again with the error
        self.assertContains(r, 'must differ from the host staff use')
        from core.models import SystemSetting
        # Refused: it is the staff host.
        self.assertEqual(SystemSetting.get_settings().portal_hostname, 'portal.example.com')
        r = self._portal_settings_post('')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SystemSetting.get_settings().portal_hostname, '')

    def test_general_settings_no_longer_change_hostname(self):
        self.client.force_login(self.admin)
        r = self.client.post('/core/settings/general/', {
            'site_name': 'MSP', 'site_url': 'https://staff.example.com',
            'default_timezone': 'UTC', 'portal_hostname': '',
        }, HTTP_HOST='staff.example.com')
        self.assertEqual(r.status_code, 302)
        from core.models import SystemSetting
        self.assertEqual(SystemSetting.get_settings().portal_hostname, 'portal.example.com')


@override_settings(MIDDLEWARE=NO_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['staff.example.com', 'portal.example.com', 'testserver'])
class CustomerLinkTests(TestCase):

    def setUp(self):
        cache.clear()
        _setup_world(self)

    def _invite(self, host='testserver'):
        from psa.tests._base import _make_msp_tech  # noqa: F401
        self.client.force_login(self.admin)
        return self.client.post(reverse('psa:portal_invite', args=[self.org.pk]), {
            'email': 'new@example.com', 'full_name': 'New Person',
        }, HTTP_HOST=host)

    def test_invite_email_links_to_portal(self):
        self._invite()
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('http://testserver/portal/set-password/', body)
        self.assertIn('http://testserver/portal/login/', body)
        self.assertNotIn('/account/login/', body)
        self.assertNotIn('/accounts/portal/', body)

    def test_invite_email_uses_portal_host(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.portal_hostname = 'portal.example.com'
        s.site_url = 'https://staff.example.com'
        s.save()
        self._invite(host='staff.example.com')
        body = mail.outbox[0].body
        self.assertIn('https://portal.example.com/portal/set-password/', body)
        self.assertIn('https://portal.example.com/portal/login/', body)

    def test_invite_link_sets_password_on_portal(self):
        self._invite()
        import re
        link = re.search(r'http://testserver(/portal/set-password/\S+)', mail.outbox[0].body).group(1)
        self.client.logout()
        r = self.client.get(link)
        self.assertContains(r, 'css/portal.css')
        r = self.client.post(link, {'password1': 'a-long-password-1', 'password2': 'a-long-password-1'})
        self.assertEqual(r['Location'], '/portal/')

    def test_old_invite_link_redirects(self):
        r = self.client.get('/accounts/portal/set-password/MQ/abc-123/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'http://testserver/portal/set-password/MQ/abc-123/')

    def test_invite_link_cannot_reset_staff_password(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(self.tech.pk))
        token = default_token_generator.make_token(self.tech)
        r = self.client.post(f'/portal/set-password/{uid}/{token}/',
                             {'password1': 'x' * 14, 'password2': 'x' * 14})
        self.assertContains(r, 'Link expired or invalid')
        self.tech.refresh_from_db()
        self.assertTrue(self.tech.check_password(PASSWORD))

    def test_password_reset_email_links_to_portal_only_for_portal_users(self):
        r = self.client.post('/portal/password-reset/', {'email': 'customer@example.com'})
        self.assertEqual(r['Location'], '/portal/password-reset/sent/')
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('http://testserver/portal/reset/', body)
        self.assertIn('http://testserver/portal/login/', body)
        # Staff address: same answer, no email.
        r = self.client.post('/portal/password-reset/', {'email': 'tech@msp.example'})
        self.assertEqual(r['Location'], '/portal/password-reset/sent/')
        self.assertEqual(len(mail.outbox), 1)

    def test_password_reset_completes(self):
        import re
        self.client.post('/portal/password-reset/', {'email': 'customer@example.com'})
        path = re.search(r'http://testserver(/portal/reset/\S+)', mail.outbox[0].body).group(1)
        r = self.client.get(path)
        self.assertEqual(r.status_code, 302)  # to the set-password form URL
        r = self.client.post(r['Location'], {'new_password1': 'N3w-Strong-Pass-99!',
                                             'new_password2': 'N3w-Strong-Pass-99!'})
        self.assertEqual(r['Location'], '/portal/reset/done/')
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password('N3w-Strong-Pass-99!'))

    def test_customer_link_helpers_follow_portal_host(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.site_url = 'https://staff.example.com'
        s.save()
        self.assertEqual(portal_surface.portal_site_url(), 'https://staff.example.com')
        s.portal_hostname = 'portal.example.com'
        s.save()
        self.assertEqual(portal_surface.portal_site_url(), 'https://portal.example.com')
        self.assertEqual(portal_surface.portal_absolute_url('/psa/csat/x/'),
                         'https://portal.example.com/psa/csat/x/')


@override_settings(MIDDLEWARE=NO_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalPasswordChangeTests(TestCase):
    URL = '/portal/account/password/'
    NEW = 'Brand-New-Passw0rd!'

    def setUp(self):
        cache.clear()
        _setup_world(self)

    def _post(self, client, old=PASSWORD, new1=None, new2=None):
        new1 = new1 or self.NEW
        return client.post(self.URL, {'old_password': old, 'new_password1': new1,
                                      'new_password2': new2 or new1})

    def test_page_renders_in_portal_theme_and_is_linked(self):
        self.client.force_login(self.customer)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'css/portal.css')
        self.assertContains(r, 'name="old_password"')
        self.assertContains(self.client.get('/portal/kb/'), self.URL)

    def test_success_keeps_this_session_ends_others_and_tokens(self):
        from api_mobile.models import MobileAuthToken
        from audit.models import AuditLog
        from django.test import Client
        other = Client()
        other.force_login(self.customer)
        _raw, token = MobileAuthToken.issue(self.customer)
        self.client.force_login(self.customer)

        r = self._post(self.client)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], self.URL)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(self.NEW))
        # This browser stays signed in; the other session is gone.
        self.assertEqual(self.client.get('/portal/kb/').status_code, 200)
        r = other.get('/portal/kb/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(PORTAL_LOGIN))
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        # Audited without password values.
        entry = AuditLog.objects.filter(extra_data__op='portal_password_change').get()
        self.assertEqual(entry.user, self.customer)
        self.assertEqual(entry.extra_data['mobile_sessions_revoked'], 1)
        dump = f'{entry.description} {entry.extra_data}'
        self.assertNotIn(PASSWORD, dump)
        self.assertNotIn(self.NEW, dump)
        # Notification email: no secrets, links to the portal reset.
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('/portal/password-reset/', body)
        self.assertNotIn(self.NEW, body)
        self.assertNotIn(PASSWORD, body)

    def test_wrong_current_password(self):
        self.client.force_login(self.customer)
        r = self._post(self.client, old='not-my-password')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['form'].errors.get('old_password'))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(PASSWORD))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_policy_applies(self):
        self.client.force_login(self.customer)
        for weak in ('short', 'password12345', '1234567890123'):
            r = self._post(self.client, new1=weak)
            self.assertEqual(r.status_code, 200, weak)
            self.assertTrue(r.context['form'].errors.get('new_password2'), weak)
        r = self._post(self.client, new1=self.NEW, new2=self.NEW + 'x')
        self.assertTrue(r.context['form'].errors.get('new_password2'))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(PASSWORD))

    def test_staff_refused(self):
        for user in (self.tech, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.URL).status_code, 404)
            r = self._post(self.client)
            self.assertEqual(r.status_code, 404)
            user.refresh_from_db()
            self.assertTrue(user.check_password(PASSWORD))

    def test_signed_out_goes_to_portal_login(self):
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(PORTAL_LOGIN + '?next='), r['Location'])

    def test_get_never_changes(self):
        self.client.force_login(self.customer)
        self.client.get(self.URL, {'old_password': PASSWORD, 'new_password1': self.NEW,
                                   'new_password2': self.NEW})
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(PASSWORD))

    def test_rate_limited(self):
        self.client.force_login(self.customer)
        for _ in range(10):
            self._post(self.client, old='wrong-wrong-wrong')
        r = self._post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Too many attempts', str(r.context['form'].non_field_errors()))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(PASSWORD))

    @override_settings(MIDDLEWARE=NO_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_csrf_required(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.customer)
        r = self._post(c)
        self.assertEqual(r.status_code, 403)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password(PASSWORD))
