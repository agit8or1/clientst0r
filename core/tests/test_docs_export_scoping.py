"""The KB list, its filters and both exports agree on which rows exist.

`document_detail` started including descendant organizations in v3.17.571,
while `document_list` still filtered a bare `organization=org` — so a parent
organization could open a subsidiary's document by slug but never saw it
listed. Its category and tag dropdowns had the same limit, which would leave a
subsidiary's category unselectable against a document visible beside it.

`document_export_bulk` shared the fault, and its whole purpose per its own
docstring is handing a departing client one archive of all their
documentation — which for a parent company silently omitted every subsidiary
document the list had just shown them.

`core.settings_views.export_data` read `Model.objects.all()` regardless of the
organization in the switcher.
"""
import json
import zipfile
from io import BytesIO

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate
from assets.models import Asset
from core.models import Organization
from docs.models import Document, DocumentCategory


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KnowledgeBaseScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.parent = Organization.objects.create(name='Holdings', slug='kb-p')
        cls.child = Organization.objects.create(
            name='Holdings North', slug='kb-c', parent=cls.parent)
        cls.stranger = Organization.objects.create(name='Rival', slug='kb-r')

        cls.child_cat = DocumentCategory.objects.create(
            organization=cls.child, name='Subsidiary Runbooks')
        cls.child_doc = Document.objects.create(
            organization=cls.child, title='child-firewall-runbook',
            body='how to', is_published=True, category=cls.child_cat)
        cls.rival_doc = Document.objects.create(
            organization=cls.stranger, title='rival-runbook',
            body='secret', is_published=True)

        User = get_user_model()
        cls.user = User.objects.create_user('kb_user', 'k@x.com', 'pw')
        rt = RoleTemplate.objects.create(name='KBAdmin')
        Membership.objects.create(user=cls.user, organization=cls.parent,
                                  role='admin', role_template=rt, is_active=True)

    def setUp(self):
        self.client.force_login(self.user)
        s = self.client.session
        s['current_organization_id'] = self.parent.pk
        s.save()

    def test_list_shows_a_descendants_document(self):
        r = self.client.get(reverse('docs:document_list'))
        self.assertContains(r, 'child-firewall-runbook')

    def test_list_does_not_show_an_unrelated_orgs_document(self):
        r = self.client.get(reverse('docs:document_list'))
        self.assertNotContains(r, 'rival-runbook')

    def test_the_filter_dropdown_offers_that_documents_category(self):
        """Otherwise a visible document sits beside an unselectable filter."""
        r = self.client.get(reverse('docs:document_list'))
        self.assertContains(r, 'Subsidiary Runbooks')

    def test_bulk_export_includes_a_descendants_document(self):
        r = self.client.get(
            reverse('docs:document_export_bulk', kwargs={'fmt': 'md'}))
        self.assertEqual(r.status_code, 200)
        names = zipfile.ZipFile(BytesIO(r.content)).namelist()
        self.assertTrue(any('child-firewall-runbook' in n for n in names),
                        f'archive held only {names}')

    def test_bulk_export_excludes_an_unrelated_org(self):
        r = self.client.get(
            reverse('docs:document_export_bulk', kwargs={'fmt': 'md'}))
        names = zipfile.ZipFile(BytesIO(r.content)).namelist()
        self.assertFalse(any('rival-runbook' in n for n in names))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DataExportScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.mine = Organization.objects.create(name='Mine', slug='ex-mine')
        cls.child = Organization.objects.create(
            name='Mine North', slug='ex-child', parent=cls.mine)
        cls.theirs = Organization.objects.create(name='Theirs', slug='ex-theirs')
        Asset.objects.create(organization=cls.mine, name='my-server')
        Asset.objects.create(organization=cls.child, name='child-server')
        Asset.objects.create(organization=cls.theirs, name='their-server')
        cls.su = get_user_model().objects.create_user(
            'ex_su', 'e@x.com', 'pw', is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.force_login(self.su)

    def _export(self, **post):
        s = self.client.session
        s['current_organization_id'] = self.mine.pk
        s.save()
        return self.client.post(reverse('core:export_data'), post)

    def test_export_covers_the_selected_org_and_its_descendants(self):
        r = self._export(type='assets', format='json')
        names = {a['name'] for a in json.loads(r.content)['assets']}
        self.assertEqual(names, {'my-server', 'child-server'})

    def test_export_leaves_out_an_unrelated_org(self):
        r = self._export(type='assets', format='json')
        names = {a['name'] for a in json.loads(r.content)['assets']}
        self.assertNotIn('their-server', names)

    def test_passwords_are_refused_in_a_format_that_cannot_carry_them(self):
        """
        `_format_for_hudu` maps assets, documents and contacts and never
        passwords, so this used to be a successful download of nothing.
        """
        for fmt in ('hudu', 'itglue'):
            with self.subTest(format=fmt):
                r = self._export(type='passwords', format=fmt)
                self.assertEqual(r.status_code, 400)
                self.assertIn('does not carry passwords', r.json()['message'])

    def test_the_json_password_export_says_the_values_are_unreadable_elsewhere(self):
        from vault.models import Password
        Password.objects.create(organization=self.mine, title='rtr', username='a')
        r = self._export(type='passwords', format='json')
        payload = json.loads(r.content)
        self.assertIn('passwords_note', payload['export_info'])
        self.assertIn('cannot be imported', payload['export_info']['passwords_note'])
