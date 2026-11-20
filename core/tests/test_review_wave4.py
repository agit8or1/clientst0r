"""Security review fixes, fourth wave (v3.17.729): SR-14, SR-15, SR-16,
SR-18, SR-19."""
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import RoleTemplate
from core.models import Organization
from core.tests._r681_fixture import TEST_MIDDLEWARE


def _client(user, org=None):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    else:
        s['global_view_mode'] = True
    s.save()
    return c


def _tech(username, scope=None, staff_flag=False, **flags):
    from accounts.models import UserType
    u = User.objects.create_user(username, f'{username}@msp.test', 'pw', is_staff=staff_flag)
    u.profile.user_type = UserType.STAFF
    u.profile.global_role_template = RoleTemplate.objects.create(name=f'role {username}', **flags)
    if scope is not None:
        u.profile.client_scope = 'selected'
    u.profile.save()
    if scope is not None:
        u.profile.scope_organizations.set(scope)
    return u


class CorsSettingsTests(SimpleTestCase):
    def test_credentialed_cors_is_limited_to_the_api_and_off_in_production(self):
        self.assertEqual(settings.CORS_URLS_REGEX, r'^/api/')
        if not settings.DEBUG:
            self.assertEqual(settings.CORS_ALLOWED_ORIGINS, [])


class LegacyImporterGuardTests(SimpleTestCase):
    def _service(self, url):
        from imports.services.hudu import HuduImportService
        job = SimpleNamespace(target_organization=None, use_fuzzy_matching=False,
                              source_api_key='k', source_url=url)
        return HuduImportService(job)

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_internal_and_metadata_source_urls_refused_before_connect(self):
        import requests
        for url in ('http://169.254.169.254', 'https://127.0.0.1', 'https://10.0.0.5'):
            svc = self._service(url)
            with mock.patch('socket.create_connection') as sock:
                with self.assertRaises(requests.RequestException) as ctx:
                    svc._make_request('GET', '/api/v1/companies')
            self.assertIn('not allowed', str(ctx.exception))
            sock.assert_not_called()

    def test_session_is_guarded(self):
        from core.safe_http import GuardedHTTPAdapter
        svc = self._service('https://hudu.example.com')
        self.assertIsInstance(svc.session.get_adapter('https://hudu.example.com'), GuardedHTTPAdapter)
        self.assertFalse(svc.session.trust_env)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StaffScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Wave4 A', slug='w4-a')
        cls.b = Organization.objects.create(name='Wave4 B', slug='w4-b')

    def test_process_in_global_view_needs_docs_view_at_its_customer(self):
        from processes.models import Process
        Process.objects.create(organization=self.b, title='B only', slug='b-only-w4')
        Process.objects.create(organization=self.a, title='Shared', slug='shared-w4', is_global=True)
        no_docs = _tech('w4-nodocs', staff_flag=True, docs_view=False)
        c = _client(no_docs)
        self.assertEqual(c.get(reverse('processes:process_detail', args=['b-only-w4'])).status_code, 404)
        self.assertEqual(c.get(reverse('processes:process_detail', args=['shared-w4'])).status_code, 200)
        reader = _tech('w4-docs', staff_flag=True, docs_view=True)
        self.assertEqual(_client(reader).get(reverse('processes:process_detail', args=['b-only-w4'])).status_code,
                         200)

    def test_dashboard_widget_needs_manage_rights_at_the_dashboard_customer(self):
        from reports.models import Dashboard, DashboardWidget
        owner = User.objects.create_superuser('w4-owner', 'o@x.test', 'pw')
        dash = Dashboard.objects.create(name='B dash', organization=self.b, created_by=owner)
        scoped = _tech('w4-dash', scope=[self.a], staff_flag=True,
                       reports_view_dashboards=True, reports_manage_dashboards=True)
        c = _client(scoped, org=self.a)
        r = c.post(reverse('reports:dashboard_widget_add', args=[dash.pk]), {'title': 'x', 'data_source': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(DashboardWidget.objects.filter(dashboard=dash).exists())
        everywhere = _tech('w4-dash-all', staff_flag=True, reports_view_dashboards=True,
                           reports_manage_dashboards=True)
        r = _client(everywhere, org=self.b).post(reverse('reports:dashboard_widget_add', args=[dash.pk]),
                                                 {'title': 'x', 'data_source': 'x'})
        self.assertEqual(r.status_code, 302)

    def test_asset_api_without_customer_selected_stays_in_reach(self):
        from assets.models import Asset
        asset = Asset.objects.create(organization=self.b, name='B laptop')
        scoped = _tech('w4-assets', scope=[self.a], assets_view=True)
        c = _client(scoped)
        r = c.get(reverse('assets:asset_api_detail', args=[asset.pk]))
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn(b'B laptop', r.content)

    def test_bulk_upload_logs_no_form_values_or_file_names(self):
        root = User.objects.create_superuser('w4-root', 'r@x.test', 'pw')
        c = _client(root, org=self.a)
        with self.assertLogs('docs.views', 'INFO') as logs:
            c.post(reverse('docs:document_upload'), {
                'note': 'SECRET-FORM-VALUE',
                'files': [SimpleUploadedFile('private-name.txt', b'hello', content_type='text/plain')]})
        out = '\n'.join(logs.output)
        self.assertNotIn('SECRET-FORM-VALUE', out)
        self.assertNotIn('private-name', out)
        self.assertIn('1 file(s)', out)
