"""`files_view`, `monitoring_view` and `integrations_view` are enforced.

Until this release the role editor labelled the three flags "not enforced
yet". They now gate /files/, /monitoring/ and /integrations/ through
SectionPermissionMiddleware (same rule as vault_view/docs_view/assets_view),
global search, the dashboards, GraphQL, the mobile API and the navbar.
Migration accounts 0040 switches monitoring_view/integrations_view on for
existing roles so nobody loses access on upgrade.
"""
import importlib
import json
from datetime import timedelta
from unittest import skipUnless

from django.apps import apps as django_apps
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserType
from core.models import Organization

try:
    import graphene_django  # noqa: F401
    HAS_GRAPHENE = True
except ImportError:
    HAS_GRAPHENE = False


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
NO_THROTTLE_REST = dict(django_settings.REST_FRAMEWORK, DEFAULT_THROTTLE_CLASSES=[])

SECTIONS = {
    'files_view': '/files/upload/',
    'monitoring_view': '/monitoring/websites/',
    'integrations_view': '/integrations/',
}

ALL_ON = dict(files_view=True, monitoring_view=True, integrations_view=True,
              assets_view=True, docs_view=True, vault_view=True)


def _role(org, name, **overrides):
    return RoleTemplate.objects.create(name=name, organization=org,
                                       **dict(ALL_ON, **overrides))


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='SF-A', slug='sf-a')
        cls.org_b = Organization.objects.create(name='SF-B', slug='sf-b')
        cls.all_on_a = _role(cls.org_a, 'SF all on A')
        cls.all_on_b = _role(cls.org_b, 'SF all on B')
        cls.no_flag_a = {p: _role(cls.org_a, f'SF no {p} A', **{p: False}) for p in SECTIONS}
        cls.no_flag_b = {p: _role(cls.org_b, f'SF no {p} B', **{p: False}) for p in SECTIONS}

    def _customer(self, name, role_a=None, role_b=None):
        user = get_user_model().objects.create_user(name, f'{name}@x.com', 'pw')
        if role_a is not None:
            Membership.objects.create(user=user, organization=self.org_a,
                                      role=Role.EDITOR, role_template=role_a)
        if role_b is not None:
            Membership.objects.create(user=user, organization=self.org_b,
                                      role=Role.EDITOR, role_template=role_b)
        return user

    def _staff(self, name, global_role=None):
        user = get_user_model().objects.create_user(name, f'{name}@x.com', 'pw')
        user.profile.user_type = UserType.STAFF
        user.profile.global_role_template = global_role
        user.profile.save()
        return user

    def _login(self, user, org=None):
        self.client.force_login(user)
        session = self.client.session
        session['2fa_prompted'] = True
        if org is not None:
            session['current_organization_id'] = org.pk
        session.save()

    def _get(self, user, path, org=None):
        self._login(user, org)
        return self.client.get(path)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SectionGateTests(_Base):

    def test_customer_without_flag_is_forbidden(self):
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                user = self._customer(f'sf_no_{perm}', self.no_flag_a[perm])
                self.assertEqual(self._get(user, path, self.org_a).status_code, 403)

    def test_customer_with_flag_passes_the_gate(self):
        user = self._customer('sf_all', self.all_on_a)
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                # /files/upload/ is POST-only: 405 means the gate let it through.
                self.assertNotEqual(self._get(user, path, self.org_a).status_code, 403)

    def test_flag_in_customer_a_does_not_reach_customer_b(self):
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                user = self._customer(f'sf_ab_{perm}', self.all_on_a, self.no_flag_b[perm])
                self.assertNotEqual(self._get(user, path, self.org_a).status_code, 403)
                self.assertEqual(self._get(user, path, self.org_b).status_code, 403)

    def test_customer_cannot_reach_a_customer_they_do_not_belong_to(self):
        user = self._customer('sf_only_a', self.all_on_a)
        Membership.objects.create(user=user, organization=self.org_b, role=Role.EDITOR,
                                  role_template=self.no_flag_b['monitoring_view'])
        self.assertEqual(self._get(user, '/monitoring/racks/', self.org_b).status_code, 403)

    def test_flag_off_blocks_upload_post(self):
        user = self._customer('sf_upload', self.no_flag_a['files_view'])
        self._login(user, self.org_a)
        r = self.client.post('/files/upload/', {'entity_type': 'asset', 'entity_id': '1'})
        self.assertEqual(r.status_code, 403)

    def test_staff_global_role_without_flag_is_forbidden(self):
        for perm, path in SECTIONS.items():
            with self.subTest(perm=perm):
                role = RoleTemplate.objects.create(name=f'SF global no {perm}',
                                                   **dict(ALL_ON, **{perm: False}))
                staff = self._staff(f'sf_staff_{perm}', role)
                self.assertEqual(self._get(staff, path, self.org_a).status_code, 403)

    def test_staff_without_global_role_passes(self):
        staff = self._staff('sf_staff_plain')
        for path in SECTIONS.values():
            with self.subTest(path=path):
                self.assertNotEqual(self._get(staff, path, self.org_a).status_code, 403)

    def test_distributor_webhook_is_exempt(self):
        user = self._customer('sf_webhook', self.no_flag_a['integrations_view'])
        r = self._get(user, '/integrations/distributors/webhooks/not-a-token/', self.org_a)
        self.assertNotEqual(r.status_code, 403)

    def test_role_form_no_longer_says_not_enforced(self):
        admin = get_user_model().objects.create_superuser('sf_root', 'r@x.com', 'pw')
        # role_create needs an admin membership in the selected customer.
        Membership.objects.create(user=admin, organization=self.org_a, role=Role.OWNER)
        self._login(admin, self.org_a)
        r = self.client.get(reverse('accounts:role_create'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b'not enforced yet', r.content)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NavAndPageTests(_Base):

    def _dashboard(self, user):
        return self._get(user, reverse('core:dashboard'), self.org_a)

    def test_nav_hides_monitoring_and_integrations_without_flags(self):
        role = _role(self.org_a, 'SF nav off', monitoring_view=False, integrations_view=False)
        user = self._customer('sf_nav_off', role)
        r = self._dashboard(user)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse('monitoring:website_monitor_list'))
        self.assertNotContains(r, reverse('monitoring:rack_list'))
        self.assertNotContains(r, 'href="%s"' % reverse('integrations:integration_list'))

    def test_nav_shows_links_with_flags(self):
        admin = get_user_model().objects.create_superuser('sf_nav_root', 'n@x.com', 'pw')
        r = self._dashboard(admin)
        self.assertContains(r, reverse('monitoring:rack_list'))
        self.assertContains(r, 'href="%s"' % reverse('integrations:integration_list'))

    def test_dashboard_monitor_count_follows_monitoring_view(self):
        from monitoring.models import WebsiteMonitor
        WebsiteMonitor.objects.create(organization=self.org_a, name='m', url='https://a.example',
                                      status='down')
        classic = reverse('core:dashboard') + '?layout=classic'
        on = self._customer('sf_dash_on', self.all_on_a)
        self.assertEqual(self._get(on, classic, self.org_a).context['stats']['monitors'], 1)
        off = self._customer('sf_dash_off', self.no_flag_a['monitoring_view'])
        r = self._get(off, classic, self.org_a)
        self.assertEqual(r.context['stats']['monitors'], 0)
        self.assertEqual(r.context['monitors_down'], 0)
        # The new dashboard (Phase 67) leaves the monitor widgets out entirely.
        keys = {p.key for p in self._dashboard(off).context['kpis']}
        keys |= {p.key for p in self._dashboard(off).context['grid']}
        self.assertNotIn('kpi_monitors', keys)
        self.assertNotIn('monitors', keys)
        self.assertIn('kpi_monitors', {p.key for p in self._dashboard(on).context['kpis']})

    def test_asset_images_hidden_without_files_view(self):
        from assets.models import Asset
        from django.core.files.uploadedfile import SimpleUploadedFile
        from files.models import Attachment
        asset = Asset.objects.create(organization=self.org_a, name='sf-asset', asset_type='server')
        Attachment.objects.create(
            organization=self.org_a, entity_type='asset', entity_id=asset.pk,
            file=SimpleUploadedFile('p.png', b'\x89PNG\r\n\x1a\n'), original_filename='p.png',
            file_size=8, content_type='image/png')
        url = reverse('assets:asset_detail', args=[asset.pk])
        on = self._customer('sf_img_on', self.all_on_a)
        self.assertEqual(len(self._get(on, url, self.org_a).context['asset_images']), 1)
        off = self._customer('sf_img_off', self.no_flag_a['files_view'])
        r = self._get(off, url, self.org_a)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['asset_images']), 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SearchTests(_Base):

    def test_psa_companies_follow_integrations_view(self):
        from integrations.models import PSACompany, PSAConnection
        conn = PSAConnection.objects.create(
            organization=self.org_a, provider_type='connectwise', name='SF CW',
            base_url='https://cw.example', encrypted_credentials='dummy', is_active=True)
        PSACompany.objects.create(organization=self.org_a, connection=conn,
                                  external_id='1', name='Wombat Holdings')
        on = self._customer('sf_search_on', self.all_on_a)
        r = self._get(on, reverse('core:search') + '?q=wombat', self.org_a)
        self.assertEqual(r.context['counts'].get('psa_companies'), 1)
        off = self._customer('sf_search_off', self.no_flag_a['integrations_view'])
        r = self._get(off, reverse('core:search') + '?q=wombat', self.org_a)
        self.assertEqual(r.context['counts'].get('psa_companies'), 0)
        self.assertNotContains(r, 'Wombat Holdings')


