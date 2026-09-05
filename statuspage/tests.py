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
from statuspage.models import (
    IncidentUpdate, MaintenanceWindow, StatusPage, StatusPageIncident,
    StatusPageService,
)

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


# ---------------------------------------------------------------------------
# Phase 40.3 (v3.17.541) — maintenance windows
# ---------------------------------------------------------------------------

class MaintenanceWindowModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='MaintCo', slug='maint-co')
        cls.page = StatusPage.objects.create(title='Maint')
        cls.monitor = WebsiteMonitor.objects.create(
            organization=cls.org, name='Mail', url='https://a.example.com')
        cls.svc = StatusPageService.objects.create(
            page=cls.page, monitor=cls.monitor, display_name='Webmail')

    def _window(self, start_offset, end_offset, **kw):
        now = timezone.now()
        return MaintenanceWindow.objects.create(
            page=self.page, title='Upgrade',
            starts_at=now + timedelta(hours=start_offset),
            ends_at=now + timedelta(hours=end_offset),
            **kw)

    def test_state_is_derived_from_the_clock(self):
        self.assertEqual(self._window(2, 4).state, 'upcoming')
        self.assertEqual(self._window(-1, 1).state, 'in_progress')
        self.assertEqual(self._window(-4, -2).state, 'completed')

    def test_cancelled_beats_the_clock(self):
        """No amount of looking at the clock tells you a window was called
        off, which is why this one flag is stored."""
        w = self._window(-1, 1, is_cancelled=True)
        self.assertEqual(w.state, 'cancelled')

    def test_no_services_means_everything(self):
        w = self._window(1, 2)
        self.assertTrue(w.affects_everything)
        self.assertIsNone(w.affected_names())

    def test_named_services_are_listed(self):
        w = self._window(1, 2)
        w.services.add(self.svc)
        self.assertFalse(w.affects_everything)
        self.assertEqual(w.affected_names(), ['Webmail'])

    def test_end_must_follow_start(self):
        from django.core.exceptions import ValidationError
        now = timezone.now()
        w = MaintenanceWindow(
            page=self.page, title='Backwards',
            starts_at=now + timedelta(hours=3), ends_at=now)
        with self.assertRaises(ValidationError):
            w.clean()

    def test_windows_cascade_with_the_page(self):
        self._window(1, 2)
        self.page.delete()
        self.assertEqual(MaintenanceWindow.objects.count(), 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MaintenanceOnPublicPageTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='PubMaint', slug='pub-maint')
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Mail', url='https://a.example.com',
            status='active')
        self.page = StatusPage.objects.create(title='Status', is_enabled=True)
        StatusPageService.objects.create(
            page=self.page, monitor=self.monitor, display_name='Webmail')
        self.client = Client()

    def _window(self, title, start_offset, end_offset, **kw):
        now = timezone.now()
        return MaintenanceWindow.objects.create(
            page=self.page, title=title,
            starts_at=now + timedelta(hours=start_offset),
            ends_at=now + timedelta(hours=end_offset), **kw)

    def test_upcoming_window_is_visible_before_it_starts(self):
        """The entire reason to post one in advance."""
        self._window('Mail server upgrade', 48, 50)
        resp = self.client.get(self.page.get_public_url())
        self.assertContains(resp, 'Mail server upgrade')
        self.assertContains(resp, 'Scheduled maintenance')

    def test_in_progress_window_says_so(self):
        self._window('Happening', -1, 1)
        resp = self.client.get(self.page.get_public_url())
        self.assertContains(resp, 'Maintenance in progress')
        self.assertContains(resp, 'happening now')

    def test_cancelled_window_stays_but_is_marked(self):
        """Vanishing would leave anyone who read the notice thinking it is
        still on."""
        self._window('Called off', 5, 6, is_cancelled=True)
        resp = self.client.get(self.page.get_public_url())
        self.assertContains(resp, 'Called off')
        self.assertContains(resp, 'cancelled')

    def test_recent_history_is_capped(self):
        for i in range(8):
            self._window(f'Old {i}', -(i + 2) * 24, -(i + 2) * 24 + 1)
        resp = self.client.get(self.page.get_public_url())
        shown = sum(1 for i in range(8)
                    if f'Old {i}' in resp.content.decode())
        self.assertEqual(shown, 5)

    def test_upcoming_are_ordered_soonest_first(self):
        self._window('Later one', 72, 73)
        self._window('Sooner one', 24, 25)
        body = self.client.get(self.page.get_public_url()).content.decode()
        self.assertLess(body.index('Sooner one'), body.index('Later one'))

    def test_affected_services_named_on_the_page(self):
        w = self._window('Partial', 5, 6)
        w.services.add(self.page.services.first())
        self.assertContains(
            self.client.get(self.page.get_public_url()), 'Affects: Webmail')

    def test_window_affecting_everything_says_so(self):
        self._window('Total', 5, 6)
        self.assertContains(
            self.client.get(self.page.get_public_url()), 'Affects all services')

    def test_windows_of_other_pages_do_not_leak(self):
        other = StatusPage.objects.create(title='Other', is_enabled=True)
        MaintenanceWindow.objects.create(
            page=other, title='Not yours',
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=2))
        self.assertNotContains(
            self.client.get(self.page.get_public_url()), 'Not yours')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MaintenanceManagementTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MgmtMaint', slug='mgmt-maint')
        self.page = StatusPage.objects.create(title='P')
        self.admin = User.objects.create_superuser(
            'maintadmin', 'ma@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.admin)

    def _post(self, **kw):
        now = timezone.now()
        data = {
            'action': 'add_maintenance',
            'title': 'Upgrade',
            'starts_at': (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'ends_at': (now + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
        }
        data.update(kw)
        return self.client.post(f'/status/{self.page.pk}/', data)

    def test_post_a_window(self):
        self._post()
        self.assertEqual(self.page.maintenance_windows.count(), 1)

    def test_title_is_required(self):
        self._post(title='   ')
        self.assertEqual(self.page.maintenance_windows.count(), 0)

    def test_end_before_start_is_refused(self):
        now = timezone.now()
        self._post(
            starts_at=(now + timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
            ends_at=(now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'))
        self.assertEqual(self.page.maintenance_windows.count(), 0)

    def test_missing_times_are_refused(self):
        self._post(starts_at='', ends_at='')
        self.assertEqual(self.page.maintenance_windows.count(), 0)

    def test_stored_times_are_timezone_aware(self):
        """datetime-local posts naive values; storing them unconverted would
        be ambiguous."""
        self._post()
        w = self.page.maintenance_windows.first()
        self.assertIsNotNone(w.starts_at.tzinfo)

    def test_cancel_keeps_the_row(self):
        self._post()
        w = self.page.maintenance_windows.first()
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'cancel_maintenance', 'window_id': w.pk})
        w.refresh_from_db()
        self.assertTrue(w.is_cancelled)
        self.assertEqual(self.page.maintenance_windows.count(), 1)

    def test_delete_removes_the_row(self):
        self._post()
        w = self.page.maintenance_windows.first()
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'delete_maintenance', 'window_id': w.pk})
        self.assertEqual(self.page.maintenance_windows.count(), 0)

    def test_cannot_touch_another_pages_window(self):
        other = StatusPage.objects.create(title='Other')
        w = MaintenanceWindow.objects.create(
            page=other, title='Theirs',
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(hours=1))
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'delete_maintenance', 'window_id': w.pk})
        self.assertTrue(MaintenanceWindow.objects.filter(pk=w.pk).exists())


