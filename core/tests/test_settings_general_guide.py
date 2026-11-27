"""Fixes found while writing the Settings -> General guide (roadmap 112.8)."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from assets.models import EquipmentModel, Vendor
from assets.tests import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsGeneralGuideFixTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('setg-admin', 'a@example.test', 'pw')
        self.client = Client()
        self.client.force_login(self.admin)

    def test_equipment_catalog_shows_model_counts(self):
        vendor = Vendor.objects.create(name='Acme Gear', slug='acme-gear')
        for n in ('A1', 'A2'):
            EquipmentModel.objects.create(vendor=vendor, model_name=n, model_number=n, slug=n.lower())
        r = self.client.get('/assets/vendors/')
        self.assertContains(r, '2 models')

    def test_crm_is_switched_on_feature_toggles(self):
        # Since 3.17.780 the CRM switch lives with every other module under
        # Modules → Feature Toggles; General settings only points there.
        r = self.client.get('/core/settings/general/')
        self.assertNotContains(r, 'name="crm_enabled"')
        self.assertContains(r, '/core/settings/features/')
        self.assertNotContains(r, 'still work for direct access')
