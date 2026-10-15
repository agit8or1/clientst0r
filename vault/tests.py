"""
Tests for vault.access_rules decision engine (v3.17.163).
"""
from datetime import time, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from core.models import Organization
from vault.models import Password, VaultAccessRule


# Mirror the test middleware setup used elsewhere so we bypass the 2FA
# enforcement middleware and django-axes lockouts.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _make_request(rf, ip='8.8.8.8', user=None):
    req = rf.get('/vault/1/', REMOTE_ADDR=ip)
    if user is not None:
        req.user = user
    return req


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VaultAccessRuleEngineTests(TestCase):
    """v3.17.163 — DENY-wins-then-priority access engine."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme', slug='acme-rules')
        cls.org_b = Organization.objects.create(name='OtherCo', slug='other-rules')
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.bob = User.objects.create_user('bob', 'b@x.com', 'pw')
        cls.password = Password.objects.create(
            organization=cls.org,
            title='Email login',
            encrypted_password='dummy',
        )
        cls.password_b = Password.objects.create(
            organization=cls.org,
            title='Other thing',
            encrypted_password='dummy',
        )

    def setUp(self):
        self.rf = RequestFactory()

    def test_no_rules_means_allow(self):
        from vault.access_rules import evaluate
        req = _make_request(self.rf, user=self.alice)
        result = evaluate(self.password, self.alice, req)
        self.assertTrue(result['allowed'])
        self.assertIsNone(result['matched_rule_id'])

    @patch('vault.access_rules._country_for_ip', return_value='CN')
    def test_deny_country_blocks(self, _mock_cc):
        VaultAccessRule.objects.create(
            organization=self.org,
            name='Block China',
            scope='organization',
            effect='deny',
            blocked_countries=['CN'],
        )
        from vault.access_rules import evaluate
        req = _make_request(self.rf, user=self.alice)
        result = evaluate(self.password, self.alice, req)
        self.assertFalse(result['allowed'])
        self.assertIn('Denied', result['reason'])

    @patch('vault.access_rules._country_for_ip', return_value='CN')
    def test_deny_wins_over_allow(self, _mock_cc):
        VaultAccessRule.objects.create(
            organization=self.org,
            name='Allow all',
            scope='organization',
            effect='allow',
            priority=10,
        )
        VaultAccessRule.objects.create(
            organization=self.org,
            name='Deny CN',
            scope='organization',
            effect='deny',
            priority=200,
            blocked_countries=['CN'],
        )
        from vault.access_rules import evaluate
        req = _make_request(self.rf, user=self.alice)
        result = evaluate(self.password, self.alice, req)
        self.assertFalse(result['allowed'])
        self.assertIn('Deny CN', result['reason'])

    def test_time_window_outside_business_hours(self):
        VaultAccessRule.objects.create(
            organization=self.org,
            name='Business hours only',
            scope='organization',
            effect='allow',
            allowed_hour_start=time(9, 0),
            allowed_hour_end=time(17, 0),
            timezone='UTC',
        )
        from vault.access_rules import evaluate
        req = _make_request(self.rf, user=self.alice)
        # Force "now" to 22:00 UTC -> outside business hours -> conservative deny.
        fake_now = datetime(2026, 4, 30, 22, 0, tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=fake_now):
            with patch('vault.access_rules._country_for_ip', return_value=None):
                result = evaluate(self.password, self.alice, req)
        self.assertFalse(result['allowed'])
        self.assertIn('No matching ALLOW rule', result['reason'])

    @patch('vault.access_rules._country_for_ip', return_value=None)
    def test_cidr_allowlist(self, _mock_cc):
        VaultAccessRule.objects.create(
            organization=self.org,
            name='Office only',
            scope='organization',
            effect='allow',
            allowed_cidrs=['10.0.0.0/8'],
        )
        from vault.access_rules import evaluate
        # Request from 8.8.8.8 -> not in 10.0.0.0/8 -> conservative deny
        req = _make_request(self.rf, ip='8.8.8.8', user=self.alice)
        result = evaluate(self.password, self.alice, req)
        self.assertFalse(result['allowed'])
        # Request from 10.0.0.5 -> in 10.0.0.0/8 -> allow
        req2 = _make_request(self.rf, ip='10.0.0.5', user=self.alice)
        result2 = evaluate(self.password, self.alice, req2)
        self.assertTrue(result2['allowed'])

    @patch('vault.access_rules._country_for_ip', return_value='CN')
    def test_user_scoped_rule(self, _mock_cc):
        # A rule that targets alice only must not affect bob's request.
        VaultAccessRule.objects.create(
            organization=self.org,
            name='No CN for alice',
            scope='user',
            target_user=self.alice,
            effect='deny',
            blocked_countries=['CN'],
        )
        from vault.access_rules import evaluate
        # Alice from CN -> denied
        result_alice = evaluate(
            self.password, self.alice, _make_request(self.rf, user=self.alice),
        )
        self.assertFalse(result_alice['allowed'])
        # Bob from CN -> rule does not apply -> default ALLOW (no rules for bob)
        result_bob = evaluate(
            self.password, self.bob, _make_request(self.rf, user=self.bob),
        )
        self.assertTrue(result_bob['allowed'])

    @patch('vault.access_rules._country_for_ip', return_value='CN')
    def test_item_scoped_rule(self, _mock_cc):
        # A rule that targets one password must not affect other passwords.
        VaultAccessRule.objects.create(
            organization=self.org,
            name='No CN for this password',
            scope='item',
            target_password=self.password,
            effect='deny',
            blocked_countries=['CN'],
        )
        from vault.access_rules import evaluate
        result_target = evaluate(
            self.password, self.alice, _make_request(self.rf, user=self.alice),
        )
        self.assertFalse(result_target['allowed'])
        result_other = evaluate(
            self.password_b, self.alice, _make_request(self.rf, user=self.alice),
        )
        self.assertTrue(result_other['allowed'])


# ---------------------------------------------------------------------------
# v3.17.181 — password mutation audit logging.
# Confirms password_edit / password_delete emit AuditLog rows on success
# AND failure. Reads were already audited; mutations were not.
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PasswordMutationAuditTests(TestCase):
    def setUp(self):
        from accounts.models import Membership, Role
        from audit.models import AuditLog
        from django.test import Client
        self.AuditLog = AuditLog
        self.org = Organization.objects.create(name='AuditCo', slug='auditco')
        self.user = User.objects.create_user('mutuser', password='pw', email='m@x.com')
        Membership.objects.create(
            user=self.user, organization=self.org,
            role=Role.OWNER, is_active=True,
        )
        self.password = Password.objects.create(
            organization=self.org, title='target', username='svc',
            password_type='server',
        )
        self.password.set_password('s3cret')
        self.password.save()

        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['2fa_prompted'] = True
        session['current_organization_id'] = self.org.id
        session.save()

    def test_password_edit_success_logs_update(self):
        url = f'/vault/{self.password.pk}/edit/'
        # Use the form's actual fields — title is required, password_type
        # must be one of the model choices.
        response = self.client.post(url, {
            'title': 'target-renamed',
            'username': 'svc',
            'password_type': 'server',
            'organization': self.org.pk,
        })
        # Either 302 (redirect on success) or 200 (form re-render); we just
        # care that an audit row landed.
        self.assertIn(response.status_code, (200, 302))
        log = (self.AuditLog.objects
               .filter(action='update', object_type='password',
                       object_id=self.password.pk)
               .order_by('-timestamp')
               .first())
        self.assertIsNotNone(log, 'expected an audit row for password update')

    def test_password_delete_logs_with_title_preserved(self):
        url = f'/vault/{self.password.pk}/delete/'
        deleted_pk = self.password.pk
        title = self.password.title
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        # `AuditLoggingMiddleware` also writes a generic URL-pattern row;
        # after delete it can't resolve the model and falls back to
        # `'password #N'`. Filter to *our* view-level row by its title.
        log = (self.AuditLog.objects
               .filter(action='delete', object_type='password',
                       object_id=deleted_pk, object_repr=title)
               .order_by('-timestamp')
               .first())
        self.assertIsNotNone(log,
            'expected the view-level audit row carrying the original title')
        self.assertTrue(log.success)
        self.assertIn('deleted', log.description.lower())


# ---------------------------------------------------------------------------
# Phase 37 — Vault Approval & Break-Glass Workflow (v3.17.241)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VaultApprovalAndBreakGlassTests(TestCase):
    """Phase 37 v1: per-credential reveal approval + emergency break-glass."""

    def setUp(self):
        from accounts.models import Membership, Role
        from core.models import Organization
        from vault.models import Password
        self.org = Organization.objects.create(name='AppRevCo', slug='appr-co')
        self.user = User.objects.create_user('appr-user', 'a@x.com', 'pw')
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)
        self.admin = User.objects.create_user('appr-admin', 'admin@x.com', 'pw',
                                                is_superuser=True, is_staff=True)
        Membership.objects.create(user=self.admin, organization=self.org,
                                   role=Role.OWNER, is_active=True)
        self.password = Password.objects.create(
            organization=self.org, title='Locked credential',
            requires_reveal_approval=True,
        )
        self.password.set_password('s3cret-value')
        self.password.save()

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_reveal_blocked_without_approval(self):
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/vault/{self.password.pk}/reveal/')
        self.assertEqual(r.status_code, 403)
        body = r.json()
        self.assertTrue(body.get('requires_approval'))

    def test_request_reveal_creates_pending_row(self):
        from vault.models import VaultRevealRequest
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/vault/{self.password.pk}/request-reveal/', data={
            'justification': 'Need to reset prod database',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(VaultRevealRequest.objects.count(), 1)
        req = VaultRevealRequest.objects.first()
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.requester_id, self.user.id)
        self.assertFalse(req.is_break_glass)

    def test_request_reveal_rejects_empty_justification(self):
        from vault.models import VaultRevealRequest
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/vault/{self.password.pk}/request-reveal/', data={
            'justification': '',
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(VaultRevealRequest.objects.count(), 0)

    def test_admin_approve_unlocks_reveal(self):
        from vault.models import VaultRevealRequest
        # User requests
        c_user = Client()
        self._login(c_user, self.user)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'standard maintenance'})
        req = VaultRevealRequest.objects.first()

        # Admin approves
        c_admin = Client()
        self._login(c_admin, self.admin)
        ar = c_admin.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'approve', 'notes': 'OK proceed',
        })
        self.assertEqual(ar.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.decided_by_id, self.admin.id)
        self.assertIsNotNone(req.expires_at)

        # User can now reveal
        rr = c_user.post(f'/vault/{self.password.pk}/reveal/')
        self.assertEqual(rr.status_code, 200)
        body = rr.json()
        self.assertEqual(body['password'], 's3cret-value')

        # And the approval is marked single-use (revealed_at set).
        req.refresh_from_db()
        self.assertIsNotNone(req.revealed_at)

        # A second reveal needs a fresh request — gate fires again.
        rr2 = c_user.post(f'/vault/{self.password.pk}/reveal/')
        self.assertEqual(rr2.status_code, 403)

    def test_admin_deny_keeps_block(self):
        from vault.models import VaultRevealRequest
        c_user = Client()
        self._login(c_user, self.user)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'curious'})
        req = VaultRevealRequest.objects.first()
        c_admin = Client()
        self._login(c_admin, self.admin)
        c_admin.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'deny', 'notes': 'no business need',
        })
        req.refresh_from_db()
        self.assertEqual(req.status, 'denied')
        rr = c_user.post(f'/vault/{self.password.pk}/reveal/')
        self.assertEqual(rr.status_code, 403)

    def test_break_glass_bypasses_approval_with_long_justification(self):
        from vault.models import VaultRevealRequest
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/vault/{self.password.pk}/break-glass/', data={
            'justification': 'Production is down at 3am, on-call has been paging me for an hour.',
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['is_break_glass'])
        self.assertEqual(body['status'], 'approved')
        # Reveal works immediately
        rr = c.post(f'/vault/{self.password.pk}/reveal/')
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(rr.json()['password'], 's3cret-value')

    def test_break_glass_requires_long_justification(self):
        from vault.models import VaultRevealRequest
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/vault/{self.password.pk}/break-glass/', data={
            'justification': 'too short',
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(VaultRevealRequest.objects.count(), 0)

    def test_password_without_flag_skips_gate(self):
        from vault.models import Password
        unguarded = Password.objects.create(
            organization=self.org, title='Free reveal',
            requires_reveal_approval=False,
        )
        unguarded.set_password('open-secret')
        unguarded.save()
        c = Client()
        self._login(c, self.user)
        rr = c.post(f'/vault/{unguarded.pk}/reveal/')
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(rr.json()['password'], 'open-secret')

    def test_non_staff_cannot_decide_request(self):
        from vault.models import VaultRevealRequest
        c_user = Client()
        self._login(c_user, self.user)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'reason'})
        req = VaultRevealRequest.objects.first()

        # Different non-staff user tries to decide.
        from accounts.models import Membership, Role
        peer = User.objects.create_user('peer', 'p@x.com', 'pw')
        Membership.objects.create(user=peer, organization=self.org,
                                   role=Role.OWNER, is_active=True)
        c_peer = Client()
        self._login(c_peer, peer)
        r = c_peer.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_reveal_request_list_renders_for_staff(self):
        c = Client()
        self._login(c, self.admin)
        r = c.get('/vault/reveal-requests/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Vault Reveal Approvals')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VaultClientLevelApprovalTests(TestCase):
    """v3.17.247 — Phase 37 v2: client-org admin can approve reveals for
    their own org, closing the "Optional client-level vault approval
    rules" sub-bullet."""

    def setUp(self):
        from accounts.models import Membership, Role
        from core.models import Organization
        from vault.models import Password
        self.client_org = Organization.objects.create(name='ClientCo', slug='cl-co')
        self.other_org = Organization.objects.create(name='OtherCo', slug='cl-other')
        # Client-org admin: a regular user who's been flagged is_org_admin
        # for THE CLIENT ORG. NOT MSP staff/superuser.
        self.client_admin = User.objects.create_user('cl-admin', 'a@x.com', 'pw')
        Membership.objects.create(
            user=self.client_admin, organization=self.client_org,
            role=Role.OWNER, is_active=True, is_org_admin=True,
        )
        # Regular client user: needs to reveal a password owned by client_org.
        self.client_user = User.objects.create_user('cl-user', 'u@x.com', 'pw')
        Membership.objects.create(
            user=self.client_user, organization=self.client_org,
            role=Role.OWNER, is_active=True,
        )
        # Outsider: same admin role on a DIFFERENT org. Must NOT be able
        # to approve reveals for client_org's passwords.
        self.outsider_admin = User.objects.create_user('out-admin', 'o@x.com', 'pw')
        Membership.objects.create(
            user=self.outsider_admin, organization=self.other_org,
            role=Role.OWNER, is_active=True, is_org_admin=True,
        )

        self.password = Password.objects.create(
            organization=self.client_org, title='Client locked credential',
            requires_reveal_approval=True,
        )
        self.password.set_password('client-secret')
        self.password.save()

    def _login(self, c, user, org):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = org.id
        s.save()

    def test_client_org_admin_can_approve_their_orgs_reveal(self):
        from vault.models import VaultRevealRequest
        # Client user requests
        c_user = Client()
        self._login(c_user, self.client_user, self.client_org)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'Production access needed'})
        req = VaultRevealRequest.objects.first()

        # Client-org admin (NOT MSP staff) approves
        c_admin = Client()
        self._login(c_admin, self.client_admin, self.client_org)
        r = c_admin.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.decided_by_id, self.client_admin.id)

    def test_outsider_org_admin_cannot_approve(self):
        from vault.models import VaultRevealRequest
        c_user = Client()
        self._login(c_user, self.client_user, self.client_org)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'standard'})
        req = VaultRevealRequest.objects.first()

        c_outsider = Client()
        self._login(c_outsider, self.outsider_admin, self.other_org)
        r = c_outsider.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_requester_cannot_self_approve_even_as_org_admin(self):
        # Make the requester also an org admin — they STILL can't approve
        # their own request (defense in depth against insider misuse).
        from accounts.models import Membership
        from vault.models import VaultRevealRequest
        Membership.objects.filter(
            user=self.client_user, organization=self.client_org,
        ).update(is_org_admin=True)
        c_user = Client()
        self._login(c_user, self.client_user, self.client_org)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'self-approval test'})
        req = VaultRevealRequest.objects.first()
        # Same user attempts to decide
        r = c_user.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_regular_member_without_org_admin_flag_blocked(self):
        from vault.models import VaultRevealRequest
        c_user = Client()
        self._login(c_user, self.client_user, self.client_org)
        c_user.post(f'/vault/{self.password.pk}/request-reveal/',
                    data={'justification': 'reason'})
        req = VaultRevealRequest.objects.first()

        # Another regular member (no is_org_admin) tries to approve.
        from accounts.models import Membership, Role
        peer = User.objects.create_user('peer', 'p@x.com', 'pw')
        Membership.objects.create(
            user=peer, organization=self.client_org,
            role=Role.OWNER, is_active=True,  # is_org_admin defaults False
        )
        c_peer = Client()
        self._login(c_peer, peer, self.client_org)
        r = c_peer.post(f'/vault/reveal-requests/{req.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')


