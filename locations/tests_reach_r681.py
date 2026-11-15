"""Location Global View endpoints stay within the technician's client
reach (v3.17.681). CONFIRMED: /locations/global-map-data/ checked only
"staff or superuser", so a technician whose client scope is Alpha only got
every client's location names and street addresses. Real roles only
(accounts.role_seeds)."""
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, override_settings
from django.urls import reverse

from core.tests._r681_fixture import TEST_MIDDLEWARE, R681Base, staff


class _Data(R681Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from locations.models import Location
        cls.loc_a = Location.objects.create(organization=cls.a, name='Alpha HQ qzx', street_address='1 Alpha Way',
                                            city='Atown', latitude=40.1, longitude=-74.1)
        cls.loc_b = Location.objects.create(organization=cls.b, name='Bravo HQ qzx', street_address='9 Bravo Rd',
                                            city='Btown', latitude=41.1, longitude=-75.1)
        cls.scoped = staff('r681_loc_scoped', 'tech_l2')
        cls.scoped.profile.client_scope = 'selected'
        cls.scoped.profile.save()
        cls.scoped.profile.scope_organizations.set([cls.a])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalMapDataTests(_Data):

    def test_scoped_technician_gets_only_their_clients(self):
        for org in (None, self.a):
            c = self.login(self.scoped, org)
            r = c.get(reverse('locations:global_location_map_data'))
            self.assertEqual(r.status_code, 200)
            body = r.content.decode()
            self.assertIn('Alpha HQ qzx', body, org)
            self.assertNotIn('Bravo HQ qzx', body, org)
            self.assertNotIn('9 Bravo Rd', body, org)

    def test_unscoped_staff_and_superuser_see_every_client(self):
        for user in (self.su, self.l2):
            r = self.login(user, self.a).get(reverse('locations:global_location_map_data'))
            self.assertIn('Bravo HQ qzx', r.content.decode(), user.username)

    def test_customer_refused(self):
        r = self.login(self.cust_admin, self.a).get(reverse('locations:global_location_map_data'))
        self.assertEqual(r.status_code, 403)
        self.assertNotIn(b'Bravo', r.content)

    def test_org_map_data_is_current_client_only(self):
        for user in (self.scoped, self.cust_admin, self.su):
            r = self.login(user, self.a).get(reverse('locations:location_map_data'))
            self.assertEqual(r.status_code, 200, user.username)
            self.assertIn('Alpha HQ qzx', r.content.decode())
            self.assertNotIn('Bravo HQ qzx', r.content.decode(), user.username)


class GlobalViewBranchTests(_Data):
    """The Global View branches of the list / detail views, called without
    the middleware's client auto-selection in front of them (hardening)."""

    def call(self, name, user, *args):
        from django.urls import resolve
        url = reverse(name, args=args)
        req = RequestFactory().get(url)
        SessionMiddleware(lambda r: None).process_request(req)
        from django.contrib.messages.storage.fallback import FallbackStorage
        req._messages = FallbackStorage(req)
        req.user = user
        req.current_organization = None
        req.is_staff_user = True
        return resolve(url).func(req, *args)

    def test_list_and_detail_stay_in_reach(self):
        from django.http import Http404
        resp = self.call('locations:location_list', self.scoped)
        self.assertNotIn(b'Bravo HQ qzx', resp.content)
        with self.assertRaises(Http404):
            self.call('locations:location_detail', self.scoped, self.loc_b.pk)
