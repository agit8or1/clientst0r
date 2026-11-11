"""`files_upload` / `files_delete` on /files/upload/ and /files/delete/,
vehicle photos following `files_view`, the mobile photo upload, and the
accounts 0044 upgrade migration."""
import importlib
import shutil
import tempfile

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate, UserType
from accounts.tests_section_flags import ALL_ON, TEST_MIDDLEWARE
from assets.models import Asset
from audit.models import AuditLog
from core.models import Organization
from files.models import Attachment

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix='gapacc-files-')


def _role(org, name, **flags):
    return RoleTemplate.objects.create(name=name, organization=org, **dict(ALL_ON, **flags))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class FileUploadDeletePermissionTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='FP-A', slug='fp-a')
        cls.b = Organization.objects.create(name='FP-B', slug='fp-b')
        cls.asset_a = Asset.objects.create(organization=cls.a, name='A-PC', asset_type='server')
        cls.asset_b = Asset.objects.create(organization=cls.b, name='B-PC', asset_type='server')
        cls.full_a = _role(cls.a, 'FP full A', files_upload=True, files_delete=True)
        cls.view_only_a = _role(cls.a, 'FP view A', files_upload=False, files_delete=False)
        cls.full_b = _role(cls.b, 'FP full B', files_upload=True, files_delete=True)

    def _user(self, name, **memberships):
        user = User.objects.create_user(name, f'{name}@x.test', 'pw')
        for org, role in memberships.values():
            Membership.objects.create(user=user, organization=org, role=Role.EDITOR, role_template=role)
        return user

    def _login(self, user, org):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = org.pk
        s.save()

    def _upload(self, entity_id, entity_type='asset'):
        return self.client.post('/files/upload/', {
            'file': SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain'),
            'entity_type': entity_type, 'entity_id': str(entity_id),
        })

    def _attachment(self, org, entity):
        return Attachment.objects.create(
            organization=org, entity_type='asset', entity_id=entity.pk,
            file=SimpleUploadedFile('x.txt', b'x'), original_filename='x.txt',
            file_size=1, content_type='text/plain')

    # --- upload ---------------------------------------------------------

    def test_upload_needs_files_upload(self):
        self._login(self._user('fp_view', m=(self.a, self.view_only_a)), self.a)
        r = self._upload(self.asset_a.pk)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Attachment.objects.exists())

    def test_upload_with_flag_works(self):
        self._login(self._user('fp_full', m=(self.a, self.full_a)), self.a)
        r = self._upload(self.asset_a.pk)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Attachment.objects.get().organization, self.a)

    def test_upload_flag_in_a_does_not_reach_b(self):
        user = self._user('fp_ab', m=(self.a, self.full_a), n=(self.b, _role(self.b, 'FP view B')))
        self._login(user, self.b)
        self.assertEqual(self._upload(self.asset_b.pk).status_code, 403)

    def test_upload_to_another_customers_entity_is_404(self):
        self._login(self._user('fp_cross', m=(self.a, self.full_a)), self.a)
        self.assertEqual(self._upload(self.asset_b.pk).status_code, 404)
        self.assertFalse(Attachment.objects.exists())

    def test_staff_without_global_role_can_upload(self):
        user = User.objects.create_user('fp_staff', 's@x.test', 'pw')
        user.profile.user_type = UserType.STAFF
        user.profile.save()
        self._login(user, self.a)
        self.assertEqual(self._upload(self.asset_a.pk).status_code, 201)

    def test_staff_global_role_without_upload_is_forbidden(self):
        user = User.objects.create_user('fp_staff2', 's2@x.test', 'pw')
        user.profile.user_type = UserType.STAFF
        user.profile.global_role_template = _role(None, 'FP global no upload', files_upload=False)
        user.profile.save()
        self._login(user, self.a)
        self.assertEqual(self._upload(self.asset_a.pk).status_code, 403)

    # --- delete ---------------------------------------------------------

    def test_delete_needs_files_delete(self):
        att = self._attachment(self.a, self.asset_a)
        self._login(self._user('fp_del_no', m=(self.a, self.view_only_a)), self.a)
        self.assertEqual(self.client.post(f'/files/delete/{att.pk}/').status_code, 403)
        self.assertTrue(Attachment.objects.filter(pk=att.pk).exists())

    def test_delete_with_flag_works_and_is_audited(self):
        att = self._attachment(self.a, self.asset_a)
        self._login(self._user('fp_del', m=(self.a, self.full_a)), self.a)
        self.assertEqual(self.client.post(f'/files/delete/{att.pk}/').status_code, 200)
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        self.assertTrue(AuditLog.objects.filter(object_type='files.Attachment', object_id=att.pk,
                                                action='delete').exists())

    def test_delete_another_customers_attachment_is_404(self):
        att = self._attachment(self.b, self.asset_b)
        self._login(self._user('fp_del_x', m=(self.a, self.full_a)), self.a)
        self.assertEqual(self.client.post(f'/files/delete/{att.pk}/').status_code, 404)
        self.assertTrue(Attachment.objects.filter(pk=att.pk).exists())

    # --- page controls --------------------------------------------------

    def test_asset_page_hides_controls_without_flags(self):
        self._login(self._user('fp_page', m=(self.a, self.view_only_a)), self.a)
        r = self.client.get(reverse('assets:asset_detail', args=[self.asset_a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['can_upload_files'])
        self.assertFalse(r.context['can_delete_files'])
        self.assertNotContains(r, 'data-bs-target="#uploadImageModal"')

    def test_asset_page_delete_uses_the_real_endpoint(self):
        self._login(self._user('fp_page2', m=(self.a, self.full_a)), self.a)
        r = self.client.get(reverse('assets:asset_detail', args=[self.asset_a.pk]))
        self.assertTrue(r.context['can_upload_files'])
        self.assertContains(r, '/files/delete/${imageId}/')
        self.assertNotContains(r, '/files/attachments/')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class VehiclePhotoVisibilityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from vehicles.models import ServiceVehicle
        cls.a = Organization.objects.create(name='VP-A', slug='vp-a')
        cls.b = Organization.objects.create(name='VP-B', slug='vp-b')
        cls.vehicle = ServiceVehicle.objects.create(name='Van', vehicle_type='van', make='Ford',
                                                    model='Transit', year=2022, license_plate='VP1')
        cls.photo_a = Attachment.objects.create(
            organization=cls.a, entity_type='vehicle', entity_id=cls.vehicle.pk,
            file=SimpleUploadedFile('a.png', b'x'), original_filename='a.png', file_size=1,
            content_type='image/png')
        cls.photo_b = Attachment.objects.create(
            organization=cls.b, entity_type='vehicle', entity_id=cls.vehicle.pk,
            file=SimpleUploadedFile('b.png', b'x'), original_filename='b.png', file_size=1,
            content_type='image/png')

    def _staff(self, name, global_role=None):
        user = User.objects.create_user(name, f'{name}@x.test', 'pw')
        user.profile.user_type = UserType.STAFF
        user.profile.global_role_template = global_role
        user.profile.save()
        return user

    def _photos(self, user, org):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = org.pk
        s.save()
        r = self.client.get(reverse('vehicles:vehicle_detail', args=[self.vehicle.pk]))
        self.assertEqual(r.status_code, 200)
        return r, {p.pk for p in r.context['vehicle_photos']}

    def test_staff_with_files_view_sees_all_photos(self):
        _r, seen = self._photos(self._staff('vp_tech'), self.a)
        self.assertEqual(seen, {self.photo_a.pk, self.photo_b.pk})

    def test_global_role_without_files_view_sees_none(self):
        role = _role(None, 'VP no files', files_view=False, files_upload=False, files_delete=False)
        r, seen = self._photos(self._staff('vp_nofiles', role), self.a)
        self.assertEqual(seen, set())
        self.assertFalse(r.context['can_upload_files'])

    def test_membership_scoped_files_view_only_shows_that_customers_photos(self):
        # Customer-side user holding files_view in A only.
        user = User.objects.create_user('vp_cust', 'c@x.test', 'pw')
        Membership.objects.create(user=user, organization=self.a, role=Role.EDITOR,
                                  role_template=_role(self.a, 'VP A files'))
        Membership.objects.create(user=user, organization=self.b, role=Role.EDITOR,
                                  role_template=_role(self.b, 'VP B nofiles', files_view=False))
        from vehicles.views import _photos_user_may_see
        seen = set(_photos_user_may_see(user, Attachment.objects.filter(entity_type='vehicle'))
                   .values_list('pk', flat=True))
        self.assertEqual(seen, {self.photo_a.pk})


class MobilePhotoUploadPermissionTests(TestCase):

    def test_mobile_photo_needs_files_upload(self):
        from api_mobile.views_vehicles import _save_attachment
        org = Organization.objects.create(name='MP', slug='mp')
        user = User.objects.create_user('mp_user', 'm@x.test', 'pw')
        m = Membership.objects.create(user=user, organization=org, role=Role.EDITOR,
                                      role_template=_role(org, 'MP no upload', files_upload=False))
        with override_settings(MEDIA_ROOT=MEDIA):
            self.assertIsNone(_save_attachment(user, SimpleUploadedFile('p.jpg', b'x'),
                                               entity_type='fuel_log', entity_id=1))
            m.role_template = _role(org, 'MP upload', files_upload=True)
            m.save()
            att = _save_attachment(user, SimpleUploadedFile('p.jpg', b'x'),
                                   entity_type='fuel_log', entity_id=1)
        self.assertEqual(att.organization, org)


class KeepFileAccessMigrationTests(TestCase):

    def test_roles_with_files_view_keep_upload_and_delete(self):
        org = Organization.objects.create(name='MG', slug='mg')
        had_view = RoleTemplate.objects.create(name='MG view', organization=org, files_view=True,
                                               files_upload=False, files_delete=False)
        no_view = RoleTemplate.objects.create(name='MG none', organization=org, files_view=False,
                                              files_upload=False, files_delete=False)
        mod = importlib.import_module('accounts.migrations.0044_keep_file_upload_delete_access')
        mod.enable_flags(django_apps, None)
        had_view.refresh_from_db()
        no_view.refresh_from_db()
        self.assertTrue(had_view.files_upload and had_view.files_delete)
        self.assertFalse(no_view.files_upload or no_view.files_delete)
