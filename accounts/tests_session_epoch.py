"""Sign out everywhere (accounts.session_epoch + SessionEpochMiddleware)."""
import time
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import session_epoch
from accounts.models import Membership, Role, UserProfile
from audit.models import AuditLog

# Same as core/tests/test_global_search_scoping.py: real stack minus 2FA and
# Axes. SessionEpochMiddleware is in settings.MIDDLEWARE, so it stays in.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
WITH_2FA_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE if 'AxesMiddleware' not in m]
PASSWORD = 'Correct-Horse-Battery-42'
PROFILE = '/accounts/profile/'


def _signed_in(client):
    return '_auth_user_id' in client.session


def _get(client, path=PROFILE):
    return client.get(path)


def _mobile_token(user):
    from api_mobile.models import MobileAuthToken
    return MobileAuthToken.objects.create(user=user, key_hash=f'h{user.pk}{time.time_ns()}', key_prefix='abcd',
                                          device_label='phone')


def _setup(test):
    from core.models import Organization, SystemSetting
    from core import security_policy
    from psa.models import ClientPSASettings
    from psa.tests._base import _make_msp_tech
    cache.clear()
    s = SystemSetting.get_settings()
    s.psa_enabled = True
    s.require_2fa = False
    s.save()
    security_policy.invalidate()
    test.org = Organization.objects.create(name='EpochCo', slug='epochco')
    ClientPSASettings.objects.update_or_create(organization=test.org, defaults={'portal_enabled': True})
    test.tech = User.objects.create_user('tech-epoch', 'tech@msp.example', PASSWORD)
    _make_msp_tech(test.tech)
    test.tech2 = User.objects.create_user('tech2-epoch', 'tech2@msp.example', PASSWORD)
    _make_msp_tech(test.tech2)
    test.admin = User.objects.create_superuser('root-epoch', 'root@msp.example', PASSWORD)
    test.customer = User.objects.create_user('cust@example.com', 'cust@example.com', PASSWORD)
    test.membership = Membership.objects.create(user=test.customer, organization=test.org,
                                                role=Role.READONLY, is_active=True)


