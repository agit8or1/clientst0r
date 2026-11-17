"""v3.17.708: "Global KB article" box on the document form, and the global
KB editor loads the article's existing content and offers Save."""
from django.test import override_settings

from .models import Document
from .tests_lifecycle import TEST_MIDDLEWARE, _Base


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MakeGlobalTests(_Base):
    def _doc(self, slug='runbook', **kw):
        return Document.objects.create(organization=self.org, title='Runbook', slug=slug,
                                       body='<p>body</p>', content_type='html', is_published=True, **kw)

    def _post(self, client, doc, **extra):
        data = {'title': doc.title, 'body': doc.body, 'content_type': 'html',
                'is_published': 'on', 'review_interval_days': 90, 'kb_visibility_shown': '1'}
        data.update(extra)
        return client.post(f'/docs/{doc.slug}/edit/', data)

    def test_staff_sees_box_and_makes_article_global(self):
        doc = self._doc()
        c = self.client_for(self.staff)
        self.assertIn('make_global', c.get(f'/docs/{doc.slug}/edit/').context['form'].fields)
        r = self._post(c, doc, make_global='on')
        doc.refresh_from_db()
        self.assertTrue(doc.is_global)
        self.assertRedirects(r, f'/docs/kb/{doc.slug}/', fetch_redirect_response=False)
        self.assertEqual(c.get(f'/docs/kb/{doc.slug}/').status_code, 200)

    def test_moves_to_placeholder_org_and_drops_customer_tags(self):
        from core.models import Organization, Tag
        home = Organization.objects.order_by('pk').first()
        org = Organization.objects.create(name='Later Co', slug='later-co')
        doc = Document.objects.create(organization=org, title='Moved', slug='moved',
                                      body='<p>b</p>', content_type='html', is_published=True)
        tag = Tag.objects.create(organization=org, name='cust-tag', slug='cust-tag')
        doc.tags.add(tag)
        self._post(self.client_for(self.staff, org=org), doc, make_global='on', tags=[tag.pk])
        doc.refresh_from_db()
        self.assertTrue(doc.is_global)
        self.assertEqual(doc.organization_id, home.pk)
        self.assertEqual(doc.tags.count(), 0)
        org.delete()
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())

    def test_staff_without_global_publish_gets_no_box(self):
        from unittest import mock
        doc = self._doc()
        c = self.client_for(self.staff)
        real = __import__('psa.views', fromlist=['_check_kb_perm'])._check_kb_perm
        with mock.patch('psa.views._check_kb_perm',
                        side_effect=lambda u, p: False if p == 'kb_publish_articles' else real(u, p)):
            self.assertNotIn('make_global', c.get(f'/docs/{doc.slug}/edit/').context['form'].fields)
            self._post(c, doc, make_global='on', is_client_visible='on')
        doc.refresh_from_db()
        self.assertFalse(doc.is_global)

    def test_unticked_stays_customer_article(self):
        doc = self._doc()
        self._post(self.client_for(self.staff), doc)
        doc.refresh_from_db()
        self.assertFalse(doc.is_global)

    def test_global_slug_clash_gets_suffix(self):
        Document.objects.create(organization=self.other_org, title='Runbook', slug='runbook',
                                body='<p>x</p>', is_global=True, is_published=True)
        doc = self._doc()
        self._post(self.client_for(self.staff), doc, make_global='on')
        doc.refresh_from_db()
        self.assertTrue(doc.is_global)
        self.assertEqual(doc.slug, 'runbook-2')

    def test_customer_editor_cannot_make_global(self):
        # Customer editors only edit customer-written articles (authz-tech).
        doc = self._doc(created_by=self.editor)
        c = self.client_for(self.editor)
        r = c.get(f'/docs/{doc.slug}/edit/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('make_global', r.context['form'].fields)
        self._post(c, doc, make_global='on')
        doc.refresh_from_db()
        self.assertFalse(doc.is_global)

    def test_global_editor_loads_content_and_has_save(self):
        doc = self._doc(is_global=True)
        r = self.client_for(self.staff).get(f'/docs/kb/{doc.slug}/edit/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Save changes', html)
        self.assertIn('dangerouslyPasteHTML(bodyTextarea.value', html)
        self.assertNotIn('clipboard.convert(bodyTextarea.value)', html)
