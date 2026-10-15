"""
Module view flags (`vault_view`, `docs_view`, `assets_view`) enforced in the
public REST API and GraphQL.

The flags live on RoleTemplate (or the simple-role defaults) and are applied
on top of the API key / session organization scoping: a row is reachable
only when its customer is in scope AND the user holds the module's view flag
there. Contacts are governed by `assets_view`.
"""
import json
from unittest import skipUnless

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from api.models import APIKey, APIKeyScope
from assets.models import Asset, Contact
from core.models import Organization
from docs.models import Diagram, Document
from vault.models import Password

try:
    import graphene_django  # noqa: F401
    HAS_GRAPHENE = True
except ImportError:
    HAS_GRAPHENE = False


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

FULL = dict(
    vault_view=True, vault_create=True, vault_edit=True, vault_delete=True,
    vault_view_password=True,
    assets_view=True, assets_create=True, assets_edit=True, assets_delete=True,
    docs_view=True, docs_create=True, docs_edit=True, docs_delete=True,
)


def _role(org, name, **overrides):
    """An org-scoped custom RoleTemplate: full access except `overrides`."""
    flags = dict(FULL, **overrides)
    return RoleTemplate.objects.create(name=name, organization=org, **flags)


def _password(org, title, **extra):
    pw = Password.objects.create(organization=org, title=title, **extra)
    pw.set_password('s3cret-value')
    pw.save()
    return pw


def _rows(resp):
    data = resp.json()
    return data['results'] if isinstance(data, dict) and 'results' in data else data


