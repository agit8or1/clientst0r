"""
Mobile API — per-customer enforcement of the `vault_view`, `docs_view` and
`assets_view` role flags.

Membership in a customer used to be enough to read every password, document,
asset and contact in it through /api/mobile/v1/. These tests pin down that the
role flags are now honoured per customer, on top of the existing membership
scoping.
"""
from __future__ import annotations

import json

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from api_mobile.models import MobileAuthToken

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
NO_THROTTLE_REST = dict(django_settings.REST_FRAMEWORK, DEFAULT_THROTTLE_CLASSES=[])

BASE = '/api/mobile/v1'


def _template(org, name, **flags):
    return RoleTemplate.objects.create(
        name=name, organization=org, is_system_template=False, **flags,
    )


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileViewPermissionTests(TestCase):
    """Customer A grants vault/docs/assets view; customer B denies all three."""

    @classmethod
    def setUpTestData(cls):
        from assets.models import Asset, Contact
        from docs.models import Document
        from vault.models import Password

        cls.org_a = Organization.objects.create(name='Perm-A', slug='perm-a')
        cls.org_b = Organization.objects.create(name='Perm-B', slug='perm-b')

        cls.tpl_allow = _template(
            cls.org_a, 'Allow-A',
            vault_view=True, vault_create=True,
            docs_view=True, assets_view=True, assets_create=True, assets_edit=True,
        )
        cls.tpl_deny = _template(
            cls.org_b, 'Deny-B',
            vault_view=False, vault_create=True,
            docs_view=False, assets_view=False, assets_create=True,
        )

        cls.user = User.objects.create_user('permtech', password='pw')
        Membership.objects.create(user=cls.user, organization=cls.org_a,
                                  role=Role.EDITOR, role_template=cls.tpl_allow,
                                  is_active=True)
        Membership.objects.create(user=cls.user, organization=cls.org_b,
                                  role=Role.EDITOR, role_template=cls.tpl_deny,
                                  is_active=True)

        # Only customer B, where every view flag is off.
        cls.blind = User.objects.create_user('permblind', password='pw')
        Membership.objects.create(user=cls.blind, organization=cls.org_b,
                                  role=Role.EDITOR, role_template=cls.tpl_deny,
                                  is_active=True)

        # Superuser whose memberships carry the deny template: the role flags
        # never narrow a superuser.
        cls.root = User.objects.create_superuser('permroot', 'r@x.com', 'pw')
        for org in (cls.org_a, cls.org_b):
            Membership.objects.create(user=cls.root, organization=org,
                                      role=Role.EDITOR, role_template=cls.tpl_deny,
                                      is_active=True)

        other = User.objects.create_user('permother', password='pw')

        cls.pw_a = Password.objects.create(
            organization=cls.org_a, title='PW-A', username='a',
            encrypted_password='x')
        cls.pw_b = Password.objects.create(
            organization=cls.org_b, title='PW-B', username='b',
            encrypted_password='x')
        cls.pw_mine = Password.objects.create(
            organization=cls.org_b, title='PW-Mine', is_personal=True,
            personal_owner=cls.user, encrypted_password='x')
        cls.pw_theirs = Password.objects.create(
            organization=cls.org_a, title='PW-Theirs', is_personal=True,
            personal_owner=other, encrypted_password='x')

        cls.asset_a = Asset.objects.create(
            organization=cls.org_a, name='SW-A', asset_type='switch',
            asset_tag='TAG-A')
        cls.asset_b = Asset.objects.create(
            organization=cls.org_b, name='SW-B', asset_type='switch',
            asset_tag='TAG-B')
        Contact.objects.create(organization=cls.org_a, first_name='Ann', last_name='A')
        Contact.objects.create(organization=cls.org_b, first_name='Bob', last_name='B')

        cls.doc_a = Document.objects.create(
            organization=cls.org_a, title='Doc-A', slug='doc-a', body='a',
            content_type='markdown', is_published=True)
        cls.doc_b = Document.objects.create(
            organization=cls.org_b, title='Doc-B', slug='doc-b', body='b',
            content_type='markdown', is_published=True)
        cls.doc_global = Document.objects.create(
            title='Doc-Global', slug='doc-global', body='g',
            content_type='markdown', is_global=True, is_published=True)

    def setUp(self):
        cache.clear()
        self.client = Client()

    # --- helpers -----------------------------------------------------------

    def _get(self, user, path):
        return self.client.get(BASE + path, HTTP_AUTHORIZATION=f'Token {self._token(user)}')

    def _post(self, user, path, payload):
        return self.client.post(BASE + path, data=json.dumps(payload),
                                content_type='application/json',
                                HTTP_AUTHORIZATION=f'Token {self._token(user)}')

    def _token(self, user):
        # One sign-in per user per test, like the old get_or_create.
        cache_ = self.__dict__.setdefault('_mobile_tokens', {})
        if user.pk not in cache_:
            cache_[user.pk] = MobileAuthToken.issue(user)[0]
        return cache_[user.pk]

    def _titles(self, resp, key='title'):
        self.assertEqual(resp.status_code, 200, resp.content)
        return {r[key] for r in resp.json()['results']}

    # --- vault -------------------------------------------------------------

    def test_vault_list_only_customers_with_vault_view(self):
        titles = self._titles(self._get(self.user, '/vault/'))
        self.assertEqual(titles, {'PW-A', 'PW-Mine'})

    def test_vault_search_respects_vault_view(self):
        titles = self._titles(self._get(self.user, '/vault/?search=PW-B'))
        self.assertEqual(titles, set())

    def test_vault_detail_and_reveal_forbidden_customer_404(self):
        self.assertEqual(self._get(self.user, f'/vault/{self.pw_b.pk}/').status_code, 404)
        self.assertEqual(
            self._post(self.user, f'/vault/{self.pw_b.pk}/reveal/', {}).status_code, 404)

    def test_own_personal_entry_stays_visible(self):
        self.assertEqual(self._get(self.user, f'/vault/{self.pw_mine.pk}/').status_code, 200)

    def test_other_users_personal_entry_hidden(self):
        self.assertEqual(self._get(self.user, f'/vault/{self.pw_theirs.pk}/').status_code, 404)

    def test_vault_create_in_forbidden_customer_403(self):
        resp = self._post(self.user, '/vault/', {
            'organization_id': self.org_b.id, 'title': 'new', 'password': 'p'})
        self.assertEqual(resp.status_code, 403)

    def test_blind_user_sees_no_vault_rows(self):
        self.assertEqual(self._titles(self._get(self.blind, '/vault/')), set())

    def test_asset_vault_link_cannot_reach_forbidden_password(self):
        resp = self._post(self.user, f'/assets/{self.asset_a.pk}/vault-links/',
                          {'password_id': self.pw_b.pk})
        self.assertEqual(resp.status_code, 404)

    # --- assets / contacts -------------------------------------------------

    def test_asset_list_only_customers_with_assets_view(self):
        names = self._titles(self._get(self.user, '/assets/'), key='name')
        self.assertEqual(names, {'SW-A'})

    def test_asset_list_filter_to_forbidden_customer_empty(self):
        names = self._titles(
            self._get(self.user, f'/assets/?organization_id={self.org_b.id}'), key='name')
        self.assertEqual(names, set())

    def test_asset_detail_forbidden_customer_404(self):
        self.assertEqual(self._get(self.user, f'/assets/{self.asset_b.pk}/').status_code, 404)
        self.assertEqual(self._get(self.user, f'/assets/{self.asset_a.pk}/').status_code, 200)

    def test_asset_create_in_forbidden_customer_403(self):
        resp = self._post(self.user, '/assets/',
                          {'organization_id': self.org_b.id, 'name': 'nope'})
        self.assertEqual(resp.status_code, 403)
        resp = self._post(self.user, '/assets/',
                          {'organization_id': self.org_a.id, 'name': 'ok'})
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_scan_does_not_resolve_forbidden_asset(self):
        self.assertEqual(self._get(self.user, '/scan/?code=TAG-B').status_code, 404)
        self.assertEqual(self._get(self.user, '/scan/?code=TAG-A').status_code, 200)

    def test_netconfig_devices_respect_assets_view(self):
        resp = self._get(self.user, '/netconfig/devices/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r['name'] for r in resp.json()['results']}, {'SW-A'})
        self.assertEqual(
            self._get(self.user, f'/netconfig/devices/{self.asset_b.pk}/').status_code, 404)

    def test_dashboard_recent_assets_respect_assets_view(self):
        resp = self._get(self.user, '/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({a['name'] for a in resp.json()['recent_assets']}, {'SW-A'})

    def test_org_detail_counts_respect_assets_view(self):
        body_a = self._get(self.user, f'/organizations/{self.org_a.id}/').json()
        self.assertEqual((body_a['asset_count'], body_a['contact_count']), (1, 1))
        body_b = self._get(self.user, f'/organizations/{self.org_b.id}/').json()
        self.assertEqual((body_b['asset_count'], body_b['contact_count']), (0, 0))

    # --- docs / KB ---------------------------------------------------------

    def test_kb_list_only_customers_with_docs_view(self):
        titles = self._titles(self._get(self.user, '/kb/'))
        self.assertEqual(titles, {'Doc-A'})

    def test_customer_user_with_docs_view_gets_no_global_article(self):
        # Global articles are MSP-internal (staff-only on the web), so
        # docs_view in a customer does not reach them.
        self.assertNotIn('Doc-Global', self._titles(self._get(self.user, '/kb/')))
        self.assertEqual(
            self._titles(self._get(self.user, '/kb/?organization_id=global')), set())
        self.assertEqual(
            self._get(self.user, f'/kb/{self.doc_global.pk}/').status_code, 404)

    def test_msp_staff_without_global_role_sees_global_article(self):
        from accounts.models import UserProfile, UserType
        staff = User.objects.create_user('permstaff', password='pw')
        Membership.objects.create(user=staff, organization=self.org_a,
                                  role=Role.EDITOR, role_template=self.tpl_allow,
                                  is_active=True)
        profile, _ = UserProfile.objects.get_or_create(user=staff)
        profile.user_type = UserType.STAFF
        profile.global_role_template = None
        profile.save()
        self.assertIn('Doc-Global', self._titles(self._get(staff, '/kb/')))
        self.assertEqual(
            self._get(staff, f'/kb/{self.doc_global.pk}/').status_code, 200)

    def test_kb_detail_forbidden_customer_404(self):
        self.assertEqual(self._get(self.user, f'/kb/{self.doc_b.pk}/').status_code, 404)
        self.assertEqual(self._get(self.user, f'/kb/{self.doc_a.pk}/').status_code, 200)

    def test_blind_user_sees_no_docs_not_even_global(self):
        self.assertEqual(self._titles(self._get(self.blind, '/kb/')), set())

    # --- superuser + auth payload -----------------------------------------

    def test_superuser_unaffected(self):
        self.assertEqual(self._titles(self._get(self.root, '/vault/')), {'PW-A', 'PW-B'})
        self.assertEqual(self._titles(self._get(self.root, '/assets/'), key='name'),
                         {'SW-A', 'SW-B'})
        self.assertEqual(self._titles(self._get(self.root, '/kb/')),
                         {'Doc-A', 'Doc-B', 'Doc-Global'})
        self.assertEqual(self._get(self.root, f'/vault/{self.pw_b.pk}/').status_code, 200)

    def test_me_reports_view_flags(self):
        perms = self._get(self.user, '/auth/me/').json()['user']['permissions']
        self.assertTrue(perms['vault_view'])
        self.assertTrue(perms['docs_view'])
        self.assertTrue(perms['assets_view'])
        perms = self._get(self.blind, '/auth/me/').json()['user']['permissions']
        self.assertFalse(perms['vault_view'])
        self.assertFalse(perms['docs_view'])
        self.assertFalse(perms['assets_view'])
