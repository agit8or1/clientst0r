"""A list that shows a row must link to a detail page that opens it.

`Organization.parent`'s own help text reads "The parent's queries see
descendants' rows; descendants stay scoped to themselves", and the list pages
implement exactly that through `OrganizationManager.for_organization()`. The
detail, edit and delete views those lists link to looked their row up with a
bare `organization=org`, which stops at the selected organization.

So a parent organization's asset list rendered a subsidiary's server, and
clicking it returned 404. Same for its passwords, inventory, scheduled tasks
and integration connections — 73 lookups across nine modules.

These tests pin both halves: the descendant's row opens, and an unrelated
organization's row still does not.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate
from assets.models import Asset, Contact
from core.models import Organization
from inventory.models import InventoryItem
from vault.models import Password


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ParentOrgReachesDescendantRowsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.parent = Organization.objects.create(name='Holdings', slug='hd-p')
        cls.child = Organization.objects.create(
            name='Holdings North', slug='hd-c', parent=cls.parent,
        )
        cls.stranger = Organization.objects.create(name='Rival', slug='hd-r')

        cls.child_asset = Asset.objects.create(
            organization=cls.child, name='child-server-01')
        cls.rival_asset = Asset.objects.create(
            organization=cls.stranger, name='rival-server-01')
        cls.child_contact = Contact.objects.create(
            organization=cls.child, first_name='Dana', last_name='Childs',
            email='dana@example.com')
        cls.child_password = Password.objects.create(
            organization=cls.child, title='child-router', username='admin')
        cls.rival_password = Password.objects.create(
            organization=cls.stranger, title='rival-router', username='admin')
        cls.child_item = InventoryItem.objects.create(
            organization=cls.child, name='child-cable', quantity=5)

        User = get_user_model()
        cls.user = User.objects.create_user('hd_user', 'h@x.com', 'pw')
        rt = RoleTemplate.objects.create(name='HierarchyAdmin')
        Membership.objects.create(
            user=cls.user, organization=cls.parent,
            role='admin', role_template=rt, is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['current_organization_id'] = self.parent.pk
        session.save()

    # -- the link the list already offers ------------------------------------

    def test_asset_list_shows_a_descendants_row(self):
        r = self.client.get(reverse('assets:asset_list'))
        self.assertContains(r, 'child-server-01')

    def test_and_that_rows_detail_page_opens(self):
        """This is the 404 the whole change exists to fix."""
        r = self.client.get(
            reverse('assets:asset_detail', kwargs={'pk': self.child_asset.pk}))
        self.assertEqual(r.status_code, 200)

    def test_a_descendants_contact_opens(self):
        r = self.client.get(
            reverse('assets:contact_detail', kwargs={'pk': self.child_contact.pk}))
        self.assertEqual(r.status_code, 200)

    def test_a_descendants_password_opens(self):
        r = self.client.get(
            reverse('vault:password_detail', kwargs={'pk': self.child_password.pk}))
        self.assertEqual(r.status_code, 200)

    def test_a_descendants_inventory_item_opens(self):
        r = self.client.get(
            reverse('inventory:item_detail', kwargs={'pk': self.child_item.pk}))
        self.assertEqual(r.status_code, 200)

    # -- and no further ------------------------------------------------------

    def test_an_unrelated_orgs_asset_is_still_out_of_reach(self):
        r = self.client.get(
            reverse('assets:asset_detail', kwargs={'pk': self.rival_asset.pk}))
        self.assertEqual(r.status_code, 404)

    def test_an_unrelated_orgs_password_is_still_out_of_reach(self):
        r = self.client.get(
            reverse('vault:password_detail', kwargs={'pk': self.rival_password.pk}))
        self.assertEqual(r.status_code, 404)

    def test_a_descendant_cannot_reach_its_parents_rows(self):
        """Descendants stay scoped to themselves — the rule is one-directional."""
        parent_asset = Asset.objects.create(
            organization=self.parent, name='parent-server-01')
        User = get_user_model()
        child_user = User.objects.create_user('hd_child', 'c@x.com', 'pw')
        Membership.objects.create(
            user=child_user, organization=self.child, role='admin',
            role_template=RoleTemplate.objects.get(name='HierarchyAdmin'),
            is_active=True,
        )
        self.client.force_login(child_user)
        session = self.client.session
        session['current_organization_id'] = self.child.pk
        session.save()

        r = self.client.get(
            reverse('assets:asset_detail', kwargs={'pk': parent_asset.pk}))
        self.assertEqual(r.status_code, 404)

    def test_a_descendants_integration_connection_opens(self):
        """
        `M365Connection` was missed on the first pass: its name contains
        digits, and the scan that built the model list captured names with
        `[A-Za-z_]+`, which stops at the `3`. Its five lookups stayed strict
        while the integrations dashboard listed it with `for_organization`.
        """
        from integrations.models import M365Connection

        conn = M365Connection.objects.create(
            organization=self.child, name='child-m365', tenant_id='t',
        )
        r = self.client.get(
            reverse('integrations:m365_detail', kwargs={'pk': conn.pk}))
        self.assertNotEqual(r.status_code, 404)

    def test_a_user_with_no_organization_selected_reaches_nothing(self):
        """`descendant_org_ids(None)` is empty, so no row matches."""
        from core.tenancy import get_org_object_or_404
        from django.http import Http404

        with self.assertRaises(Http404):
            get_org_object_or_404(Asset, None, pk=self.child_asset.pk)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RackDeviceAssetScopeTests(TestCase):
    """
    `create_rack_device` writes its asset lookup as a conditional expression
    with the *unscoped* branch first:

        asset = <unscoped> if not org else <scoped>

    which is easy to invert while editing — and an inversion here hands any
    organization's asset to any caller, silently, through a JSON API. These
    tests pin the branch rather than the spelling.
    """

    @classmethod
    def setUpTestData(cls):
        from monitoring.models import Rack

        cls.mine = Organization.objects.create(name='Mine', slug='rk-mine')
        cls.theirs = Organization.objects.create(name='Theirs', slug='rk-theirs')
        cls.rack = Rack.objects.create(organization=cls.mine, name='Rack 1')
        cls.their_asset = Asset.objects.create(
            organization=cls.theirs, name='their-server')

        User = get_user_model()
        cls.user = User.objects.create_user('rk_user', 'r@x.com', 'pw')
        rt = RoleTemplate.objects.create(name='RackAdmin')
        Membership.objects.create(
            user=cls.user, organization=cls.mine,
            role='admin', role_template=rt, is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['current_organization_id'] = self.mine.pk
        session.save()

    def test_cannot_rack_another_organizations_asset(self):
        r = self.client.post(
            reverse('monitoring:api_create_rack_device',
                    kwargs={'pk': self.rack.pk}),
            data=f'{{"asset_id": {self.their_asset.pk}, "start_unit": 1}}',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 404)

    def test_can_rack_a_descendants_asset(self):
        child = Organization.objects.create(
            name='Mine North', slug='rk-mine-n', parent=self.mine)
        child_asset = Asset.objects.create(
            organization=child, name='child-server')
        r = self.client.post(
            reverse('monitoring:api_create_rack_device',
                    kwargs={'pk': self.rack.pk}),
            data=f'{{"asset_id": {child_asset.pk}, "start_unit": 2}}',
            content_type='application/json',
        )
        self.assertNotEqual(r.status_code, 404)
