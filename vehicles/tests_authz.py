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


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VehicleInventoryAccessTests(TestCase):
    """The van stock pages checked a vehicle organization that does not exist
    (a server error for every technician without Django staff), and the
    count could be set to text or a negative number."""

    @classmethod
    def setUpTestData(cls):
        from vehicles.models import VehicleInventoryItem
        cls.tech = _make_msp_tech(User.objects.create_user('veh-inv-tech', 't2@x.test', 'pw'))
        org = Organization.objects.create(name='V Cust 2', slug='authz-veh-cust2')
        cls.customer = User.objects.create_user('veh-inv-cust', 'c2@c.test', 'pw')
        Membership.objects.create(user=cls.customer, organization=org, role=Role.OWNER)
        cls.van = ServiceVehicle.objects.create(
            name='Van 2', vehicle_type='van', make='Ford', model='Transit', year=2022,
            license_plate='AUTHZ2', current_mileage=1)
        cls.item = VehicleInventoryItem.objects.create(vehicle=cls.van, name='CAT6 patch lead', quantity=5)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def test_technician_gets_the_qr_code(self):
        self.assertFalse(self.tech.is_staff)
        r = self._client(self.tech).get(reverse('vehicles:inventory_qr_image', args=[self.item.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')

    def test_customer_user_is_refused(self):
        r = self._client(self.customer).get(reverse('vehicles:inventory_qr_image', args=[self.item.pk]))
        self.assertEqual(r.status_code, 403)

    def test_count_must_be_a_whole_number_of_zero_or_more(self):
        c = self._client(self.tech)
        url = reverse('vehicles:inventory_scan_update', args=[self.item.qr_code])
        for bad in ('abc', '-3'):
            r = c.post(url, {'action': 'set_quantity', 'quantity': bad})
            self.assertEqual(r.status_code, 302, bad)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)
        c.post(url, {'action': 'set_quantity', 'quantity': '7'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 7)
