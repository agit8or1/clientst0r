"""
Browser-extension endpoints honour the per-customer `vault_view` role flag.

`vault_extension_use` lets the extension talk to the vault; it must not by
itself reveal a customer's passwords to someone whose role there denies
`vault_view`.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from vault.models import Password, WebExtensionAuthToken

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

AUTOFILL = '/vault/api/extension/autofill/?url=https://perm.test/login'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ExtensionVaultViewPermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='ExtPerm-A', slug='extperm-a')
        cls.org_b = Organization.objects.create(name='ExtPerm-B', slug='extperm-b')
        ext = dict(vault_extension_use=True, vault_extension_offline_cache=True,
                   vault_view_password=True)
        cls.tpl_allow = RoleTemplate.objects.create(
            name='ExtAllow', organization=cls.org_a, vault_view=True, **ext)
        cls.tpl_deny = RoleTemplate.objects.create(
            name='ExtDeny', organization=cls.org_b, vault_view=False, **ext)

        cls.user = User.objects.create_user('extperm', 'e@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org_a,
                                  role=Role.EDITOR, role_template=cls.tpl_allow,
                                  is_active=True)
        Membership.objects.create(user=cls.user, organization=cls.org_b,
                                  role=Role.EDITOR, role_template=cls.tpl_deny,
                                  is_active=True)

        cls.pw = {}
        for org in (cls.org_a, cls.org_b):
            cls.pw[org.pk] = Password.objects.create(
                organization=org, title=f'Site {org.slug}',
                url='https://perm.test/login', username=f'u-{org.slug}',
                encrypted_password='dummy',
            )

    def setUp(self):
        self.c = Client()
        self.secret, _ = WebExtensionAuthToken.issue(user=self.user, organization=None)

    def _get(self, path, org, secret=None):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {secret or self.secret}'}
        if org is not None:
            headers['HTTP_X_ORGANIZATION_ID'] = str(org.pk)
        return self.c.get(path, **headers)

    def test_autofill_no_matches_without_vault_view(self):
        r = self._get(AUTOFILL, self.org_b)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['matches'], [])

    def test_autofill_matches_where_vault_view_granted(self):
        r = self._get(AUTOFILL, self.org_a)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([m['id'] for m in r.json()['matches']],
                         [self.pw[self.org_a.pk].pk])

    def test_pinned_token_without_vault_view_sees_nothing(self):
        secret_b, _ = WebExtensionAuthToken.issue(user=self.user, organization=self.org_b)
        r = self._get(AUTOFILL, None, secret=secret_b)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['matches'], [])

    def test_bulk_sync_without_vault_view_empty(self):
        r = self._get('/vault/api/extension/sync/', self.org_b)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['count'], 0)
        r = self._get('/vault/api/extension/sync/', self.org_a)
        self.assertEqual(r.json()['count'], 1)

    def test_reveal_and_totp_without_vault_view_404(self):
        pk = self.pw[self.org_b.pk].pk
        r = self.c.post(f'/vault/api/extension/{pk}/reveal/',
                        HTTP_AUTHORIZATION=f'Bearer {self.secret}',
                        HTTP_X_ORGANIZATION_ID=str(self.org_b.pk))
        self.assertEqual(r.status_code, 404)
        r = self._get(f'/vault/api/extension/{pk}/totp/', self.org_b)
        self.assertEqual(r.status_code, 404)

    def test_superuser_unaffected(self):
        root = User.objects.create_superuser('extroot', 'r@x.com', 'pw')
        secret, _ = WebExtensionAuthToken.issue(user=root, organization=None)
        r = self._get(AUTOFILL, self.org_b, secret=secret)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()['matches']), 1)
        # Global view: every customer.
        r = self._get(AUTOFILL, None, secret=secret)
        self.assertEqual(len(r.json()['matches']), 2)

    def test_staff_global_role_without_vault_view_sees_nothing(self):
        from accounts.models import UserProfile, UserType
        staff = User.objects.create_user('extstaff', 's@x.com', 'pw')
        tpl = RoleTemplate.objects.create(name='StaffNoVault', vault_view=False, **{
            'vault_extension_use': True})
        profile, _ = UserProfile.objects.get_or_create(user=staff)
        profile.user_type = UserType.STAFF
        profile.global_role_template = tpl
        profile.save()
        secret, _ = WebExtensionAuthToken.issue(user=staff, organization=None)
        r = self._get(AUTOFILL, None, secret=secret)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['matches'], [])
