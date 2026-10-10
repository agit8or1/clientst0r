"""
Regression tests for the v3.17.593 security hardening pass on the API
surfaces: the removed password-only token endpoint, the REST vault reveal
gate, and GraphQL tenant scoping.
"""
import json
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from assets.models import Asset
from core.models import Organization
from vault.models import Password, VaultAccessRule, VaultRevealRequest

try:
    import graphene_django  # noqa: F401
    HAS_GRAPHENE = True
except ImportError:
    HAS_GRAPHENE = False


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _login_in_org(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


def _member(username, org, role):
    user = User.objects.create_user(username, password='pw')
    Membership.objects.create(user=user, organization=org, role=role, is_active=True)
    return user


def _password(org, title, **extra):
    pw = Password.objects.create(organization=org, title=title, **extra)
    pw.set_password('s3cret-value')
    pw.save()
    return pw


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PasswordOnlyTokenEndpointTests(TestCase):
    def test_token_endpoint_removed(self):
        User.objects.create_user('tok-user', password='pw')
        resp = Client().post('/api/auth/token/', {'username': 'tok-user', 'password': 'pw'})
        self.assertEqual(resp.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RestVaultRevealGateTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='GateCo', slug='gate-co')
        self.owner = _member('gate-owner', self.org, Role.OWNER)
        self.reader = _member('gate-reader', self.org, Role.READONLY)
        self.password = _password(self.org, 'Shared')

    def _client(self, user):
        c = Client()
        _login_in_org(c, user, self.org)
        return c

    def test_owner_can_reveal(self):
        resp = self._client(self.owner).post(f'/api/passwords/{self.password.pk}/reveal/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['password'], 's3cret-value')

    def test_readonly_cannot_reveal_by_any_route(self):
        c = self._client(self.reader)
        self.assertEqual(c.post(f'/api/passwords/{self.password.pk}/reveal/').status_code, 403)
        resp = c.get(f'/api/passwords/{self.password.pk}/?reveal=true')
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn('s3cret-value', resp.content.decode())
        self.assertEqual(c.get(f'/api/passwords/{self.password.pk}/otp/').status_code, 403)

    def test_otp_code_and_password_only_on_gated_reveal(self):
        otp = _password(self.org, 'OTP entry', password_type='otp')
        otp.set_otp_secret('JBSWY3DPEHPK3PXP')
        otp.save()
        reader = self._client(self.reader)
        self.assertIsNone(reader.get(f'/api/passwords/{otp.pk}/').json().get('otp_code'))
        owner = self._client(self.owner)
        resp = owner.patch(f'/api/passwords/{self.password.pk}/?reveal=true',
                           data=json.dumps({'title': 'Renamed'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.json().get('password'), 's3cret-value')

    def test_readonly_cannot_edit_or_delete(self):
        c = self._client(self.reader)
        resp = c.patch(f'/api/passwords/{self.password.pk}/', data=json.dumps({'title': 'pwned'}),
                       content_type='application/json')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(c.delete(f'/api/passwords/{self.password.pk}/').status_code, 403)
        self.assertTrue(Password.objects.filter(pk=self.password.pk, title='Shared').exists())

    def test_other_users_personal_entries_hidden(self):
        personal = _password(self.org, 'Mine', is_personal=True, personal_owner=self.reader)
        c = self._client(self.owner)
        self.assertEqual(c.get(f'/api/passwords/{personal.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/api/passwords/{personal.pk}/reveal/').status_code, 404)

    def test_approval_required_and_single_use(self):
        self.password.requires_reveal_approval = True
        self.password.save()
        c = self._client(self.owner)
        resp = c.post(f'/api/passwords/{self.password.pk}/reveal/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.json().get('requires_approval'))

        from django.utils import timezone
        VaultRevealRequest.objects.create(
            password=self.password, requester=self.owner, status='approved',
            decided_at=timezone.now(), justification='test',
        )
        self.assertEqual(c.post(f'/api/passwords/{self.password.pk}/reveal/').status_code, 200)
        self.assertEqual(c.post(f'/api/passwords/{self.password.pk}/reveal/').status_code, 403)

    @patch('vault.access_rules._country_for_ip', return_value='CN')
    def test_access_rule_deny_applies(self, _cc):
        VaultAccessRule.objects.create(organization=self.org, name='No CN', scope='organization',
                                       effect='deny', blocked_countries=['CN'])
        resp = self._client(self.owner).post(f'/api/passwords/{self.password.pk}/reveal/')
        self.assertEqual(resp.status_code, 403)


@skipUnless(HAS_GRAPHENE, 'graphene-django not installed (optional dependency)')
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GraphQLScopingTests(TestCase):
    URL = '/api/v2/graphql/'

    def setUp(self):
        self.org_a = Organization.objects.create(name='GqlA', slug='gql-a')
        self.org_b = Organization.objects.create(name='GqlB', slug='gql-b')
        self.user_a = _member('gql-a', self.org_a, Role.OWNER)
        self.reader_a = _member('gql-reader', self.org_a, Role.READONLY)
        self.asset_a = Asset.objects.create(organization=self.org_a, name='A-box', asset_type='server')
        self.asset_b = Asset.objects.create(organization=self.org_b, name='B-box', asset_type='server')
        self.pw_b = _password(self.org_b, 'B-secret')

    def _query(self, user, query, csrf=False):
        c = Client(enforce_csrf_checks=csrf)
        _login_in_org(c, user, self.org_a)
        return c.post(self.URL, data=json.dumps({'query': query}), content_type='application/json')

    def test_lists_scoped_to_own_orgs(self):
        data = self._query(self.user_a, '{ assets { name } passwords { title } organizations { name } }').json()['data']
        self.assertEqual([a['name'] for a in data['assets']], ['A-box'])
        self.assertEqual(data['passwords'], [])
        self.assertEqual([o['name'] for o in data['organizations']], ['GqlA'])

    def test_cross_tenant_lookup_by_id_returns_null(self):
        body = self._query(self.user_a, f'{{ asset(id: {self.asset_b.pk}) {{ name }} '
                                        f'password(id: {self.pw_b.pk}) {{ title }} }}').json()
        self.assertIsNone(body['data']['asset'])
        self.assertIsNone(body['data']['password'])

    def test_ciphertext_fields_not_exposed(self):
        body = self._query(self.user_a, '{ passwords { encryptedPassword } }').json()
        self.assertIn('errors', body)

    def test_cross_tenant_delete_refused(self):
        self._query(self.user_a, f'mutation {{ deleteAsset(id: {self.asset_b.pk}) {{ success }} }}')
        self.assertTrue(Asset.objects.filter(pk=self.asset_b.pk).exists())

    def test_readonly_cannot_delete_in_own_org(self):
        self._query(self.reader_a, f'mutation {{ deleteAsset(id: {self.asset_a.pk}) {{ success }} }}')
        self.assertTrue(Asset.objects.filter(pk=self.asset_a.pk).exists())

    def test_csrf_enforced_for_session_auth(self):
        resp = self._query(self.user_a, f'mutation {{ deleteAsset(id: {self.asset_a.pk}) {{ success }} }}',
                           csrf=True)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Asset.objects.filter(pk=self.asset_a.pk).exists())
