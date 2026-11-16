"""v3.17.688 — Microsoft (Azure AD / Entra ID) sign-in is matched on the
verified (tenant id, object id), never on an e-mail address.

Nothing here talks to Microsoft: ID tokens are signed with a throwaway RSA key
and the JWKS lookup and MSAL's token exchange are patched.
"""
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from msal.oauth2cli.oidc import Client as OidcClient

from accounts import azure_auth
from accounts.azure_auth import (
    AzureADBackend, AzureIdentity, AzureIdentityError, allowed_tenants, load_azure_config,
    nonce_claim, resolve_sso_user, verify_id_token,
)
from accounts.models import AzureADLinkRequest, Membership, UserProfile
from audit.models import AuditLog
from core.models import Organization, SystemSetting

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]

TENANT = '11111111-1111-4111-8111-111111111111'
OTHER_TENANT = '22222222-2222-4222-8222-222222222222'
CLIENT_ID = '33333333-3333-4333-8333-333333333333'
NONCE = 'n-0S6_WzA2Mj'

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _oid():
    return str(uuid.uuid4())


def _token(oid, tid=TENANT, nonce=nonce_claim(NONCE), aud=CLIENT_ID, key=_KEY, email='alice@example.com', **over):
    now = int(time.time())
    claims = {
        'iss': f'https://login.microsoftonline.com/{tid}/v2.0', 'aud': aud, 'tid': tid, 'oid': oid,
        'sub': 'pairwise-sub', 'nonce': nonce, 'iat': now, 'nbf': now, 'exp': now + 3600,
        'preferred_username': email, 'name': 'Alice Example',
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test-kid'})


def _jwks(key=_KEY):
    return SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=key.public_key()))


def _configure(tenant_id=TENANT, allowed='', auto_create=None):
    s = SystemSetting.get_settings()
    s.azure_ad_enabled = True
    s.azure_ad_tenant_id = tenant_id
    s.azure_ad_client_id = CLIENT_ID
    s.azure_ad_client_secret = 'test-client-secret'
    s.azure_ad_redirect_uri = 'http://testserver/accounts/auth/azure/callback/'
    s.azure_ad_allowed_tenant_ids = allowed
    if auto_create is not None:
        s.azure_ad_auto_create_users = auto_create
    s.save()
    return load_azure_config()


def _identity(oid, tid=TENANT, email='alice@example.com'):
    with patch.object(azure_auth, '_jwks_client', return_value=_jwks()):
        return verify_id_token(_token(oid, tid=tid, email=email), load_azure_config(), NONCE)


def _link(user, oid, tid=TENANT, explicit=True):
    p, _ = UserProfile.objects.get_or_create(user=user)
    p.azure_ad_oid, p.azure_ad_tid = oid, tid
    p.azure_ad_linked_at = timezone.now() if explicit else None
    p.save()
    return p