@skipUnless(HAS_GRAPHENE, 'graphene-django not installed (optional dependency)')
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GraphQLMonitoringTests(_Base):

    def test_monitors_and_expirations_follow_monitoring_view(self):
        from monitoring.models import Expiration, WebsiteMonitor
        soon = timezone.now() + timedelta(days=5)
        for org in (self.org_a, self.org_b):
            WebsiteMonitor.objects.create(organization=org, name=f'mon-{org.slug}',
                                          url='https://x.example')
            Expiration.objects.create(organization=org, name=f'exp-{org.slug}',
                                      expiration_type='domain', expires_at=soon)
        user = self._customer('sf_gql', self.all_on_a, self.no_flag_b['monitoring_view'])
        self._login(user, self.org_a)
        q = ('{ websiteMonitors { name } expirations { name } expiringSoon { name } '
             'dashboardStats { activeMonitors } }')
        data = self.client.post('/api/v2/graphql/', data=json.dumps({'query': q}),
                                content_type='application/json').json()['data']
        self.assertEqual([m['name'] for m in data['websiteMonitors']], ['mon-sf-a'])
        self.assertEqual([e['name'] for e in data['expirations']], ['exp-sf-a'])
        self.assertEqual([e['name'] for e in data['expiringSoon']], ['exp-sf-a'])
        self.assertEqual(data['dashboardStats']['activeMonitors'], 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTests(_Base):

    def setUp(self):
        cache.clear()

    def _mobile(self, user, path):
        from api_mobile.models import MobileAuthToken
        token = MobileAuthToken.issue(user)[0]
        return Client().get('/api/mobile/v1' + path, HTTP_AUTHORIZATION=f'Token {token}')

    def test_dashboard_counts_follow_monitoring_view(self):
        from monitoring.models import Expiration, WebsiteMonitor
        soon = timezone.now() + timedelta(days=5)
        for org in (self.org_a, self.org_b):
            WebsiteMonitor.objects.create(organization=org, name='m', url='https://x.example',
                                          status='down')
            Expiration.objects.create(organization=org, name='e', expiration_type='domain',
                                      expires_at=soon)
        user = self._customer('sf_mob', self.all_on_a, self.no_flag_b['monitoring_view'])
        body = self._mobile(user, '/dashboard/').json()
        self.assertEqual(body['monitors_down'], 1)
        self.assertEqual(body['expiring_soon'], 1)

    def test_me_reports_the_three_flags(self):
        user = self._customer('sf_me', self.no_flag_a['integrations_view'])
        perms = self._mobile(user, '/auth/me/').json()['user']['permissions']
        self.assertTrue(perms['files_view'])
        self.assertTrue(perms['monitoring_view'])
        self.assertFalse(perms['integrations_view'])


class UpgradeKeepsAccessTests(TestCase):
    """Migration 0040 and the built-in templates keep today's access."""

    def test_migration_switches_both_flags_on_for_existing_roles(self):
        org = Organization.objects.create(name='SF-M', slug='sf-m')
        role = RoleTemplate.objects.create(name='SF legacy', organization=org,
                                           monitoring_view=False, integrations_view=False,
                                           files_view=False)
        mod = importlib.import_module('accounts.migrations.0040_keep_monitoring_integrations_access')
        mod.enable_flags(django_apps, None)
        role.refresh_from_db()
        self.assertTrue(role.monitoring_view)
        self.assertTrue(role.integrations_view)
        # files_view has gated downloads since v3.17.600: left alone.
        self.assertFalse(role.files_view)

    def test_builtin_staff_templates_grant_the_flags(self):
        RoleTemplate.get_or_create_system_templates()
        for name in ('Owner', 'Administrator', 'Editor', 'Help Desk', 'IT Manager',
                     'Documentation Writer', 'Read-Only', 'Technician', 'Tech Manager',
                     'Office Manager', 'Full Admin'):
            with self.subTest(name=name):
                t = RoleTemplate.objects.get(name=name, organization=None)
                self.assertTrue(t.monitoring_view)
                self.assertTrue(t.integrations_view)

    def test_simple_role_fallbacks_grant_integrations_view(self):
        user = get_user_model().objects.create_user('sf_simple', 's@x.com', 'pw')
        org = Organization.objects.create(name='SF-S', slug='sf-s')
        for role in (Role.OWNER, Role.ADMIN, Role.EDITOR, Role.READONLY):
            with self.subTest(role=role):
                m = Membership(user=user, organization=org, role=role)
                perms = m.get_permissions()
                self.assertTrue(perms.integrations_view)
                self.assertTrue(perms.monitoring_view)
                self.assertTrue(perms.files_view)
