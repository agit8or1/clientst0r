"""Global search honours vault_view / docs_view / assets_view and reports
real per-category counts rather than the length of the 10-row slice."""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate, UserType
from assets.models import Asset, Contact
from core.models import Organization
from docs.models import Document
from vault.models import Password


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

SECRET = 'S3cr3t-Pl41ntext-Value!'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SearchPermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Quokka Co', slug='sp-quokka')
        cls.other = Organization.objects.create(name='Other Co', slug='sp-other')

        for i in range(12):
            Asset.objects.create(organization=cls.org, name=f'quokka-asset-{i:02d}')
        Contact.objects.create(organization=cls.org, first_name='Quokka', last_name='Smith')
        Document.objects.create(organization=cls.org, title='quokka runbook',
                                body='b', is_published=True)
        Document.objects.create(organization=None, title='quokka global kb',
                                body='b', is_published=True, is_global=True)
        for i in range(3):
            pw = Password(organization=cls.org, title=f'quokka router {i}', username='admin')
            pw.set_password(SECRET)
            pw.save()
        # Same customer-B rows, for the per-customer test.
        Password(organization=cls.other, title='quokka other pw',
                 username='u', encrypted_password='x').save()

        User = get_user_model()
        cls.no_vault = RoleTemplate.objects.create(
            name='No vault', organization=cls.org, vault_view=False)
        cls.no_docs = RoleTemplate.objects.create(
            name='No docs', organization=cls.org, docs_view=False)
        cls.no_assets = RoleTemplate.objects.create(
            name='No assets', organization=cls.org, assets_view=False)
        cls.all_on = RoleTemplate.objects.create(name='All on', organization=cls.org)

        def customer(name, role):
            u = User.objects.create_user(name, f'{name}@x.com', 'pw')
            Membership.objects.create(user=u, organization=cls.org, role='admin',
                                      role_template=role)
            return u

        cls.u_no_vault = customer('sp_novault', cls.no_vault)
        cls.u_no_docs = customer('sp_nodocs', cls.no_docs)
        cls.u_no_assets = customer('sp_noassets', cls.no_assets)
        cls.u_all = customer('sp_all', cls.all_on)

        cls.superuser = User.objects.create_user(
            'sp_super', 'su@x.com', 'pw', is_superuser=True, is_staff=True)
        cls.staff_no_docs = User.objects.create_user('sp_staff', 'st@x.com', 'pw')
        cls.staff_no_docs.profile.user_type = UserType.STAFF
        cls.staff_no_docs.profile.global_role_template = RoleTemplate.objects.create(
            name='Global no docs', docs_view=False)
        cls.staff_no_docs.profile.save()

    def _search(self, user, org=None, term='quokka'):
        self.client.force_login(user)
        session = self.client.session
        if org is None:
            session.pop('current_organization_id', None)
            session['global_view_mode'] = True
        else:
            session['current_organization_id'] = org.pk
        session.save()
        r = self.client.get(reverse('core:search'), {'q': term})
        self.assertEqual(r.status_code, 200)
        return r

    def test_vault_view_false_hides_passwords_and_their_count(self):
        r = self._search(self.u_no_vault, self.org)
        self.assertEqual(list(r.context['passwords']), [])
        self.assertEqual(r.context['counts']['passwords'], 0)
        self.assertNotIn(b'quokka router', r.content)
        # Other categories unaffected.
        self.assertEqual(r.context['counts']['assets'], 12)

    def test_docs_view_false_hides_documents(self):
        r = self._search(self.u_no_docs, self.org)
        self.assertEqual(r.context['counts']['documents'], 0)
        self.assertNotIn(b'quokka runbook', r.content)
        self.assertEqual(r.context['counts']['passwords'], 3)

    def test_assets_view_false_hides_assets_and_contacts(self):
        r = self._search(self.u_no_assets, self.org)
        self.assertEqual(r.context['counts']['assets'], 0)
        self.assertEqual(r.context['counts']['contacts'], 0)
        self.assertNotIn(b'quokka-asset', r.content)

    def test_counts_are_real_beyond_the_slice(self):
        r = self._search(self.u_all, self.org)
        self.assertEqual(len(r.context['assets']), 10)
        self.assertEqual(r.context['counts']['assets'], 12)
        self.assertContains(r, 'Showing 10 of 12')
        c = r.context['counts']
        self.assertEqual(r.context['total_count'], sum(c.values()))
        # 12 assets + 1 contact + 1 doc + 3 passwords (customer user: no global KB)
        self.assertEqual(r.context['total_count'], 17)
        self.assertNotIn('global_kb', c)

    def test_secrets_never_in_output(self):
        for user, org in ((self.u_all, self.org), (self.superuser, None)):
            with self.subTest(user=user.username):
                r = self._search(user, org)
                self.assertNotIn(SECRET.encode(), r.content)

    def test_superuser_global_view_sees_everything_including_global_kb(self):
        r = self._search(self.superuser, None)
        c = r.context['counts']
        self.assertEqual(c['passwords'], 4)
        self.assertEqual(c['global_kb'], 1)

    def test_staff_global_role_without_docs_view_loses_docs_and_global_kb(self):
        r = self._search(self.staff_no_docs, None)
        c = r.context['counts']
        self.assertEqual(c['documents'], 0)
        self.assertNotIn('global_kb', c)
        self.assertEqual(list(r.context['global_kb']), [])
        self.assertEqual(c['assets'], 12)
