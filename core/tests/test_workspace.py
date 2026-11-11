"""Technician workspace (core/workspace.py): My Work's extra panels and their
customer scoping, opening a device in its customer's context and coming
back, recent devices, saved list views, and the wider global search.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization, RecentClient, RecentDevice, SavedView, SystemSetting
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed,
)


def _login(client, user, org=None):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    s.save()


class _Fixture(TestCase):

    @classmethod
    def setUpTestData(cls):
        from integrations.models import RMMAlert, RMMConnection, RMMDevice
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        _setup_seed()
        _enable_psa_global()
        cls.msp = Organization.objects.create(name='WS MSP', slug='ws-msp')
        cls.a = Organization.objects.create(name='WS Alpha', slug='ws-alpha')
        cls.b = Organization.objects.create(name='WS Bravo', slug='ws-bravo')
        for org in (cls.msp, cls.a, cls.b):
            _enable_psa_for(org)

        cls.tech = _make_msp_tech(User.objects.create_user('ws_tech', 't@msp.test', 'pw-ws-123'))
        cls.tech2 = _make_msp_tech(User.objects.create_user('ws_tech2', 't2@msp.test', 'pw-ws-123'))
        cls.customer = User.objects.create_user('ws_cust', 'c@alpha.test', 'pw-ws-123')
        Membership.objects.create(user=cls.customer, organization=cls.a, role=Role.OWNER, is_active=True)

        status = TicketStatus.objects.get(slug='in-progress')
        common = dict(queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                      ticket_type=TicketType.objects.first(), status=status)
        # The technician works for Alpha (an assigned open ticket), not Bravo.
        cls.t_a = Ticket.objects.create(organization=cls.a, subject='WS alpha printer',
                                        assigned_to=cls.tech, client_can_view=True, **common)
        Ticket.objects.filter(pk=cls.t_a.pk).update(first_response_due_at=None,
                                                    resolution_due_at=timezone.now() + timedelta(minutes=30))
        cls.t_b = Ticket.objects.create(organization=cls.b, subject='WS bravo unassigned breach', **common)
        Ticket.objects.filter(pk=cls.t_b.pk).update(first_response_due_at=None,
                                                    resolution_due_at=timezone.now() - timedelta(hours=1))

        conn = RMMConnection.objects.create(organization=cls.msp, provider_type='ninjaone',
                                            name='WS RMM', base_url='https://rmm.ws.test')
        cls.dev_a = RMMDevice.objects.create(organization=cls.a, connection=conn, external_id='a1',
                                             device_name='WS-ALPHA-SRV', is_online=False)
        cls.dev_b = RMMDevice.objects.create(organization=cls.b, connection=conn, external_id='b1',
                                             device_name='WS-BRAVO-SRV', is_online=False)
        cls.dev_unowned = RMMDevice.objects.create(organization=cls.a, connection=conn, external_id='u1',
                                                   device_name='WS-UNSETTLED', is_online=False,
                                                   ownership_status=RMMDevice.OWNERSHIP_MOVED)
        RMMAlert.objects.create(organization=cls.a, connection=conn, device=cls.dev_a, external_id='al-a',
                                alert_type='WS disk full alpha', message='disk', severity='critical',
                                status='active', triggered_at=timezone.now())
        RMMAlert.objects.create(organization=cls.b, connection=conn, device=cls.dev_b, external_id='al-b',
                                alert_type='WS disk full bravo', message='disk', severity='critical',
                                status='active', triggered_at=timezone.now())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MyWorkScopingTests(_Fixture):

    def test_technician_sees_their_customers_only_by_default(self):
        _login(self.client, self.tech, self.a)
        r = self.client.get(reverse('psa:my_work'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertContains(r, 'id="mw-devices"')
        self.assertIn('WS-ALPHA-SRV', html)
        self.assertIn('WS disk full alpha', html)
        self.assertNotIn('WS-BRAVO-SRV', html)
        self.assertNotIn('WS disk full bravo', html)
        self.assertNotIn('WS-UNSETTLED', html)      # unowned devices never show
        # SLA: mine (alpha, due in 30 min); bravo's unassigned breach is not a customer of mine.
        self.assertContains(r, 'id="mw-sla"')
        self.assertIn('WS alpha printer', html.split('id="mw-sla"', 1)[1].split('id="mw-open"', 1)[0])
        self.assertNotIn('WS bravo unassigned breach', html)

    def test_all_customers_widens_devices_alerts_and_sla(self):
        _login(self.client, self.tech, self.a)
        html = self.client.get(reverse('psa:my_work'), {'scope': 'all'}).content.decode()
        self.assertIn('WS-BRAVO-SRV', html)
        self.assertIn('WS disk full bravo', html)
        self.assertIn('WS bravo unassigned breach', html)
        self.assertNotIn('WS-UNSETTLED', html)

    def test_selected_client_counts_as_working_for_it(self):
        _login(self.client, self.tech2, self.b)   # no tickets anywhere, Bravo selected
        html = self.client.get(reverse('psa:my_work')).content.decode()
        self.assertIn('WS-BRAVO-SRV', html)
        self.assertNotIn('WS-ALPHA-SRV', html)

    def test_customer_user_gets_no_staff_panels(self):
        _login(self.client, self.customer, self.a)
        r = self.client.get(reverse('psa:my_work'), {'scope': 'all'})
        self.assertEqual(r.status_code, 200)
        for panel in ('mw-sla', 'mw-devices', 'mw-alerts', 'mw-review', 'mw-recent-devices', 'mw-setup'):
            self.assertNotContains(r, f'id="{panel}"')
        self.assertNotContains(r, 'WS-ALPHA-SRV')
        self.assertEqual(r.context['panels'], {})

    def test_device_links_open_in_context(self):
        _login(self.client, self.tech, self.a)
        html = self.client.get(reverse('psa:my_work')).content.decode()
        self.assertIn(reverse('core:open_device', args=['rmm_device', self.dev_a.pk]), html)

    def test_ai_panel_only_with_optional_ai_on(self):
        _login(self.client, self.tech, self.a)
        self.assertNotContains(self.client.get(reverse('psa:my_work')), 'id="mw-ai"')
        s = SystemSetting.get_settings()
        s.psa_ai_enabled = True
        s.save()
        self.assertContains(self.client.get(reverse('psa:my_work')), 'id="mw-ai"')

    def test_setup_guidance_without_an_rmm(self):
        from integrations.models import RMMConnection
        RMMConnection.objects.all().delete()
        _login(self.client, self.tech, self.a)
        r = self.client.get(reverse('psa:my_work'))
        self.assertNotContains(r, 'id="mw-devices"')
        self.assertContains(r, 'id="mw-setup"')
        self.assertContains(r, 'Connect an RMM')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OpenDeviceInContextTests(_Fixture):

    def test_opening_another_customers_device_switches_and_offers_the_way_back(self):
        _login(self.client, self.tech, self.a)
        url = reverse('core:open_device', args=['rmm_device', self.dev_b.pk])
        r = self.client.get(url, {'next': reverse('psa:my_work')})
        self.assertRedirects(r, reverse('integrations:rmm_device_detail', args=[self.dev_b.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(self.client.session['current_organization_id'], self.b.pk)
        page = self.client.get(r['Location'])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="workTrail"')
        self.assertContains(page, 'Back to WS Alpha')
        back = self.client.post(reverse('core:context_return'))
        self.assertRedirects(back, reverse('psa:my_work'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)

    def test_same_customer_does_not_switch_or_leave_a_trail(self):
        _login(self.client, self.tech, self.a)
        self.client.get(reverse('core:open_device', args=['rmm_device', self.dev_a.pk]))
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)
        self.assertNotIn('work_context_return', self.client.session)

    def test_customer_cannot_open_another_customers_device(self):
        _login(self.client, self.customer, self.a)
        r = self.client.get(reverse('core:open_device', args=['rmm_device', self.dev_b.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)

    def test_unsettled_device_and_unknown_kind_are_404(self):
        _login(self.client, self.tech, self.a)
        self.assertEqual(self.client.get(
            reverse('core:open_device', args=['rmm_device', self.dev_unowned.pk])).status_code, 404)
        self.assertEqual(self.client.get(
            reverse('core:open_device', args=['nope', self.dev_a.pk])).status_code, 404)

    def test_next_must_be_local(self):
        _login(self.client, self.tech, self.a)
        self.client.get(reverse('core:open_device', args=['rmm_device', self.dev_b.pk]),
                        {'next': 'https://evil.example/'})
        r = self.client.post(reverse('core:context_return'))
        self.assertFalse(r['Location'].startswith('http'))

    def test_context_return_is_post_only(self):
        _login(self.client, self.tech, self.a)
        self.assertEqual(self.client.get(reverse('core:context_return')).status_code, 405)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RecentDeviceTests(_Fixture):

    def test_opening_a_device_records_it_and_my_work_lists_it(self):
        _login(self.client, self.tech, self.a)
        self.assertEqual(self.client.get(
            reverse('integrations:rmm_device_detail', args=[self.dev_a.pk])).status_code, 200)
        self.assertTrue(RecentDevice.objects.filter(user=self.tech, kind='rmm_device',
                                                    object_id=self.dev_a.pk).exists())
        html = self.client.get(reverse('psa:my_work')).content.decode()
        # The recent-devices card is the right column's lower half.
        self.assertIn('WS-ALPHA-SRV', html.split('id="mw-recent-devices"', 1)[1])

    def test_a_404_is_not_recorded(self):
        _login(self.client, self.tech, self.a)
        # Bravo's device under Alpha's context: the detail view answers 404.
        self.assertEqual(self.client.get(
            reverse('integrations:rmm_device_detail', args=[self.dev_b.pk])).status_code, 404)
        self.assertFalse(RecentDevice.objects.filter(user=self.tech, object_id=self.dev_b.pk).exists())

    def test_rows_are_rechecked_against_current_access(self):
        RecentDevice.objects.create(user=self.customer, kind='rmm_device', object_id=self.dev_b.pk,
                                    organization=self.b, opened_at=timezone.now())
        from types import SimpleNamespace
        from core.workspace import recent_devices
        req = SimpleNamespace(user=self.customer, is_staff_user=False, current_organization=self.a)
        self.assertEqual(recent_devices(req), [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SavedViewTests(_Fixture):

    def test_save_apply_default_and_opt_out(self):
        _login(self.client, self.tech, self.a)
        r = self.client.post(reverse('core:saved_view_save'), {
            'list_key': 'tickets', 'name': 'Mine open', 'is_default': '1',
            'query': 'assigned=me&queue=open&evil=1&q=' + 'x' * 300,
        })
        self.assertEqual(r.status_code, 302)
        view = SavedView.objects.get(user=self.tech, list_key='tickets')
        self.assertEqual(view.query, 'queue=open&assigned=me')   # unknown / oversized params dropped
        self.assertTrue(view.is_default)
        # Bare list URL → the default view.
        r = self.client.get(reverse('psa:ticket_list'))
        self.assertRedirects(r, reverse('psa:ticket_list') + '?queue=open&assigned=me',
                             fetch_redirect_response=False)
        # ?view=all skips it; the bar is on the list.
        r = self.client.get(reverse('psa:ticket_list'), {'view': 'all'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="savedViews"')
        self.assertContains(r, 'Mine open')

    def test_views_are_per_user(self):
        SavedView.objects.create(user=self.tech, list_key='tickets', name='Tech one view',
                                 query='assigned=me', is_default=True)
        _login(self.client, self.tech2, self.a)
        r = self.client.get(reverse('psa:ticket_list'))
        self.assertEqual(r.status_code, 200)              # no redirect: not their default
        self.assertNotContains(r, 'Tech one view')
        other = SavedView.objects.get(name='Tech one view')
        self.assertEqual(self.client.post(reverse('core:saved_view_delete', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('core:saved_view_default', args=[other.pk])).status_code, 404)
        self.assertTrue(SavedView.objects.filter(pk=other.pk, is_default=True).exists())

    def test_one_default_per_list(self):
        _login(self.client, self.tech, self.a)
        for name, q in (('One', 'queue=open'), ('Two', 'assigned=me')):
            self.client.post(reverse('core:saved_view_save'),
                             {'list_key': 'tickets', 'name': name, 'query': q, 'is_default': '1'})
        self.assertEqual(list(SavedView.objects.filter(user=self.tech, is_default=True)
                              .values_list('name', flat=True)), ['Two'])

    def test_unknown_list_is_404_and_customers_get_no_ticket_bar(self):
        _login(self.client, self.tech, self.a)
        self.assertEqual(self.client.post(reverse('core:saved_view_save'),
                                          {'list_key': 'nope', 'name': 'x'}).status_code, 404)
        _login(self.client, self.customer, self.a)
        self.assertNotContains(self.client.get(reverse('psa:ticket_list')), 'id="savedViews"')

    def test_rmm_device_filters(self):
        _login(self.client, self.tech, self.a)
        r = self.client.get(reverse('integrations:rmm_devices'), {'status': 'online'})
        self.assertNotContains(r, 'WS-ALPHA-SRV')
        r = self.client.get(reverse('integrations:rmm_devices'), {'status': 'offline', 'q': 'alpha'})
        self.assertContains(r, 'WS-ALPHA-SRV')
        self.assertContains(r, 'id="savedViews"')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DenseListFilterTests(_Fixture):
    """Default filters and the saved-views bar on RMM alerts, routing triage,
    invoices and timesheet approvals."""

    def test_rmm_alert_filters_and_bar(self):
        _login(self.client, self.tech, self.a)
        url = reverse('integrations:rmm_alerts')
        r = self.client.get(url, {'severity': 'critical'})
        self.assertContains(r, 'WS-ALPHA-SRV')
        self.assertContains(r, 'id="savedViews"')
        self.assertContains(r, 'Critical')  # preset
        self.assertNotContains(self.client.get(url, {'severity': 'warning'}), 'WS-ALPHA-SRV')
        self.assertNotContains(self.client.get(url, {'q': 'no-such-device'}), 'WS-ALPHA-SRV')
        self.assertContains(self.client.get(url, {'q': 'no-such-device'}), 'No alerts match these filters')
        # Another customer's id in ?client= is ignored, never a way in.
        r = self.client.get(url, {'client': self.b.pk})
        self.assertNotContains(r, 'WS-BRAVO-SRV')
        self.client.post(reverse('core:saved_view_save'), {
            'list_key': 'rmm_alerts', 'name': 'Crit', 'query': 'severity=critical&status=all'})
        self.assertEqual(SavedView.objects.get(user=self.tech, list_key='rmm_alerts').query,
                         'status=all&severity=critical')

    def test_rmm_alerts_bar_is_staff_only(self):
        _login(self.client, self.customer, self.a)
        self.assertNotContains(self.client.get(reverse('integrations:rmm_alerts')), 'id="savedViews"')

    def test_triage_filters(self):
        from psa.routing.models import STATUS_FALLBACK, STATUS_SUGGESTED, TRIGGER_CREATED, RoutingDecision
        from psa.models import Ticket
        t2 = Ticket.objects.create(organization=self.a, subject='WS triage suggested',
                                   queue=self.t_b.queue, priority=self.t_b.priority,
                                   ticket_type=self.t_b.ticket_type, status=self.t_b.status)
        RoutingDecision.objects.create(ticket=self.t_b, trigger=TRIGGER_CREATED, idempotency_key='ws-1',
                                       status=STATUS_FALLBACK, reason='nobody qualified')
        RoutingDecision.objects.create(ticket=t2, trigger=TRIGGER_CREATED, idempotency_key='ws-2',
                                       status=STATUS_SUGGESTED, reason='suggested')
        _login(self.client, self.tech, self.a)
        url = reverse('ticket_routing:triage')
        r = self.client.get(url)
        self.assertContains(r, self.t_b.ticket_number)
        self.assertContains(r, t2.ticket_number)
        self.assertContains(r, 'id="savedViews"')
        r = self.client.get(url, {'routing': 'suggested'})
        self.assertNotContains(r, self.t_b.ticket_number)
        self.assertContains(r, t2.ticket_number)
        r = self.client.get(url, {'client': self.a.pk})
        self.assertNotContains(r, self.t_b.ticket_number)
        r = self.client.get(url, {'q': 'no-such-ticket'})
        self.assertContains(r, 'No waiting tickets match these filters')

    def test_invoice_filters_and_bar(self):
        from psa.models import Invoice
        day = timezone.localdate()
        Invoice.objects.create(organization=self.a, client_org=self.a, title='WS alpha invoice',
                               invoice_date=day, status='draft')
        Invoice.objects.create(organization=self.a, client_org=self.b, title='WS bravo invoice',
                               invoice_date=day, status='sent')
        _login(self.client, self.tech, self.a)
        url = reverse('psa:invoice_list')
        r = self.client.get(url, {'status': 'draft'})
        self.assertContains(r, 'WS alpha invoice')
        self.assertNotContains(r, 'WS bravo invoice')
        self.assertContains(r, 'id="savedViews"')
        r = self.client.get(url, {'client': self.b.pk})
        self.assertNotContains(r, 'WS alpha invoice')
        self.assertContains(r, 'WS bravo invoice')
        self.assertContains(self.client.get(url, {'q': 'bravo'}), 'WS bravo invoice')
        self.assertNotContains(self.client.get(url, {'q': 'bravo'}), 'WS alpha invoice')

    def test_timesheet_filters(self):
        from psa.models import TimesheetSubmission
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        TimesheetSubmission.objects.create(user=self.tech, period_start=monday,
                                           period_end=monday + timedelta(days=6), status='pending')
        TimesheetSubmission.objects.create(user=self.tech2, period_start=monday - timedelta(days=7),
                                           period_end=monday - timedelta(days=1),
                                           status='rejected', decided_at=timezone.now())
        su = User.objects.create_user('ws_su', 'su@msp.test', 'pw-ws-123', is_superuser=True, is_staff=True)
        _login(self.client, su, self.a)
        url = reverse('psa:timesheet_approval_queue')
        r = self.client.get(url, {'tech': self.tech2.pk})
        self.assertEqual(len(r.context['pending']), 0)
        self.assertEqual([s.user_id for s in r.context['decided']], [self.tech2.pk])
        r = self.client.get(url, {'decision': 'approved'})
        self.assertEqual(list(r.context['decided']), [])
        self.assertContains(r, 'id="savedViews"')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SearchAndContextTests(_Fixture):

    def test_search_finds_tickets_devices_clients_and_pages_for_staff(self):
        _login(self.client, self.tech, self.a)
        r = self.client.get(reverse('core:search'), {'q': 'WS'})
        self.assertContains(r, 'id="search-tickets"')
        self.assertContains(r, 'WS alpha printer')
        self.assertContains(r, 'WS bravo unassigned breach')   # staff: every ticket, as the list
        self.assertContains(r, 'id="search-clients"')
        r = self.client.get(reverse('core:search'), {'q': 'alpha-srv'})
        self.assertContains(r, 'id="search-devices"')
        r = self.client.get(reverse('core:search'), {'q': 'dispatch'})
        self.assertContains(r, 'id="search-pages"')
        self.assertContains(r, reverse('psa:dispatch_board'))

    def test_customer_search_stays_inside_their_tickets(self):
        _login(self.client, self.customer, self.a)
        r = self.client.get(reverse('core:search'), {'q': 'WS'})
        self.assertContains(r, 'WS alpha printer')
        self.assertNotContains(r, 'WS bravo unassigned breach')
        self.assertNotContains(r, 'WS Bravo')
        self.assertNotContains(r, 'id="search-devices"')
        self.assertNotContains(r, 'id="search-clients"')

    def test_new_session_resumes_the_last_client(self):
        RecentClient.objects.create(user=self.tech, organization=self.b, switched_at=timezone.now())
        RecentClient.objects.create(user=self.tech, organization=self.a,
                                    switched_at=timezone.now() - timedelta(days=1))
        _login(self.client, self.tech)
        self.client.get(reverse('psa:my_work'))
        self.assertEqual(self.client.session['current_organization_id'], self.b.pk)

    def test_resume_rechecks_membership(self):
        RecentClient.objects.create(user=self.customer, organization=self.b, switched_at=timezone.now())
        _login(self.client, self.customer)
        self.client.get(reverse('psa:my_work'))
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)
