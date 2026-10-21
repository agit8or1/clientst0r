"""v3.17.621 — custom asset fields and custom asset types (discussion #135),
and the equipment catalog limited to MSP staff for changes (#132)."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership
from api.models import APIKey
from assets.forms import AssetForm
from assets.models import Asset, AssetCustomField, AssetType, Vendor
from core.models import Organization

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _client(user, org=None):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomFieldTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='CF', slug='cf')
        self.admin = User.objects.create_superuser('cfadmin', 'a@x.com', 'pw')
        self.editor = User.objects.create_user('cfeditor', password='pw')
        Membership.objects.create(user=self.editor, organization=self.org, role='admin')
        self.budget = AssetCustomField.objects.create(label='Budget code', key='budget_code')
        self.rack_row = AssetCustomField.objects.create(
            label='Rack row', key='rack_row', field_type='dropdown', choices='A\nB',
            is_required=True, asset_types=['server'])

    def _form(self, data, instance=None):
        base = {'name': 'srv1', 'asset_type': 'server'}
        base.update(data)
        return AssetForm(base, instance=instance, organization=self.org)

    def test_values_saved_and_other_keys_kept(self):
        asset = Asset.objects.create(organization=self.org, name='srv1', asset_type='server',
                                     custom_fields={'discovered_os': 'Linux'})
        form = self._form({'cf__budget_code': 'IT-42', 'cf__rack_row': 'B'}, instance=asset)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        asset.refresh_from_db()
        self.assertEqual(asset.custom_fields,
                         {'discovered_os': 'Linux', 'budget_code': 'IT-42', 'rack_row': 'B'})

    def test_required_only_for_matching_type(self):
        form = self._form({'cf__budget_code': 'x'})
        self.assertFalse(form.is_valid())
        self.assertIn('cf__rack_row', form.errors)
        form = self._form({'asset_type': 'laptop'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_clearing_a_value_removes_the_key(self):
        asset = Asset.objects.create(organization=self.org, name='srv1', asset_type='laptop',
                                     custom_fields={'budget_code': 'old'})
        form = self._form({'asset_type': 'laptop', 'cf__budget_code': ''}, instance=asset)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        asset.refresh_from_db()
        self.assertNotIn('budget_code', asset.custom_fields)

    def test_form_and_detail_pages(self):
        asset = Asset.objects.create(organization=self.org, name='srv1', asset_type='server',
                                     custom_fields={'budget_code': 'IT-42', 'last_scanned': 'today'})
        c = _client(self.editor, self.org)
        self.assertContains(c.get('/assets/create/'), 'name="cf__budget_code"')
        r = c.get(f'/assets/{asset.pk}/')
        self.assertContains(r, 'Budget code')
        self.assertContains(r, 'IT-42')
        self.assertContains(r, 'Last_Scanned')

    def test_manage_pages_staff_only(self):
        c = _client(self.editor, self.org)
        self.assertEqual(c.get('/assets/custom-fields/').status_code, 403)
        self.assertEqual(c.post('/assets/custom-fields/new/', {'label': 'X'}).status_code, 403)
        self.assertEqual(c.post('/assets/types/new/', {'name': 'X'}).status_code, 403)

    def test_admin_creates_field(self):
        c = _client(self.admin)
        r = c.post('/assets/custom-fields/new/', {
            'label': 'Support contract', 'key': '', 'field_type': 'text', 'order': 0,
            'is_active': 'on', 'asset_types': ['server', 'nas']})
        self.assertEqual(r.status_code, 302)
        f = AssetCustomField.objects.get(label='Support contract')
        self.assertEqual(f.key, 'support_contract')
        self.assertEqual(f.asset_types, ['server', 'nas'])

    def test_dropdown_needs_options(self):
        c = _client(self.admin)
        r = c.post('/assets/custom-fields/new/', {
            'label': 'Tier', 'field_type': 'dropdown', 'order': 0, 'is_active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(AssetCustomField.objects.filter(label='Tier').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomAssetTypeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='CT', slug='ct')
        self.admin = User.objects.create_superuser('ctadmin', 'a@x.com', 'pw')

    def test_create_type_and_use_it(self):
        c = _client(self.admin)
        r = c.post('/assets/types/new/', {'name': 'Solar Inverter', 'slug': '', 'icon': 'fa-plug',
                                         'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        t = AssetType.objects.get(name='Solar Inverter')
        self.assertIsNone(t.organization)
        self.assertEqual(t.slug, 'solar_inverter')
        form = AssetForm({'name': 'inv1', 'asset_type': 'solar_inverter'}, organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save(commit=False)
        asset.organization = self.org
        asset.save()
        self.assertEqual(asset.get_asset_type_display(), 'Solar Inverter')
        self.assertIn(('solar_inverter', 'Solar Inverter'),
                      [tuple(ch) for ch in AssetForm(organization=self.org).fields['asset_type'].choices])

    def test_builtin_code_rejected(self):
        r = _client(self.admin).post('/assets/types/new/', {'name': 'Server', 'slug': 'server',
                                                            'icon': 'fa-box', 'is_active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(AssetType.objects.filter(slug='server').exists())

    def test_inactive_or_unknown_type_rejected(self):
        AssetType.objects.create(name='Old', slug='old_thing', is_active=False)
        for code in ('old_thing', 'nope'):
            form = AssetForm({'name': 'x', 'asset_type': code}, organization=self.org)
            self.assertFalse(form.is_valid(), code)

    def test_type_in_use_not_deleted(self):
        t = AssetType.objects.create(name='Kiosk', slug='kiosk')
        Asset.objects.create(organization=self.org, name='k1', asset_type='kiosk')
        _client(self.admin).post(f'/assets/types/{t.pk}/delete/')
        self.assertTrue(AssetType.objects.filter(pk=t.pk).exists())

    def test_api_accepts_custom_type_and_fields(self):
        AssetType.objects.create(name='Kiosk', slug='kiosk')
        Membership.objects.create(user=self.admin, organization=self.org, role='owner')
        key, raw = APIKey.create_key(user=self.admin, organization=self.org, name='t', role='admin')
        c = Client()
        r = c.post('/api/assets/', {'name': 'k2', 'asset_type': 'kiosk', 'organization': self.org.pk,
                                    'custom_fields': {'budget_code': 'A1'}},
                   content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {raw}')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['asset_type_display'], 'Kiosk')
        self.assertEqual(Asset.objects.get(name='k2').custom_fields, {'budget_code': 'A1'})
        r = c.post('/api/assets/', {'name': 'k3', 'asset_type': 'nope', 'organization': self.org.pk},
                   content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {raw}')
        self.assertEqual(r.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CatalogEditTests(TestCase):
    def test_customer_admin_cannot_change_catalog(self):
        org = Organization.objects.create(name='CC', slug='cc')
        user = User.objects.create_user('ccadmin', password='pw')
        Membership.objects.create(user=user, organization=org, role='admin')
        vendor = Vendor.objects.create(name='Acme', slug='acme')
        c = _client(user, org)
        self.assertEqual(c.get('/assets/vendors/').status_code, 200)
        self.assertNotContains(c.get('/assets/vendors/'), '/assets/vendors/create/')
        self.assertEqual(c.post('/assets/vendors/create/', {'name': 'Evil'}).status_code, 403)
        self.assertEqual(c.post(f'/assets/vendors/{vendor.pk}/edit/', {'name': 'X'}).status_code, 403)
        self.assertFalse(Vendor.objects.filter(name='Evil').exists())
