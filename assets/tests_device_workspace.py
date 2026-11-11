"""
ClientSt0r ↔ RMM Phase 3: the Device Workspace (assets/device_workspace.py,
assets/workspace_views.py).
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset
from integrations.models import RMMDevice, RMMSoftware
from integrations.rem0te import testing as rem0te_testing
from psa.affected import add
from psa.tests._base import TEST_MIDDLEWARE
from psa_ai.models import Rem0teAlertEvent, RMMRequest
from psa_ai.tests_assist import KEY_DIR, sign_in
from psa_ai.tests_rmm import RMMActionBase
from tech_access.testing import make_tech, make_ticket
from vault.models import Password, PasswordRelation

from . import device_workspace as ws


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AI_GATEWAY_KEY_DIR=KEY_DIR,
                   AI_GATEWAY_MODE='in_process', ALLOWED_HOSTS=['*'])
class WorkspaceBase(RMMActionBase):
    def setUp(self):
        super().setUp()
        RMMDevice.objects.filter(pk=self.device.pk).update(
            is_online=True, last_seen=timezone.now(),
            raw_data={'logged_username': 'pat.frontdesk', 'agent_version': '2.7.0', 'total_ram': 16,
                      'cpu_model': ['Intel i5-12500'], 'needs_reboot': True,
                      'boot_time': (timezone.now() - timedelta(days=2, hours=3)).timestamp(),
                      'disks': [{'device': 'C:', 'total_gb': 238, 'percent': 71}],
                      'local_ips': ['10.0.0.21']})
        self.device.refresh_from_db()

    def ws(self, asset=None, client=None, **params):
        return (client or self.c).get(f'/assets/{(asset or self.asset).pk}/workspace/', params)


class WorkspaceContentTests(WorkspaceBase):
    def test_renders_inventory_freshness_and_toolbar(self):
        r = self.ws()
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('data-ws-state="online"', html)
        self.assertIn('pat.frontdesk', html)  # technician with an assignment at this customer
        self.assertIn('Version 2.7.0', html)
        self.assertIn('Intel i5-12500', html)
        self.assertIn('2d 3h', html)
        self.assertIn('10.0.0.21', html)
        self.assertIn('data-ws-reboot', html)
        for key in ('connect', 'diagnose', 'action', 'patches', 'ticket', 'more'):
            self.assertIn(f'data-ws-action="{key}"', html)
        # No ticket in context: device actions point to a ticket and say why.
        self.assertIn('data-ws-reason="diagnose"', html)
        self.assertIn('Requested from a ticket', html)

    def test_unsupported_and_not_synced_are_explicit(self):
        html = self.ws().content.decode()
        self.assertIn('data-ws-support="software:not_synced"', html)
        self.assertIn('data-ws-unsupported="services"', html)
        self.assertIn('data-ws-unsupported="events"', html)

    def test_logged_in_user_hidden_without_an_assignment_here(self):
        other = make_tech('nadia')  # MSP staff, no technician access at Alpha
        html = self.ws(client=sign_in(other, self.a)).content.decode()
        self.assertNotIn('pat.frontdesk', html)
        self.assertIn('Hidden — needs a technician access assignment', html)

    def test_stale_data_is_labelled_and_uptime_not_invented(self):
        RMMDevice.objects.filter(pk=self.device.pk).update(data_refreshed_at=timezone.now() - timedelta(days=2))
        html = self.ws().content.decode()
        self.assertIn('data-ws-stale', html)
        self.assertIn('data-ws-state="stale"', html)
        self.assertNotIn('2d 3h', html)

    def test_offline_agent_with_ticket_context(self):
        RMMDevice.objects.filter(pk=self.device.pk).update(is_online=False,
                                                           last_seen=timezone.now() - timedelta(hours=6))
        html = self.ws(ticket=self.ticket.ticket_number).content.decode()
        self.assertIn(f'data-ws-ticket="{self.ticket.ticket_number}"', html)
        self.assertIn('data-ws-back-ticket', html)
        self.assertIn('disabled data-ws-action="diagnose"', html)
        self.assertIn('The agent is offline', html)

    def test_ticket_context_enables_actions_through_the_ticket_routes(self):
        html = self.ws(ticket=self.ticket.ticket_number).content.decode()
        self.assertIn(f'action="/psa/rmm/{self.ticket.ticket_number}/launch/"', html)
        self.assertNotIn('disabled data-ws-action="diagnose"', html)

    def test_failed_job_and_unconfirmed_launch_in_history(self):
        self.post('fix', {'device': self.device.pk, 'idempotency_key': 'ws-fix-1', 'risk': 'low',
                          'title': 'Restart spooler', 'description': 'Stuck'})
        RMMRequest.objects.filter(kind='fix_referral').update(status='failed', error='Refused: ENDPOINT_NOT_READY')
        self.post('launch', {'device': self.device.pk, 'mode': 'view'})
        html = self.ws().content.decode()
        self.assertIn('data-status="failed"', html)
        self.assertIn('Refused: ENDPOINT_NOT_READY', html)
        self.assertIn('session not confirmed by the RMM', html)
        self.assertIn('data-session-confirmed="0"', html)

    def test_related_tickets_and_credentials_without_secrets(self):
        ticket2 = make_ticket(self.a, assigned_to=self.tech, subject='Second ticket')
        add(ticket2, self.asset.pk, self.tech)
        pw = Password(organization=self.a, title='FRONTDESK local admin', username='admin')
        pw.set_password('S3cret-value!')
        pw.save()
        PasswordRelation.objects.create(password=pw, relation_type='asset', relation_id=self.asset.pk)
        html = self.ws().content.decode()
        self.assertIn(self.ticket.ticket_number, html)
        self.assertIn(ticket2.ticket_number, html)
        self.assertIn('FRONTDESK local admin', html)
        self.assertNotIn('S3cret-value!', html)


class WorkspaceBoundaryTests(WorkspaceBase):
    def test_other_customers_asset_and_ticket_context(self):
        asset_b = Asset.objects.create(organization=self.b, name='Front desk PC', hostname='FRONTDESK-01')
        RMMDevice.objects.create(organization=self.b, connection=self.conn_b, external_id='c-1',
                                 device_name='FRONTDESK-01', linked_asset=asset_b, data_refreshed_at=timezone.now())
        # Selected customer is Alpha: Beta's asset does not exist here.
        self.assertEqual(self.ws(asset=asset_b).status_code, 404)
        # A Beta ticket in the link is ignored on Alpha's asset.
        ticket_b = make_ticket(self.b, assigned_to=self.tech)
        html = self.ws(ticket=ticket_b.ticket_number).content.decode()
        self.assertIn('data-ws-ticket-ignored', html)
        self.assertNotIn(ticket_b.ticket_number + '/launch', html)
        # A device id from Beta's identically named machine can't be selected.
        dev_b = RMMDevice.objects.get(organization=self.b)
        html = self.ws(device=dev_b.pk).content.decode()
        self.assertNotIn(f'?device={dev_b.pk}', html)
        self.assertIn(self.device.external_id, html)

    def test_customer_users_get_404(self):
        portal = User.objects.create_user('client', password='pw')
        Membership.objects.create(user=portal, organization=self.a, role=Role.OWNER)
        self.assertEqual(self.ws(client=sign_in(portal, self.a)).status_code, 404)

    def test_asset_without_rmm(self):
        bare = Asset.objects.create(organization=self.a, name='Printer', asset_type='printer')
        html = self.ws(asset=bare).content.decode()
        self.assertIn('data-ws-no-rmm', html)
        self.assertIn('disabled data-ws-action="connect"', html)


class Rem0teWorkspaceTests(WorkspaceBase):
    def setUp(self):
        super().setUp()
        self.r_conn = rem0te_testing.make_connection(self.a, name='Rem0te Alpha')
        self.r_asset = Asset.objects.create(organization=self.a, name='Clinic PC', asset_type='desktop')
        self.r_dev = RMMDevice.objects.create(organization=self.a, connection=self.r_conn,
                                              external_id='cmwb69a26000rx4amwdqpfgpi', device_name='FRONTDESK',
                                              linked_asset=self.r_asset, is_online=True, last_seen=timezone.now(),
                                              data_refreshed_at=timezone.now())

    def test_unsupported_rem0te_data_and_no_patch_summary_yet(self):
        html = self.ws(asset=self.r_asset).content.decode()
        self.assertIn('data-ws-support="software:unsupported"', html)
        self.assertIn('inventory API doesn&#x27;t share installed software', html)
        self.assertIn('data-ws-patches="no_data"', html)
        self.assertIn('Unknown', html)  # restart pending is unknown, never "No"

    def test_patch_summary_from_alert_event(self):
        ps = {'managers': [], 'freshness': 'stale', 'failed_kbs': ['KB5034441'],
              'managed_by': 'rem0te_or_windows_update', 'evidence_at': '2026-11-10T20:58:09.298Z',
              'pending_kbs': ['KB5035845'], 'last_boot_at': None, 'confirmed_kbs': [], 'pending_count': 1,
              'evidence_source': 'standard_agent_scan', 'reboot_required': True, 'deploy_available': False,
              'evidence_age_hours': 40, 'awaiting_confirmation_kbs': []}
        alert = {'kind': 'REBOOT_PENDING', 'state': 'open', 'title': 'FRONTDESK needs a restart',
                 'alert_id': 'al-1', 'severity': 'warning', 'computer_name': 'FRONTDESK',
                 'rem0te_endpoint_id': self.r_dev.external_id, 'patch_summary': ps}
        Rem0teAlertEvent.objects.create(connection=self.r_conn, event_id='e1', sequence=1, event_type='alert.raised',
                                        alert_id='al-1', body={'type': 'alert.raised', 'alert': alert})
        # Another computer's summary on the same connection is not this one's.
        Rem0teAlertEvent.objects.create(connection=self.r_conn, event_id='e2', sequence=2, event_type='alert.raised',
                                        alert_id='al-2', body={'type': 'alert.raised', 'alert': dict(
                                            alert, rem0te_endpoint_id='other', patch_summary=dict(ps, pending_kbs=['KB1111111']))})
        html = self.ws(asset=self.r_asset).content.decode()
        self.assertIn('Standard agent scan (read-only)', html)
        self.assertIn('data-ws-patch-freshness="stale"', html)
        self.assertIn('KB5035845', html)
        self.assertIn('KB5034441', html)
        self.assertNotIn('KB1111111', html)

    def test_support_matrix(self):
        sup = ws.support(self.r_dev)
        self.assertEqual(sup['software']['state'], ws.UNSUPPORTED)
        self.assertEqual(sup['services']['state'], ws.UNSUPPORTED)
        RMMSoftware.objects.create(organization=self.a, connection=self.conn_a, device=self.device, name='7-Zip',
                                   install_date=timezone.now())
        self.conn_a.sync_software = True
        self.conn_a.save()
        self.device.refresh_from_db()
        view = ws.device_view(self.device, show_user=True)
        self.assertEqual([s.name for s in view['recent_software']], ['7-Zip'])
