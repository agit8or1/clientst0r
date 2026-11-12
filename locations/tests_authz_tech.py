"""Roles & permissions program (authz-tech): locations follow the assets_*
role flags in the customer that owns the location.

Read-Only members can no longer create, edit, delete or refresh locations or
send navigation mails; a customer associated with a shared location cannot
rewrite the owner's record or see the owner's circuits; customer users cannot
share a location with other customers; the WAN check no longer runs on GET.
"""
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from locations.models import WAN, Location

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LocationRoleFlagTests(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='Loc A', slug='authz-loc-a')
        self.b = Organization.objects.create(name='Loc B', slug='authz-loc-b')
        self.loc = Location.objects.create(organization=self.a, name='HQ', city='Town')
        self.shared = Location.objects.create(organization=self.b, name='DC', is_shared=True)
        self.shared.associated_organizations.add(self.a)
        self.c = Client()

    def _member(self, role, org=None):
        u = User.objects.create_user(f'authz-loc-{role}-{User.objects.count()}', password='pw')
        Membership.objects.create(user=u, organization=org or self.a, role=role)
        _login(self.c, u, org or self.a)
        return u

    def test_readonly_cannot_create_edit_or_delete(self):
        self._member(Role.READONLY)
        self.assertEqual(self.c.post(reverse('locations:location_create'), {'name': 'New'}).status_code, 403)
        self.assertEqual(self.c.get(reverse('locations:location_edit', args=[self.loc.pk])).status_code, 403)
        self.assertEqual(self.c.post(reverse('locations:location_delete', args=[self.loc.pk])).status_code, 403)
        self.assertTrue(Location.objects.filter(pk=self.loc.pk).exists())
        self.assertFalse(Location.objects.filter(name='New').exists())

    def test_readonly_cannot_refresh_or_send_navigation(self):
        self._member(Role.READONLY)
        for name in ('refresh_geocoding', 'refresh_property_data', 'refresh_satellite_image'):
            with self.subTest(name):
                self.assertEqual(self.c.post(reverse(f'locations:{name}', args=[self.loc.pk])).status_code, 403)
        resp = self.c.post(reverse('locations:send_navigation_link', args=[self.loc.pk]),
                           {'method': 'email', 'recipient_email': 'x@example.test', 'map_service': 'google'})
        self.assertEqual(resp.status_code, 403)

    def test_editor_still_edits_own_location(self):
        self._member(Role.EDITOR)
        self.assertEqual(self.c.get(reverse('locations:location_edit', args=[self.loc.pk])).status_code, 200)

    def test_associated_customer_cannot_edit_owners_shared_location(self):
        self._member(Role.OWNER)
        self.assertEqual(self.c.get(reverse('locations:location_detail', args=[self.shared.pk])).status_code, 200)
        self.assertEqual(self.c.get(reverse('locations:location_edit', args=[self.shared.pk])).status_code, 403)
        self.assertEqual(self.c.post(reverse('locations:refresh_geocoding', args=[self.shared.pk])).status_code, 403)

    def test_customer_form_has_no_sharing_fields(self):
        from locations.forms import LocationForm
        u = self._member(Role.OWNER)
        form = LocationForm(organization=self.a, user=u)
        self.assertNotIn('associated_organizations', form.fields)
        self.assertNotIn('is_shared', form.fields)

    def test_shared_location_hides_other_customers_circuits(self):
        WAN.objects.create(organization=self.b, location=self.shared, name='B fiber')
        WAN.objects.create(organization=self.a, location=self.shared, name='A cable')
        self._member(Role.OWNER)
        # (The separate WAN list page has no template; the location page
        # carries the same list.)
        resp = self.c.get(reverse('locations:location_detail', args=[self.shared.pk]))
        names = {w.name for w in resp.context['wan_connections']}
        self.assertEqual(names, {'A cable'})

    def test_wan_check_needs_post(self):
        wan = WAN.objects.create(organization=self.a, location=self.loc, name='Fiber',
                                 monitoring_enabled=True, monitor_target='203.0.113.1')
        self._member(Role.OWNER)
        with mock.patch.object(WAN, 'check_status') as check:
            resp = self.c.get(reverse('locations:wan_check_status', args=[self.loc.pk, wan.pk]))
        self.assertEqual(resp.status_code, 405)
        check.assert_not_called()

    def test_readonly_cannot_run_wan_check(self):
        wan = WAN.objects.create(organization=self.a, location=self.loc, name='Fiber',
                                 monitoring_enabled=True, monitor_target='203.0.113.1')
        self._member(Role.READONLY)
        with mock.patch.object(WAN, 'check_status') as check:
            resp = self.c.post(reverse('locations:wan_check_status', args=[self.loc.pk, wan.pk]))
        self.assertEqual(resp.status_code, 403)
        check.assert_not_called()
