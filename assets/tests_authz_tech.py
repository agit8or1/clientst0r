"""Roles & permissions program (authz-tech): asset writes check the assets_*
flag in the asset's customer. `require_write` passed any create flag, so the
built-in Editor (assets_delete off) could delete assets and contacts, and a
role holding only files_upload could create assets. The asset JSON detail no
longer falls back to an unscoped lookup for non-staff users."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from assets.models import Asset, Contact
from core.models import Organization

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetFlagTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Asset authz', slug='authz-assets')
        self.asset = Asset.objects.create(organization=self.org, name='srv-1', asset_type='server')
        self.contact = Contact.objects.create(organization=self.org, first_name='Ann', last_name='A')
        self.c = Client()

    def _member(self, role, template=None, select=True):
        u = User.objects.create_user(f'authz-asset-{User.objects.count()}', password='pw')
        Membership.objects.create(user=u, organization=self.org, role=role, role_template=template)
        self.c.force_login(u)
        s = self.c.session
        s['2fa_prompted'] = True
        if select:
            s['current_organization_id'] = self.org.id
        s.save()
        return u

    def test_editor_cannot_delete_asset_or_contact(self):
        self._member(Role.EDITOR)
        self.assertEqual(self.c.post(f'/assets/{self.asset.pk}/delete/').status_code, 403)
        self.assertEqual(self.c.post(f'/assets/contacts/{self.contact.pk}/delete/').status_code, 403)
        self.assertTrue(Asset.objects.filter(pk=self.asset.pk).exists())
        self.assertTrue(Contact.objects.filter(pk=self.contact.pk).exists())

    def test_editor_still_edits(self):
        self._member(Role.EDITOR)
        self.assertEqual(self.c.get(f'/assets/{self.asset.pk}/edit/').status_code, 200)

    def test_files_only_role_cannot_create_asset(self):
        role = RoleTemplate.objects.create(name='authz asset files', files_view=True, files_upload=True,
                                           assets_view=True, assets_create=False)
        self._member(Role.EDITOR, role)
        resp = self.c.post('/assets/create/', {'name': 'sneaky', 'asset_type': 'server'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Asset.objects.filter(name='sneaky').exists())

    def test_profile_generation_needs_post(self):
        self._member(Role.OWNER)
        self.assertEqual(self.c.get(f'/assets/{self.asset.pk}/generate-profile/').status_code, 405)

    def test_no_unscoped_json_lookup_for_customer_users(self):
        self._member(Role.OWNER, select=False)
        Membership.objects.filter(organization=self.org).update(is_active=False)
        resp = self.c.get(f'/assets/api/assets/{self.asset.pk}/')
        self.assertNotEqual(resp.status_code, 200)
