"""Server-side authorization regressions for service vehicles (roles/
permissions program): the MSP fleet is MSP-staff only."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from vehicles.models import ServiceVehicle


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VehiclesStaffOnlyTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='V Cust', slug='authz-veh-cust')
        cls.customer = User.objects.create_user('veh-cust', 'c@c.test', 'pw')
        Membership.objects.create(user=cls.customer, organization=cls.org, role=Role.OWNER)
        cls.tech = _make_msp_tech(User.objects.create_user('veh-tech', 't@x.test', 'pw'))
        cls.van = ServiceVehicle.objects.create(
            name='Van', vehicle_type='van', make='Ford', model='Transit', year=2022,
            license_plate='AUTHZ1', current_mileage=1)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def test_customer_user_is_refused_every_fleet_page(self):
        c = self._client(self.customer)
        for url in (reverse('vehicles:vehicles_dashboard'), reverse('vehicles:vehicle_list'),
                    reverse('vehicles:vehicle_detail', args=[self.van.pk]),
                    reverse('vehicles:vehicle_edit', args=[self.van.pk])):
            self.assertEqual(c.get(url).status_code, 403, url)
        r = c.post(reverse('vehicles:vehicle_delete', args=[self.van.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(ServiceVehicle.objects.filter(pk=self.van.pk).exists())

    def test_anonymous_is_sent_to_login(self):
        r = Client().get(reverse('vehicles:vehicle_list'))
        self.assertEqual(r.status_code, 302)

    def test_msp_tech_keeps_access(self):
        self.assertEqual(self._client(self.tech).get(reverse('vehicles:vehicle_list')).status_code, 200)
