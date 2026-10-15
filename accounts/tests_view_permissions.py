"""Role flags vault_view / docs_view / assets_view gate the staff UI.

The flags were stored and editable on every role template but nothing read
them. `accounts.middleware.SectionPermissionMiddleware` now gates /vault/,
/docs/ and /assets/ by URL prefix using `orgs_with_perm`.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.models import Membership, RoleTemplate, UserType
from core.models import Organization


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

SECTIONS = {
    'vault_view': '/vault/',
    'docs_view': '/docs/',
    'assets_view': '/assets/',
}


class MiddlewareRegisteredTests(TestCase):
    def test_registered_right_after_current_org_middleware(self):
        mw = list(django_settings.MIDDLEWARE)
        i = mw.index('core.middleware.CurrentOrganizationMiddleware')
        self.assertEqual(mw[i + 1], 'accounts.middleware.SectionPermissionMiddleware')

    def test_survives_the_test_middleware_filter(self):
        self.assertIn('accounts.middleware.SectionPermissionMiddleware', TEST_MIDDLEWARE)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SectionPermissionMiddlewareTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.org_a = Organization.objects.create(name='Acme', slug='vp-acme')
        cls.org_b = Organization.objects.create(name='Bravo', slug='vp-bravo')

        cls.full_role = {}
        cls.no_flag_role = {}
        for perm in SECTIONS:
            cls.no_flag_role[perm] = RoleTemplate.objects.create(
                name=f'No {perm}', organization=cls.org_a, **{perm: False})
        cls.all_on = RoleTemplate.objects.create(name='All on', organization=cls.org_a)

        cls.superuser = User.objects.create_user(
            'vp_super', 'su@x.com', 'pw', is_superuser=True, is_staff=True)

        # MSP staff, no global role template: every customer (unchanged).
        cls.staff_plain = User.objects.create_user('vp_staff', 's@x.com', 'pw')
        cls.staff_plain.profile.user_type = UserType.STAFF
        cls.staff_plain.profile.save()

    def _customer(self, name, role_a, role_b=None):
        user = get_user_model().objects.create_user(name, f'{name}@x.com', 'pw')
        Membership.objects.create(user=user, organization=self.org_a,
                                  role='admin', role_template=role_a)
        if role_b is not None:
            Membership.objects.create(user=user, organization=self.org_b,
                                      role='admin', role_template=role_b)
        return user

    def _staff_with_global_role(self, name, role):
        user = get_user_model().objects.create_user(name, f'{name}@x.com', 'pw')
        user.profile.user_type = UserType.STAFF
        user.profile.global_role_template = role
        user.profile.save()
        return user

    def _get(self, user, path, org=None):
        self.client.force_login(user)
        if org is not None:
            session = self.client.session
            session['current_organization_id'] = org.pk
            session.save()
        return self.client.get(path)

    # -- customer users -------------------------------------------------------

    def test_customer_without_flag_is_forbidden(self):
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                user = self._customer(f'vp_no_{perm}', self.no_flag_role[perm])
                r = self._get(user, path, self.org_a)
                self.assertEqual(r.status_code, 403)

    def test_customer_without_flag_reaches_other_sections(self):
        user = self._customer('vp_no_vault_only', self.no_flag_role['vault_view'])
        for path in ('/docs/', '/assets/'):
            with self.subTest(path=path):
                self.assertNotEqual(self._get(user, path, self.org_a).status_code, 403)

    def test_personal_vault_is_exempt(self):
        user = self._customer('vp_personal', self.no_flag_role['vault_view'])
        r = self._get(user, '/vault/personal/', self.org_a)
        self.assertEqual(r.status_code, 200)

    def test_vault_utilities_are_exempt(self):
        user = self._customer('vp_utils', self.no_flag_role['vault_view'])
        r = self._get(user, '/vault/api/generate/', self.org_a)
        self.assertNotEqual(r.status_code, 403)

    def test_customer_with_flag_passes(self):
        user = self._customer('vp_all_on', self.all_on)
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertEqual(self._get(user, path, self.org_a).status_code, 200)

    def test_flag_in_customer_a_but_not_b(self):
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                user = self._customer(f'vp_ab_{perm}', self.all_on, self.no_flag_role[perm])
                self.assertNotEqual(self._get(user, path, self.org_a).status_code, 403)
                self.assertEqual(self._get(user, path, self.org_b).status_code, 403)

    def test_simple_role_without_template_passes(self):
        user = get_user_model().objects.create_user('vp_simple', 'si@x.com', 'pw')
        Membership.objects.create(user=user, organization=self.org_a, role='readonly')
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertNotEqual(self._get(user, path, self.org_a).status_code, 403)

    def test_user_with_no_membership_is_left_to_view_scoping(self):
        """No role anywhere: nothing to consult, so no 403 from the gate —
        the views' own scoping (which shows such users nothing org-owned)
        decides, as before."""
        user = get_user_model().objects.create_user('vp_nomember', 'nm@x.com', 'pw')
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertNotEqual(self._get(user, path).status_code, 403)

    def test_inactive_membership_with_flag_off_elsewhere_still_403s(self):
        user = self._customer('vp_mixed', self.no_flag_role['vault_view'])
        Membership.objects.create(user=user, organization=self.org_b,
                                  role='admin', is_active=False)
        self.assertEqual(self._get(user, '/vault/', self.org_a).status_code, 403)

    def test_anonymous_is_not_turned_into_403(self):
        r = self.client.get('/vault/')
        self.assertEqual(r.status_code, 302)  # login redirect, as before

    # -- MSP side ---------------------------------------------------------------

    def test_superuser_passes(self):
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertEqual(self._get(self.superuser, path, self.org_a).status_code, 200)

    def test_staff_without_global_role_passes(self):
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertEqual(
                    self._get(self.staff_plain, path, self.org_b).status_code, 200)

    def test_staff_with_global_role_lacking_flag_is_forbidden(self):
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                role = RoleTemplate.objects.create(name=f'Global no {perm}', **{perm: False})
                user = self._staff_with_global_role(f'vp_gstaff_{perm}', role)
                self.assertEqual(self._get(user, path, self.org_a).status_code, 403)
                # ...and the personal vault stays reachable.
                if perm == 'vault_view':
                    self.assertEqual(
                        self._get(user, '/vault/personal/', self.org_a).status_code, 200)

    def test_staff_with_global_role_holding_flag_passes(self):
        role = RoleTemplate.objects.create(name='Global all on')
        user = self._staff_with_global_role('vp_gstaff_ok', role)
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertEqual(self._get(user, path, self.org_b).status_code, 200)