# ===========================================================================
# Phase 28 — Browser extension API
# ===========================================================================


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebExtensionAuthTokenModelTests(TestCase):
    """v3.17.327 — token issue/expiry/revoke."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ExtCo', slug='ext-co-tok')
        cls.user = User.objects.create_user('ext_user', 'e@x.com', 'pw')

    def test_issue_returns_secret_string_and_row(self):
        from vault.models import WebExtensionAuthToken
        secret, row = WebExtensionAuthToken.issue(
            user=self.user, label='Chrome on Mac',
        )
        # Stored hashed: the row carries the HMAC, never the token.
        self.assertNotEqual(row.token_hash, secret)
        self.assertEqual(row.token_hash, WebExtensionAuthToken.hash(secret))
        self.assertEqual(WebExtensionAuthToken.lookup(secret).pk, row.pk)
        self.assertGreater(len(secret), 30)
        self.assertEqual(row.label, 'Chrome on Mac')
        self.assertTrue(row.is_active)

    def test_revoke_makes_token_inactive(self):
        from vault.models import WebExtensionAuthToken
        _, row = WebExtensionAuthToken.issue(user=self.user)
        row.revoke()
        self.assertFalse(row.is_active)
        self.assertIsNotNone(row.revoked_at)

    def test_expired_token_inactive(self):
        from datetime import timedelta
        from vault.models import WebExtensionAuthToken
        _, row = WebExtensionAuthToken.issue(user=self.user, ttl_days=1)
        row.expires_at = timezone.now() - timedelta(seconds=1)
        row.save(update_fields=['expires_at'])
        self.assertFalse(row.is_active)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionAuthDecoratorTests(TestCase):
    """v3.17.327 — extension_auth_required decorator."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ExtCo', slug='ext-co-dec')
        cls.user = User.objects.create_user('ext_user2', 'e2@x.com', 'pw')

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, self.row = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org, label='Chrome',
        )
        self.rf = RequestFactory()

    def _wrap_passthrough(self):
        from vault.extension_auth import extension_auth_required

        @extension_auth_required
        def _view(request):
            from django.http import JsonResponse as JR
            return JR({
                'user': request.user.username,
                'org': request.current_organization.id if request.current_organization else None,
            })
        return _view

    def test_valid_token_resolves_user_and_org(self):
        view = self._wrap_passthrough()
        req = self.rf.get('/api/vault/extension/x/',
                          HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        import json as _json
        data = _json.loads(resp.content)
        self.assertEqual(data['user'], 'ext_user2')
        self.assertEqual(data['org'], self.org.id)

    def test_missing_header_401(self):
        view = self._wrap_passthrough()
        req = self.rf.get('/api/vault/extension/x/')
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

    def test_revoked_token_401(self):
        self.row.revoke()
        view = self._wrap_passthrough()
        req = self.rf.get('/api/vault/extension/x/',
                          HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

    def test_expired_token_401(self):
        from datetime import timedelta
        self.row.expires_at = timezone.now() - timedelta(seconds=1)
        self.row.save(update_fields=['expires_at'])
        view = self._wrap_passthrough()
        req = self.rf.get('/api/vault/extension/x/',
                          HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

    def test_token_pin_wins_over_org_id_header(self):
        # A token pinned to a customer never acts for another one, even when
        # the user is also a member there and the header asks for it.
        other_org = Organization.objects.create(name='OtherCo', slug='ext-co-other')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=self.user, organization=other_org, role=Role.READONLY, is_active=True,
        )
        view = self._wrap_passthrough()
        req = self.rf.get('/api/vault/extension/x/',
                          HTTP_AUTHORIZATION=f'Bearer {self.secret}',
                          HTTP_X_ORGANIZATION_ID=str(other_org.id))
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        import json as _json
        data = _json.loads(resp.content)
        self.assertEqual(data['org'], self.org.id)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionTokenLifecycleEndpointTests(TestCase):
    """v3.17.327 — token issue / list / revoke endpoints (session-authed)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('ext_user3', 'e3@x.com', 'pw')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.user)

    def test_issue_returns_token_once(self):
        r = self.c.post('/vault/api/extension/tokens/issue/',
                        data={'label': 'Firefox'})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertIn('token', body)
        self.assertEqual(body['label'], 'Firefox')

    def test_list_excludes_secret(self):
        # Issue first, then list.
        self.c.post('/vault/api/extension/tokens/issue/', data={'label': 'A'})
        r = self.c.get('/vault/api/extension/tokens/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data['tokens']), 1)
        self.assertNotIn('token', data['tokens'][0])

    def test_revoke_marks_revoked(self):
        r1 = self.c.post('/vault/api/extension/tokens/issue/', data={})
        token_id = r1.json()['id']
        r2 = self.c.delete(f'/vault/api/extension/tokens/{token_id}/revoke/')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()['revoked'])

    def test_other_user_cannot_revoke(self):
        r1 = self.c.post('/vault/api/extension/tokens/issue/', data={})
        token_id = r1.json()['id']
        intruder = User.objects.create_user('intruder', 'i@x.com', 'pw')
        c2 = Client()
        c2.force_login(intruder)
        r2 = c2.delete(f'/vault/api/extension/tokens/{token_id}/revoke/')
        self.assertEqual(r2.status_code, 403)


# ===========================================================================
# Phase 28 v3.17.328 — autofill match + bulk sync + RoleTemplate perms
# ===========================================================================


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionAutofillEndpointTests(TestCase):
    """v3.17.328 — autofill match endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='AutofillCo', slug='af-co')
        cls.user = User.objects.create_user('af_user', 'af@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )
        cls.match_pw = Password.objects.create(
            organization=cls.org, title='Example login',
            url='https://example.com/login', username='alice',
            encrypted_password='dummy',
        )
        cls.other_pw = Password.objects.create(
            organization=cls.org, title='Other site',
            url='https://other.test/', username='bob',
            encrypted_password='dummy',
        )

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, self.row = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org,
        )
        self.c = Client()

    def _hdrs(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.secret}'}

    def test_autofill_returns_match(self):
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://example.com/admin',
            **self._hdrs(),
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['matches'][0]['title'], 'Example login')
        self.assertNotIn('encrypted_password', data['matches'][0])

    def test_autofill_no_match(self):
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://nope.invalid/',
            **self._hdrs(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['count'], 0)

    def test_autofill_emits_audit_log(self):
        from audit.models import AuditLog
        before = AuditLog.objects.filter(extra_data__event='vault_autofill').count()
        self.c.get(
            '/vault/api/extension/autofill/?url=https://example.com/login',
            **self._hdrs(),
        )
        after = AuditLog.objects.filter(extra_data__event='vault_autofill').count()
        self.assertEqual(after - before, 1)

    def test_autofill_requires_url_param(self):
        r = self.c.get('/vault/api/extension/autofill/', **self._hdrs())
        self.assertEqual(r.status_code, 400)

    def test_autofill_blocked_for_user_without_extension_use_perm(self):
        from accounts.models import Membership, Role
        ro_user = User.objects.create_user('ro', 'ro@x.com', 'pw')
        Membership.objects.create(
            user=ro_user, organization=self.org,
            role=Role.READONLY, is_active=True,
        )
        from vault.models import WebExtensionAuthToken
        secret, _ = WebExtensionAuthToken.issue(
            user=ro_user, organization=self.org,
        )
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://example.com/',
            HTTP_AUTHORIZATION=f'Bearer {secret}',
        )
        self.assertEqual(r.status_code, 403)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionBulkSyncEndpointTests(TestCase):
    """v3.17.328 — bulk-sync endpoint with offline-cache permission gate."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SyncCo', slug='sync-co')
        cls.user = User.objects.create_user('sync_user', 's@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )
        for i in range(3):
            Password.objects.create(
                organization=cls.org, title=f'Pw {i}',
                url=f'https://x{i}.test/', username='u',
                encrypted_password=f'cipher{i}',
            )

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org,
        )
        self.c = Client()

    def test_sync_returns_encrypted_blobs_only(self):
        r = self.c.get(
            '/vault/api/extension/sync/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['count'], 3)
        for row in data['passwords']:
            self.assertIn('encrypted_password', row)
            self.assertNotIn('password', row)

    def test_sync_pagination(self):
        r = self.c.get(
            '/vault/api/extension/sync/?limit=2',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['count'], 2)
        self.assertTrue(data['has_more'])
        self.assertIsNotNone(data['next_cursor'])
        r2 = self.c.get(
            f'/vault/api/extension/sync/?limit=2&cursor={data["next_cursor"]}',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        data2 = r2.json()
        self.assertEqual(data2['count'], 1)
        self.assertFalse(data2['has_more'])

    def test_sync_blocked_without_offline_cache_perm(self):
        from accounts.models import Membership, Role
        ed_user = User.objects.create_user('ed', 'ed@x.com', 'pw')
        Membership.objects.create(
            user=ed_user, organization=self.org,
            role=Role.EDITOR, is_active=True,
        )
        from vault.models import WebExtensionAuthToken
        secret, _ = WebExtensionAuthToken.issue(
            user=ed_user, organization=self.org,
        )
        r = self.c.get(
            '/vault/api/extension/sync/',
            HTTP_AUTHORIZATION=f'Bearer {secret}',
        )
        self.assertEqual(r.status_code, 403)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleTemplateExtensionPermissionFieldTests(TestCase):
    """v3.17.328 — RoleTemplate has the two new boolean fields."""

    def test_fields_default_false_on_new_template(self):
        from accounts.models import RoleTemplate
        org = Organization.objects.create(name='X', slug='rt-x')
        rt = RoleTemplate.objects.create(organization=org, name='Tester')
        self.assertFalse(rt.vault_extension_use)
        self.assertFalse(rt.vault_extension_offline_cache)

    def test_simple_role_owner_grants_extension_use(self):
        from accounts.models import Membership, Role
        org = Organization.objects.create(name='Y', slug='rt-y')
        user = User.objects.create_user('rt_user', 'rt@x.com', 'pw')
        m = Membership.objects.create(
            user=user, organization=org, role=Role.OWNER, is_active=True,
        )
        perms = m.get_permissions()
        self.assertTrue(perms.vault_extension_use)
        self.assertTrue(perms.vault_extension_offline_cache)


# ===========================================================================
# Phase 28 v3.17.329 — TOTP + reveal + master-password verify
# ===========================================================================


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionTOTPEndpointTests(TestCase):
    """v3.17.329 — TOTP code generation via the extension API."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='TOTPCo', slug='totp-co')
        cls.user = User.objects.create_user('totp_user', 't@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )
        cls.password = Password.objects.create(
            organization=cls.org, title='2FA-enabled',
            url='https://app.test/', username='alice',
            encrypted_password='dummy',
        )
        # Set a known TOTP secret so generate_otp() works deterministically.
        cls.password.set_otp_secret('JBSWY3DPEHPK3PXP')
        cls.password.save()

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org,
        )
        self.c = Client()

    def test_totp_returns_six_digit_code(self):
        r = self.c.get(
            f'/vault/api/extension/{self.password.pk}/totp/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('code', data)
        self.assertEqual(len(data['code']), 6)
        self.assertTrue(data['code'].isdigit())
        self.assertIn('valid_until_unix', data)

    def test_totp_404_on_unknown_password(self):
        r = self.c.get(
            '/vault/api/extension/99999/totp/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 404)

    def test_totp_400_when_no_secret(self):
        no_otp = Password.objects.create(
            organization=self.org, title='No 2FA',
            url='https://app.test/', encrypted_password='dummy',
        )
        r = self.c.get(
            f'/vault/api/extension/{no_otp.pk}/totp/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionRevealEndpointTests(TestCase):
    """v3.17.329 — password reveal via the extension API + approval gate."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='RevealCo', slug='rev-co')
        cls.user = User.objects.create_user('rev_user', 'r@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )
        cls.password = Password.objects.create(
            organization=cls.org, title='Open',
            url='https://x.test/', encrypted_password='dummy',
        )
        cls.password.set_password('hunter2')
        cls.password.save()

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org,
        )
        self.c = Client()

    def test_reveal_returns_plaintext(self):
        r = self.c.post(
            f'/vault/api/extension/{self.password.pk}/reveal/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['password'], 'hunter2')

    def test_reveal_blocked_when_approval_required(self):
        guarded = Password.objects.create(
            organization=self.org, title='Guarded',
            url='https://x.test/', encrypted_password='dummy',
            requires_reveal_approval=True,
        )
        guarded.set_password('topsecret')
        guarded.save()
        r = self.c.post(
            f'/vault/api/extension/{guarded.pk}/reveal/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json().get('requires_approval'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionVerifyMasterTests(TestCase):
    """v3.17.329 — master-password verify (proof-of-knowledge stub)."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='VMCo', slug='vm-co')
        cls.user = User.objects.create_user('vm_user', 'v@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, self.row = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org,
        )
        self.c = Client()

    def test_happy_path(self):
        # 1) request a nonce
        r1 = self.c.get(
            '/vault/api/extension/verify-master/nonce/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r1.status_code, 200)
        nonce = r1.json()['nonce']
        # 2) compute the expected HMAC the way the server will validate
        import hashlib, hmac, json as _json
        key = hashlib.sha256(self.user.password.encode('utf-8')).digest()
        ext_hmac = hmac.new(key, nonce.encode('utf-8'), hashlib.sha256).hexdigest()
        # 3) post it back
        r2 = self.c.post(
            '/vault/api/extension/verify-master/',
            data=_json.dumps({'nonce': nonce, 'hmac_hex': ext_hmac}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()['verified'])

    def test_wrong_hmac_returns_401(self):
        r1 = self.c.get(
            '/vault/api/extension/verify-master/nonce/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        nonce = r1.json()['nonce']
        import json as _json
        r2 = self.c.post(
            '/vault/api/extension/verify-master/',
            data=_json.dumps({'nonce': nonce, 'hmac_hex': 'deadbeef' * 8}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r2.status_code, 401)

    def test_nonce_mismatch_returns_401(self):
        # No GET first; just attempt to post a guessed nonce.
        import json as _json
        r = self.c.post(
            '/vault/api/extension/verify-master/',
            data=_json.dumps({'nonce': 'fake', 'hmac_hex': 'a' * 64}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 401)


# ===========================================================================
# Phase 28 v3.17.330 — Strong password generator + per-org isolation
# ===========================================================================


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionGeneratorEndpointTests(TestCase):
    """v3.17.330 — strong password generator endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='GenCo', slug='gen-co')
        cls.user = User.objects.create_user('gen_user', 'g@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        self.secret, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org,
        )
        self.c = Client()

    def test_generator_default_length_24(self):
        r = self.c.get(
            '/vault/api/extension/generate/',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data['password']), 24)
        self.assertEqual(data['length'], 24)
        self.assertGreater(data['entropy_bits'], 100)

    def test_generator_respects_length_parameter(self):
        r = self.c.get(
            '/vault/api/extension/generate/?length=32',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(len(r.json()['password']), 32)

    def test_generator_excludes_symbols_when_requested(self):
        r = self.c.get(
            '/vault/api/extension/generate/?length=40&symbols=0',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        pw = r.json()['password']
        symbols = set('!@#$%^&*()_+-=[]{}|;:,.<>?')
        self.assertFalse(any(c in symbols for c in pw),
                         f'expected no symbols, got {pw}')

    def test_generator_no_classes_400(self):
        r = self.c.get(
            '/vault/api/extension/generate/'
            '?uppercase=0&lowercase=0&numbers=0&symbols=0',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        self.assertEqual(r.status_code, 400)

    def test_generator_entropy_calculation_matches(self):
        r = self.c.get(
            '/vault/api/extension/generate/'
            '?length=24&uppercase=1&lowercase=1&numbers=1&symbols=0',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
        )
        data = r.json()
        # 26 + 26 + 10 = 62 charset
        self.assertEqual(data['charset_size'], 62)
        import math
        expected = round(24 * math.log2(62), 2)
        self.assertEqual(data['entropy_bits'], expected)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionPerOrgIsolationTests(TestCase):
    """v3.17.330 — confirm X-Organization-Id header is honoured + cross-org isolation."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='OrgA', slug='iso-a')
        cls.org_b = Organization.objects.create(name='OrgB', slug='iso-b')
        cls.user = User.objects.create_user('iso_user', 'iso@x.com', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(
            user=cls.user, organization=cls.org_a, role=Role.OWNER, is_active=True,
        )
        Membership.objects.create(
            user=cls.user, organization=cls.org_b, role=Role.OWNER, is_active=True,
        )
        # One password in each org with the same URL
        for org in (cls.org_a, cls.org_b):
            Password.objects.create(
                organization=org, title=f'Same site — {org.slug}',
                url='https://shared.test/login', username=f'u-{org.slug}',
                encrypted_password='dummy',
            )

    def setUp(self):
        from vault.models import WebExtensionAuthToken
        # Token NOT pinned to any org -- header decides per-call.
        self.secret, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=None,
        )
        self.c = Client()

    def test_autofill_in_org_a_returns_only_org_a_match(self):
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://shared.test/login',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
            HTTP_X_ORGANIZATION_ID=str(self.org_a.id),
        )
        self.assertEqual(r.status_code, 200)
        matches = r.json()['matches']
        self.assertEqual(len(matches), 1)
        self.assertIn(self.org_a.slug, matches[0]['title'])

    def test_autofill_in_org_b_returns_only_org_b_match(self):
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://shared.test/login',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
            HTTP_X_ORGANIZATION_ID=str(self.org_b.id),
        )
        matches = r.json()['matches']
        self.assertEqual(len(matches), 1)
        self.assertIn(self.org_b.slug, matches[0]['title'])

    def test_token_pinned_to_org_a_ignores_b(self):
        # Issue a new token pinned to org_a; even without an X-Organization-Id
        # header, requests resolve to org_a.
        from vault.models import WebExtensionAuthToken
        secret_a, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org_a,
        )
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://shared.test/login',
            HTTP_AUTHORIZATION=f'Bearer {secret_a}',
        )
        matches = r.json()['matches']
        self.assertEqual(len(matches), 1)
        self.assertIn(self.org_a.slug, matches[0]['title'])

    def test_token_pinned_to_org_a_ignores_header_for_org_b(self):
        # A pinned token never acts for another customer, whatever the
        # X-Organization-Id header says.
        from vault.models import WebExtensionAuthToken
        secret_a, _ = WebExtensionAuthToken.issue(
            user=self.user, organization=self.org_a,
        )
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://shared.test/login',
            HTTP_AUTHORIZATION=f'Bearer {secret_a}',
            HTTP_X_ORGANIZATION_ID=str(self.org_b.id),
        )
        self.assertEqual(r.status_code, 200)
        matches = r.json()['matches']
        self.assertEqual(len(matches), 1)
        self.assertIn(self.org_a.slug, matches[0]['title'])
        self.assertNotIn(self.org_b.slug, matches[0]['title'])

    def test_unpinned_token_still_honours_header(self):
        r = self.c.get(
            '/vault/api/extension/autofill/?url=https://shared.test/login',
            HTTP_AUTHORIZATION=f'Bearer {self.secret}',
            HTTP_X_ORGANIZATION_ID=str(self.org_b.id),
        )
        self.assertEqual(r.status_code, 200)
        matches = r.json()['matches']
        self.assertEqual(len(matches), 1)
        self.assertIn(self.org_b.slug, matches[0]['title'])

    def test_token_rejected_when_user_deactivated(self):
        url = '/vault/api/extension/autofill/?url=https://shared.test/login'
        headers = {
            'HTTP_AUTHORIZATION': f'Bearer {self.secret}',
            'HTTP_X_ORGANIZATION_ID': str(self.org_a.id),
        }
        self.assertEqual(self.c.get(url, **headers).status_code, 200)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.c.get(url, **headers).status_code, 401)


class LegacyFernetDecryptTests(TestCase):
    """
    v3.17.453 — `vault.encryption.decrypt` and `vault.encryption_v2.decrypt_v2`
    must accept legacy Fernet-encoded blobs (signature `gAAAAA`). 5 entries
    on prod (id 103-107) were stored this way by an earlier code version
    that called `cryptography.fernet.Fernet.encrypt` directly. Standard
    `base64.b64decode` rejects the URL-safe base64 they produce, so
    without the Fernet detection branch the API returns 500 and the user
    sees "Failed to decrypt password."
    """

    def _fernet_encrypt(self, plaintext: str) -> str:
        """Reproduce the legacy Fernet encode using the configured master key."""
        import base64
        from cryptography.fernet import Fernet
        from vault.encryption import get_master_key
        key = get_master_key()
        return Fernet(base64.urlsafe_b64encode(key)).encrypt(
            plaintext.encode('utf-8'),
        ).decode('ascii')

    def test_v1_decrypt_handles_fernet_blob(self):
        from vault.encryption import decrypt
        token = self._fernet_encrypt('hunter2-legacy')
        self.assertTrue(token.startswith('gAAAAA'),
                        'Fernet token signature should appear')
        # Token contains URL-safe base64 chars that standard base64 rejects.
        # Pre-fix this call raised EncryptionError on b64decode.
        self.assertEqual(decrypt(token), 'hunter2-legacy')

    def test_v2_decrypt_routes_fernet_blob_through_v1(self):
        from vault.encryption_v2 import decrypt_v2
        token = self._fernet_encrypt('legacy-secret-via-v2')
        # decrypt_v2 with default args — should detect the gAAAAA prefix
        # and bypass its own base64 path.
        self.assertEqual(decrypt_v2(token), 'legacy-secret-via-v2')

    def test_password_get_password_handles_fernet_blob(self):
        """End-to-end: Password.get_password() (model helper) decrypts Fernet."""
        from vault.models import Password
        from core.models import Organization
        org = Organization.objects.create(name='LegacyOrg', slug='legacy')
        token = self._fernet_encrypt('end-to-end-legacy')
        p = Password.objects.create(
            organization=org, title='Legacy Fernet entry',
            encrypted_password=token,
        )
        self.assertEqual(p.get_password(), 'end-to-end-legacy')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, HIBP_CHECK_ON_SAVE=False)
class PasswordFormTOTPForAnyTypeTests(TestCase):
    """A TOTP secret can be stored on ANY password type, not only 'otp'.

    Guards the regression reported in discussion #21: the entry form used to
    hide the TOTP fields for every type except 'otp', so a user could never
    attach a 2FA secret to a website/database/etc. credential. The backend
    always supported it — this exercises that save path end-to-end.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='TOTPForm', slug='totp-form')

    def _form(self, **overrides):
        from vault.forms import PasswordForm
        data = {
            'title': 'Web login with 2FA',
            'password_type': 'website',
            'plaintext_password': 'sup3r-secret-pw',
            'plaintext_otp_secret': 'JBSWY3DPEHPK3PXP',
            'client_access_mode': 'none',
        }
        data.update(overrides)
        return PasswordForm(data=data, organization=self.org)

    def test_website_password_stores_totp_secret(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors.as_json())
        pw = form.save()
        # Both the password AND the TOTP secret persist on one record.
        self.assertEqual(pw.password_type, 'website')
        self.assertEqual(pw.get_password(), 'sup3r-secret-pw')
        self.assertTrue(pw.otp_secret, 'TOTP secret should be stored for a website entry')
        otp = pw.generate_otp()
        self.assertEqual(len(otp['code']), 6)
        self.assertTrue(otp['code'].isdigit())

    def test_generate_new_secret_on_non_otp_type(self):
        form = self._form(plaintext_otp_secret='', generate_new_secret='on',
                          password_type='database')
        self.assertTrue(form.is_valid(), form.errors.as_json())
        pw = form.save()
        self.assertTrue(pw.otp_secret, 'auto-generated TOTP secret should be stored')
        self.assertEqual(len(pw.generate_otp()['code']), 6)