# ---------------------------------------------------------------------------
# Phase 40.4 (v3.17.542) — incidents
# ---------------------------------------------------------------------------

def _make_ticket(org, subject='Exchange transport stuck, DAG node 2 down again'):
    """A Ticket needs queue / priority / type / status, all PROTECT FKs the
    seed command provides."""
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    return Ticket.objects.create(
        organization=org, subject=subject,
        queue=Queue.objects.first(),
        priority=TicketPriority.objects.first(),
        ticket_type=TicketType.objects.first(),
        status=TicketStatus.objects.filter(slug='new').first(),
    )


class IncidentModelTests(TestCase):
    def setUp(self):
        from psa.tests._base import _setup_seed
        _setup_seed()
        self.org = Organization.objects.create(name='IncCo', slug='inc-co')
        self.page = StatusPage.objects.create(title='Inc')
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Mail', url='https://a.example.com')
        self.svc = StatusPageService.objects.create(
            page=self.page, monitor=self.monitor, display_name='Webmail')

    def _incident(self, **kw):
        kw.setdefault('title', 'Email delivery delays')
        kw.setdefault('started_at', timezone.now() - timedelta(hours=2))
        return StatusPageIncident.objects.create(page=self.page, **kw)

    def test_unresolved_reads_ongoing(self):
        self.assertEqual(self._incident().state, 'ongoing')

    def test_resolved_reads_resolved(self):
        inc = self._incident(resolved_at=timezone.now())
        self.assertEqual(inc.state, 'resolved')
        self.assertTrue(inc.is_resolved)

    def test_ticket_is_optional(self):
        """An incident often needs posting before anyone opens a ticket."""
        self.assertIsNone(self._incident().ticket)

    def test_ticket_can_be_linked_without_its_subject_being_used(self):
        ticket = _make_ticket(self.org)
        inc = self._incident(ticket=ticket)
        self.assertEqual(inc.ticket, ticket)
        self.assertNotEqual(inc.title, ticket.subject)

    def test_deleting_the_ticket_keeps_the_incident(self):
        """SET_NULL: the published record must outlive the ticket."""
        ticket = _make_ticket(self.org)
        inc = self._incident(ticket=ticket)
        ticket.delete()
        inc.refresh_from_db()
        self.assertIsNone(inc.ticket)
        self.assertEqual(inc.title, 'Email delivery delays')

    def test_timeline_is_oldest_first(self):
        inc = self._incident()
        first = IncidentUpdate.objects.create(
            incident=inc, stage='investigating', body='Looking into it')
        second = IncidentUpdate.objects.create(
            incident=inc, stage='resolved', body='Fixed')
        self.assertEqual(list(inc.timeline()), [first, second])

    def test_no_services_means_everything(self):
        inc = self._incident()
        self.assertTrue(inc.affects_everything)
        self.assertIsNone(inc.affected_names())

    def test_updates_cascade_with_the_incident(self):
        inc = self._incident()
        IncidentUpdate.objects.create(incident=inc, body='x')
        inc.delete()
        self.assertEqual(IncidentUpdate.objects.count(), 0)

    def test_ticket_flag_defaults_off(self):
        """A ticket is not publishable until somebody says so."""
        self.assertFalse(_make_ticket(self.org).is_status_page)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class IncidentPublicPageTests(TestCase):
    def setUp(self):
        from psa.tests._base import _setup_seed
        _setup_seed()
        self.org = Organization.objects.create(name='IncPub', slug='inc-pub')
        self.monitor = WebsiteMonitor.objects.create(
            organization=self.org, name='Mail', url='https://a.example.com',
            status='active')
        self.page = StatusPage.objects.create(title='Status', is_enabled=True)
        self.svc = StatusPageService.objects.create(
            page=self.page, monitor=self.monitor, display_name='Webmail')
        self.client = Client()

    def _incident(self, **kw):
        kw.setdefault('title', 'Email delivery delays')
        kw.setdefault('started_at', timezone.now() - timedelta(hours=2))
        return StatusPageIncident.objects.create(page=self.page, **kw)

    def test_ongoing_incident_appears(self):
        self._incident()
        resp = self.client.get(self.page.get_public_url())
        self.assertContains(resp, 'Ongoing incidents')
        self.assertContains(resp, 'Email delivery delays')

    def test_resolved_incident_moves_to_history(self):
        self._incident(resolved_at=timezone.now())
        resp = self.client.get(self.page.get_public_url())
        self.assertContains(resp, 'Past incidents')
        self.assertNotContains(resp, 'Ongoing incidents')

    def test_ticket_subject_is_never_published(self):
        """The reason StatusPageIncident.title exists."""
        ticket = _make_ticket(self.org)
        self._incident(ticket=ticket)
        body = self.client.get(self.page.get_public_url()).content.decode()
        self.assertNotIn('DAG node 2', body)
        self.assertNotIn(ticket.ticket_number, body)

    def test_updates_render_as_a_timeline(self):
        inc = self._incident()
        IncidentUpdate.objects.create(
            incident=inc, stage='identified', body='Upstream provider issue')
        resp = self.client.get(self.page.get_public_url())
        self.assertContains(resp, 'Identified')
        self.assertContains(resp, 'Upstream provider issue')

    def test_root_cause_is_published_when_set(self):
        self._incident(resolved_at=timezone.now(),
                       root_cause='A failed switch in the primary rack.')
        self.assertContains(
            self.client.get(self.page.get_public_url()),
            'A failed switch in the primary rack.')

    def test_unpublished_incident_is_hidden(self):
        self._incident(is_published=False)
        self.assertNotContains(
            self.client.get(self.page.get_public_url()), 'Email delivery delays')

    def test_incidents_of_other_pages_do_not_leak(self):
        other = StatusPage.objects.create(title='Other', is_enabled=True)
        StatusPageIncident.objects.create(
            page=other, title='Not yours', started_at=timezone.now())
        self.assertNotContains(
            self.client.get(self.page.get_public_url()), 'Not yours')

    def test_resolved_history_is_capped(self):
        for i in range(13):
            self._incident(title=f'Old incident {i}',
                           started_at=timezone.now() - timedelta(days=i + 1),
                           resolved_at=timezone.now() - timedelta(days=i))
        body = self.client.get(self.page.get_public_url()).content.decode()
        shown = sum(1 for i in range(13) if f'Old incident {i}' in body)
        self.assertEqual(shown, 10)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class IncidentManagementTests(TestCase):
    def setUp(self):
        from psa.tests._base import _setup_seed
        _setup_seed()
        self.org = Organization.objects.create(name='IncMgmt', slug='inc-mgmt')
        self.other_org = Organization.objects.create(name='IncOther', slug='inc-other')
        self.page = StatusPage.objects.create(title='P')
        self.admin = User.objects.create_superuser(
            'incadmin', 'i@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.admin)

    def test_publish_an_incident(self):
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays'})
        self.assertEqual(self.page.incidents.count(), 1)

    def test_public_title_is_required(self):
        """Defaulting to the ticket subject is the leak this prevents."""
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': '   '})
        self.assertEqual(self.page.incidents.count(), 0)

    def test_started_at_defaults_to_now(self):
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays'})
        self.assertIsNotNone(self.page.incidents.first().started_at)

    def test_first_update_is_posted_with_the_incident(self):
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays',
            'first_update': 'We are investigating.'})
        inc = self.page.incidents.first()
        self.assertEqual(inc.updates.count(), 1)

    def test_client_page_cannot_publish_another_clients_ticket(self):
        page = StatusPage.objects.create(title='Scoped', organization=self.org)
        ticket = _make_ticket(self.other_org)
        self.client.post(f'/status/{page.pk}/', {
            'action': 'add_incident', 'title': 'Sneaky', 'ticket': ticket.pk})
        self.assertEqual(page.incidents.count(), 0)

    def test_posting_a_resolved_update_resolves_the_incident(self):
        """Marking it resolved separately is a step everyone forgets."""
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays'})
        inc = self.page.incidents.first()
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident_update', 'incident_id': inc.pk,
            'stage': 'resolved', 'body': 'All clear.'})
        inc.refresh_from_db()
        self.assertTrue(inc.is_resolved)

    def test_update_needs_a_body(self):
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays'})
        inc = self.page.incidents.first()
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident_update', 'incident_id': inc.pk,
            'stage': 'monitoring', 'body': '  '})
        self.assertEqual(inc.updates.count(), 0)

    def test_bogus_stage_falls_back_rather_than_500s(self):
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays'})
        inc = self.page.incidents.first()
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident_update', 'incident_id': inc.pk,
            'stage': 'nonsense', 'body': 'Something'})
        self.assertEqual(inc.updates.first().stage, 'investigating')

    def test_cannot_update_another_pages_incident(self):
        other = StatusPage.objects.create(title='Other')
        inc = StatusPageIncident.objects.create(
            page=other, title='Theirs', started_at=timezone.now())
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident_update', 'incident_id': inc.pk,
            'stage': 'monitoring', 'body': 'Injected'})
        self.assertEqual(inc.updates.count(), 0)

    def test_resolve_and_delete(self):
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'add_incident', 'title': 'Email delays'})
        inc = self.page.incidents.first()
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'resolve_incident', 'incident_id': inc.pk})
        inc.refresh_from_db()
        self.assertTrue(inc.is_resolved)
        self.client.post(f'/status/{self.page.pk}/', {
            'action': 'delete_incident', 'incident_id': inc.pk})
        self.assertEqual(self.page.incidents.count(), 0)

    def test_only_flagged_tickets_are_offered(self):
        plain = _make_ticket(self.org)
        flagged = _make_ticket(self.org, subject='Publishable')
        flagged.is_status_page = True
        flagged.save(update_fields=['is_status_page'])
        resp = self.client.get(f'/status/{self.page.pk}/')
        offered = list(resp.context['flagged_tickets'])
        self.assertIn(flagged, offered)
        self.assertNotIn(plain, offered)
