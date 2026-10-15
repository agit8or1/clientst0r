"""Settings → Security values take effect (core.security_policy).

They used to be saved and never read. Precedence pinned here, for each item:
environment variable when set (operator override, read-only in the UI) >
saved SystemSetting value > built-in default.
"""
import time
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core import security_policy
from core.models import SystemSetting

NO_AXES = [m for m in django_settings.MIDDLEWARE if 'AxesMiddleware' not in m]

# Every env override unset, whatever the machine's .env says.
ENV_UNSET = dict(
    SESSION_IDLE_TIMEOUT=None, SESSION_ABSOLUTE_TIMEOUT=None, REQUIRE_2FA=None,
    PASSWORD_MIN_LENGTH=None, PASSWORD_REQUIRE_SPECIAL=None,
    LOCKOUT_FAILURE_LIMIT=None, LOCKOUT_COOLOFF_HOURS=None,
)


def _save(**fields):
    row = SystemSetting.get_settings()
    for k, v in fields.items():
        setattr(row, k, v)
    row.save()
    return row


@override_settings(**ENV_UNSET)
class ResolutionTests(TestCase):

    def setUp(self):
        security_policy.invalidate()

    def test_defaults_without_saved_row(self):
        SystemSetting.objects.all().delete()
        security_policy.invalidate()
        self.assertEqual(security_policy.idle_timeout_seconds(), 3600)
        self.assertEqual(security_policy.session_max_age_seconds(), 8 * 3600)
        self.assertTrue(security_policy.require_2fa())
        self.assertEqual(security_policy.lockout_failure_limit(), 5)

    def test_saved_values_apply(self):
        _save(session_idle_timeout_minutes=15, session_timeout_minutes=120, require_2fa=False,
              password_min_length=14, failed_login_attempts=7, lockout_duration_minutes=45)
        self.assertEqual(security_policy.idle_timeout_seconds(), 900)
        self.assertEqual(security_policy.session_max_age_seconds(), 7200)
        self.assertFalse(security_policy.require_2fa())
        self.assertEqual(security_policy.get('password_min_length'), 14)
        self.assertEqual(security_policy.lockout_failure_limit(), 7)
        self.assertEqual(security_policy.lockout_cooloff(), timedelta(minutes=45))

    def test_save_invalidates_cache(self):
        _save(failed_login_attempts=4)
        self.assertEqual(security_policy.lockout_failure_limit(), 4)
        _save(failed_login_attempts=9)
        self.assertEqual(security_policy.lockout_failure_limit(), 9)

    def test_out_of_range_saved_values_are_clamped(self):
        _save(password_min_length=2, failed_login_attempts=1000)
        self.assertEqual(security_policy.get('password_min_length'), 8)
        self.assertEqual(security_policy.lockout_failure_limit(), 20)

    @override_settings(SESSION_IDLE_TIMEOUT=600, SESSION_ABSOLUTE_TIMEOUT=3600, REQUIRE_2FA=True,
                       PASSWORD_MIN_LENGTH=20, LOCKOUT_FAILURE_LIMIT=3, LOCKOUT_COOLOFF_HOURS=2)
    def test_env_overrides_saved(self):
        _save(session_idle_timeout_minutes=600, session_timeout_minutes=5000, require_2fa=False,
              password_min_length=8, failed_login_attempts=20, lockout_duration_minutes=5)
        self.assertEqual(security_policy.idle_timeout_seconds(), 600)
        self.assertEqual(security_policy.session_max_age_seconds(), 3600)
        self.assertTrue(security_policy.require_2fa())
        self.assertEqual(security_policy.get('password_min_length'), 20)
        self.assertEqual(security_policy.lockout_failure_limit(), 3)
        self.assertEqual(security_policy.lockout_cooloff(), timedelta(hours=2))
        self.assertTrue(security_policy.is_env_locked('require_2fa'))


