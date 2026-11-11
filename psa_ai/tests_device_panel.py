"""
ClientSt0r ↔ RMM Phase 4: the ticket's RMM side panel with several affected
devices, health, history, result notes, remote-launch status and
verify-then-close. Uses the test processor from tests_rmm (this file plays
the RMM).
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset
from audit.models import AuditLog
from integrations.models import RMMAlert, RMMDevice
from psa.affected import add, ticket_assets
from psa.models import TicketAffectedAsset, TicketComment, TicketStatus
from psa.tests._base import TEST_MIDDLEWARE
from tech_access.testing import make_ticket

from .models import RMMRequest
from .services import device_panel, rmm_actions
from .tests_assist import KEY_DIR, sign_in
from .tests_rmm import RMMActionBase


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AI_GATEWAY_KEY_DIR=KEY_DIR,
                   AI_GATEWAY_MODE='in_process', ALLOWED_HOSTS=['*'])
class DevicePanelBase(RMMActionBase):
    def setUp(self):
        super().setUp()
        RMMDevice.objects.filter(pk=self.device.pk).update(is_online=True, last_seen=timezone.now())
        self.device.refresh_from_db()
        # A second workstation of the same customer, managed by the same paired RMM.
        self.asset2 = Asset.objects.create(organization=self.a, name='Reception laptop', hostname='RECEPTION-02',
                                           asset_type='laptop')
        self.device2 = RMMDevice.objects.create(
            organization=self.a, connection=self.conn_a, external_id='c-2', device_name='RECEPTION-02',
            device_type='laptop', client_id='biz-alpha', linked_asset=self.asset2, is_online=True,
            last_seen=timezone.now(), data_refreshed_at=timezone.now())

    def page(self, client=None):
        return (client or self.c).get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()


class MultiDeviceTicketTests(DevicePanelBase):
    def test_affected_devices_become_targets_and_actions_name_the_right_device(self):
        self.assertEqual([t.device.pk for t in rmm_actions.targets(self.ticket)], [self.device.pk])
        r = self.post('affected', {'op': 'add', 'asset': self.asset2.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual([a.pk for a in ticket_assets(self.ticket)], [self.asset.pk, self.asset2.pk])
        self.assertEqual([t.device.pk for t in rmm_actions.targets(self.ticket)], [self.device.pk, self.device2.pk])
        html = self.page()
        self.assertIn(f'data-rmm-target="{self.device2.pk}"', html)
        self.assertIn(f'data-ticket-device="{self.asset2.pk}"', html)
        # A diagnostic on the second device goes out with that device's RMM id.
        self.post('diagnostic', {'device': self.device2.pk, 'diagnostic': 'disk_space',
                                 'idempotency_key': 'multi-device-1'})
        req = self.last('diagnostic')
        self.assertEqual((req.device_id, req.device_external_id), (self.device2.pk, 'c-2'))
        self.assertEqual(self.calls[-1][3]['device']['external_id'], 'c-2')
        self.assertTrue(AuditLog.objects.filter(object_type='psa.Ticket', description__contains='Affected device').exists())
        # Removing it takes the device out of reach again.
        self.post('affected', {'op': 'remove', 'asset': self.asset2.pk})
        self.assertEqual([t.device.pk for t in rmm_actions.targets(self.ticket)], [self.device.pk])
        before = len(self.calls)
        self.post('diagnostic', {'device': self.device2.pk, 'diagnostic': 'disk_space',
                                 'idempotency_key': 'multi-device-2'})
        self.assertEqual(len(self.calls), before)

    def test_another_customers_asset_cannot_be_added(self):
        asset_b = Asset.objects.create(organization=self.b, name='FRONTDESK-01', hostname='FRONTDESK-01',
                                       asset_type='desktop')
        self.post('affected', {'op': 'add', 'asset': asset_b.pk})
        self.assertFalse(TicketAffectedAsset.objects.exists())
        with self.assertRaises(ValueError):
            TicketAffectedAsset.objects.create(ticket=self.ticket, asset=asset_b)
        # A row smuggled in at the database level is still never read.
        TicketAffectedAsset.objects.bulk_create([TicketAffectedAsset(ticket=self.ticket, asset=asset_b,
                                                                     organization=self.a)])
        self.assertEqual([a.pk for a in ticket_assets(self.ticket)], [self.asset.pk])

    def test_duplicate_hostnames_across_customers_stay_apart(self):
        asset_b = Asset.objects.create(organization=self.b, name='Front desk PC', hostname='FRONTDESK-01',
                                       asset_type='desktop')
        dev_b = RMMDevice.objects.create(organization=self.b, connection=self.conn_b, external_id='c-1',
                                         device_name='FRONTDESK-01', device_type='workstation',
                                         client_id='biz-beta', linked_asset=asset_b, is_online=True,
                                         last_seen=timezone.now(), data_refreshed_at=timezone.now())
        ticket_b = make_ticket(self.b, assigned_to=self.tech)
        add(ticket_b, asset_b.pk, self.tech)
        self.assertEqual([t.device.pk for t in rmm_actions.targets(self.ticket)], [self.device.pk])
        before = len(self.calls)
        self.post('diagnostic', {'device': dev_b.pk, 'diagnostic': 'disk_space', 'idempotency_key': 'dup-host-1'})
        self.post('launch', {'device': dev_b.pk, 'mode': 'view'})
        self.assertEqual(len(self.calls), before)
        html = self.page()
        self.assertNotIn(f'data-rmm-target="{dev_b.pk}"', html)
        # The technician has no access at Beta: its ticket's routes don't exist for them.
        self.assertEqual(self.post('affected', {'op': 'add', 'asset': self.asset.pk}, ticket=ticket_b).status_code,
                         302)
        self.assertFalse(TicketAffectedAsset.objects.filter(ticket=ticket_b, asset=self.asset).exists())

    def test_portal_user_cannot_change_devices_or_see_the_panel(self):
        portal = User.objects.create_user('client', password='pw')
        Membership.objects.create(user=portal, organization=self.a, role=Role.OWNER)
        self.ticket.client_can_view = True
        self.ticket.save()
        pc = sign_in(portal, self.a)
        self.assertIn(self.post('affected', {'op': 'add', 'asset': self.asset2.pk}, client=pc).status_code,
                      (403, 404))
        self.assertFalse(TicketAffectedAsset.objects.exists())
        self.assertNotIn('data-ticket-devices', self.page(pc))
        self.assertEqual(pc.get(f'/psa/rmm/{self.ticket.ticket_number}/verify/').status_code, 404)


class HealthAndStateTests(DevicePanelBase):
    def test_offline_agent_disables_remote_and_diagnostics_with_the_reason(self):
        RMMDevice.objects.filter(pk=self.device.pk).update(is_online=False,
                                                           last_seen=timezone.now() - timedelta(hours=5))
        html = self.page()
        self.assertIn('data-rmm-health="offline"', html)
        self.assertIn('The agent is offline', html)
        self.assertIn('disabled data-rmm-action="remote_view"', html)
        before = len(self.calls)
        self.post('diagnostic', {'device': self.device.pk, 'diagnostic': 'disk_space', 'idempotency_key': 'off-1'})
        self.post('launch', {'device': self.device.pk, 'mode': 'view'})
        self.assertEqual(len(self.calls), before)
        self.assertFalse(RMMRequest.objects.exists())

    def test_stale_data_is_labelled_and_never_verifies(self):
        RMMDevice.objects.filter(pk=self.device.pk).update(data_refreshed_at=timezone.now() - timedelta(days=3))
        html = self.page()
        self.assertIn('data-rmm-health="stale"', html)
        v = device_panel.verification(self.ticket)
        self.assertFalse(v['all_ok'])
        self.assertEqual(v['unknown'], 1)

    def test_launch_is_never_shown_as_a_started_session(self):
        r = self.post('launch', {'device': self.device.pk, 'mode': 'view'})
        self.assertEqual(r.status_code, 302)
        html = self.page()
        self.assertIn('data-rmm-launch data-session-confirmed="0"', html)
        self.assertIn('Link issued — session not confirmed', html)
        self.assertNotRegex(html.lower(), r'(?<!whether a )session started')
        self.assertNotIn(self.LAUNCH_URL, html)


class NotesTimeAndCloseTests(DevicePanelBase):
    def _failed_fix(self):
        self.post('fix', {'device': self.device.pk, 'idempotency_key': 'fix-fail-1', 'risk': 'low',
                          'title': 'Restart spooler', 'description': 'Spooler stuck'})
        req = self.last('fix_referral')
        RMMRequest.objects.filter(pk=req.pk).update(status='failed', error='Service did not start (1053).')
        req.refresh_from_db()
        return req

    def test_failed_job_shows_attaches_as_internal_note_and_blocks_verification(self):
        req = self._failed_fix()
        html = self.page()
        self.assertIn(f'data-rmm-attach-note="{req.pk}"', html)
        self.post('note', {'request': str(req.pk)})
        note = TicketComment.objects.filter(ticket=self.ticket, source='rmm').get()
        self.assertTrue(note.is_internal)
        self.assertIn('Service did not start (1053).', note.body)
        self.assertTrue(AuditLog.objects.filter(object_type='psa.TicketComment', object_id=note.pk).exists())
        v = device_panel.verification(self.ticket)
        self.assertFalse(v['all_ok'])
        self.assertTrue(any('failed' in c['text'] for row in v['rows'] for c in row['checks']))

    def test_note_needs_a_request_of_this_ticket(self):
        req = self._failed_fix()
        other = make_ticket(self.a, assigned_to=self.tech)
        self.post('note', {'request': str(req.pk)}, ticket=other)
        self.post('note', {'request': 'not-a-uuid'})
        self.assertFalse(TicketComment.objects.filter(source='rmm').exists())

    def test_verify_then_close(self):
        TicketStatus.objects.get_or_create(slug='closed', defaults={'name': 'Closed', 'is_terminal': True,
                                                                     'sort_order': 99})
        alert = RMMAlert.objects.create(organization=self.a, connection=self.conn_a, device=self.device,
                                        external_id='al-1', alert_type='Disk', message='C: 95% full',
                                        severity='warning', triggered_at=timezone.now())
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/verify/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-verify-result="not-ok"', page.content.decode())
        data = {'resolution_summary': 'Freed disk space', 'closure_category': 'fixed'}
        self.post('verify/close', data)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.closed_at)  # refused without the acknowledgement
        alert.status = 'resolved'
        alert.save()
        self.assertTrue(device_panel.verification(self.ticket)['all_ok'])
        self.post('verify/close', data)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.closed_at)
        note = TicketComment.objects.get(ticket=self.ticket, source='rmm')
        self.assertTrue(note.is_internal)
        self.assertIn('[OK]', note.body)

    def test_close_anyway_is_recorded(self):
        TicketStatus.objects.get_or_create(slug='closed', defaults={'name': 'Closed', 'is_terminal': True,
                                                                     'sort_order': 99})
        RMMDevice.objects.filter(pk=self.device.pk).update(is_online=False)
        self.post('verify/close', {'resolution_summary': 'Replaced cable', 'closure_category': 'fixed',
                                   'acknowledge': '1'})
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.closed_at)
        self.assertIn('Closed anyway', TicketComment.objects.get(ticket=self.ticket, source='rmm').body)
        self.assertTrue(AuditLog.objects.filter(description__contains='unverified checks acknowledged').exists())

    def test_time_entry_from_the_panel(self):
        html = self.page()
        self.assertIn('data-rmm-time', html)
        self.c.post(f'/psa/t/{self.ticket.ticket_number}/time/manual/', {'minutes': 15, 'notes': 'RMM work',
                                                                        'is_billable': '1'})
        self.assertEqual(self.ticket.time_entries.get().duration_minutes, 15)