class _Base(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name='VP-A', slug='vp-a')
        self.org_b = Organization.objects.create(name='VP-B', slug='vp-b')
        self.user = User.objects.create_user('vp-user', password='pw')

        self.pw_a = _password(self.org_a, 'pw-a')
        self.pw_b = _password(self.org_b, 'pw-b')
        self.doc_a = Document.objects.create(organization=self.org_a, title='doc-a', slug='doc-a')
        self.doc_b = Document.objects.create(organization=self.org_b, title='doc-b', slug='doc-b')
        self.asset_a = Asset.objects.create(organization=self.org_a, name='asset-a', asset_type='server')
        self.asset_b = Asset.objects.create(organization=self.org_b, name='asset-b', asset_type='server')
        self.contact_a = Contact.objects.create(organization=self.org_a, first_name='Ann', last_name='A')
        self.contact_b = Contact.objects.create(organization=self.org_b, first_name='Bob', last_name='B')

    def _member(self, org, role_template=None, user=None):
        return Membership.objects.create(
            user=user or self.user, organization=org, role=Role.OWNER,
            role_template=role_template, is_active=True,
        )

    def _key(self, scope=APIKeyScope.SINGLE, home=None, user=None):
        _, plaintext = APIKey.create_key(
            organization=home or self.org_a, user=user or self.user,
            name=f'vp-{scope}', role=Role.OWNER, scope=scope,
        )
        return plaintext

    def _get(self, path, key):
        return Client().get(path, HTTP_AUTHORIZATION=f'Bearer {key}')

    def _post(self, path, key, data=None):
        return Client().post(path, data=json.dumps(data or {}),
                             content_type='application/json',
                             HTTP_AUTHORIZATION=f'Bearer {key}')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VaultViewDeniedTests(_Base):
    def setUp(self):
        super().setUp()
        self._member(self.org_a, _role(self.org_a, 'no-vault', vault_view=False))
        self.key = self._key()

    def test_list_empty(self):
        resp = self._get('/api/passwords/', self.key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp), [])

    def test_detail_404(self):
        self.assertEqual(self._get(f'/api/passwords/{self.pw_a.pk}/', self.key).status_code, 404)

    def test_reveal_blocked(self):
        resp = self._get(f'/api/passwords/{self.pw_a.pk}/?reveal=true', self.key)
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn('s3cret-value', resp.content.decode())
        resp = self._post(f'/api/passwords/{self.pw_a.pk}/reveal/', self.key)
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn('s3cret-value', resp.content.decode())
        self.assertEqual(self._get(f'/api/passwords/{self.pw_a.pk}/otp/', self.key).status_code, 404)

    def test_update_and_delete_404(self):
        c = Client()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {self.key}'}
        resp = c.patch(f'/api/passwords/{self.pw_a.pk}/', data=json.dumps({'title': 'x'}),
                       content_type='application/json', **auth)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(c.delete(f'/api/passwords/{self.pw_a.pk}/', **auth).status_code, 404)
        self.assertTrue(Password.objects.filter(pk=self.pw_a.pk, title='pw-a').exists())

    def test_create_forbidden(self):
        resp = self._post('/api/passwords/', self.key, {'title': 'new', 'password_type': 'website'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Password.objects.filter(title='new').exists())

    def test_own_personal_entry_still_visible(self):
        mine = _password(self.org_a, 'mine', is_personal=True, personal_owner=self.user)
        other = User.objects.create_user('vp-other', password='pw')
        _password(self.org_a, 'theirs', is_personal=True, personal_owner=other)
        titles = {r['title'] for r in _rows(self._get('/api/passwords/', self.key))}
        self.assertEqual(titles, {'mine'})
        self.assertEqual(self._get(f'/api/passwords/{mine.pk}/', self.key).status_code, 200)

    def test_other_modules_unaffected(self):
        self.assertEqual({r['title'] for r in _rows(self._get('/api/documents/', self.key))}, {'doc-a'})
        self.assertEqual({r['name'] for r in _rows(self._get('/api/assets/', self.key))}, {'asset-a'})


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RevealGateStillAppliesTests(_Base):
    def test_vault_view_without_view_password_cannot_reveal(self):
        self._member(self.org_a, _role(self.org_a, 'meta-only', vault_view_password=False))
        key = self._key()
        self.assertEqual(self._get(f'/api/passwords/{self.pw_a.pk}/', key).status_code, 200)
        resp = self._get(f'/api/passwords/{self.pw_a.pk}/?reveal=true', key)
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn('s3cret-value', resp.content.decode())
        self.assertEqual(self._post(f'/api/passwords/{self.pw_a.pk}/reveal/', key).status_code, 403)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DocsViewDeniedTests(_Base):
    def setUp(self):
        super().setUp()
        self._member(self.org_a, _role(self.org_a, 'no-docs', docs_view=False))
        self.key = self._key()

    def test_list_empty_detail_404(self):
        self.assertEqual(_rows(self._get('/api/documents/', self.key)), [])
        self.assertEqual(self._get(f'/api/documents/{self.doc_a.pk}/', self.key).status_code, 404)

    def test_custom_actions_404(self):
        self.assertEqual(self._post(f'/api/documents/{self.doc_a.pk}/archive/', self.key).status_code, 404)
        self.assertEqual(self._post(f'/api/documents/{self.doc_a.pk}/publish/', self.key).status_code, 404)
        self.doc_a.refresh_from_db()
        self.assertFalse(self.doc_a.is_archived)

    def test_create_forbidden(self):
        resp = self._post('/api/documents/', self.key, {'title': 'new-doc', 'body': 'x'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Document.objects.filter(title='new-doc').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetsViewDeniedTests(_Base):
    def setUp(self):
        super().setUp()
        self._member(self.org_a, _role(self.org_a, 'no-assets', assets_view=False))
        self.key = self._key()

    def test_assets_hidden(self):
        self.assertEqual(_rows(self._get('/api/assets/', self.key)), [])
        self.assertEqual(self._get(f'/api/assets/{self.asset_a.pk}/', self.key).status_code, 404)

    def test_contacts_follow_assets_view(self):
        self.assertEqual(_rows(self._get('/api/contacts/', self.key)), [])
        self.assertEqual(self._get(f'/api/contacts/{self.contact_a.pk}/', self.key).status_code, 404)

    def test_create_forbidden(self):
        resp = self._post('/api/assets/', self.key, {'name': 'new-asset', 'asset_type': 'server'})
        self.assertEqual(resp.status_code, 403)
        resp = self._post('/api/contacts/', self.key, {'first_name': 'New', 'last_name': 'C'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Asset.objects.filter(name='new-asset').exists())
        self.assertFalse(Contact.objects.filter(first_name='New').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MultiOrgKeyTests(_Base):
    """User has every module in A, none in B; an ALL-scope key sees only A."""

    def setUp(self):
        super().setUp()
        self._member(self.org_a)  # simple OWNER role: everything
        self._member(self.org_b, _role(self.org_b, 'nothing-b',
                                       vault_view=False, docs_view=False, assets_view=False))
        self.key = self._key(APIKeyScope.ALL)

    def test_lists_only_permitted_org(self):
        self.assertEqual({r['title'] for r in _rows(self._get('/api/passwords/', self.key))}, {'pw-a'})
        self.assertEqual({r['title'] for r in _rows(self._get('/api/documents/', self.key))}, {'doc-a'})
        self.assertEqual({r['name'] for r in _rows(self._get('/api/assets/', self.key))}, {'asset-a'})
        self.assertEqual({r['first_name'] for r in _rows(self._get('/api/contacts/', self.key))}, {'Ann'})

    def test_explicit_org_param_narrows_to_nothing(self):
        resp = self._get(f'/api/assets/?organization={self.org_b.id}', self.key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp), [])

    def test_detail_in_denied_org_404(self):
        self.assertEqual(self._get(f'/api/passwords/{self.pw_b.pk}/?reveal=true', self.key).status_code, 404)
        self.assertEqual(self._get(f'/api/documents/{self.doc_b.pk}/', self.key).status_code, 404)
        self.assertEqual(self._get(f'/api/assets/{self.asset_b.pk}/', self.key).status_code, 404)

    def test_create_in_denied_org_forbidden(self):
        resp = self._post(f'/api/assets/?organization={self.org_b.id}', self.key,
                          {'name': 'b-new', 'asset_type': 'server'})
        self.assertEqual(resp.status_code, 403)
        resp = self._post(f'/api/assets/?organization={self.org_a.id}', self.key,
                          {'name': 'a-new', 'asset_type': 'server'})
        self.assertEqual(resp.status_code, 201)

    def test_cannot_move_row_into_denied_org(self):
        resp = Client().patch(
            f'/api/assets/{self.asset_a.pk}/', data=json.dumps({'organization': self.org_b.id}),
            content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.key}',
        )
        self.assertEqual(resp.status_code, 403)
        self.asset_a.refresh_from_db()
        self.assertEqual(self.asset_a.organization_id, self.org_a.id)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SuperuserUnaffectedTests(_Base):
    def test_superuser_sees_everything(self):
        admin = User.objects.create_superuser('vp-admin', 'a@x.com', 'pw')
        key = self._key(APIKeyScope.ALL, user=admin)
        self.assertEqual({r['title'] for r in _rows(self._get('/api/passwords/', key))}, {'pw-a', 'pw-b'})
        self.assertEqual({r['title'] for r in _rows(self._get('/api/documents/', key))}, {'doc-a', 'doc-b'})
        self.assertEqual({r['name'] for r in _rows(self._get('/api/assets/', key))}, {'asset-a', 'asset-b'})
        self.assertEqual({r['first_name'] for r in _rows(self._get('/api/contacts/', key))}, {'Ann', 'Bob'})


@skipUnless(HAS_GRAPHENE, 'graphene-django not installed (optional dependency)')
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GraphQLViewPermTests(_Base):
    URL = '/api/v2/graphql/'

    def _query(self, query):
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org_a.id
        s.save()
        return c.post(self.URL, data=json.dumps({'query': query}),
                      content_type='application/json').json()

    def test_vault_view_false_returns_no_passwords(self):
        self._member(self.org_a, _role(self.org_a, 'gql-no-vault', vault_view=False))
        mine = _password(self.org_a, 'mine', is_personal=True, personal_owner=self.user)
        data = self._query(
            f'{{ passwords {{ title }} password(id: {self.pw_a.pk}) {{ title }} '
            f'organizations {{ passwordCount }} dashboardStats {{ totalPasswords }} }}'
        )['data']
        self.assertEqual([p['title'] for p in data['passwords']], [mine.title])
        self.assertIsNone(data['password'])
        self.assertEqual(data['organizations'][0]['passwordCount'], 1)
        self.assertEqual(data['dashboardStats']['totalPasswords'], 1)

    def test_docs_and_assets_view_false(self):
        self._member(self.org_a, _role(self.org_a, 'gql-none', docs_view=False, assets_view=False))
        Document.objects.create(title='kb', slug='kb', is_global=True, is_published=True)
        data = self._query(
            f'{{ documents {{ title }} document(id: {self.doc_a.pk}) {{ title }} '
            f'assets {{ name }} asset(id: {self.asset_a.pk}) {{ name }} '
            f'organizations {{ assetCount }} }}'
        )['data']
        self.assertEqual(data['documents'], [])
        self.assertIsNone(data['document'])
        self.assertEqual(data['assets'], [])
        self.assertIsNone(data['asset'])
        self.assertEqual(data['organizations'][0]['assetCount'], 0)

    def test_mutations_refused_without_view(self):
        self._member(self.org_a, _role(self.org_a, 'gql-no-assets', assets_view=False, docs_view=False))
        self._query(f'mutation {{ deleteAsset(id: {self.asset_a.pk}) {{ success }} }}')
        self.assertTrue(Asset.objects.filter(pk=self.asset_a.pk).exists())
        self._query(f'mutation {{ createAsset(name: "g-new", organizationId: {self.org_a.id}) {{ success }} }}')
        self.assertFalse(Asset.objects.filter(name='g-new').exists())
        self._query(f'mutation {{ createDocument(title: "g-doc", content: "x", '
                    f'organizationId: {self.org_a.id}) {{ success }} }}')
        self.assertFalse(Document.objects.filter(title='g-doc').exists())

    def test_with_view_sees_rows(self):
        self._member(self.org_a)
        data = self._query('{ passwords { title } documents { title } assets { name } }')['data']
        self.assertEqual([p['title'] for p in data['passwords']], ['pw-a'])
        self.assertEqual([d['title'] for d in data['documents']], ['doc-a'])
        self.assertEqual([a['name'] for a in data['assets']], ['asset-a'])

    def _diagrams(self):
        Diagram.objects.create(organization=self.org_a, title='dia-a', slug='dia-a',
                               diagram_xml='<mxfile/>')
        Diagram.objects.create(organization=self.org_b, title='dia-b', slug='dia-b',
                               diagram_xml='<mxfile/>')
        Diagram.objects.create(title='dia-kb', slug='dia-kb', diagram_xml='<mxfile/>',
                               is_global=True, is_published=True)
        return Diagram.objects.get(title='dia-a')

    def test_docs_view_false_hides_diagrams(self):
        self._member(self.org_a, _role(self.org_a, 'gql-no-docs-dia', docs_view=False))
        dia_a = self._diagrams()
        data = self._query(
            f'{{ diagrams {{ title }} diagram(id: {dia_a.pk}) {{ title }} '
            f'dashboardStats {{ totalDiagrams }} }}'
        )['data']
        self.assertEqual(data['diagrams'], [])
        self.assertIsNone(data['diagram'])
        self.assertEqual(data['dashboardStats']['totalDiagrams'], 0)

    def test_docs_view_sees_diagrams(self):
        self._member(self.org_a)
        dia_a = self._diagrams()
        data = self._query(
            f'{{ diagrams {{ title }} diagram(id: {dia_a.pk}) {{ title }} '
            f'dashboardStats {{ totalDiagrams }} }}'
        )['data']
        self.assertEqual({d['title'] for d in data['diagrams']}, {'dia-a'})
        self.assertEqual(data['diagram']['title'], 'dia-a')
        self.assertEqual(data['dashboardStats']['totalDiagrams'], 1)

    def test_customer_with_docs_view_gets_no_global_kb(self):
        """Global KB is staff-only in the web UI; the API matches."""
        self._member(self.org_a)  # docs_view in its own customer
        self._diagrams()
        kb_doc = Document.objects.create(title='kb-doc', slug='kb-doc',
                                         is_global=True, is_published=True)
        kb_dia = Diagram.objects.get(title='dia-kb')
        data = self._query(
            f'{{ documents {{ title }} document(id: {kb_doc.pk}) {{ title }} '
            f'diagrams {{ title }} diagram(id: {kb_dia.pk}) {{ title }} }}'
        )['data']
        self.assertEqual([d['title'] for d in data['documents']], ['doc-a'])
        self.assertIsNone(data['document'])
        self.assertEqual([d['title'] for d in data['diagrams']], ['dia-a'])
        self.assertIsNone(data['diagram'])
        key = self._key()
        rest = _rows(self._get('/api/documents/', key))
        self.assertEqual({r['title'] for r in rest}, {'doc-a'})
        self.assertEqual(self._get(f'/api/documents/{kb_doc.pk}/', key).status_code, 404)

    def test_superuser_sees_global_kb(self):
        self.user.is_superuser = True
        self.user.save()
        self._diagrams()
        Document.objects.create(title='kb-doc', slug='kb-doc', is_global=True, is_published=True)
        data = self._query('{ documents { title } diagrams { title } }')['data']
        self.assertIn('kb-doc', {d['title'] for d in data['documents']})
        self.assertIn('dia-kb', {d['title'] for d in data['diagrams']})
