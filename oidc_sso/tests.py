"""Tests for the generic OIDC client, against a fake OP.

The fake OP generates its own RSA / EC keys, serves discovery + JWKS and a
token endpoint (with a real PKCE S256 check) through a stand-in for the
guarded requests session (oidc_sso.http.session_for). No network.
"""
import base64
import hashlib
import json
import secrets
import time
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate, UserProfile, UserType
from audit.models import AuditLog
from core.models import Organization

from . import claims as claimlib
from . import discovery, keys
from .http import OPError, check_url
from .models import (
    OIDCCustomerMapping, OIDCIdentity, OIDCManagedMembership, OIDCProvider, OIDCRoleMapping, OIDCSession,
    ReplayRecord,
)
from .tokens import LOGOUT_EVENT, TokenError, validate_id_token, validate_logout_token

User = get_user_model()

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
# MFA tests need the 2FA middleware itself.
MFA_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE if 'AxesMiddleware' not in m]

ISSUER = 'https://id.example.com/realms/agit8or'
CLIENT_ID = 'clientst0r-acme'
ALIAS = 'acme'
ORG_ID = '6f1c2a9e-3b7d-4c11-9a0e-2f5d8b7c1a01'


def _rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private_key, kid, alg):
    pub = private_key.public_key()
    if alg in ('RS256', 'PS256'):
        d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(pub))
    else:
        d = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(pub))
    d.update({'kid': kid, 'use': 'sig', 'alg': alg})
    return d


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._body = json.dumps(payload).encode()
        self.headers = {'Content-Type': 'application/json'}

    def iter_content(self, chunk_size=1):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOP:
    """A minimal OP: discovery, JWKS, token endpoint with PKCE."""

    def __init__(self, issuer=ISSUER):
        self.issuer = issuer
        self.keys = {'k1': (_rsa(), 'RS256')}
        self.signing_kid = 'k1'
        self.codes = {}
        self.calls = []
        self.token_requests = []
        self.discovery_overrides = {}

    # --- documents ---
    def discovery(self):
        doc = {
            'issuer': self.issuer,
            'authorization_endpoint': f'{self.issuer}/protocol/openid-connect/auth',
            'token_endpoint': f'{self.issuer}/protocol/openid-connect/token',
            'jwks_uri': f'{self.issuer}/protocol/openid-connect/certs',
            'userinfo_endpoint': f'{self.issuer}/protocol/openid-connect/userinfo',
            'end_session_endpoint': f'{self.issuer}/protocol/openid-connect/logout',
            'id_token_signing_alg_values_supported': ['RS256', 'ES256', 'HS256'],
            'code_challenge_methods_supported': ['S256'],
            'backchannel_logout_supported': True,
            'backchannel_logout_session_supported': True,
        }
        doc.update(self.discovery_overrides)
        return doc

    def jwks(self):
        return {'keys': [_jwk(k, kid, alg) for kid, (k, alg) in self.keys.items()]}

    # --- tokens ---
    def sign(self, claims, kid=None, alg=None, key=None):
        kid = kid or self.signing_kid
        k, kalg = self.keys.get(kid, (None, None))
        return jwt.encode(claims, key or k, algorithm=alg or kalg, headers={'kid': kid})

    def base_claims(self, **over):
        now = int(time.time())
        c = {
            'iss': self.issuer, 'aud': CLIENT_ID, 'azp': CLIENT_ID, 'sub': 'sub-alice',
            'exp': now + 300, 'iat': now, 'auth_time': now, 'sid': 'sid-1',
            'email': 'alice@example.com', 'email_verified': True,
            'given_name': 'Alice', 'family_name': 'Admin',
            'organization': {ALIAS: {'id': ORG_ID}},
            'resource_access': {CLIENT_ID: {'roles': [f'{ALIAS}:technician']}},
            'acr': 'urn:agit8or:acr:pwd', 'amr': ['pwd'],
        }
        c.update(over)
        return {k: v for k, v in c.items() if v is not None}

    def issue_code(self, auth_url, **claim_over):
        q = parse_qs(urlsplit(auth_url).query)
        code = secrets.token_urlsafe(16)
        claims = self.base_claims(nonce=q['nonce'][0], **claim_over)
        self.codes[code] = {'challenge': q['code_challenge'][0], 'claims': claims,
                            'redirect_uri': q['redirect_uri'][0]}
        return code, q['state'][0]

    # --- the fake transport ---
    def request(self, method, url, data=None, headers=None, auth=None, **kwargs):
        self.calls.append((method, url))
        if url.endswith('/.well-known/openid-configuration'):
            return FakeResponse(200, self.discovery())
        if url.endswith('/certs'):
            return FakeResponse(200, self.jwks())
        if url.endswith('/token') and method == 'POST':
            self.token_requests.append({'data': dict(data or {}), 'auth': auth})
            entry = self.codes.pop((data or {}).get('code'), None)
            if entry is None:
                return FakeResponse(400, {'error': 'invalid_grant'})
            verifier = data.get('code_verifier', '')
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            if challenge != entry['challenge'] or data.get('redirect_uri') != entry['redirect_uri']:
                return FakeResponse(400, {'error': 'invalid_grant'})
            return FakeResponse(200, {'access_token': 'at-' + secrets.token_hex(8), 'token_type': 'Bearer',
                                      'id_token': self.sign(entry['claims'])})
        return FakeResponse(404, {'error': 'not_found'})


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.op = FakeOP()
        patcher = mock.patch('oidc_sso.http.session_for', lambda provider: self.op)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = OIDCProvider(
            name='Agit8or Identity', slug='agit8or', enabled=True, issuer=ISSUER, client_id=CLIENT_ID,
            msp_org_alias=ALIAS, msp_org_id=ORG_ID)
        keys.generate_keypair(self.provider)
        self.provider.save()
        self.tech_role = RoleTemplate.objects.create(name='SSO Technician', audience='internal')
        self.cust_role = RoleTemplate.objects.create(name='SSO Customer Tech', audience='any')
        self.staff_map = OIDCRoleMapping.objects.create(provider=self.provider, role_key='technician',
                                                        target='staff', role_template=self.tech_role)
        self.cust_map = OIDCRoleMapping.objects.create(provider=self.provider, role_key='technician',
                                                       target='customer', role_template=self.cust_role)
        self.alice = User.objects.create_user('alice', 'alice@example.com', 'pw-Alice-12345!')
        prof = self.alice.profile
        prof.user_type = UserType.STAFF
        prof.save()

    def link(self, user=None, sub='sub-alice', manages=False):
        return OIDCIdentity.objects.create(provider=self.provider, issuer=ISSUER, sub=sub,
                                           user=user or self.alice, manages_staff_role=manages)

    def start(self, url_name='oidc_sso:login', method='get', data=None):
        url = reverse(url_name, args=[self.provider.slug])
        resp = (self.client.post(url, data or {}) if method == 'post' else self.client.get(url))
        self.assertEqual(resp.status_code, 302, getattr(resp, 'content', b'')[:300])
        return resp['Location']

    def sso_login(self, **claim_over):
        auth_url = self.start()
        code, state = self.op.issue_code(auth_url, **claim_over)
        return self.client.get(reverse('oidc_sso:callback', args=[self.provider.slug]),
                               {'code': code, 'state': state})

    def denied(self, reason):
        return AuditLog.objects.filter(action='sso_login_denied', extra_data__reason=reason).exists()

    def logged_in(self):
        return '_auth_user_id' in self.client.session


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LoginFlowTests(_Base):
    def test_happy_path(self):
        self.link()
        resp = self.sso_login()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/core/dashboard/')
        self.assertEqual(resp['Referrer-Policy'], 'no-referrer')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.alice.pk)
        self.assertEqual(self.client.session['_auth_user_backend'], 'oidc_sso.backends.OIDCBackend')
        self.assertTrue(self.client.session['oidc_sso_authenticated'])
        self.assertFalse(self.client.session['oidc_sso_mfa'])
        row = OIDCSession.objects.get(user=self.alice)
        self.assertEqual(row.sid, 'sid-1')
        self.assertEqual(row.session_key, self.client.session.session_key)
        self.assertTrue(AuditLog.objects.filter(action='sso_login', user=self.alice).exists())
        self.assertIsNotNone(OIDCIdentity.objects.get().last_login_at)
        # PKCE + private_key_jwt sent to the token endpoint
        req = self.op.token_requests[-1]['data']
        self.assertIn('code_verifier', req)
        self.assertEqual(req['client_assertion_type'], 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer')
        assertion = jwt.decode(req['client_assertion'], key=jwt.PyJWK(keys.public_jwk(self.provider)).key,
                               algorithms=['RS256'], audience=self.op.discovery()['token_endpoint'])
        self.assertEqual(assertion['iss'], CLIENT_ID)
        self.assertEqual(assertion['sub'], CLIENT_ID)

    def test_authorize_request_parameters(self):
        q = parse_qs(urlsplit(self.start()).query)
        self.assertEqual(q['code_challenge_method'], ['S256'])
        self.assertEqual(q['response_type'], ['code'])
        self.assertIn('openid', q['scope'][0].split())
        self.assertTrue(q['state'][0] and q['nonce'][0])
        pending = self.client.session['oidc_sso_pending'][q['state'][0]]
        verifier = pending['verifier']
        self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),
                         q['code_challenge'][0])

    def test_no_tokens_in_audit_log(self):
        self.link()
        self.sso_login()
        blob = json.dumps(list(AuditLog.objects.values_list('extra_data', 'description')))
        self.assertNotIn('eyJ', blob)  # no JWTs
        self.assertNotIn('code_verifier', blob)

    def test_state_mismatch(self):
        self.link()
        auth_url = self.start()
        code, _state = self.op.issue_code(auth_url)
        resp = self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': 'forged'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('bad_state'))

    def test_state_single_use(self):
        self.link()
        auth_url = self.start()
        code, state = self.op.issue_code(auth_url)
        cb = reverse('oidc_sso:callback', args=['agit8or'])
        self.client.get(cb, {'code': code, 'state': state})
        self.assertTrue(self.logged_in())
        self.client.logout()
        resp = self.client.get(cb, {'code': code, 'state': state})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('bad_state'))

    def test_nonce_replay_rejected(self):
        """An ID token minted for an earlier flow (its nonce) is refused in a new flow."""
        self.link()
        first = self.start()
        old_nonce = parse_qs(urlsplit(first).query)['nonce'][0]
        auth_url = self.start()
        code, state = self.op.issue_code(auth_url)
        self.op.codes[code]['claims']['nonce'] = old_nonce
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('bad_nonce'))

    def test_pkce_verifier_mismatch(self):
        self.link()
        auth_url = self.start()
        code, state = self.op.issue_code(auth_url)
        self.op.codes[code]['challenge'] = 'not-the-challenge'
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('token_exchange_failed'))

    def test_op_error_param(self):
        auth_url = self.start()
        state = parse_qs(urlsplit(auth_url).query)['state'][0]
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'error': 'access_denied', 'state': state})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('op_error'))

    def test_email_match_never_links(self):
        self.provider.jit_provisioning = True
        self.provider.save()
        resp = self.sso_login(sub='sub-someone-else')  # alice@example.com exists locally
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('email_collision'))
        self.assertFalse(OIDCIdentity.objects.exists())
        self.assertEqual(User.objects.filter(email__iexact='alice@example.com').count(), 1)

    def test_unknown_identity_jit_disabled(self):
        self.sso_login(sub='sub-new', email='new@example.com')
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('unknown_identity'))
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_jit_requires_verified_email(self):
        self.provider.jit_provisioning = True
        self.provider.save()
        self.sso_login(sub='sub-new', email='new@example.com', email_verified=False)
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('email_not_verified'))
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_jit_requires_role(self):
        self.provider.jit_provisioning = True
        self.provider.save()
        self.sso_login(sub='sub-new', email='new@example.com',
                       resource_access={CLIENT_ID: {'roles': [f'{ALIAS}:unmapped']}})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('no_role'))
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_jit_creates_managed_staff(self):
        self.provider.jit_provisioning = True
        self.provider.save()
        self.sso_login(sub='sub-new', email='new@example.com')
        self.assertTrue(self.logged_in())
        user = User.objects.get(email='new@example.com')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(user.profile.user_type, UserType.STAFF)
        self.assertEqual(user.profile.global_role_template, self.tech_role)
        self.assertEqual(user.profile.auth_source, 'oidc')
        self.assertTrue(OIDCIdentity.objects.get(user=user).manages_staff_role)

    def test_msp_pin_alias_mismatch(self):
        self.link()
        self.sso_login(organization={'other-msp': {'id': ORG_ID}},
                       resource_access={CLIENT_ID: {'roles': ['other-msp:technician']}})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('org_mismatch'))

    def test_msp_pin_id_mismatch(self):
        self.link()
        self.sso_login(organization={ALIAS: {'id': 'someone-elses-uuid'}})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('org_mismatch'))

    def test_no_role_denied(self):
        self.link()
        self.sso_login(resource_access={CLIENT_ID: {'roles': []}})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('no_role'))

    def test_other_orgs_roles_discarded(self):
        self.link()
        self.sso_login(organization={ALIAS: {'id': ORG_ID}, 'evil': {'id': 'x'}},
                       resource_access={CLIENT_ID: {'roles': ['evil:technician']}})
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('no_role'))

    def test_inactive_user_denied(self):
        self.link()
        self.alice.is_active = False
        self.alice.save()
        self.sso_login()
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('user_inactive'))

    def test_wrong_issuer_in_token(self):
        self.link()
        self.sso_login(iss='https://evil.example.com/realms/agit8or')
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('bad_iss'))

    def test_rp_initiated_logout(self):
        self.link()
        self.sso_login()
        resp = self.client.post(reverse('logout'))
        self.assertEqual(resp.status_code, 302)
        loc = urlsplit(resp['Location'])
        self.assertTrue(resp['Location'].startswith(f'{ISSUER}/protocol/openid-connect/logout'))
        q = parse_qs(loc.query)
        self.assertEqual(q['client_id'], [CLIENT_ID])
        self.assertIn('id_token_hint', q)
        self.assertTrue(q['post_logout_redirect_uri'][0].endswith('/account/login/'))
        self.assertFalse(self.logged_in())
        self.assertFalse(OIDCSession.objects.exists())

    def test_local_logout_unchanged(self):
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('logout'))
        self.assertEqual(resp['Location'], '/')

    def test_client_secret_basic(self):
        self.link()
        self.provider.client_auth_method = OIDCProvider.AUTH_CLIENT_SECRET_BASIC
        self.provider.client_secret = 's3cr3t value'
        self.provider.save()
        self.sso_login()
        self.assertTrue(self.logged_in())
        req = self.op.token_requests[-1]
        self.assertEqual(req['auth'], (CLIENT_ID, 's3cr3t%20value'))
        self.assertNotIn('client_assertion', req['data'])

    def test_userinfo_merge_requires_same_sub(self):
        self.link()
        self.provider.use_userinfo = True
        self.provider.save()
        orig = self.op.request

        def with_userinfo(method, url, **kw):
            if url.endswith('/userinfo'):
                return FakeResponse(200, {'sub': 'someone-else'})
            return orig(method, url, **kw)
        self.op.request = with_userinfo
        self.sso_login()
        self.assertFalse(self.logged_in())
        self.assertTrue(self.denied('userinfo_sub'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MappingTests(_Base):
    def setUp(self):
        super().setUp()
        self.c1 = Organization.objects.create(name='Customer One', slug='sso-c1')
        self.c2 = Organization.objects.create(name='Customer Two', slug='sso-c2')
        self.c3 = Organization.objects.create(name='Customer Three', slug='sso-c3')
        OIDCCustomerMapping.objects.create(provider=self.provider, customer_key='cust-1', organization=self.c1)
        OIDCCustomerMapping.objects.create(provider=self.provider, customer_key='cust-2', organization=self.c2)

    def roles(self, *items):
        return {CLIENT_ID: {'roles': [f'{ALIAS}:{i}' for i in items]}}

    def test_customer_claims_narrow_managed_staff(self):
        self.link(manages=True)
        self.sso_login(resource_access=self.roles('technician', 'customer:cust-1:technician'))
        prof = UserProfile.objects.get(user=self.alice)
        self.assertEqual(prof.global_role_template, self.tech_role)
        self.assertEqual(prof.client_scope, 'selected')
        self.assertEqual(set(prof.scope_organizations.values_list('pk', flat=True)), {self.c1.pk})
        # without customer claims: back to the mapping's own scope
        self.client.logout()
        self.sso_login(resource_access=self.roles('technician'))
        prof.refresh_from_db()
        self.assertEqual(prof.client_scope, 'all')
        self.assertFalse(prof.scope_organizations.exists())

    def test_customer_claims_never_widen_assigned_scope(self):
        self.staff_map.client_scope = 'assigned'
        self.staff_map.save()
        self.link(manages=True)
        self.sso_login(resource_access=self.roles('technician', 'customer:cust-1:technician',
                                                  'customer:cust-2:technician'))
        prof = UserProfile.objects.get(user=self.alice)
        self.assertEqual(prof.client_scope, 'selected')
        # no technician access assignment anywhere: the ceiling is empty
        self.assertFalse(prof.scope_organizations.exists())

    def test_linked_account_role_untouched(self):
        other = RoleTemplate.objects.create(name='Local Role', audience='internal')
        prof = self.alice.profile
        prof.global_role_template = other
        prof.client_scope = 'all'
        prof.save()
        self.link(manages=False)
        self.sso_login(resource_access=self.roles('technician', 'customer:cust-1:technician'))
        prof.refresh_from_db()
        self.assertEqual(prof.global_role_template, other)
        self.assertEqual(prof.client_scope, 'all')

    def test_never_grants_superuser(self):
        self.link(manages=True)
        self.sso_login()
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_superuser)
        self.assertFalse(self.alice.is_staff)

    def test_sso_memberships_reconciled_manual_untouched(self):
        manual_role = RoleTemplate.objects.create(name='Manual', audience='any')
        manual = Membership.objects.create(user=self.alice, organization=self.c2, role_template=manual_role)
        self.link()
        self.sso_login(resource_access=self.roles('technician', 'customer:cust-1:technician',
                                                  'customer:cust-2:technician'))
        m1 = Membership.objects.get(user=self.alice, organization=self.c1)
        self.assertTrue(m1.is_active)
        self.assertEqual(m1.role_template, self.cust_role)
        self.assertTrue(OIDCManagedMembership.objects.filter(membership=m1).exists())
        manual.refresh_from_db()
        self.assertEqual(manual.role_template, manual_role)
        self.assertFalse(OIDCManagedMembership.objects.filter(membership=manual).exists())

        self.client.logout()
        self.sso_login(resource_access=self.roles('technician'))
        m1.refresh_from_db()
        manual.refresh_from_db()
        self.assertFalse(m1.is_active)
        self.assertTrue(manual.is_active)

        self.client.logout()
        self.sso_login(resource_access=self.roles('technician', 'customer:cust-1:technician'))
        m1.refresh_from_db()
        self.assertTrue(m1.is_active)

    def test_removal_applies_even_when_login_refused(self):
        self.link()
        self.sso_login(resource_access=self.roles('technician', 'customer:cust-1:technician'))
        m1 = Membership.objects.get(user=self.alice, organization=self.c1)
        self.client.logout()
        self.sso_login(resource_access=self.roles())
        self.assertFalse(self.logged_in())
        m1.refresh_from_db()
        self.assertFalse(m1.is_active)

    def test_unmapped_customer_key_ignored(self):
        self.link()
        self.sso_login(resource_access=self.roles('technician', 'customer:unknown:technician'))
        self.assertTrue(self.logged_in())
        self.assertFalse(Membership.objects.filter(user=self.alice).exists())

    def test_extract_roles(self):
        roles = claimlib.extract_roles(self.provider, {'resource_access': {CLIENT_ID: {'roles': [
            'acme:technician', 'acme:customer:k1:readonly', 'other:admin', 'acme:bad:shape', 7]}}})
        self.assertEqual(roles.staff, {'technician'})
        self.assertEqual(roles.customers, {'k1': {'readonly'}})


class TokenValidationTests(_Base):
    def claims(self, **over):
        return self.op.base_claims(nonce='n-1', **over)

    def check(self, token, **kw):
        return validate_id_token(self.provider, token, nonce='n-1', **kw)

    def assertReason(self, token, reason, **kw):
        with self.assertRaises(TokenError) as cm:
            self.check(token, **kw)
        self.assertEqual(cm.exception.reason, reason)

    def test_valid(self):
        self.assertEqual(self.check(self.op.sign(self.claims()))['sub'], 'sub-alice')

    def test_wrong_iss(self):
        self.assertReason(self.op.sign(self.claims(iss='https://id.example.com/realms/other')), 'bad_iss')

    def test_wrong_aud(self):
        self.assertReason(self.op.sign(self.claims(aud='another-client', azp='another-client')), 'bad_aud')

    def test_wrong_azp(self):
        self.assertReason(self.op.sign(self.claims(azp='another-client')), 'bad_azp')

    def test_multiple_aud_needs_azp(self):
        self.assertReason(self.op.sign(self.claims(aud=[CLIENT_ID, 'x'], azp=None)), 'bad_azp')
        self.check(self.op.sign(self.claims(aud=[CLIENT_ID, 'x'])))

    def test_expired(self):
        now = int(time.time())
        self.assertReason(self.op.sign(self.claims(exp=now - 3600, iat=now - 4000)), 'expired')

    def test_issued_in_future(self):
        self.assertReason(self.op.sign(self.claims(iat=int(time.time()) + 3600)), 'not_yet_valid')

    def test_alg_none_rejected(self):
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b'=').decode()
        body = base64.urlsafe_b64encode(json.dumps(self.claims()).encode()).rstrip(b'=').decode()
        self.assertReason(f'{header}.{body}.', 'bad_alg')

    def test_hs256_rejected(self):
        # nosemgrep: python.jwt.security.jwt-hardcode.jwt-python-hardcoded-secret -- test: an HS256 token must be refused
        token = jwt.encode(self.claims(), 'shared-secret-of-sufficient-length-123', algorithm='HS256',
                           headers={'kid': 'k1'})
        self.assertReason(token, 'bad_alg')

    def test_bad_signature(self):
        forged = jwt.encode(self.claims(), _rsa(), algorithm='RS256', headers={'kid': 'k1'})
        self.assertReason(forged, 'bad_signature')

    def test_nonce_mismatch(self):
        self.assertReason(self.op.sign(self.op.base_claims(nonce='other')), 'bad_nonce')

    def test_max_age(self):
        old = int(time.time()) - 3600
        self.assertReason(self.op.sign(self.claims(auth_time=old)), 'stale_auth', max_age=300)
        self.assertReason(self.op.sign(self.claims(auth_time=None)), 'no_auth_time', max_age=300)

    def test_es256_key(self):
        self.op.keys['e1'] = (ec.generate_private_key(ec.SECP256R1()), 'ES256')
        self.assertEqual(self.check(self.op.sign(self.claims(), kid='e1'))['sub'], 'sub-alice')

    def test_algorithm_not_enabled_for_provider(self):
        self.provider.allowed_algorithms = 'ES256'
        self.assertReason(self.op.sign(self.claims()), 'bad_alg')

    def test_jwks_rotation_refetches_once(self):
        self.check(self.op.sign(self.claims()))  # caches JWKS with k1
        self.op.keys = {'k2': (_rsa(), 'RS256')}
        self.op.signing_kid = 'k2'
        before = sum(1 for _m, u in self.op.calls if u.endswith('/certs'))
        self.check(self.op.sign(self.claims()))
        after = sum(1 for _m, u in self.op.calls if u.endswith('/certs'))
        self.assertEqual(after - before, 1)

    def test_unknown_kid_refetch_throttled(self):
        self.check(self.op.sign(self.claims()))
        stranger = _rsa()
        token = jwt.encode(self.claims(), stranger, algorithm='RS256', headers={'kid': 'nope'})
        before = sum(1 for _m, u in self.op.calls if u.endswith('/certs'))
        self.assertReason(token, 'unknown_key')
        self.assertReason(token, 'unknown_key')
        after = sum(1 for _m, u in self.op.calls if u.endswith('/certs'))
        self.assertEqual(after - before, 1)

    def test_discovery_issuer_must_match(self):
        self.op.discovery_overrides = {'issuer': 'https://id.example.com/realms/agit8or/'}
        with self.assertRaises(OPError):
            discovery.get_metadata(self.provider, force=True)

    def test_mfa_rules(self):
        p = self.provider
        self.assertTrue(claimlib.mfa_satisfied(p, {'acr': 'urn:agit8or:acr:mfa', 'amr': ['pwd', 'otp']}))
        self.assertTrue(claimlib.mfa_satisfied(p, {'amr': ['pwd', 'otp']}))
        self.assertFalse(claimlib.mfa_satisfied(p, {'acr': 'urn:agit8or:acr:pwd', 'amr': ['pwd']}))
        # acr says MFA but amr says password only: inconsistent
        self.assertFalse(claimlib.mfa_satisfied(p, {'acr': 'urn:agit8or:acr:mfa', 'amr': ['pwd']}))


