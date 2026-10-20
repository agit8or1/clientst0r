"""
API key Permission Level and module write flags (v3.17.618).

Until then the level picked when a key was made (Read-Only, Editor, Admin,
Owner) was stored and shown but never checked, and REST writes only checked
the module's view flag, so a Read-Only key, or a member whose role lacks
`assets_create`, could create, edit and delete.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from api.models import APIKey
from api.tests_view_permissions import TEST_MIDDLEWARE, FULL, _password
from assets.models import Asset
from core.models import Organization, Tag
from docs.models import Document


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class _Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='KL-A', slug='kl-a')
        self.other = Organization.objects.create(name='KL-B', slug='kl-b')
        self.user = User.objects.create_user('kl-user', password='pw')
        self.asset = Asset.objects.create(organization=self.org, name='a1', asset_type='server')
        self.doc = Document.objects.create(organization=self.org, title='d1', slug='d1',
                                           is_published=False)
        self.pw = _password(self.org, 'pw1')

    def _member(self, role=Role.OWNER, template=None):
        Membership.objects.create(user=self.user, organization=self.org, role=role,
                                  role_template=template, is_active=True)

    def _client(self, level):
        _, key = APIKey.create_key(organization=self.org, user=self.user, name=level, role=level)
        return Client(HTTP_AUTHORIZATION=f'Bearer {key}')


class KeyLevelTests(_Base):
    def setUp(self):
        super().setUp()
        self._member(Role.OWNER)

    def test_readonly_key_reads(self):
        c = self._client(Role.READONLY)
        self.assertEqual(c.get('/api/assets/').status_code, 200)
        self.assertEqual(c.get(f'/api/passwords/{self.pw.pk}/').status_code, 200)

    def test_readonly_key_cannot_write(self):
        c = self._client(Role.READONLY)
        r = c.post('/api/assets/', {'name': 'new', 'asset_type': 'server'},
                   content_type='application/json')
        self.assertEqual(r.status_code, 403)
        self.assertIn('Read-Only', r.json()['detail'])
        self.assertEqual(c.patch(f'/api/assets/{self.asset.pk}/', {'name': 'x'},
                                 content_type='application/json').status_code, 403)
        self.assertEqual(c.delete(f'/api/assets/{self.asset.pk}/').status_code, 403)
        self.assertEqual(c.delete(f'/api/passwords/{self.pw.pk}/').status_code, 403)
        self.assertEqual(c.post(f'/api/documents/{self.doc.pk}/publish/').status_code, 403)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.name, 'a1')
        self.assertTrue(Asset.objects.filter(pk=self.asset.pk).exists())

    def test_readonly_key_cannot_reveal(self):
        c = self._client(Role.READONLY)
        r = c.get(f'/api/passwords/{self.pw.pk}/?reveal=true')
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('s3cret-value', r.content.decode())
        self.assertEqual(c.post(f'/api/passwords/{self.pw.pk}/reveal/').status_code, 403)
        self.assertEqual(c.get(f'/api/passwords/{self.pw.pk}/otp/').status_code, 403)

    def test_editor_key_creates_but_cannot_delete_or_publish(self):
        c = self._client(Role.EDITOR)
        r = c.post('/api/assets/', {'name': 'new', 'asset_type': 'server'},
                   content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(c.delete(f'/api/assets/{self.asset.pk}/').status_code, 403)
        self.assertEqual(c.post(f'/api/documents/{self.doc.pk}/publish/').status_code, 403)
        self.assertEqual(c.patch(f'/api/documents/{self.doc.pk}/', {'is_published': True},
                                 content_type='application/json').status_code, 403)
        # Editing other fields is fine.
        self.assertEqual(c.patch(f'/api/documents/{self.doc.pk}/', {'title': 'd2'},
                                 content_type='application/json').status_code, 200)
        r = c.post(f'/api/passwords/{self.pw.pk}/reveal/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['password'], 's3cret-value')

    def test_owner_key_full(self):
        c = self._client(Role.OWNER)
        self.assertEqual(c.post(f'/api/documents/{self.doc.pk}/publish/').status_code, 200)
        self.assertEqual(c.delete(f'/api/assets/{self.asset.pk}/').status_code, 204)


class ModuleWriteFlagTests(_Base):
    """The user's own role flags gate writes, not only the view flag."""

    def setUp(self):
        super().setUp()
        flags = dict(FULL, assets_create=False, assets_edit=False, assets_delete=False,
                     docs_publish=False)
        self._member(template=RoleTemplate.objects.create(
            name='viewer-ish', organization=self.org, **flags))
        self.c = self._client(Role.OWNER)

    def test_asset_writes_need_flags(self):
        self.assertEqual(self.c.get('/api/assets/').status_code, 200)
        self.assertEqual(self.c.post('/api/assets/', {'name': 'n', 'asset_type': 'server'},
                                     content_type='application/json').status_code, 403)
        self.assertEqual(self.c.patch(f'/api/assets/{self.asset.pk}/', {'name': 'x'},
                                      content_type='application/json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/assets/{self.asset.pk}/').status_code, 403)
        self.assertEqual(Asset.objects.filter(organization=self.org).count(), 1)

    def test_publish_needs_docs_publish(self):
        self.assertEqual(self.c.post(f'/api/documents/{self.doc.pk}/publish/').status_code, 403)
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.is_published)
        r = self.c.post('/api/documents/', {'title': 'pub', 'body': 'x', 'is_published': True},
                        content_type='application/json')
        self.assertEqual(r.status_code, 403)
        r = self.c.post('/api/documents/', {'title': 'draft', 'body': 'x', 'is_published': False},
                        content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)


class TagTests(_Base):
    def setUp(self):
        super().setUp()
        self._member(Role.OWNER)
        self.foreign_tag = Tag.objects.create(organization=self.other, name='Secret', slug='secret')

    def test_non_superuser_cannot_manage_tags(self):
        c = self._client(Role.OWNER)
        self.assertEqual(c.get('/api/tags/').status_code, 200)
        self.assertEqual(c.post('/api/tags/', {'name': 'x'},
                                content_type='application/json').status_code, 403)

    def test_foreign_tag_rejected(self):
        c = self._client(Role.OWNER)
        r = c.post('/api/documents/', {'title': 't', 'body': 'b', 'is_published': False,
                                       'tag_ids': [self.foreign_tag.pk]},
                   content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('Secret', r.content.decode())
        self.assertFalse(Document.objects.filter(title='t').exists())