class IdTokenVerificationTests(TestCase):
    def setUp(self):
        self.config = _configure()
        self.oid = _oid()

    def _verify(self, token, key=_KEY, nonce=NONCE, config=None):
        with patch.object(azure_auth, '_jwks_client', return_value=_jwks(key)):
            return verify_id_token(token, config or self.config, nonce)

    def test_valid_token_gives_tid_and_oid(self):
        ident = self._verify(_token(self.oid))
        self.assertEqual((ident.tid, ident.oid), (TENANT, self.oid))

    def test_signature_audience_expiry_and_nonce_are_checked(self):
        bad = [
            _token(self.oid, key=_OTHER_KEY),                            # not Microsoft's key
            _token(self.oid, aud='44444444-4444-4444-8444-444444444444'),  # another app's token
            _token(self.oid, exp=int(time.time()) - 3600),              # expired
            _token(self.oid, nonce=nonce_claim('another-flow')),       # replayed into this flow
            _token(self.oid, nonce=NONCE),                              # unhashed nonce
            _token(self.oid, nonce=None),                               # no nonce
            _token(self.oid, iss=f'https://login.microsoftonline.com/{OTHER_TENANT}/v2.0'),
            _token(None),                                               # no oid
        ]
        for token in bad:
            with self.assertRaises(AzureIdentityError) as cm:
                self._verify(token)
            self.assertEqual(cm.exception.code, 'invalid_token')
        unsigned = jwt.encode({'tid': TENANT, 'oid': self.oid, 'nonce': NONCE, 'aud': CLIENT_ID},
                              None, algorithm='none')
        with self.assertRaises(AzureIdentityError):
            self._verify(unsigned)

    def test_other_tenant_refused_unless_allowlisted(self):
        with self.assertRaises(AzureIdentityError) as cm:
            self._verify(_token(self.oid, tid=OTHER_TENANT))
        self.assertEqual(cm.exception.code, 'tenant_not_allowed')
        config = _configure(allowed=OTHER_TENANT)
        self.assertEqual(self._verify(_token(self.oid, tid=OTHER_TENANT), config=config).tid, OTHER_TENANT)

    def test_multi_tenant_authority_needs_an_allowlist(self):
        config = _configure(tenant_id='organizations')
        self.assertEqual(allowed_tenants(config), frozenset())
        with self.assertRaises(AzureIdentityError) as cm:
            self._verify(_token(self.oid), config=config)
        self.assertEqual(cm.exception.code, 'tenant_not_allowed')
        config = _configure(tenant_id='common', allowed=f'{TENANT}\nnot-a-guid')
        self.assertEqual(allowed_tenants(config), frozenset({TENANT}))
        self.assertEqual(self._verify(_token(self.oid), config=config).tid, TENANT)

    def test_identity_cannot_be_built_without_verification(self):
        with self.assertRaises(TypeError):
            AzureIdentity(tid=TENANT, oid=self.oid, email='', name='', given_name='', family_name='')
        self.assertIsNone(AzureADBackend().authenticate(None, azure_identity={'tid': TENANT, 'oid': self.oid}))
        self.assertIsNone(AzureADBackend().authenticate(None, azure_token={'access_token': 'x'}))


class AccountMatchingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.config = _configure()
        self.oid = _oid()

    def test_email_only_match_is_refused_and_recorded(self):
        victim = User.objects.create_user('alice', 'Alice@Example.com', 'pw')
        user, err = resolve_sso_user(_identity(self.oid), self.config)
        self.assertIsNone(user)
        self.assertEqual(err, 'link_required')
        self.assertEqual(UserProfile.objects.get(user=victim).azure_ad_oid, '')
        req = AzureADLinkRequest.objects.get(user=victim)
        self.assertEqual((req.status, req.tenant_id, req.object_id), ('pending', TENANT, self.oid))
        self.assertTrue(AuditLog.objects.filter(extra_data__event='azure_sso_email_match_refused',
                                                success=False).exists())
        resolve_sso_user(_identity(self.oid), self.config)  # retry: still one request
        self.assertEqual(AzureADLinkRequest.objects.filter(user=victim).count(), 1)

    def test_superuser_email_match_is_never_linked(self):
        admin = User.objects.create_superuser('root', 'alice@example.com', 'pw')
        _configure(auto_create=True)
        user, err = resolve_sso_user(_identity(self.oid), load_azure_config())
        self.assertIsNone(user)
        self.assertEqual(err, 'link_required')
        self.assertEqual(UserProfile.objects.get(user=admin).azure_ad_oid, '')
        self.assertEqual(User.objects.count(), 1)  # not auto-created either

    def test_oid_match_is_accepted(self):
        alice = User.objects.create_user('alice', 'someone-else@example.com', 'pw')
        _link(alice, self.oid)
        user, err = resolve_sso_user(_identity(self.oid, email='renamed@example.com'), self.config)
        self.assertEqual((user, err), (alice, None))

    def test_tid_mismatch_is_refused(self):
        alice = User.objects.create_user('alice', 'alice@example.com', 'pw')
        _link(alice, self.oid, tid=OTHER_TENANT)
        user, err = resolve_sso_user(_identity(self.oid), self.config)
        self.assertIsNone(user)
        self.assertEqual(err, 'tenant_mismatch')
        self.assertTrue(AuditLog.objects.filter(extra_data__event='azure_sso_tenant_mismatch').exists())

    def test_legacy_link_keeps_working_and_captures_the_tenant(self):
        bob = User.objects.create_user('bob', 'bob@example.com', 'pw', is_staff=True)
        _link(bob, self.oid.upper(), tid='', explicit=False)
        user, err = resolve_sso_user(_identity(self.oid, email='bob@example.com'), self.config)
        self.assertEqual((user, err), (bob, None))
        self.assertEqual(UserProfile.objects.get(user=bob).azure_ad_tid, TENANT)

    def test_legacy_superuser_link_must_be_renewed(self):
        root = User.objects.create_superuser('root', 'root@example.com', 'pw')
        _link(root, self.oid, tid='', explicit=False)
        user, err = resolve_sso_user(_identity(self.oid, email='root@example.com'), self.config)
        self.assertIsNone(user)
        self.assertEqual(err, 'superuser_link_required')
        _link(root, self.oid)  # explicitly linked
        user, err = resolve_sso_user(_identity(self.oid, email='root@example.com'), self.config)
        self.assertEqual((user, err), (root, None))

    def test_inactive_linked_account_is_refused(self):
        u = User.objects.create_user('gone', 'gone@example.com', 'pw', is_active=False)
        _link(u, self.oid)
        self.assertEqual(resolve_sso_user(_identity(self.oid), self.config), (None, 'inactive'))

    def test_auto_create_is_off_by_default(self):
        self.assertFalse(SystemSetting._meta.get_field('azure_ad_auto_create_users').default)
        self.assertFalse(self.config['auto_create'])
        user, err = resolve_sso_user(_identity(self.oid, email='new@example.com'), self.config)
        self.assertEqual((user, err), (None, 'no_account'))
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_auto_created_user_has_no_access(self):
        Organization.objects.create(name='First Co', slug='first-co-688')
        config = _configure(auto_create=True)
        user, err = resolve_sso_user(_identity(self.oid, email='new@example.com'), config)
        self.assertIsNone(err)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(Membership.objects.filter(user=user).exists())
        p = UserProfile.objects.get(user=user)
        self.assertEqual((p.azure_ad_tid, p.azure_ad_oid, p.auth_source), (TENANT, self.oid, 'azure_ad'))
        again, _ = resolve_sso_user(_identity(self.oid, email='new@example.com'), config)
        self.assertEqual(again, user)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SignInFlowTests(TestCase):
    """The views, with MSAL's real flow generator and a patched token exchange."""

    def setUp(self):
        cache.clear()
        _configure()
        self.oid = _oid()
        self.oidc = OidcClient({'authorization_endpoint': f'https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize',
                                'token_endpoint': f'https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token'},
                               client_id=CLIENT_ID)
        self.app = MagicMock()
        self.app.initiate_auth_code_flow.side_effect = (
            lambda scopes, **kw: self.oidc.initiate_auth_code_flow(scope=scopes, **kw))
        patcher = patch.object(azure_auth.AzureOAuthClient, '_app', return_value=self.app)
        patcher.start()
        self.addCleanup(patcher.stop)
        jwks = patch.object(azure_auth, '_jwks_client', return_value=_jwks())
        jwks.start()
        self.addCleanup(jwks.stop)

    def _start(self, url=None, data=None):
        r = self.client.post(url, data) if data is not None else self.client.get(reverse('accounts:azure_login'))
        return r, self.client.session.get('azure_auth_flow')

    def _callback(self, flow, email='alice@example.com', oid=None):
        def exchange(f, resp, **kw):
            assert resp['state'] == f['state']
            return {'id_token': _token(oid or self.oid, nonce=nonce_claim(f['nonce']), email=email),
                    'access_token': 'a.e30.s', 'id_token_claims': {}}
        self.app.acquire_token_by_auth_code_flow.side_effect = exchange
        return self.client.get(reverse('accounts:azure_callback'), {'code': 'c', 'state': flow['state']})

    def test_login_uses_pkce_s256_and_a_nonce(self):
        r, flow = self._start()
        self.assertEqual(r.status_code, 302)
        q = parse_qs(urlparse(r['Location']).query)
        self.assertEqual(q['code_challenge_method'], ['S256'])
        self.assertTrue(q['code_challenge'][0])
        self.assertEqual(q['nonce'][0], nonce_claim(flow['nonce']))
        self.assertEqual(q['state'][0], flow['state'])
        self.assertTrue(flow['code_verifier'])
        self.assertNotIn(flow['code_verifier'], r['Location'])

    def test_linked_identity_signs_in(self):
        alice = User.objects.create_user('alice', 'alice@example.com', 'pw')
        _link(alice, self.oid)
        _, flow = self._start()
        r = self._callback(flow)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), alice.pk)
        self.assertNotIn('azure_auth_flow', self.client.session)

    def test_email_match_does_not_sign_in(self):
        User.objects.create_superuser('root', 'alice@example.com', 'pw')
        _, flow = self._start()
        r = self._callback(flow)
        self.assertRedirects(r, reverse('two_factor:login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_state_or_reused_flow_is_refused(self):
        _link(User.objects.create_user('alice', 'a@example.com', 'pw'), self.oid)
        _, flow = self._start()
        r = self.client.get(reverse('accounts:azure_callback'), {'code': 'c', 'state': 'forged'})
        self.assertNotIn('_auth_user_id', self.client.session)
        r = self._callback(flow)  # the flow was consumed by the failed attempt
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(r.status_code, 302)

    def test_user_links_after_reauthentication(self):
        alice = User.objects.create_user('alice', 'alice@example.com', 'pw-alice')
        self.client.force_login(alice)
        r, flow = self._start(reverse('accounts:azure_link_start'), {'password': 'wrong'})
        self.assertIsNone(flow)
        self.assertEqual(UserProfile.objects.get(user=alice).azure_ad_oid, '')
        r, flow = self._start(reverse('accounts:azure_link_start'), {'password': 'pw-alice'})
        self.assertEqual(urlparse(r['Location']).netloc, 'login.microsoftonline.com')
        r = self._callback(flow)
        self.assertRedirects(r, reverse('accounts:profile'), fetch_redirect_response=False)
        p = UserProfile.objects.get(user=alice)
        self.assertEqual((p.azure_ad_tid, p.azure_ad_oid), (TENANT, self.oid))
        self.assertIsNotNone(p.azure_ad_linked_at)
        self.assertTrue(AuditLog.objects.filter(extra_data__event='azure_sso_linked',
                                                extra_data__method='self').exists())

    def test_identity_linked_elsewhere_cannot_be_linked_again(self):
        _link(User.objects.create_user('bob', 'bob@example.com', 'pw'), self.oid)
        alice = User.objects.create_user('alice', 'alice@example.com', 'pw-alice')
        self.client.force_login(alice)
        _, flow = self._start(reverse('accounts:azure_link_start'), {'password': 'pw-alice'})
        self._callback(flow)
        self.assertEqual(UserProfile.objects.get(user=alice).azure_ad_oid, '')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AdminConfirmedLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.config = _configure()
        self.oid = _oid()
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw-admin')
        self.alice = User.objects.create_user('alice', 'alice@example.com', 'pw')
        resolve_sso_user(_identity(self.oid), self.config)
        self.req = AzureADLinkRequest.objects.get(user=self.alice)
        self.client.force_login(self.admin)

    def _decide(self, decision, password='pw-admin', user=None, req=None):
        user, req = user or self.alice, req or self.req
        return self.client.post(reverse('accounts:azure_link_request_decide', args=[user.pk, req.pk]),
                                {'decision': decision, 'password': password})

    def test_admin_approval_needs_their_password_then_links(self):
        self._decide('approve', password='wrong')
        self.assertEqual(UserProfile.objects.get(user=self.alice).azure_ad_oid, '')
        self._decide('approve')
        self.assertEqual(AzureADLinkRequest.objects.get(pk=self.req.pk).status, 'approved')
        self.assertEqual(resolve_sso_user(_identity(self.oid), self.config), (self.alice, None))

    def test_reject_links_nothing(self):
        self._decide('reject')
        self.assertEqual(AzureADLinkRequest.objects.get(pk=self.req.pk).status, 'rejected')
        self.assertEqual(resolve_sso_user(_identity(self.oid), self.config)[1], 'link_required')

    def test_admin_cannot_confirm_a_link_to_their_own_account(self):
        resolve_sso_user(_identity(_oid(), email='admin@example.com'), self.config)
        own = AzureADLinkRequest.objects.get(user=self.admin)
        self._decide('approve', user=self.admin, req=own)
        self.assertEqual(AzureADLinkRequest.objects.get(pk=own.pk).status, 'pending')
        self.assertEqual(UserProfile.objects.get(user=self.admin).azure_ad_oid, '')

    def test_non_superuser_cannot_decide(self):
        tech = User.objects.create_user('tech', 't@example.com', 'pw-tech', is_staff=True)
        self.client.force_login(tech)
        self._decide('approve', password='pw-tech')
        self.assertEqual(AzureADLinkRequest.objects.get(pk=self.req.pk).status, 'pending')

    def test_user_page_shows_the_request(self):
        r = self.client.get(reverse('accounts:user_detail', args=[self.alice.pk]))
        self.assertContains(r, self.oid)
        self.assertContains(r, 'Approve link')
