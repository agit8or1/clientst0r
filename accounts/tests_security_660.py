"""v3.17.660 — fixes from the 2026-11-10 security scan:

* a Microsoft (Azure AD) sign-in skipped ClientSt0r's 2FA even when Microsoft
  never asked for a second factor;
* the customer portal's password reveal skipped the approval requirement and
  access rules, had no rate limit, and returned the secret when its audit
  entry failed (the org-admin access change swallowed audit failures too);
* Maintenance → Clean Up Audit Logs took any age from the POST, so 0 erased
  the whole trail;
* install.sh wrote REQUIRE_2FA=False into every new .env, switching the 2FA
  requirement off and locking Settings → Security.
"""
import base64
import json
import pathlib
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.azure_auth import azure_mfa_asserted
from audit.models import AuditLog

MIDDLEWARE_WITH_2FA = [m for m in django_settings.MIDDLEWARE if 'AxesMiddleware' not in m]
TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


def _jwt(claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=').decode()
    return f'e30.{body}.sig'


class AzureMfaClaimTests(TestCase):
    def test_mfa_read_from_id_token_or_access_token(self):
        self.assertTrue(azure_mfa_asserted({'id_token_claims': {'amr': ['pwd', 'mfa']}}))
        self.assertTrue(azure_mfa_asserted({'access_token': _jwt({'amr': ['pwd', 'mfa']})}))
        self.assertFalse(azure_mfa_asserted({'id_token_claims': {'amr': ['pwd']}}))
        self.assertFalse(azure_mfa_asserted({'access_token': _jwt({'amr': ['pwd']})}))
        self.assertFalse(azure_mfa_asserted({'access_token': 'not-a-jwt'}))
        self.assertFalse(azure_mfa_asserted(None))


@override_settings(MIDDLEWARE=MIDDLEWARE_WITH_2FA, SECURE_SSL_REDIRECT=False, REQUIRE_2FA=True)
class AzureSsoTwoFactorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('sso-user', password='pw', is_staff=True)
        self.device = TOTPDevice.objects.create(user=self.user, name='phone', confirmed=True)

    def _sso_client(self, mfa):
        c = Client()
        c.force_login(self.user, backend='accounts.azure_auth.AzureADBackend')
        s = c.session
        s['azure_ad_authenticated'] = True
        s['azure_ad_mfa'] = mfa
        s.save()
        return c

    def _code(self):
        return f'{totp(self.device.bin_key, self.device.step, self.device.t0, self.device.digits):06d}'

    def test_microsoft_mfa_still_counts_as_2fa(self):
        c = self._sso_client(mfa=True)
        r = c.get('/core/secure-notes/')
        self.assertNotEqual(r.status_code, 302, r.get('Location'))
        self.assertIn('_auth_user_id', c.session)

    def test_without_mfa_the_authenticator_code_is_asked_for(self):
        c = self._sso_client(mfa=False)
        r = c.get('/core/secure-notes/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(reverse('accounts:azure_verify')))
        self.assertIn('_auth_user_id', c.session)  # not logged out: may have no local password
        self.assertEqual(c.get(r['Location']).status_code, 200)
        r = c.post(reverse('accounts:azure_verify'), {'token': self._code(), 'next': '/core/secure-notes/'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/core/secure-notes/')
        self.assertNotEqual(c.get('/core/secure-notes/').status_code, 302)
        self.assertTrue(AuditLog.objects.filter(extra_data__event='azure_sso_2fa_verified').exists())

    def test_wrong_codes_end_the_session(self):
        c = self._sso_client(mfa=False)
        for _ in range(5):
            r = c.post(reverse('accounts:azure_verify'), {'token': '000000'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('_auth_user_id', c.session)
        self.assertEqual(AuditLog.objects.filter(extra_data__event='azure_sso_2fa_failed').count(), 5)

    def test_without_mfa_and_without_a_device_enrolment_is_required(self):
        self.device.delete()
        c = self._sso_client(mfa=False)
        r = c.get('/core/secure-notes/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], reverse('two_factor:setup'))

    @override_settings(AZURE_SSO_TRUSTED_AS_2FA=True)
    def test_operator_can_trust_the_tenant(self):
        c = self._sso_client(mfa=False)
        self.assertNotEqual(c.get('/core/secure-notes/').status_code, 302)

    def test_verify_page_is_only_for_microsoft_sessions(self):
        c = Client()
        c.force_login(self.user)
        r = c.post(reverse('accounts:azure_verify'), {'token': self._code()})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('_auth_user_id', c.session)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalRevealGateTests(TestCase):
    def setUp(self):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import ClientPSASettings
        from vault.models import Password
        cache.clear()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='GateCo', slug='gate-co-660')
        ClientPSASettings.objects.create(organization=self.org, portal_enabled=True)
        self.user = User.objects.create_user('gate-portal', 'g@x.example.com', 'pw')
        self.membership = Membership.objects.create(user=self.user, organization=self.org,
                                                    role=Role.READONLY, is_active=True, is_org_admin=True)
        self.pwd = Password(organization=self.org, title='Wi-Fi', username='guest',
                            client_visible=True, client_access_mode='all_org')
        self.pwd.set_password('correct-horse')
        self.pwd.save()
        self.client.force_login(self.user)
        sess = self.client.session
        sess['2fa_prompted'] = True
        sess.save()

    def _reveal(self):
        return self.client.post(f'/portal/vault/{self.pwd.pk}/reveal/')

    def test_approval_requirement_applies_to_the_portal(self):
        self.pwd.requires_reveal_approval = True
        self.pwd.save(update_fields=['requires_reveal_approval'])
        r = self._reveal()
        self.assertEqual(r.status_code, 403)
        self.assertNotIn(b'correct-horse', r.content)
        self.assertTrue(AuditLog.objects.filter(action='reveal_blocked', object_id=self.pwd.pk,
                                                success=False).exists())

    def test_approved_request_is_used_up(self):
        from vault.models import VaultRevealRequest
        self.pwd.requires_reveal_approval = True
        self.pwd.save(update_fields=['requires_reveal_approval'])
        approver = User.objects.create_superuser('gate-approver', 'a@x.example.com', 'pw-approver-660!')
        VaultRevealRequest.objects.create(password=self.pwd, requester=self.user, status='approved',
                                          justification='test', decided_by=approver, decided_at=timezone.now(),
                                          expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self._reveal().status_code, 200)
        self.assertEqual(self._reveal().status_code, 403)  # single use

    def test_access_rules_apply_to_the_portal(self):
        with patch('vault.access_rules.evaluate', return_value={'allowed': False, 'reason': 'Outside hours'}):
            r = self._reveal()
        self.assertEqual(r.status_code, 403)
        self.assertNotIn(b'correct-horse', r.content)

    def test_shares_the_vault_reveal_rate_limit(self):
        for _ in range(30):
            self.assertEqual(self._reveal().status_code, 200)
        r = self._reveal()
        self.assertEqual(r.status_code, 429)
        self.assertNotIn(b'correct-horse', r.content)

    def test_not_revealed_when_the_audit_entry_fails(self):
        real_log = AuditLog.log

        def failing_log(*a, **kw):
            if kw.get('action') == 'reveal':
                raise RuntimeError('audit store down')
            return real_log(*a, **kw)

        with patch.object(AuditLog, 'log', side_effect=failing_log):
            r = self._reveal()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(b'correct-horse', r.content)

    def test_org_admin_access_change_rolls_back_when_it_cannot_be_audited(self):
        self.pwd.client_access_mode = 'org_admin_managed'
        self.pwd.save(update_fields=['client_access_mode'])
        with patch.object(AuditLog, 'log', side_effect=RuntimeError('audit store down')):
            r = self.client.post(f'/portal/vault/admin/{self.pwd.pk}/', {'allowed_user_ids': [self.user.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.pwd.client_allowed_users.exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AuditPurgeBoundsTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser('purge-su', 'p@x.example.com', 'pw-purge-660!')
        self.client.force_login(self.su)
        self.old = AuditLog.log(user=self.su, action='update', description='old entry')
        AuditLog.objects.filter(pk=self.old.pk).update(timestamp=timezone.now() - timedelta(days=10))

    def test_ages_below_the_minimum_or_not_numbers_delete_nothing(self):
        for days in ('0', '-5', '29', 'abc', '99999'):
            with self.subTest(days=days):
                self.client.post(reverse('core:maintenance'), {'action': 'cleanup_audit_logs', 'days': days})
                self.assertTrue(AuditLog.objects.filter(pk=self.old.pk).exists())

    def test_allowed_age_still_cleans_up(self):
        AuditLog.objects.filter(pk=self.old.pk).update(timestamp=timezone.now() - timedelta(days=40))
        self.client.post(reverse('core:maintenance'), {'action': 'cleanup_audit_logs', 'days': '30'})
        self.assertFalse(AuditLog.objects.filter(pk=self.old.pk).exists())


class InstallerDefaultsTests(TestCase):
    def test_installer_does_not_switch_2fa_off(self):
        script = (pathlib.Path(django_settings.BASE_DIR) / 'install.sh').read_text()
        self.assertNotIn('\nREQUIRE_2FA=False', script)
