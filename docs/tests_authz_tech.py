"""Roles & permissions program (authz-tech): documentation isolation.

Customer users (anyone who is not MSP staff) never get internal-only
documentation, internal blocks inside customer-visible articles, or global
KB articles through the placeholder customer those rows carry; docs_create
/ docs_delete are checked for the customer, not inferred from any *_create
flag. The same rule holds on the REST API, GraphQL helpers, mobile and
/media/.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from docs.models import Document
from docs.tests import _TEST_MIDDLEWARE
from psa.tests._base import _make_msp_tech

INTERNAL_BODY = 'Internal runbook: the break-glass account is kept in the safe.'
VISIBLE_BODY = 'How to reset your password.\n\n:::internal\nTech note: use the hidden admin console.\n:::\n'


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerDocumentIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Created first, so it is the "placeholder" org global KB rows get.
        cls.org = Organization.objects.create(name='AAA Docs Customer', slug='aaa-authz-docs')
        cls.staff = _make_msp_tech(User.objects.create_user('authz-docs-tech', password='pw'))
        cls.customer = User.objects.create_user('authz-docs-customer', password='pw')
        Membership.objects.create(user=cls.customer, organization=cls.org, role=Role.EDITOR)
        cls.internal = Document.objects.create(
            organization=cls.org, title='Break glass', slug='break-glass', body=INTERNAL_BODY,
            content_type='markdown', is_published=True, created_by=cls.staff)
        cls.visible = Document.objects.create(
            organization=cls.org, title='Reset password', slug='reset-password', body=VISIBLE_BODY,
            content_type='markdown', is_published=True, is_client_visible=True, created_by=cls.staff)
        cls.own = Document.objects.create(
            organization=cls.org, title='Our office notes', slug='office-notes', body='Customer text',
            content_type='markdown', is_published=True, created_by=cls.customer)
        cls.global_kb = Document.objects.create(
            organization=cls.org, title='MSP global article', slug='msp-global', body='Global internal',
            content_type='markdown', is_published=True, is_global=True, created_by=cls.staff)

    def setUp(self):
        self.c = Client()
        _login(self.c, self.customer, self.org)

    def test_list_hides_internal_and_global(self):
        resp = self.c.get(reverse('docs:document_list'))
        self.assertEqual(resp.status_code, 200)
        titles = {d.title for d in resp.context['org_docs']}
        self.assertEqual(titles, {'Reset password', 'Our office notes'})

    def test_detail_404_for_internal_and_global(self):
        for slug in ('break-glass', 'msp-global'):
            with self.subTest(slug):
                self.assertEqual(self.c.get(reverse('docs:document_detail', args=[slug])).status_code, 404)

    def test_visible_article_has_internal_blocks_stripped(self):
        resp = self.c.get(reverse('docs:document_detail', args=['reset-password']))
        self.assertContains(resp, 'How to reset your password')
        self.assertNotContains(resp, 'hidden admin console')

    def test_customer_cannot_open_editor_or_versions_of_msp_article(self):
        self.assertEqual(self.c.get(reverse('docs:document_edit', args=['reset-password'])).status_code, 403)
        self.assertEqual(self.c.get(reverse('docs:document_versions', args=[self.visible.pk])).status_code, 403)
        # Their own document stays editable.
        self.assertEqual(self.c.get(reverse('docs:document_edit', args=['office-notes'])).status_code, 200)

    def test_export_is_customer_copy_and_internal_404(self):
        resp = self.c.get(reverse('docs:document_export', args=['reset-password', 'md']))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'hidden admin console', resp.content)
        self.assertEqual(self.c.get(reverse('docs:document_export', args=['break-glass', 'md'])).status_code, 404)

    def test_editor_role_cannot_delete(self):
        # Built-in Editor: docs_delete is off.
        resp = self.c.post(reverse('docs:document_delete', args=['office-notes']))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Document.objects.filter(pk=self.own.pk).exists())

    def test_staff_still_see_everything(self):
        _login(self.c, self.staff, self.org)
        resp = self.c.get(reverse('docs:document_detail', args=['break-glass']))
        self.assertContains(resp, 'break-glass account')
        resp = self.c.get(reverse('docs:document_detail', args=['reset-password']))
        self.assertContains(resp, 'hidden admin console')

    def test_rest_api_applies_the_same_rule(self):
        resp = self.c.get('/api/documents/')
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()['results']
        titles = {r['title'] for r in rows}
        self.assertEqual(titles, {'Reset password', 'Our office notes'})
        body = next(r['body'] for r in rows if r['title'] == 'Reset password')
        self.assertNotIn('hidden admin console', body)
        self.assertEqual(self.c.get(f'/api/documents/{self.internal.pk}/').status_code, 404)

    def test_media_rule_denies_internal_document_files(self):
        from core.media_views import _document
        self.assertFalse(_document(self.customer, self.internal))
        self.assertFalse(_document(self.customer, self.global_kb))
        self.assertTrue(_document(self.customer, self.visible))
        self.assertTrue(_document(self.staff, self.internal))

    def test_mobile_kb_hides_internal(self):
        from api_mobile.views_kb import _kb_queryset
        titles = set(_kb_queryset(self.customer).values_list('title', flat=True))
        self.assertEqual(titles, {'Reset password', 'Our office notes'})


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DocsFlagTests(TestCase):
    def test_files_upload_role_cannot_create_documents(self):
        org = Organization.objects.create(name='Docs flags', slug='authz-docs-flags')
        role = RoleTemplate.objects.create(name='authz uploader', files_upload=True, files_view=True,
                                           docs_view=True, docs_create=False)
        user = User.objects.create_user('authz-docs-uploader', password='pw')
        Membership.objects.create(user=user, organization=org, role=Role.EDITOR, role_template=role)
        c = Client()
        _login(c, user, org)
        resp = c.post(reverse('docs:document_create'), {'title': 'x', 'body': 'y', 'content_type': 'markdown'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Document.objects.filter(title='x').exists())

    def test_rest_create_without_publish_flag_is_a_draft_or_refused(self):
        org = Organization.objects.create(name='Docs rest', slug='authz-docs-rest')
        role = RoleTemplate.objects.create(name='authz writer no publish', docs_view=True,
                                           docs_create=True, docs_edit=True, docs_publish=False,
                                           api_access=True)
        user = User.objects.create_user('authz-docs-rest', password='pw')
        Membership.objects.create(user=user, organization=org, role=Role.EDITOR, role_template=role)
        c = Client()
        _login(c, user, org)
        resp = c.post('/api/documents/', {'title': 'Sneaky live', 'body': 'b', 'content_type': 'markdown'})
        self.assertIn(resp.status_code, (201, 403))
        self.assertFalse(Document.objects.filter(title='Sneaky live', is_published=True).exists())