def _two_clients(user):
    a, b = Client(), Client()
    b.force_login(user)
    time.sleep(0.002)
    a.force_login(user)
    return a, b


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SelfServiceTests(TestCase):

    def setUp(self):
        _setup(self)

    def test_login_stamps_session(self):
        c = Client()
        c.force_login(self.tech)
        self.assertIsInstance(c.session.get(session_epoch.ISSUED_AT_KEY), float)

    def test_sign_out_others_keeps_current(self):
        current, other = _two_clients(self.tech)
        token = _mobile_token(self.tech)
        other_key = other.session.session_key
        r = current.post(reverse('accounts:sessions_sign_out'), {'scope': 'others'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_get(current).status_code, 200)
        r = _get(other)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/account/login/', r['Location'])
        self.assertFalse(_signed_in(other))
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)  # "others" leaves the mobile app alone by default
        entry = AuditLog.objects.get(extra_data__op='sign_out_sessions')
        self.assertEqual(entry.user, self.tech)
        self.assertEqual(entry.object_id, self.tech.pk)
        self.assertEqual(entry.extra_data['scope'], 'others')
        dump = f'{entry.description} {entry.extra_data}'
        self.assertNotIn(current.session.session_key, dump)
        self.assertNotIn(other_key, dump)

    def test_sign_out_everywhere_ends_current_and_mobile(self):
        current, other = _two_clients(self.tech)
        token = _mobile_token(self.tech)
        current.post(reverse('accounts:sessions_sign_out'), {'scope': 'all'})
        self.assertFalse(_signed_in(current))
        self.assertEqual(_get(current).status_code, 302)
        self.assertEqual(_get(other).status_code, 302)
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        entry = AuditLog.objects.get(extra_data__op='sign_out_sessions')
        self.assertEqual(entry.extra_data['scope'], 'all')
        self.assertEqual(entry.extra_data['mobile_sessions_revoked'], 1)

    def test_everywhere_can_keep_mobile(self):
        current, _ = _two_clients(self.tech)
        token = _mobile_token(self.tech)
        current.post(reverse('accounts:sessions_sign_out'), {'scope': 'all', 'revoke_mobile': ['0']})
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)

    def test_others_with_mobile_ticked(self):
        current, _ = _two_clients(self.tech)
        token = _mobile_token(self.tech)
        current.post(reverse('accounts:sessions_sign_out'), {'scope': 'others', 'revoke_mobile': ['0', '1']})
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertEqual(_get(current).status_code, 200)

    def test_self_service_ignores_user_id(self):
        """The self-service endpoint only ever acts on request.user."""
        c = Client()
        c.force_login(self.tech)
        victim = Client()
        victim.force_login(self.tech2)
        c.post(reverse('accounts:sessions_sign_out'), {'scope': 'all', 'user_id': self.tech2.pk})
        self.assertEqual(_get(victim).status_code, 200)

    def test_get_not_allowed(self):
        c = Client()
        c.force_login(self.tech)
        self.assertEqual(c.get(reverse('accounts:sessions_sign_out')).status_code, 405)

    def test_profile_shows_buttons(self):
        c = Client()
        c.force_login(self.tech)
        r = _get(c)
        self.assertContains(r, 'Sign out of all other sessions')
        self.assertContains(r, 'Sign out everywhere')

    def test_password_change_signs_out_other_sessions(self):
        current, other = _two_clients(self.tech)
        r = current.post(reverse('accounts:password_change'), {
            'old_password': PASSWORD, 'new_password1': 'An-Entirely-New-Pass-77',
            'new_password2': 'An-Entirely-New-Pass-77'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_get(current).status_code, 200)
        self.assertEqual(_get(other).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(extra_data__op='sign_out_sessions',
                                                extra_data__reason='password changed').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AdminSignOutTests(TestCase):

    def setUp(self):
        _setup(self)
        self.url = reverse('accounts:user_sessions_sign_out', args=[self.tech.pk])

    def test_admin_signs_user_out_with_password(self):
        target = Client()
        target.force_login(self.tech)
        token = _mobile_token(self.tech)
        admin = Client()
        admin.force_login(self.admin)
        r = admin.post(self.url, {'password': PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_get(target).status_code, 302)
        self.assertEqual(_get(admin).status_code, 200)  # the admin stays signed in
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        entry = AuditLog.objects.get(extra_data__op='sign_out_sessions')
        self.assertEqual(entry.user, self.admin)
        self.assertEqual(entry.object_id, self.tech.pk)
        self.assertEqual(entry.extra_data['scope'], 'all')
        self.assertEqual(entry.extra_data['mobile_sessions_revoked'], 1)

    def test_step_up_required(self):
        target = Client()
        target.force_login(self.tech)
        admin = Client()
        admin.force_login(self.admin)
        admin.post(self.url, {})
        admin.post(self.url, {'password': 'wrong-password'})
        self.assertEqual(_get(target).status_code, 200)
        self.assertFalse(AuditLog.objects.filter(extra_data__op='sign_out_sessions').exists())

    def test_fresh_auth_is_enough(self):
        from tech_access.protected import SESSION_KEY
        target = Client()
        target.force_login(self.tech)
        admin = Client()
        admin.force_login(self.admin)
        s = admin.session
        s[SESSION_KEY] = int(timezone.now().timestamp())
        s.save()
        admin.post(self.url, {})
        self.assertEqual(_get(target).status_code, 302)

    def test_non_superuser_cannot_sign_out_another_user(self):
        target = Client()
        target.force_login(self.tech)
        attacker = Client()
        attacker.force_login(self.tech2)
        r = attacker.post(self.url, {'password': PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_get(target).status_code, 200)
        self.assertFalse(AuditLog.objects.filter(extra_data__op='sign_out_sessions').exists())

    def test_customer_cannot_target_staff(self):
        target = Client()
        target.force_login(self.tech)
        cust = Client()
        cust.force_login(self.customer)
        cust.post(self.url, {'password': PASSWORD})
        self.assertEqual(_get(target).status_code, 200)
        self.tech.profile.refresh_from_db()
        self.assertIsNone(self.tech.profile.sessions_valid_after)

    def test_admin_password_reset_ends_target_sessions(self):
        target = Client()
        target.force_login(self.tech)
        admin = Client()
        admin.force_login(self.admin)
        admin.post(reverse('accounts:user_password_reset', args=[self.tech.pk]),
                   {'password1': 'Reset-By-Admin-Pass-91', 'password2': 'Reset-By-Admin-Pass-91'})
        self.assertEqual(_get(target).status_code, 302)
        self.tech.profile.refresh_from_db()
        self.assertIsNotNone(self.tech.profile.sessions_valid_after)

    def test_user_detail_shows_button(self):
        admin = Client()
        admin.force_login(self.admin)
        r = admin.get(reverse('accounts:user_detail', args=[self.tech.pk]))
        self.assertContains(r, 'Sign this user out everywhere')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalTests(TestCase):

    def setUp(self):
        _setup(self)

    def test_portal_sign_out_others(self):
        current, other = _two_clients(self.customer)
        staff = Client()
        staff.force_login(self.tech)
        r = current.post(reverse('portal_auth:sessions_sign_out'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(current.get(reverse('portal_auth:password_change')).status_code, 200)
        r = other.get(reverse('portal_auth:password_change'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/portal/login/', r['Location'])
        self.assertEqual(_get(staff).status_code, 200)

    def test_portal_page_shows_button(self):
        c = Client()
        c.force_login(self.customer)
        r = c.get(reverse('portal_auth:password_change'))
        self.assertContains(r, 'Sign out of all other sessions')

    def test_portal_endpoint_refuses_staff(self):
        c = Client()
        c.force_login(self.tech)
        r = c.post(reverse('portal_auth:sessions_sign_out'))
        self.assertEqual(r.status_code, 404)

    def test_portal_password_reset_confirm_ends_sessions(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        existing = Client()
        existing.force_login(self.customer)
        uid = urlsafe_base64_encode(force_bytes(self.customer.pk))
        token = default_token_generator.make_token(self.customer)
        anon = Client()
        r = anon.get(reverse('portal_auth:password_reset_confirm', args=[uid, token]))
        r = anon.post(r['Location'], {'new_password1': 'Portal-Reset-Pass-552',
                                      'new_password2': 'Portal-Reset-Pass-552'})
        self.assertEqual(r.status_code, 302)
        self.customer.profile.refresh_from_db()
        self.assertIsNotNone(self.customer.profile.sessions_valid_after)
        self.assertEqual(existing.get(reverse('portal_auth:password_change')).status_code, 302)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EpochMechanicsTests(TestCase):

    def setUp(self):
        _setup(self)

    def test_unstamped_session_survives_upgrade_and_gets_stamped(self):
        c = Client()
        c.force_login(self.tech)
        s = c.session
        del s[session_epoch.ISSUED_AT_KEY]
        s.pop('_auth_started', None)
        s.save()
        self.assertEqual(_get(c).status_code, 200)
        self.assertIsInstance(c.session.get(session_epoch.ISSUED_AT_KEY), float)

    def test_legacy_session_uses_auth_started(self):
        c = Client()
        c.force_login(self.tech)
        s = c.session
        del s[session_epoch.ISSUED_AT_KEY]
        s['_auth_started'] = time.time() - 600
        s.save()
        self.assertEqual(_get(c).status_code, 200)
        self.assertLess(c.session[session_epoch.ISSUED_AT_KEY], time.time() - 500)
        # A sign-out after the upgrade ends it.
        session_epoch.bump(self.tech)
        self.assertEqual(_get(c).status_code, 302)

    def test_unstamped_legacy_session_killed_when_epoch_already_set(self):
        UserProfile.objects.filter(user=self.tech).update(
            sessions_valid_after=timezone.now() + timedelta(seconds=5))
        c = Client()
        c.force_login(self.tech)
        s = c.session
        del s[session_epoch.ISSUED_AT_KEY]
        s['_auth_started'] = time.time()
        s.save()
        self.assertEqual(_get(c).status_code, 302)

    def test_login_after_epoch_works(self):
        session_epoch.bump(self.tech)
        time.sleep(0.002)
        c = Client()
        c.force_login(self.tech)
        self.assertEqual(_get(c).status_code, 200)

    def test_bump_updates_loaded_profile(self):
        """The epoch is read from the request's own profile, so there is no
        cache to go stale across workers; bump() keeps a loaded profile in
        step and a fresh load sees the new value."""
        user = User.objects.get(pk=self.tech.pk)
        _ = user.profile
        self.assertIsNone(session_epoch.valid_after_ts(user))
        session_epoch.bump(user)
        self.assertIsNotNone(session_epoch.valid_after_ts(user))
        fresh = User.objects.get(pk=self.tech.pk)
        self.assertAlmostEqual(session_epoch.valid_after_ts(fresh), session_epoch.valid_after_ts(user),
                               places=3)

    def test_stale_profile_save_does_not_undo_sign_out(self):
        stale = UserProfile.objects.get(user=self.tech)
        session_epoch.bump(self.tech)
        stale.phone = '555-0100'
        stale.save()  # full save of a copy loaded before the sign-out
        fresh = UserProfile.objects.get(user=self.tech)
        self.assertIsNotNone(fresh.sessions_valid_after)
        self.assertEqual(fresh.phone, '555-0100')

    def test_epoch_check_adds_no_query(self):
        """The middleware reads the profile the request loads anyway."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        c = Client()
        c.force_login(self.tech)
        _get(c)
        with CaptureQueriesContext(connection) as ctx:
            _get(c)
        profile_selects = [q for q in ctx.captured_queries
                           if 'FROM "accounts_userprofile"' in q['sql']
                           and 'WHERE "accounts_userprofile"."user_id" =' in q['sql']]
        self.assertLessEqual(len(profile_selects), 1)

    def test_profile_missing_is_harmless(self):
        UserProfile.objects.filter(user=self.admin).delete()
        rf = RequestFactory()
        req = rf.get('/')
        req.user = User.objects.get(pk=self.admin.pk)
        self.assertIsNone(session_epoch.valid_after_ts(req.user))

    def test_deactivated_user_session_ends(self):
        c = Client()
        c.force_login(self.tech)
        self.tech.is_active = False
        self.tech.save()
        self.assertEqual(_get(c).status_code, 302)
        self.tech.profile.refresh_from_db()
        self.assertIsNotNone(self.tech.profile.sessions_valid_after)
        # Re-activation does not revive the old session.
        self.tech.is_active = True
        self.tech.save()
        self.assertEqual(_get(c).status_code, 302)

    def test_middleware_ends_inactive_user_even_if_backend_returns_them(self):
        from accounts.middleware import SessionEpochMiddleware
        from django.contrib.sessions.backends.db import SessionStore
        rf = RequestFactory()
        req = rf.get('/assets/')
        req.session = SessionStore()
        user = User.objects.get(pk=self.tech.pk)
        user.is_active = False  # not saved: as if a backend handed back an inactive user
        req.user = user
        r = SessionEpochMiddleware(lambda request: None)(req)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(req.user.is_authenticated)

    def test_customer_membership_deactivated_ends_sessions(self):
        c = Client()
        c.force_login(self.customer)
        self.membership.is_active = False
        self.membership.save()
        self.customer.profile.refresh_from_db()
        self.assertIsNotNone(self.customer.profile.sessions_valid_after)

    def test_staff_membership_change_does_not_sign_out(self):
        m = Membership.objects.create(user=self.tech, organization=self.org, role=Role.READONLY, is_active=True)
        m.is_active = False
        m.save()
        self.tech.profile.refresh_from_db()
        self.assertIsNone(self.tech.profile.sessions_valid_after)

    def test_organization_deactivated_ends_customer_sessions(self):
        Membership.objects.create(user=self.tech, organization=self.org, role=Role.READONLY, is_active=True)
        self.org.is_active = False
        self.org.save()
        self.customer.profile.refresh_from_db()
        self.tech.profile.refresh_from_db()
        self.assertIsNotNone(self.customer.profile.sessions_valid_after)
        self.assertIsNone(self.tech.profile.sessions_valid_after)

    def test_own_2fa_removal_keeps_current_session(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        current, other = _two_clients(self.tech)
        TOTPDevice.objects.create(user=self.tech, name='default', confirmed=True)
        # Mark the sessions verified the cheap way: the test stack has no 2FA middleware.
        r = current.post(reverse('accounts:two_factor_setup'), {'action': 'disable'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(TOTPDevice.objects.filter(user=self.tech).exists())
        self.assertEqual(_get(current).status_code, 200)
        self.assertEqual(_get(other).status_code, 302)

    def test_2fa_device_removed_by_someone_else_ends_all(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        c = Client()
        c.force_login(self.tech)
        d = TOTPDevice.objects.create(user=self.tech, name='default', confirmed=True)
        d.delete()
        self.assertEqual(_get(c).status_code, 302)

    def test_unconfirmed_device_delete_is_ignored(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        c = Client()
        c.force_login(self.tech)
        TOTPDevice.objects.create(user=self.tech, name='pending', confirmed=False).delete()
        self.assertEqual(_get(c).status_code, 200)

    def test_totp_rekey_counts_as_reset(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        c = Client()
        c.force_login(self.tech)
        d = TOTPDevice.objects.create(user=self.tech, name='default', confirmed=True)
        d = TOTPDevice.objects.get(pk=d.pk)
        d.drift = 1
        d.save()  # an ordinary save (code check) changes nothing
        self.assertEqual(_get(c).status_code, 200)
        d.key = 'ab' * 20
        d.save()
        self.assertEqual(_get(c).status_code, 302)


@override_settings(MIDDLEWARE=WITH_2FA_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class With2FAMiddlewareTests(TestCase):

    def setUp(self):
        _setup(self)
        from core.models import SystemSetting
        from core import security_policy
        s = SystemSetting.get_settings()
        s.require_2fa = True
        s.save()
        security_policy.invalidate()

    def test_2fa_enforcement_still_applies(self):
        c = Client()
        c.force_login(self.tech)
        r = _get(c)
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('/account/login/', r['Location'])  # sent to 2FA enrolment, not signed out
        self.assertTrue(_signed_in(c))

    def test_revoked_session_goes_to_login_before_2fa(self):
        c = Client()
        c.force_login(self.tech)
        session_epoch.bump(self.tech)
        r = _get(c)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/account/login/', r['Location'])
        self.assertFalse(_signed_in(c))