@override_settings(MIDDLEWARE=MFA_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MFATests(_Base):
    def setUp(self):
        super().setUp()
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.create(user=self.alice, name='phone', confirmed=True)
        self.link()

    def test_local_totp_required_when_idp_mfa_not_accepted(self):
        self.sso_login(acr='urn:agit8or:acr:mfa', amr=['pwd', 'otp'])
        self.assertTrue(self.logged_in())
        resp = self.client.get(reverse('oidc_sso:account'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith(reverse('oidc_sso:verify')))
        self.assertTrue(self.logged_in())  # not ended: sent to enter the code

    def test_idp_mfa_accepted(self):
        self.provider.accept_idp_mfa = True
        self.provider.save()
        self.sso_login(acr='urn:agit8or:acr:mfa', amr=['pwd', 'otp'])
        self.assertTrue(self.client.session['oidc_sso_mfa'])
        resp = self.client.get(reverse('oidc_sso:account'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='oidc_sso_2fa_accepted').exists())

    def test_idp_password_only_not_accepted(self):
        self.provider.accept_idp_mfa = True
        self.provider.save()
        self.sso_login(acr='urn:agit8or:acr:mfa', amr=['pwd'])
        self.assertFalse(self.client.session['oidc_sso_mfa'])
        resp = self.client.get(reverse('oidc_sso:account'))
        self.assertTrue(resp['Location'].startswith(reverse('oidc_sso:verify')))

    def test_verify_with_local_code(self):
        from django_otp.oath import totp
        from django_otp.plugins.otp_totp.models import TOTPDevice
        self.sso_login()
        device = TOTPDevice.objects.get(user=self.alice)
        code = str(totp(device.bin_key)).zfill(6)
        resp = self.client.post(reverse('oidc_sso:verify'), {'token': code, 'next': '/accounts/sso/oidc/account/'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(reverse('oidc_sso:account')).status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StepUpAndLinkTests(_Base):
    def test_stepup_sets_fresh_auth(self):
        from tech_access.protected import has_fresh_auth
        self.link()
        self.sso_login()
        auth_url = self.start('oidc_sso:stepup', method='post', data={'next': '/accounts/sso/oidc/account/'})
        q = parse_qs(urlsplit(auth_url).query)
        self.assertEqual(q['prompt'], ['login'])
        self.assertEqual(q['max_age'], ['300'])
        code, state = self.op.issue_code(auth_url, amr=['pwd', 'otp'])
        resp = self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertEqual(resp['Location'], '/accounts/sso/oidc/account/')
        request = RequestFactory().get('/')
        request.session = self.client.session
        self.assertTrue(has_fresh_auth(request))
        self.assertTrue(AuditLog.objects.filter(action='sso_step_up').exists())

    def test_stepup_stale_auth_time_refused(self):
        self.link()
        self.sso_login()
        auth_url = self.start('oidc_sso:stepup', method='post')
        code, state = self.op.issue_code(auth_url, auth_time=int(time.time()) - 3600)
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertNotIn('tech_access_reauth_at', self.client.session)

    def test_stepup_other_account_refused(self):
        self.link()
        self.sso_login()
        auth_url = self.start('oidc_sso:stepup', method='post')
        code, state = self.op.issue_code(auth_url, sub='sub-mallory')
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertNotIn('tech_access_reauth_at', self.client.session)
        self.assertTrue(self.denied('stepup_wrong_account'))

    def test_stepup_needs_idp_mfa_when_user_has_totp(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.create(user=self.alice, name='phone', confirmed=True)
        self.link()
        self.sso_login()
        auth_url = self.start('oidc_sso:stepup', method='post')
        code, state = self.op.issue_code(auth_url, amr=['pwd'])
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertNotIn('tech_access_reauth_at', self.client.session)
        self.assertTrue(self.denied('stepup_no_mfa'))

    def test_local_reauthenticate_still_works(self):
        from tech_access.protected import has_fresh_auth, reauthenticate
        request = RequestFactory().get('/')
        request.user = self.alice
        request.session = {}
        self.assertEqual(reauthenticate(request, 'pw-Alice-12345!'), '')
        self.assertTrue(has_fresh_auth(request))

    def test_link_requires_fresh_auth(self):
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('oidc_sso:link', args=['agit8or']))
        self.assertEqual(resp['Location'], reverse('oidc_sso:account'))

    def test_link_flow(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('oidc_sso:reauth'), {'password': 'pw-Alice-12345!'})
        auth_url = self.start('oidc_sso:link', method='post')
        self.assertEqual(parse_qs(urlsplit(auth_url).query)['prompt'], ['login'])
        code, state = self.op.issue_code(auth_url, sub='sub-alice-at-op', email='different@example.com')
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        identity = OIDCIdentity.objects.get(user=self.alice)
        self.assertEqual((identity.issuer, identity.sub), (ISSUER, 'sub-alice-at-op'))
        self.assertFalse(identity.manages_staff_role)
        self.assertTrue(AuditLog.objects.filter(action='sso_link', user=self.alice).exists())

    def test_link_refused_when_sub_linked_elsewhere(self):
        bob = User.objects.create_user('bob', 'bob@example.com', 'pw-Bob-12345!')
        self.link(user=bob, sub='sub-taken')
        self.client.force_login(self.alice)
        self.client.post(reverse('oidc_sso:reauth'), {'password': 'pw-Alice-12345!'})
        auth_url = self.start('oidc_sso:link', method='post')
        code, state = self.op.issue_code(auth_url, sub='sub-taken')
        self.client.get(reverse('oidc_sso:callback', args=['agit8or']), {'code': code, 'state': state})
        self.assertFalse(OIDCIdentity.objects.filter(user=self.alice).exists())
        self.assertTrue(self.denied('identity_linked_elsewhere'))

    def test_unlink_self(self):
        self.link()
        self.client.force_login(self.alice)
        self.client.post(reverse('oidc_sso:reauth'), {'password': 'pw-Alice-12345!'})
        self.client.post(reverse('oidc_sso:unlink', args=['agit8or']))
        self.assertFalse(OIDCIdentity.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action='sso_unlink').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BackChannelLogoutTests(_Base):
    def logout_token(self, key=None, **over):
        now = int(time.time())
        c = {'iss': ISSUER, 'aud': CLIENT_ID, 'iat': now, 'exp': now + 120, 'jti': secrets.token_hex(8),
             'sid': 'sid-1', 'sub': 'sub-alice', 'events': {LOGOUT_EVENT: {}}}
        c.update(over)
        c = {k: v for k, v in c.items() if v is not None}
        return self.op.sign(c, key=key)

    def post(self, token):
        return self.client_class().post(reverse('oidc_sso:backchannel_logout', args=['agit8or']),
                                        {'logout_token': token})

    def test_kills_session_by_sid_and_rejects_replay(self):
        self.link()
        self.sso_login()
        self.assertEqual(self.client.get(reverse('oidc_sso:account')).status_code, 200)
        token = self.logout_token()
        resp = self.post(token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get(reverse('oidc_sso:account')).status_code, 302)
        self.assertFalse(OIDCSession.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action='sso_backchannel_logout', success=True).exists())
        self.assertEqual(self.post(token).status_code, 400)
        self.assertEqual(ReplayRecord.objects.count(), 1)

    def test_sub_only_kills_all_sso_sessions(self):
        self.link()
        self.sso_login()
        resp = self.post(self.logout_token(sid=None))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(reverse('oidc_sso:account')).status_code, 302)

    def test_other_sid_untouched(self):
        self.link()
        self.sso_login()
        self.assertEqual(self.post(self.logout_token(sid='sid-other')).status_code, 200)
        self.assertEqual(self.client.get(reverse('oidc_sso:account')).status_code, 200)

    def test_invalid_signature_rejected(self):
        self.link()
        self.sso_login()
        self.assertEqual(self.post(self.logout_token(key=_rsa())).status_code, 400)
        self.assertEqual(self.client.get(reverse('oidc_sso:account')).status_code, 200)

    def test_nonce_or_missing_event_rejected(self):
        self.assertEqual(self.post(self.logout_token(nonce='x')).status_code, 400)
        self.assertEqual(self.post(self.logout_token(events={'other': {}})).status_code, 400)
        self.assertEqual(self.post(self.logout_token(aud='other-client')).status_code, 400)
        self.assertEqual(self.post(self.logout_token(sid=None, sub=None)).status_code, 400)
        self.assertEqual(self.post('garbage').status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse('oidc_sso:backchannel_logout', args=['agit8or'])).status_code, 405)

    def test_unit_validation(self):
        claims = validate_logout_token(self.provider, self.logout_token())
        self.assertEqual(claims['sid'], 'sid-1')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DisabledAndPageTests(_Base):
    def test_button_shown_when_enabled(self):
        resp = self.client.get('/account/login/')
        self.assertContains(resp, 'Sign in with Agit8or Identity')
        self.assertContains(resp, reverse('oidc_sso:login', args=['agit8or']))

    def test_disabled_hides_button_and_404s(self):
        self.provider.enabled = False
        self.provider.save()
        resp = self.client.get('/account/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Sign in with Agit8or Identity')
        for name in ('login', 'callback', 'jwks'):
            self.assertEqual(self.client.get(reverse(f'oidc_sso:{name}', args=['agit8or'])).status_code, 404)
        self.assertEqual(self.client.post(reverse('oidc_sso:backchannel_logout', args=['agit8or']),
                                          {'logout_token': 'x'}).status_code, 404)

    def test_jwks_serves_public_key_only(self):
        resp = self.client.get(reverse('oidc_sso:jwks', args=['agit8or']))
        data = resp.json()
        self.assertEqual(len(data['keys']), 1)
        self.assertEqual(set(data['keys'][0]), {'kty', 'use', 'alg', 'kid', 'e', 'n'})


class SSRFTests(TestCase):
    def setUp(self):
        cache.clear()

    def provider(self, issuer, private=False):
        return OIDCProvider.objects.create(name='X', slug=f'x{OIDCProvider.objects.count()}', issuer=issuer,
                                           client_id='c', allow_private_network=private)

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_metadata_ip_refused(self):
        for private in (False, True):
            with self.assertRaises(OPError):
                discovery.fetch_metadata(self.provider('https://169.254.169.254/realms/x', private))

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_private_ip_needs_opt_in(self):
        with self.assertRaises(OPError):
            check_url(self.provider('https://10.0.0.5/realms/x'), 'https://10.0.0.5/realms/x')
        p = self.provider('https://10.0.0.5/realms/x', private=True)
        self.assertEqual(check_url(p, 'https://10.0.0.5/realms/x'), 'https://10.0.0.5/realms/x')
        with self.assertRaises(OPError):
            check_url(p, 'https://127.0.0.1/x')  # loopback still needs the global opt-in

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_http_refused_without_private_opt_in(self):
        with self.assertRaises(OPError):
            check_url(self.provider('http://id.example.com/realms/x'), 'http://id.example.com/realms/x')

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_dns_to_private_address_refused_at_connect(self):
        import socket
        p = self.provider('https://id.example.com/realms/x')
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 443))]
        with mock.patch('core.safe_http.socket.getaddrinfo', return_value=fake):
            with self.assertRaises(OPError) as cm:
                discovery.fetch_metadata(p)
        self.assertIn('guard', str(cm.exception))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AdminTests(_Base):
    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser('root', 'root@example.com', 'pw-Root-12345!')
        self.provider.client_secret = 'super-secret-value-123'
        self.provider.save()

    def detail_url(self):
        return reverse('oidc_sso:provider_detail', args=[self.provider.pk])

    def test_secret_and_private_key_never_rendered(self):
        self.client.force_login(self.root)
        resp = self.client.get(self.detail_url())
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'super-secret-value-123')
        self.assertNotContains(resp, 'PRIVATE KEY')
        self.assertContains(resp, self.provider.key_id)  # public JWK shown

    def test_permission_gating(self):
        self.client.force_login(self.alice)  # MSP staff without the permission
        self.assertEqual(self.client.get(reverse('oidc_sso:settings')).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 403)
        role = RoleTemplate.objects.create(name='SSO Admin', audience='internal', manage_sso_settings=True)
        prof = self.alice.profile
        prof.global_role_template = role
        prof.save()
        self.assertEqual(self.client.get(reverse('oidc_sso:settings')).status_code, 200)
        # A customer membership with the flag grants nothing.
        carol = User.objects.create_user('carol', 'carol@example.com', 'pw')
        org = Organization.objects.create(name='Cust', slug='sso-cust')
        Membership.objects.create(user=carol, organization=org, role_template=role)
        self.client.force_login(carol)
        self.assertEqual(self.client.get(reverse('oidc_sso:settings')).status_code, 403)

    def test_save_keeps_secret_and_audits(self):
        self.client.force_login(self.root)
        data = {f: getattr(self.provider, f) for f in (
            'name', 'slug', 'issuer', 'client_id', 'client_auth_method', 'scopes', 'allowed_algorithms',
            'org_claim', 'msp_org_alias', 'msp_org_id', 'roles_claim', 'mfa_acr_values', 'mfa_amr_values',
            'login_acr_values', 'stepup_acr_values', 'ca_bundle_pem')}
        data.update({'action': 'save', 'enabled': 'on', 'require_email_verified': 'on', 'rp_logout': 'on',
                     'client_secret': '', 'name': 'Renamed'})
        resp = self.client.post(self.detail_url(), data)
        self.assertEqual(resp.status_code, 302, resp.content[:500])
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.name, 'Renamed')
        self.assertEqual(self.provider.client_secret, 'super-secret-value-123')
        entry = AuditLog.objects.filter(action='sso_config_change').latest('timestamp')
        self.assertNotIn('super-secret', json.dumps(entry.extra_data))

    def test_hs_algorithms_cannot_be_configured(self):
        self.client.force_login(self.root)
        resp = self.client.post(self.detail_url(), {'action': 'save', 'name': 'X', 'slug': 'agit8or',
                                                    'issuer': ISSUER, 'client_id': CLIENT_ID,
                                                    'client_auth_method': 'private_key_jwt',
                                                    'scopes': 'openid', 'allowed_algorithms': 'RS256 HS256',
                                                    'roles_claim': 'x'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'HS* are never accepted')

    def test_privileged_role_mapping_needs_superuser(self):
        role = RoleTemplate.objects.create(name='SSO Admin', audience='internal', manage_sso_settings=True)
        prof = self.alice.profile
        prof.global_role_template = role
        prof.save()
        self.client.force_login(self.alice)
        self.client.post(self.detail_url(), {'action': 'add_role_mapping', 'role_key': 'admin',
                                             'target': 'staff', 'role_template': role.pk})
        self.assertFalse(OIDCRoleMapping.objects.filter(role_key='admin').exists())
        self.client.force_login(self.root)
        self.client.post(self.detail_url(), {'action': 'add_role_mapping', 'role_key': 'admin',
                                             'target': 'staff', 'role_template': role.pk})
        self.assertTrue(OIDCRoleMapping.objects.filter(role_key='admin').exists())

    def test_prelink_and_unlink(self):
        self.client.force_login(self.root)
        self.client.post(self.detail_url(), {'action': 'prelink', 'user': self.alice.pk, 'sub': 'sub-alice'})
        identity = OIDCIdentity.objects.get(user=self.alice)
        self.assertEqual(identity.sub, 'sub-alice')
        self.client.logout()
        self.sso_login()
        self.assertTrue(self.logged_in())
        self.client.force_login(self.root)
        self.client.post(self.detail_url(), {'action': 'unlink', 'identity_id': identity.pk})
        self.assertFalse(OIDCIdentity.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action='sso_unlink').exists())

    def test_test_discovery_button(self):
        self.client.force_login(self.root)
        self.client.post(self.detail_url(), {'action': 'test'})
        resp = self.client.get(self.detail_url())
        self.assertContains(resp, 'Discovery OK')

    def test_create_provider_generates_key_disabled(self):
        self.client.force_login(self.root)
        resp = self.client.post(reverse('oidc_sso:settings'), {'name': 'Keycloak', 'slug': 'kc'})
        p = OIDCProvider.objects.get(slug='kc')
        self.assertFalse(p.enabled)
        self.assertTrue(p.key_id)
        self.assertTrue(p.private_key_pem.startswith('-----BEGIN PRIVATE KEY'))
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT private_key_pem FROM oidc_providers WHERE id = %s', [p.pk])
            self.assertTrue(cur.fetchone()[0].startswith('enc2$'))
