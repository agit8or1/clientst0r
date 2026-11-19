"""KB lists are grouped under category headings."""
from django.test import override_settings

from .kb_grouping import group_documents_by_category
from .models import Document, DocumentCategory
from .tests_lifecycle import TEST_MIDDLEWARE, _Base


def _cats():
    z = DocumentCategory.objects.create(name='Zeta', slug='zeta', order=1)
    a = DocumentCategory.objects.create(name='Alpha', slug='alpha', order=2)
    b = DocumentCategory.objects.create(name='Beta', slug='beta', order=2)
    sub = DocumentCategory.objects.create(name='Subby', slug='subby', order=0, parent=a)
    return z, a, b, sub


class GroupingHelperTests(_Base):
    def test_order_subcategory_and_uncategorized_last(self):
        z, a, b, sub = _cats()
        mk = lambda t, c: Document.objects.create(  # noqa: E731
            organization=self.org, title=t, slug=t.lower(), body='x',
            is_published=True, is_global=True, category=c)
        docs = [mk('Dn', None), mk('Db', b), mk('Dsub', sub), mk('Da', a), mk('Dz', z)]
        docs = list(Document.objects.filter(pk__in=[d.pk for d in docs])
                    .select_related('category__parent'))
        ordered, groups = group_documents_by_category(docs)
        self.assertEqual([g['label'] for g in groups],
                         ['Zeta', 'Alpha', 'Alpha › Subby', 'Beta', 'Uncategorized'])
        self.assertEqual([d.title for d in ordered], ['Dz', 'Da', 'Dsub', 'Db', 'Dn'])
        _, short = group_documents_by_category(docs, full_path=False)
        self.assertIn('Subby', [g['label'] for g in short])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalKbListGroupingTests(_Base):
    def test_rows_grouped_by_category_order(self):
        z, a, b, sub = _cats()
        mk = lambda t, c: Document.objects.create(  # noqa: E731
            organization=self.org, title=t, slug=t.lower(), body='x',
            is_published=True, is_global=True, category=c)
        mk('Uncat', None)
        mk('InBeta', b)
        mk('InZeta', z)
        mk('InAlpha', a)
        r = self.client_for(self.staff).get('/docs/kb/')
        self.assertEqual(r.status_code, 200)
        titles = [d.title for d in r.context['documents']]
        self.assertEqual(titles, ['InZeta', 'InAlpha', 'InBeta', 'Uncat'])
        html = r.content.decode()
        pos = [html.index(t) for t in ('InZeta', 'InAlpha', 'InBeta', 'Uncat')]
        self.assertEqual(pos, sorted(pos))
        self.assertContains(r, '0003 Uncategorized')

    def test_category_filter_still_works(self):
        z, a, b, sub = _cats()
        for t, c in (('OnlyZ', z), ('OnlyA', a)):
            Document.objects.create(organization=self.org, title=t, slug=t.lower(), body='x',
                                    is_published=True, is_global=True, category=c)
        r = self.client_for(self.staff).get(f'/docs/kb/?category={z.pk}')
        self.assertEqual([d.title for d in r.context['documents']], ['OnlyZ'])
