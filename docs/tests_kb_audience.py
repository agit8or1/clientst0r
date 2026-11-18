"""v3.17.711: who a KB article is for -- every customer, selected customers
and customer groups, or one customer -- set in the editor or in bulk."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import ClientPSASettings

from .models import CustomerGroup, Document
from .tests_kb_portal_global import _portal_client
from .tests_lifecycle import TEST_MIDDLEWARE, _Base


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalAudienceTests(TestCase):
    def setUp(self):
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        # The first organization is the global KB's placeholder owner.
        self.home = Organization.objects.create(name='Home', slug='aud-home')
        self.orgs, self.clients = [], []
        for n in ('a', 'b', 'c'):
            org = Organization.objects.create(name=f'Aud {n}', slug=f'aud-{n}')
            ClientPSASettings.objects.create(organization=org, portal_enabled=True)
            u = User.objects.create_user(f'aud-{n}', f'{n}@aud.test', 'pw')
            Membership.objects.create(user=u, organization=org, role=Role.READONLY, is_active=True)
            self.orgs.append(org)
            self.clients.append(_portal_client(u))
        ClientPSASettings.objects.create(organization=self.home, portal_enabled=True)
        hu = User.objects.create_user('aud-home', 'h@aud.test', 'pw')
        Membership.objects.create(user=hu, organization=self.home, role=Role.READONLY, is_active=True)
        self.home_client = _portal_client(hu)
        a, b, c = self.orgs
        mk = Document.objects.create
        mk(organization=self.home, is_global=True, title='ForEveryone', slug='aud-all', body='<p>x</p>',
           is_published=True, is_client_visible=True)
        direct = mk(organization=self.home, is_global=True, title='ForA', slug='aud-a', body='<p>x</p>',
                    is_published=True, is_client_visible=True, audience='selected')
        direct.shared_with.add(a)
        group = CustomerGroup.objects.create(name='M365')
        group.organizations.add(a, b)
        grouped = mk(organization=self.home, is_global=True, title='ForGroup', slug='aud-g',
                     body='<p>x</p>', is_published=True, is_client_visible=True, audience='selected')
        grouped.shared_with_groups.add(group)
        self.group = group

    def test_every_customer(self):
        for c in self.clients:
            self.assertContains(c.get('/portal/kb/'), 'ForEveryone')

    def test_shared_with_one_customer(self):
        a, b, c = self.clients
        self.assertContains(a.get('/portal/kb/'), 'ForA')
        self.assertEqual(a.get('/portal/kb/aud-a/').status_code, 200)
        self.assertNotContains(b.get('/portal/kb/'), 'ForA')
        self.assertEqual(b.get('/portal/kb/aud-a/').status_code, 404)

    def test_shared_through_a_group(self):
        a, b, c = self.clients
        self.assertContains(a.get('/portal/kb/'), 'ForGroup')
        self.assertContains(b.get('/portal/kb/'), 'ForGroup')
        self.assertNotContains(c.get('/portal/kb/'), 'ForGroup')
        # Joining the group later is enough.
        self.group.organizations.add(self.orgs[2])
        self.assertContains(c.get('/portal/kb/'), 'ForGroup')

    def test_placeholder_owner_does_not_see_restricted_articles(self):
        r = self.home_client.get('/portal/kb/')
        self.assertContains(r, 'ForEveryone')
        self.assertNotContains(r, 'ForA')
        self.assertNotContains(r, 'ForGroup')

    def test_no_duplicate_rows_with_several_paths(self):
        from portal.views import portal_kb_queryset
        doc = Document.objects.get(slug='aud-g')
        doc.shared_with.add(self.orgs[0])
        titles = list(portal_kb_queryset(self.orgs[0]).values_list('title', flat=True))
        self.assertEqual(titles.count('ForGroup'), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EditorAudienceTests(_Base):
    def setUp(self):
        self.doc = Document.objects.create(organization=self.other_org, title='Generic', slug='generic',
                                           body='<p>b</p>', content_type='html', is_published=True,
                                           is_global=True, is_client_visible=True)
        self.group = CustomerGroup.objects.create(name='Group X')

    def _data(self, **extra):
        data = {'title': 'Generic', 'body': '<p>b</p>', 'content_type': 'html', 'is_published': 'on',
                'review_interval_days': 90, 'kb_visibility_shown': '1', 'is_client_visible': 'on'}
        data.update(extra)
        return data

    def test_selected_customers_and_groups(self):
        c = self.client_for(self.staff)
        c.post('/docs/kb/generic/edit/', self._data(scope='selected', share_orgs=[self.org.pk],
                                                    share_groups=[self.group.pk]))
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.is_global)
        self.assertEqual(self.doc.audience, 'selected')
        self.assertEqual(list(self.doc.shared_with.all()), [self.org])
        self.assertEqual(list(self.doc.shared_with_groups.all()), [self.group])
        # The editor shows it again as Selected.
        f = c.get('/docs/kb/generic/edit/').context['form']
        self.assertEqual(f['scope'].value(), 'selected')

    def test_selected_needs_someone(self):
        r = self.client_for(self.staff).post('/docs/kb/generic/edit/', self._data(scope='selected'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('share_orgs', r.context['form'].errors)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.audience, 'all')

    def test_back_to_every_customer_clears_the_list(self):
        self.doc.audience = 'selected'
        self.doc.save()
        self.doc.shared_with.add(self.org)
        self.client_for(self.staff).post('/docs/kb/generic/edit/', self._data(scope='global'))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.audience, 'all')
        self.assertEqual(self.doc.shared_with.count(), 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BulkAudienceTests(_Base):
    def setUp(self):
        mk = Document.objects.create
        self.d1 = mk(organization=self.other_org, title='B1', slug='b1', body='x', is_published=True,
                     is_global=True, is_client_visible=True)
        self.d2 = mk(organization=self.other_org, title='B2', slug='b2', body='x', is_published=True,
                     is_global=True, is_client_visible=True)
        self.group = CustomerGroup.objects.create(name='G')
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True   # the Knowledge Base list is the PSA KB browser
        ss.save()
        self.c = self.client_for(self.staff)

    def _post(self, **data):
        data.setdefault('article_ids', [self.d1.pk, self.d2.pk])
        return self.c.post('/docs/kb/audience/', data)

    def test_only_selected_then_add_then_all(self):
        self._post(audience_action='selected', share_orgs=[self.org.pk])
        for d in (self.d1, self.d2):
            d.refresh_from_db()
            self.assertEqual(d.audience, 'selected')
            self.assertEqual(list(d.shared_with.all()), [self.org])
        self._post(audience_action='add', share_groups=[self.group.pk])
        self.d1.refresh_from_db()
        self.assertEqual(list(self.d1.shared_with.all()), [self.org])
        self.assertEqual(list(self.d1.shared_with_groups.all()), [self.group])
        self._post(audience_action='all')
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.audience, 'all')
        self.assertEqual(self.d1.shared_with.count() + self.d1.shared_with_groups.count(), 0)

    def test_add_leaves_every_customer_articles_alone(self):
        self._post(audience_action='add', share_orgs=[self.org.pk])
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.audience, 'all')
        self.assertEqual(self.d1.shared_with.count(), 0)

    def test_selected_without_anyone_is_refused(self):
        self._post(audience_action='selected')
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.audience, 'all')

    def test_move_out_of_the_global_kb(self):
        Document.objects.create(organization=self.org, title='Clash', slug='b1', body='x')
        self._post(audience_action='move', move_org=self.org.pk)
        self.d1.refresh_from_db()
        self.assertFalse(self.d1.is_global)
        self.assertEqual(self.d1.organization_id, self.org.pk)
        self.assertEqual(self.d1.slug, 'b1-2')

    def test_needs_publish_rights(self):
        from unittest import mock
        real = __import__('psa.views', fromlist=['_check_kb_perm'])._check_kb_perm
        with mock.patch('psa.views._check_kb_perm',
                        side_effect=lambda u, p: False if p == 'kb_publish_articles' else real(u, p)):
            r = self._post(audience_action='all')
            self.assertEqual(r.status_code, 403)
            page = self.c.get('/psa/kb/')
        self.assertNotContains(page, 'kb-audience-bar')

    def test_customer_user_cannot(self):
        r = self.client_for(self.publisher).post('/docs/kb/audience/', {
            'audience_action': 'selected', 'article_ids': [self.d1.pk], 'share_orgs': [self.org.pk]})
        self.assertIn(r.status_code, (302, 403))   # sent away by the staff-only gate
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.audience, 'all')

    def test_kb_list_shows_audience_and_bulk_bar(self):
        self.d1.audience = 'selected'
        self.d1.save()
        self.d1.shared_with_groups.add(self.group)
        r = self.c.get('/psa/kb/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'kb-audience-bar')
        self.assertContains(r, 'Every customer')
        self.assertContains(r, 'Customer groups')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerGroupPageTests(_Base):
    def test_create_edit_delete(self):
        c = self.client_for(self.staff)
        self.assertEqual(c.get('/docs/customer-groups/').status_code, 200)
        r = c.post('/docs/customer-groups/new/', {'name': 'Dental', 'description': 'd',
                                                   'organizations': [self.org.pk, self.other_org.pk]})
        self.assertEqual(r.status_code, 302)
        g = CustomerGroup.objects.get(name='Dental')
        self.assertEqual(g.organizations.count(), 2)
        c.post(f'/docs/customer-groups/{g.pk}/edit/', {'name': 'Dental', 'organizations': [self.org.pk]})
        self.assertEqual(g.organizations.count(), 1)
        c.post(f'/docs/customer-groups/{g.pk}/delete/')
        self.assertFalse(CustomerGroup.objects.filter(pk=g.pk).exists())

    def test_customer_users_are_kept_out(self):
        c = self.client_for(self.publisher)
        self.assertNotEqual(c.get('/docs/customer-groups/').status_code, 200)
        c.post('/docs/customer-groups/new/', {'name': 'Nope'})
        self.assertFalse(CustomerGroup.objects.filter(name='Nope').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BulkMakeGlobalTests(_Base):
    def test_documents_move_into_the_global_kb(self):
        mk = Document.objects.create
        d1 = mk(organization=self.org, title='One', slug='one', body='x', is_published=True)
        d2 = mk(organization=self.org, title='Two', slug='two', body='x', is_published=True)
        c = self.client_for(self.staff)
        self.assertContains(c.get('/docs/'), 'docBulkForm')
        c.post('/docs/bulk/make-global/', {'ids': [d1.pk, d2.pk]})
        for d in (d1, d2):
            d.refresh_from_db()
            self.assertTrue(d.is_global)
            self.assertEqual(d.audience, 'all')

    def test_customer_user_cannot(self):
        d = Document.objects.create(organization=self.org, title='Mine', slug='mine', body='x',
                                    created_by=self.publisher)
        c = self.client_for(self.publisher)
        self.assertNotContains(c.get('/docs/'), 'docBulkForm')
        c.post('/docs/bulk/make-global/', {'ids': [d.pk]})
        d.refresh_from_db()
        self.assertFalse(d.is_global)
