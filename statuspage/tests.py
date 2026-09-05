"""
Phase 40.2 (v3.17.540) — status page tests.

The bulk of these are about disclosure. This is the only view in the app that
serves real customer data to an unauthenticated caller, so what it refuses to
say matters as much as what it shows.
"""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import Organization
from monitoring.models import MonitorCheck, WebsiteMonitor
from statuspage.models import StatusPage, StatusPageService

# Same shape as the other app suites: drop the 2FA gate and Axes so a view
# test exercises the view rather than the login flow.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class StatusPageModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='StatusCo', slug='status-co')
        cls.monitor = WebsiteMonitor.objects.create(
            organization=cls.org, name='PROD mail relay 10.4.0.7',
            url='https://mail.internal.example.com', status='active')

    def test_token_is_generated_and_long(self):
        page = StatusPage.objects.create(title='Status')
        self.assertTrue(page.token)
        self.assertGreaterEqual(len(page.token), 40)

    def test_tokens_are_unique_across_pages(self):
        a = StatusPage.objects.create(title='A')
        b = StatusPage.objects.create(title='B')
        self.assertNotEqual(a.token, b.token)

    def test_rotate_changes_the_token(self):
        page = StatusPage.objects.create(title='Status')
        before = page.token
        page.rotate_token()
        self.assertNotEqual(before, page.token)

    def test_refresh_has_a_floor(self):
        """A page reloading every second would hammer the server for no human
        benefit."""
        page = StatusPage.objects.create(title='Status', refresh_seconds=1)
        self.assertEqual(page.refresh_seconds, 30)

    def test_default_title(self):
        self.assertEqual(StatusPage.objects.create().display_title, 'Service status')

    def test_status_translation(self):
        page = StatusPage.objects.create()
        svc = StatusPageService.objects.create(
            page=page, monitor=self.monitor, display_name='Webmail')
        for monitor_status, expected in [
            ('active', 'operational'),
            ('warning', 'degraded'),
            ('down', 'outage'),
            ('unknown', 'unknown'),
        ]:
            self.monitor.status = monitor_status
            self.monitor.save(update_fields=['status'])
            svc.refresh_from_db()
            self.assertEqual(svc.current_status(), expected, monitor_status)

    def test_worst_status_wins_overall(self):
        """A client whose mail is down does not care that the website is up."""
        page = StatusPage.objects.create()
        up = WebsiteMonitor.objects.create(
            organization=self.org, name='Site', url='https://a.example.com',
            status='active')
        StatusPageService.objects.create(page=page, monitor=up, display_name='Website')
        StatusPageService.objects.create(page=page, monitor=self.monitor, display_name='Mail')

        self.monitor.status = 'warning'
        self.monitor.save(update_fields=['status'])
        self.assertEqual(page.overall_status(), 'degraded')

        self.monitor.status = 'down'
        self.monitor.save(update_fields=['status'])
        self.assertEqual(page.overall_status(), 'outage')

    def test_page_with_no_services_is_unknown_not_operational(self):
        """An empty page must not claim everything is fine."""
        self.assertEqual(StatusPage.objects.create().overall_status(), 'unknown')

    def test_hidden_services_are_excluded_everywhere(self):
        page = StatusPage.objects.create()
        self.monitor.status = 'down'
        self.monitor.save(update_fields=['status'])
        StatusPageService.objects.create(
            page=page, monitor=self.monitor, display_name='Mail', is_visible=False)
        self.assertEqual(page.visible_services(), [])
        self.assertEqual(page.overall_status(), 'unknown')

    def test_uptime_windows_shape(self):
        page = StatusPage.objects.create()
        svc = StatusPageService.objects.create(
            page=page, monitor=self.monitor, display_name='Mail')
        MonitorCheck.objects.create(
            monitor=self.monitor, checked_at=timezone.now(), status='active')
        windows = svc.uptime_windows()
        self.assertEqual([w['days'] for w in windows], [30, 90, 365])
        self.assertEqual(windows[0]['percent'], 100.0)

    def test_same_monitor_twice_on_one_page_is_refused(self):
        from django.db import IntegrityError, transaction
        page = StatusPage.objects.create()
        StatusPageService.objects.create(
            page=page, monitor=self.monitor, display_name='Mail')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StatusPageService.objects.create(
                    page=page, monitor=self.monitor, display_name='Mail again')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StatusPagePublicViewTests(TestCase):
    """The unauthenticated view."""

    def setUp(self):
        self.org = Organization.objects.create(name='PubCo', slug='pub-co')
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org,
            name='PROD mail relay 10.4.0.7',
            url='https://mail.internal.example.com',
            status='active')
        self.page = StatusPage.objects.create(title='PubCo status', is_enabled=True)
        StatusPageService.objects.create(
            page=self.page, monitor=self.monitor,
            display_name='Webmail', description='Mail and calendar')
        self.client = Client()

    def test_enabled_page_is_readable_without_logging_in(self):
        resp = self.client.get(self.page.get_public_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Webmail')

    def test_disabled_page_404s(self):
        self.page.is_enabled = False
        self.page.save(update_fields=['is_enabled'])
        self.assertEqual(self.client.get(self.page.get_public_url()).status_code, 404)

    def test_unknown_token_404s(self):
        resp = self.client.get('/status/p/not-a-real-token/')
        self.assertEqual(resp.status_code, 404)

    def test_never_discloses_the_monitor_name_or_url(self):
        """The whole reason display_name exists. "PROD mail relay 10.4.0.7"
        tells a stranger more about the estate than the client needs."""
        body = self.client.get(self.page.get_public_url()).content.decode()
        self.assertNotIn('PROD mail relay', body)
        self.assertNotIn('10.4.0.7', body)
        self.assertNotIn('mail.internal.example.com', body)

    def test_not_cacheable_and_not_indexable(self):
        resp = self.client.get(self.page.get_public_url())
        self.assertIn('no-store', resp['Cache-Control'])
        self.assertIn('noindex', resp['X-Robots-Tag'])

    def test_window_without_checks_says_no_data_not_a_percentage(self):
        body = self.client.get(self.page.get_public_url()).content.decode()
        self.assertIn('no data', body)
        self.assertNotIn('100.0%', body)

    def test_uptime_hidden_when_switched_off(self):
        MonitorCheck.objects.create(
            monitor=self.monitor, checked_at=timezone.now(), status='active')
        self.page.show_uptime = False
        self.page.save(update_fields=['show_uptime'])
        body = self.client.get(self.page.get_public_url()).content.decode()
        self.assertNotIn('no data', body)

    def test_outage_is_announced_in_the_banner(self):
        self.monitor.status = 'down'
        self.monitor.save(update_fields=['status'])
        self.assertContains(
            self.client.get(self.page.get_public_url()), 'Service outage')

    def test_rotating_the_token_kills_the_old_link(self):
        old = self.page.get_public_url()
        self.page.rotate_token()
        self.assertEqual(self.client.get(old).status_code, 404)
        self.assertEqual(self.client.get(self.page.get_public_url()).status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StatusPageManagementTests(TestCase):
    """The authenticated side."""

    def setUp(self):
        self.org = Organization.objects.create(name='MgmtCo', slug='mgmt-co')
        self.other_org = Organization.objects.create(name='OtherCo', slug='other-co')
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Mail', url='https://a.example.com')
        self.other_monitor = WebsiteMonitor.objects.create(
            organization=self.other_org, name='TheirMail', url='https://b.example.com')
        self.admin = User.objects.create_superuser(
            'spadmin', 'sp@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.admin)

    def test_anonymous_cannot_reach_management(self):
        anon = Client()
        resp = anon.get('/status/')
        self.assertIn(resp.status_code, (302, 403))

    def test_create_page_starts_disabled(self):
        resp = self.client.post('/status/new/', {'title': 'Ours'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        page = StatusPage.objects.get(title='Ours')
        self.assertFalse(page.is_enabled)

    def test_add_service_requires_a_public_name(self):
        page = StatusPage.objects.create(title='P')
        self.client.post(f'/status/{page.pk}/', {
            'action': 'add_service',
            'monitor': self.monitor.pk,
            'display_name': '   ',
        })
        self.assertEqual(page.services.count(), 0)

    def test_client_page_cannot_publish_another_clients_service(self):
        page = StatusPage.objects.create(title='MgmtCo', organization=self.org)
        self.client.post(f'/status/{page.pk}/', {
            'action': 'add_service',
            'monitor': self.other_monitor.pk,
            'display_name': 'Sneaky',
        })
        self.assertEqual(page.services.count(), 0)

    def test_add_and_remove_service(self):
        page = StatusPage.objects.create(title='P')
        self.client.post(f'/status/{page.pk}/', {
            'action': 'add_service',
            'monitor': self.monitor.pk,
            'display_name': 'Webmail',
        })
        self.assertEqual(page.services.count(), 1)
        svc = page.services.first()
        self.client.post(f'/status/{page.pk}/', {
            'action': 'remove_service', 'service_id': svc.pk,
        })
        self.assertEqual(page.services.count(), 0)

    def test_rotate_via_the_view(self):
        page = StatusPage.objects.create(title='P')
        before = page.token
        self.client.post(f'/status/{page.pk}/', {'action': 'rotate'})
        page.refresh_from_db()
        self.assertNotEqual(before, page.token)

    def test_available_monitors_scoped_to_the_pages_client(self):
        page = StatusPage.objects.create(title='P', organization=self.org)
        resp = self.client.get(f'/status/{page.pk}/')
        available = list(resp.context['available_monitors'])
        self.assertIn(self.monitor, available)
        self.assertNotIn(self.other_monitor, available)

    def test_enabling_and_disabling(self):
        page = StatusPage.objects.create(title='P')
        self.client.post(f'/status/{page.pk}/', {'is_enabled': 'on', 'title': 'P'})
        page.refresh_from_db()
        self.assertTrue(page.is_enabled)
        self.client.post(f'/status/{page.pk}/', {'title': 'P'})
        page.refresh_from_db()
        self.assertFalse(page.is_enabled)

    def test_delete_page(self):
        page = StatusPage.objects.create(title='P')
        self.client.post(f'/status/{page.pk}/', {'action': 'delete'})
        self.assertFalse(StatusPage.objects.filter(pk=page.pk).exists())
