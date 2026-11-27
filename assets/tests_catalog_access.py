"""Equipment catalog lists are for MSP staff only (roadmap 112.8)."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, UserProfile, UserType
from assets.models import Vendor
from assets.tests import TEST_MIDDLEWARE, _login_in_org
from core.models import Organization


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EquipmentCatalogAccessTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Cat Org', slug='cat-org')
        self.vendor = Vendor.objects.create(name='Acme Networks', slug='acme-networks-catalog-test')
        self.urls = [reverse('assets:vendor_list'),
                     reverse('assets:vendor_detail', args=[self.vendor.pk]),
                     reverse('assets:equipment_model_list')]

    def _user(self, name, staff):
        u = User.objects.create_user(name, password='pw')
        Membership.objects.create(user=u, organization=self.org, role=Role.OWNER, is_active=True)
        if staff:
            UserProfile.objects.filter(user=u).update(user_type=UserType.STAFF)
            u = User.objects.get(pk=u.pk)
        c = Client()
        _login_in_org(c, u, self.org)
        return c

    def test_customer_user_gets_403(self):
        c = self._user('cust-owner', staff=False)
        for url in self.urls:
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_msp_staff_can_view(self):
        c = self._user('tech', staff=True)
        for url in self.urls:
            self.assertEqual(c.get(url).status_code, 200, url)
        self.assertContains(c.get(self.urls[0]), 'Acme Networks')

    def test_anonymous_is_sent_to_sign_in(self):
        r = Client().get(self.urls[0])
        self.assertEqual(r.status_code, 302)