@override_settings(MIDDLEWARE=NO_AXES, SECURE_SSL_REDIRECT=False, **ENV_UNSET)
class SessionTimeoutTests(TestCase):

    def setUp(self):
        security_policy.invalidate()
        _save(require_2fa=False, session_idle_timeout_minutes=10, session_timeout_minutes=60)
        self.user = get_user_model().objects.create_user('sess_user', 's@x.com', 'pw', is_superuser=True)
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def _set(self, **values):
        s = self.client.session
        for k, v in values.items():
            s[k] = v
        s.save()

    def _get(self):
        return self.client.get(reverse('core:dashboard'))

    def test_active_session_ok(self):
        now = time.time()
        self._set(_last_activity=now - 60, _auth_started=now - 300)
        self.assertEqual(self._get().status_code, 200)

    def test_saved_idle_timeout_applies(self):
        now = time.time()
        self._set(_last_activity=now - 11 * 60, _auth_started=now - 11 * 60)
        r = self._get()
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    @override_settings(SESSION_IDLE_TIMEOUT=3600)
    def test_env_idle_timeout_overrides_saved(self):
        now = time.time()
        self._set(_last_activity=now - 11 * 60, _auth_started=now - 11 * 60)
        self.assertEqual(self._get().status_code, 200)

    def test_saved_absolute_age_applies_even_when_active(self):
        now = time.time()
        self._set(_last_activity=now - 30, _auth_started=now - 61 * 60)
        r = self._get()
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    @override_settings(SESSION_ABSOLUTE_TIMEOUT=4 * 3600)
    def test_env_absolute_age_overrides_saved(self):
        now = time.time()
        self._set(_last_activity=now - 30, _auth_started=now - 61 * 60)
        self.assertEqual(self._get().status_code, 200)

    def test_session_start_is_recorded(self):
        self._get()
        self.assertIn('_auth_started', self.client.session)


@override_settings(MIDDLEWARE=NO_AXES, SECURE_SSL_REDIRECT=False, **ENV_UNSET)
class Require2FATests(TestCase):

    def setUp(self):
        security_policy.invalidate()
        self.user = get_user_model().objects.create_user('tfa_user', 't@x.com', 'pw', is_superuser=True)
        self.client.force_login(self.user)
        self.setup_url = reverse('two_factor:setup')

    def _dash(self):
        return self.client.get(reverse('core:dashboard'))

    def test_saved_required_forces_setup_every_time(self):
        _save(require_2fa=True)
        self.assertRedirects(self._dash(), self.setup_url, fetch_redirect_response=False)
        self.assertRedirects(self._dash(), self.setup_url, fetch_redirect_response=False)

    def test_saved_optional_prompts_once(self):
        _save(require_2fa=False)
        self.assertRedirects(self._dash(), self.setup_url, fetch_redirect_response=False)
        self.assertEqual(self._dash().status_code, 200)

    @override_settings(REQUIRE_2FA=True)
    def test_env_required_overrides_saved_optional(self):
        _save(require_2fa=False)
        self._dash()
        self.assertRedirects(self._dash(), self.setup_url, fetch_redirect_response=False)


@override_settings(**ENV_UNSET)
class PasswordPolicyTests(TestCase):

    def setUp(self):
        security_policy.invalidate()

    def test_validator_is_installed(self):
        names = [v['NAME'] for v in django_settings.AUTH_PASSWORD_VALIDATORS]
        self.assertIn('core.security_policy.SystemPasswordPolicyValidator', names)

    def test_saved_min_length_and_special(self):
        _save(password_min_length=16, password_require_special=True)
        with self.assertRaises(ValidationError) as cm:
            validate_password('Zq7#Lm2pVx9!')  # 12 chars
        self.assertIn('password_too_short', [e.code for e in cm.exception.error_list])
        with self.assertRaises(ValidationError) as cm:
            validate_password('Zq7wLm2pVx9rTk4bYh')  # no special
        self.assertIn('password_no_special', [e.code for e in cm.exception.error_list])
        validate_password('Zq7#Lm2pVx9!Tk4bYh')

    def test_special_not_required_when_saved_off(self):
        _save(password_min_length=12, password_require_special=False)
        validate_password('Zq7wLm2pVx9rTk4b')

    @override_settings(PASSWORD_MIN_LENGTH=20, PASSWORD_REQUIRE_SPECIAL=True)
    def test_env_overrides_saved(self):
        _save(password_min_length=8, password_require_special=False)
        with self.assertRaises(ValidationError):
            validate_password('Zq7#Lm2pVx9!Tk4bYh')  # 18 < 20

    def test_help_text_reflects_policy(self):
        _save(password_min_length=15, password_require_special=True)
        text = security_policy.SystemPasswordPolicyValidator().get_help_text()
        self.assertIn('15', text)
        self.assertIn('special', text)


