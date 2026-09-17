"""Global search has to see what the list pages see.

`core.search_views.global_search` filtered a bare `organization=org` on every
content type, while the list pages it mirrors go through
`OrganizationManager.for_organization()`. Two consequences, both under-returns
and so both invisible — a search saying "no results" looks exactly like the
thing not existing:

  * Phase 18's organization hierarchy was ignored. A user at a parent org sees
    a subsidiary's rows on every list page and got no hits for them here.
  * In global view (`org is None`, staff or superuser) `organization=None`
    matched nothing, so search came back empty across all six content types
    while every list page showed the whole install.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, Contact
from core.models import Organization
from docs.models import Document
from vault.models import Password


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalSearchScopingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate

        cls.parent = Organization.objects.create(name='Holdings', slug='gs-parent')
        cls.child = Organization.objects.create(
            name='Holdings North', slug='gs-child', parent=cls.parent,
        )
        cls.stranger = Organization.objects.create(name='Rival', slug='gs-rival')

        # One searchable row per content type, all owned by the CHILD org and
        # all sharing a distinctive term.
        Asset.objects.create(organization=cls.child, name='zebrafish-switch')
        Contact.objects.create(
            organization=cls.child, first_name='Zebrafish', last_name='Jones',
            email='z@example.com',
        )
        Document.objects.create(
            organization=cls.child, title='zebrafish runbook', body='body',
            is_published=True,
        )
        pw = Password(organization=cls.child, title='zebrafish router',
                      username='admin')
        pw.set_password('hunter2') if hasattr(pw, 'set_password') else None
        pw.save()

        # A row at the unrelated org that must never appear for the parent.
        Asset.objects.create(organization=cls.stranger, name='zebrafish-rival')

        User = get_user_model()
        cls.parent_user = User.objects.create_user('gs_parent', 'p@x.com', 'pw')
        rt = RoleTemplate.objects.create(name='GSViewer')
        Membership.objects.create(
            user=cls.parent_user, organization=cls.parent,
            role='admin', role_template=rt, is_active=True,
        )
        cls.msp = User.objects.create_user(
            'gs_msp', 'm@x.com', 'pw', is_staff=True, is_superuser=True,
        )

    def _search(self, user, term='zebrafish', org_id=...):
        self.client.force_login(user)
        if org_id is not ...:
            session = self.client.session
            if org_id is None:
                session.pop('current_organization_id', None)
                session['global_view_mode'] = True
            else:
                session['current_organization_id'] = org_id
            session.save()
        return self.client.get(reverse('core:search'), {'q': term})

    # -- the hierarchy --------------------------------------------------------

    def test_parent_org_search_finds_a_subsidiarys_asset(self):
        r = self._search(self.parent_user, org_id=self.parent.pk)
        self.assertEqual(r.status_code, 200)
        names = [a.name for a in r.context['assets']]
        self.assertIn('zebrafish-switch', names)

    def test_parent_org_search_finds_a_subsidiarys_contact(self):
        r = self._search(self.parent_user, org_id=self.parent.pk)
        self.assertEqual(len(r.context['contacts']), 1)

    def test_parent_org_search_finds_a_subsidiarys_document(self):
        r = self._search(self.parent_user, org_id=self.parent.pk)
        self.assertEqual(len(r.context['documents']), 1)

    def test_parent_org_search_finds_a_subsidiarys_password(self):
        r = self._search(self.parent_user, org_id=self.parent.pk)
        self.assertEqual(len(r.context['passwords']), 1)

    def test_search_still_stops_at_an_unrelated_org(self):
        """Reaching descendants must not mean reaching sideways."""
        r = self._search(self.parent_user, org_id=self.parent.pk)
        names = [a.name for a in r.context['assets']]
        self.assertIn('zebrafish-switch', names)
        self.assertNotIn('zebrafish-rival', names)

    # -- global view ----------------------------------------------------------

    def test_global_view_search_returns_every_organizations_rows(self):
        r = self._search(self.msp, org_id=None)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['in_global_view'])
        names = {a.name for a in r.context['assets']}
        self.assertIn('zebrafish-switch', names)
        self.assertIn('zebrafish-rival', names)

    def test_global_view_used_to_return_nothing_at_all(self):
        """The regression this file exists for: `organization=None` matched no row."""
        r = self._search(self.msp, org_id=None)
        self.assertGreater(r.context['total_count'], 0)

    # -- the floor ------------------------------------------------------------

    def test_a_user_with_no_org_and_no_staff_flag_finds_nothing(self):
        User = get_user_model()
        nobody = User.objects.create_user('gs_nobody', 'n@x.com', 'pw')
        r = self._search(nobody, org_id=None)
        self.assertEqual(r.context['total_count'], 0)

    def test_a_short_query_searches_nothing(self):
        r = self._search(self.parent_user, term='z', org_id=self.parent.pk)
        self.assertEqual(r.context['total_count'], 0)

    # -- telling the rows apart ----------------------------------------------

    def test_results_name_their_org_when_the_set_can_span_orgs(self):
        """
        Results never used to span organizations, so nothing said which one a
        row belonged to. Now that a parent sees its subsidiaries' rows, and
        global view sees everything, each row has to say whose it is.
        """
        r = self._search(self.parent_user, org_id=self.parent.pk)
        self.assertTrue(r.context['show_org_badge'])
        self.assertIn(b'Holdings North', r.content)

    def test_no_org_badge_when_results_cannot_span_orgs(self):
        from accounts.models import Membership, RoleTemplate

        User = get_user_model()
        leaf_user = User.objects.create_user('gs_leaf', 'l@x.com', 'pw')
        rt = RoleTemplate.objects.get(name='GSViewer')
        Membership.objects.create(
            user=leaf_user, organization=self.child,
            role='admin', role_template=rt, is_active=True,
        )
        r = self._search(leaf_user, org_id=self.child.pk)
        self.assertFalse(r.context['show_org_badge'])
