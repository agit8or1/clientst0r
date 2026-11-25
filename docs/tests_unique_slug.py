"""Creating a document, template or diagram whose title is already used in the
same customer gets its own slug (it used to be an IntegrityError, HTTP 500),
and a title that equals a fixed URL ("Templates", "Create") stays reachable."""
from django.test import override_settings

from .models import Diagram, Document
from .tests_lifecycle import TEST_MIDDLEWARE, _Base


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UniqueSlugTests(_Base):
    def _create_doc(self, c, title):
        return c.post('/docs/create/', {
            'title': title, 'body': 'x', 'content_type': 'markdown',
            'is_published': 'on', 'review_interval_days': 90})

    def test_same_title_twice_gets_second_slug(self):
        c = self.client_for(self.staff)
        self.assertEqual(self._create_doc(c, 'Runbook').status_code, 302)
        self.assertEqual(self._create_doc(c, 'Runbook').status_code, 302)
        slugs = set(Document.objects.filter(organization=self.org, title='Runbook')
                    .values_list('slug', flat=True))
        self.assertEqual(slugs, {'runbook', 'runbook-2'})
        self.assertEqual(c.get('/docs/runbook-2/').status_code, 200)

    def test_title_matching_a_fixed_url_is_renamed(self):
        c = self.client_for(self.staff)
        self.assertEqual(self._create_doc(c, 'Templates').status_code, 302)
        doc = Document.objects.get(organization=self.org, title='Templates')
        self.assertEqual(doc.slug, 'templates-2')
        self.assertEqual(c.get('/docs/templates-2/').status_code, 200)

    def test_diagram_same_title_twice(self):
        c = self.client_for(self.staff)
        for _ in range(2):
            r = c.post('/docs/diagrams/create/', {
                'title': 'Core network', 'diagram_type': 'network', 'is_published': 'on'})
            self.assertEqual(r.status_code, 302)
        self.assertEqual(
            set(Diagram.objects.filter(organization=self.org).values_list('slug', flat=True)),
            {'core-network', 'core-network-2'})

    def test_diagram_form_has_no_slug_field_label(self):
        c = self.client_for(self.staff)
        html = c.get('/docs/diagrams/create/').content.decode()
        self.assertNotIn('>Slug</label>', html)

    def test_category_same_name_twice(self):
        from .models import DocumentCategory
        c = self.client_for(self.staff)
        for _ in range(2):
            r = c.post('/docs/categories/create/', {'name': 'Runbooks', 'icon': 'fa-book', 'order': 0})
            self.assertEqual(r.status_code, 302)
        self.assertEqual(
            set(DocumentCategory.objects.filter(organization=self.org).values_list('slug', flat=True)),
            {'runbooks', 'runbooks-2'})


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DocsSmallFixesTests(_Base):
    """Diagram buttons follow the role, the category icon renders, and a global
    KB article with a repeated title gets its own slug."""

    def _diagram(self):
        return Diagram.objects.create(organization=self.org, title='Floor A', slug='floor-a',
                                      diagram_type='network', is_published=True)

    def test_reader_sees_no_edit_or_delete_on_a_diagram(self):
        self._diagram()
        html = self.client_for(self.reader).get('/docs/diagrams/floor-a/').content.decode()
        self.assertNotIn('/docs/diagrams/floor-a/edit/', html)
        self.assertNotIn('/docs/diagrams/floor-a/delete/', html)
        html = self.client_for(self.publisher).get('/docs/diagrams/floor-a/').content.decode()
        self.assertIn('/docs/diagrams/floor-a/edit/', html)
        self.assertIn('/docs/diagrams/floor-a/delete/', html)

    def test_default_category_icon_renders_as_a_font_awesome_class(self):
        from .models import DocumentCategory
        DocumentCategory.objects.create(organization=self.org, name='Plain', slug='plain')
        html = self.client_for(self.staff).get('/docs/categories/').content.decode()
        self.assertIn('fas fa-folder', html)
        self.assertNotIn('class="fas folder"', html)

    def test_global_kb_same_title_twice(self):
        c = self.client_for(self.staff, org=False)
        from django.urls import reverse
        url = reverse('docs:global_kb_create')
        for _ in range(2):
            r = c.post(url, {'title': 'VPN setup', 'body': '<p>x</p>', 'content_type': 'html',
                             'scope': 'global'})
            self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        slugs = set(Document.objects.filter(title='VPN setup', is_global=True).values_list('slug', flat=True))
        self.assertEqual(slugs, {'vpn-setup', 'vpn-setup-2'})