@override_settings(**ENV_UNSET)
class LockoutTests(TestCase):

    def setUp(self):
        security_policy.invalidate()
        self.request = RequestFactory().post('/account/login/')

    def test_axes_reads_saved_values(self):
        from axes.helpers import get_cool_off, get_failure_limit
        _save(failed_login_attempts=4, lockout_duration_minutes=20)
        self.assertEqual(get_failure_limit(self.request, {}), 4)
        self.assertEqual(get_cool_off(), timedelta(minutes=20))

    @override_settings(LOCKOUT_FAILURE_LIMIT=10, LOCKOUT_COOLOFF_HOURS=1.5)
    def test_env_overrides_saved(self):
        from axes.helpers import get_cool_off, get_failure_limit
        _save(failed_login_attempts=4, lockout_duration_minutes=20)
        self.assertEqual(get_failure_limit(self.request, {}), 10)
        self.assertEqual(get_cool_off(), timedelta(minutes=90))

    def _attempt(self, password, ip):
        from django.contrib.auth import authenticate
        from axes.handlers.proxy import AxesProxyHandler
        req = RequestFactory().post('/account/login/', REMOTE_ADDR=ip)
        AxesProxyHandler.update_request(req)
        return req, authenticate(req, username='lock_me', password=password)

    def test_axes_locks_after_saved_limit(self):
        _save(failed_login_attempts=3)
        get_user_model().objects.create_user('lock_me', 'l@x.com', 'right-password')
        for _ in range(3):
            self._attempt('wrong', '203.0.113.9')
        # the saved limit of 3 is reached: even the right password is refused
        req, user = self._attempt('right-password', '203.0.113.9')
        self.assertIsNone(user)
        self.assertTrue(getattr(req, 'axes_locked_out', False))

    def test_axes_not_locked_below_saved_limit(self):
        _save(failed_login_attempts=5)
        get_user_model().objects.create_user('lock_me', 'l@x.com', 'right-password')
        for _ in range(3):
            self._attempt('wrong', '203.0.113.10')
        req, user = self._attempt('right-password', '203.0.113.10')
        self.assertIsNotNone(user)


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, **ENV_UNSET)
class SecuritySettingsPageTests(TestCase):

    def setUp(self):
        security_policy.invalidate()
        self.admin = get_user_model().objects.create_user(
            'sec_admin', 'a@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.url = reverse('core:settings_security')

    def _form(self, **overrides):
        data = {
            'session_idle_timeout_minutes': '30', 'session_timeout_minutes': '240',
            'require_2fa': 'on', 'password_min_length': '14', 'password_require_special': 'on',
            'failed_login_attempts': '6', 'lockout_duration_minutes': '20',
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def test_saving_applies_immediately(self):
        r = self.client.post(self.url, self._form(require_2fa=None))
        self.assertEqual(r.status_code, 302)
        row = SystemSetting.get_settings()
        self.assertEqual(row.session_idle_timeout_minutes, 30)
        self.assertFalse(row.require_2fa)
        self.assertFalse(security_policy.require_2fa())
        self.assertEqual(security_policy.idle_timeout_seconds(), 1800)

    def test_values_are_clamped(self):
        self.client.post(self.url, self._form(password_min_length='3', failed_login_attempts='999'))
        row = SystemSetting.get_settings()
        self.assertEqual(row.password_min_length, 8)
        self.assertEqual(row.failed_login_attempts, 20)

    def test_unlocked_fields_are_editable(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('set by environment', html)
        self.assertRegex(html, r'id="require_2fa"[^>]*\s+checked')
        self.assertNotRegex(html, r'id="require_2fa"[^>]*disabled')

    @override_settings(REQUIRE_2FA=True, LOCKOUT_FAILURE_LIMIT=4)
    def test_env_locked_fields_are_read_only(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('set by environment', html)
        self.assertRegex(html, r'id="require_2fa"[^>]*\bdisabled')
        self.assertRegex(html, r'id="failed_login_attempts"[^>]*value="4"[^>]*\bdisabled')
        self.assertNotRegex(html, r'id="password_min_length"[^>]*\bdisabled')

    @override_settings(REQUIRE_2FA=True)
    def test_post_cannot_change_env_locked_field(self):
        _save(require_2fa=True)
        self.client.post(self.url, self._form(require_2fa=None))
        self.assertTrue(SystemSetting.get_settings().require_2fa)
        self.assertTrue(security_policy.require_2fa())
        # the unlocked fields in the same POST are still saved
        self.assertEqual(SystemSetting.get_settings().password_min_length, 14)
