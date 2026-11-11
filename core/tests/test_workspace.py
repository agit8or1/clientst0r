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


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DeviceWorkspaceLinkTests(_Fixture):
    """The Device Workspace is reachable from the sidebar (Devices), My Work's
    recent devices, the asset page and the ticket's asset."""

    def setUp(self):
        from assets.models import Asset
        from integrations.models import RMMDevice
        self.asset = Asset.objects.create(organization=self.a, name='WS Alpha PC', asset_type='desktop')
        RMMDevice.objects.filter(pk=self.dev_a.pk).update(linked_asset=self.asset)
        self.dev_a.refresh_from_db()

    def test_opening_a_workspace_records_the_asset_and_my_work_links_back(self):
        _login(self.client, self.tech, self.a)
        ws = reverse('assets:device_workspace', args=[self.asset.pk])
        self.assertEqual(self.client.get(ws).status_code, 200)
        self.assertTrue(RecentDevice.objects.filter(user=self.tech, kind='asset', object_id=self.asset.pk).exists())
        html = self.client.get(reverse('psa:my_work')).content.decode()
        self.assertIn('data-mw-workspace-link', html)
        self.assertIn(reverse('core:open_device', args=['asset', self.asset.pk]) + '?to=workspace', html)

    def test_open_device_to_workspace(self):
        _login(self.client, self.tech, self.a)
        r = self.client.get(reverse('core:open_device', args=['asset', self.asset.pk]), {'to': 'workspace'})
        self.assertEqual(r['Location'], reverse('assets:device_workspace', args=[self.asset.pk]))
        r = self.client.get(reverse('core:open_device', args=['rmm_device', self.dev_a.pk]), {'to': 'workspace'})
        self.assertEqual(r['Location'],
                         reverse('assets:device_workspace', args=[self.asset.pk]) + f'?device={self.dev_a.pk}')
        # An RMM device without an asset has no workspace: its detail page.
        r = self.client.get(reverse('core:open_device', args=['rmm_device', self.dev_b.pk]), {'to': 'workspace'})
        self.assertEqual(r['Location'], reverse('integrations:rmm_device_detail', args=[self.dev_b.pk]))

    def test_customer_users_get_no_workspace_links(self):
        from types import SimpleNamespace
        from core.workspace import recent_devices
        RecentDevice.objects.create(user=self.customer, kind='asset', object_id=self.asset.pk,
                                    organization=self.a, opened_at=timezone.now())
        req = SimpleNamespace(user=self.customer, is_staff_user=False, current_organization=self.a)
        self.assertTrue(all(not d['workspace_url'] for d in recent_devices(req)))
        _login(self.client, self.customer, self.a)
        r = self.client.get(reverse('core:open_device', args=['asset', self.asset.pk]), {'to': 'workspace'})
        self.assertNotIn('/workspace/', r.get('Location', ''))
        self.assertEqual(self.client.get(reverse('assets:device_workspace_home')).status_code, 404)

    def test_sidebar_entry_page_lists_recent_workspaces(self):
        _login(self.client, self.tech, self.a)
        self.client.get(reverse('assets:device_workspace', args=[self.asset.pk]))
        home = reverse('assets:device_workspace_home')
        html = self.client.get(home).content.decode()
        self.assertIn('data-ws-home-recent', html)
        self.assertIn('WS Alpha PC', html)
        self.assertIn(f'href="{home}"', html)  # the sidebar's Devices group links it

    def test_asset_page_and_ticket_asset_open_the_workspace(self):
        from psa.models import Ticket
        _login(self.client, self.tech, self.a)
        html = self.client.get(reverse('assets:asset_detail', args=[self.asset.pk])).content.decode()
        self.assertIn(reverse('assets:device_workspace', args=[self.asset.pk]), html)
        Ticket.objects.filter(pk=self.t_a.pk).update(related_asset=self.asset)
        self.t_a.refresh_from_db()
        html = self.client.get(reverse('psa:ticket_detail', args=[self.t_a.ticket_number])).content.decode()
        self.assertIn(reverse('assets:device_workspace', args=[self.asset.pk])
                      + f'?ticket={self.t_a.ticket_number}', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RemoteSourceTests(_Fixture):
    """psa_ai.workspace_sources: My Work's remote-session launches and the
    remote jobs that join "Needs your review". Customer-scoped, and never a
    claim that a session started."""

    def _launch(self, user, device, success=True, minutes_ago=5):
        from audit.models import AuditLog
        log = AuditLog.log(user=user, action='api_call', organization=device.organization,
                           object_type='psa_ai.RemoteLaunch', object_repr='Remote view',
                           description='Remote view session launched', success=success,
                           extra_data={'launch': 'x', 'mode': 'view', 'device': device.pk})
        AuditLog.objects.filter(pk=log.pk).update(timestamp=timezone.now() - timedelta(minutes=minutes_ago))

    def _remote(self, caps=('remote_view',)):
        from unittest import mock
        return mock.patch('integrations.ticket_rmm.advertised', return_value=set(caps))

    def test_both_sources_are_registered(self):
        from core.workspace import _SOURCES
        self.assertIn('remote_sessions', _SOURCES)
        self.assertIn('jobs', _SOURCES)

    def test_no_remote_panel_until_a_pairing_offers_remote_sessions(self):
        self._launch(self.tech, self.dev_a)
        _login(self.client, self.tech, self.a)
        with self._remote(caps=('rmm_handoff',)):
            r = self.client.get(reverse('psa:my_work'))
        self.assertNotContains(r, 'id="mw-remote"')
        self.assertContains(r, 'Remote sessions appear here once remote access is connected')

    def test_launches_are_listed_as_unconfirmed_and_customer_scoped(self):
        self._launch(self.tech, self.dev_a)
        self._launch(self.tech, self.dev_b)                      # Bravo: not a customer of mine
        self._launch(self.tech, self.dev_a, success=False)       # refused launches are not listed
        self._launch(self.tech2, self.dev_a)                     # another technician's launch
        self._launch(self.tech, self.dev_a, minutes_ago=180)     # too old
        _login(self.client, self.tech, self.a)
        with self._remote():
            html = self.client.get(reverse('psa:my_work')).content.decode()
        panel = html.split('id="mw-remote"', 1)[1].split('class="card mb-3', 1)[0].split('<script', 1)[0]
        self.assertIn('Remote session launches', panel)
        self.assertIn('WS-ALPHA-SRV', panel)
        self.assertNotIn('WS-BRAVO-SRV', panel)
        self.assertEqual(panel.count('session not confirmed'), 1)
        self.assertNotIn('Active remote sessions', panel)
        self.assertNotIn('running', panel.lower().replace('no remote sessions are running', ''))
        self.assertIn('data-mw-remote-note', panel)
        self.assertIn('?to=workspace', panel)

    def test_every_item_says_unconfirmed(self):
        from types import SimpleNamespace
        from psa_ai.workspace_sources import remote_sessions
        self._launch(self.tech, self.dev_a)
        self._launch(self.tech, self.dev_b)
        req = SimpleNamespace(user=self.tech, is_staff_user=True, current_organization=self.a)
        with self._remote():
            data = remote_sessions(req, None)
        self.assertEqual(data['count'], 2)
        for item in data['items']:
            self.assertFalse(item['session_confirmed'])
            self.assertIn('session not confirmed', item['state'])

    def _rem0te_conn(self):
        from integrations.models import RMMConnection
        return RMMConnection.objects.create(organization=self.msp, provider_type='rem0te',
                                            name='WS Rem0te', base_url='https://rem0te.ws.test')

    def test_jobs_feed_the_review_panel_scoped_to_my_customers(self):
        from psa.support_workflows.models import WorkflowRun
        from psa_ai.models import RMMRequest
        conn = self._rem0te_conn()
        for i, t in enumerate((self.t_a, self.t_b)):
            RMMRequest.objects.create(organization=t.organization, ticket=t, connection=conn,
                                      device_external_id='d', device_name=f'WS-PROP-{i}', tenant_id='t',
                                      actor=self.tech, kind=RMMRequest.KIND_FIX, fix_title=f'WS restart spooler {i}',
                                      payload={}, payload_digest='d', idempotency_key=f'ws-prop-{i}',
                                      status='pending')
            WorkflowRun.objects.create(organization=t.organization, ticket=t, workflow_slug='printer',
                                       workflow_name=f'WS printer workflow {i}', actor=self.tech, status='ready')
        WorkflowRun.objects.create(organization=self.a, ticket=self.t_a, workflow_slug='printer',
                                   workflow_name='WS finished workflow', actor=self.tech, status='verified')
        _login(self.client, self.tech, self.a)
        html = self.client.get(reverse('psa:my_work')).content.decode()
        panel = html.split('id="mw-review"', 1)[1]
        self.assertIn('WS restart spooler 0', panel)
        self.assertIn('Waiting for approval in Rem0te', panel)
        self.assertIn('WS printer workflow 0', panel)
        self.assertNotIn('WS restart spooler 1', panel)
        self.assertNotIn('WS printer workflow 1', panel)
        self.assertNotIn('WS finished workflow', panel)

    def test_ai_jobs_only_while_ai_is_on(self):
        from types import SimpleNamespace
        from psa_ai.models import AnalysisJob
        from psa_ai.workspace_sources import jobs
        AnalysisJob.objects.create(
            organization=self.a, ticket=self.t_a, ticket_revision='r', actor=self.tech, kind='analyze',
            connection=self._rem0te_conn(), business_id='b', evidence={}, evidence_digest='e',
            payload_digest='p', idempotency_key='ws-job-1', expires_at=timezone.now() + timedelta(hours=1),
            status='completed')
        req = SimpleNamespace(user=self.tech, is_staff_user=True, current_organization=self.a)
        self.assertFalse(any(i['title'].startswith('AI analysis') for i in jobs(req, {self.a.pk})['items']))
        s = SystemSetting.get_settings()
        s.psa_ai_enabled = True
        s.save()
        items = jobs(req, {self.a.pk})['items']
        self.assertTrue(any(i['title'].startswith('AI analysis') for i in items))
        self.assertFalse(any(i['title'].startswith('AI analysis') for i in jobs(req, {self.b.pk})['items']))
