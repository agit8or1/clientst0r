"""Safe removal of an RMM connection (docs/ux/STANDALONE_REQUIREMENTS.md P0-6,
D1–D3, test matrix J; increment 113.6).

The delete page says what deleting does (devices, alerts, ticket links,
ticket requests) and recommends Disable. Deleting never removes tickets or
the record of which alert opened which ticket (kept with the connection's
name and provider). A connection that ticket requests went through cannot
be deleted: the page explains why in plain words, never "integrity error"
and never a 500. Disable and delete are audit-logged.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from core.models import Organization
from integrations.models import RMMAlert, RMMConnection, RMMDevice
from psa.routing.models import AlertTicketLink
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed
from psa_ai.models import Rem0teAlertTicket, RMMRequest

User = get_user_model()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RMMRemovalTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Removal Co', slug='removal-co')
        cls.su = User.objects.create_superuser('removal_root', 'r@x.test', 'pw')

    def setUp(self):
        from psa.tests.test_ticket_site import _ticket
        self.conn = RMMConnection.objects.create(organization=self.org, name='Tactical Prod',
                                                 provider_type='tactical_rmm', base_url='https://rmm.removal.test')
        self.device = RMMDevice.objects.create(organization=self.org, connection=self.conn, external_id='d-1',
                                               device_name='FRONT-01')
        self.alert = RMMAlert.objects.create(organization=self.org, connection=self.conn, device=self.device,
                                             external_id='a-1', alert_type='disk', message='Disk full',
                                             severity='error', status='active', triggered_at=timezone.now())
        self.ticket = _ticket(self.org, subject='Disk full on FRONT-01')
        self.link = AlertTicketLink.objects.create(
            source=AlertTicketLink.SOURCE_RMM, connection=self.conn, external_id='a-1', organization=self.org,
            device=self.device, device_name='FRONT-01', title='Disk full', disposition='created', ticket=self.ticket)
        self.rem0te_link = Rem0teAlertTicket.objects.create(connection=self.conn, organization=self.org,
                                                            alert_id='r-1', ticket=self.ticket, title='Disk full')
        self.client.force_login(self.su)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()

    def url(self, name='rmm_delete'):
        return reverse(f'integrations:{name}', args=[self.conn.pk])

    def request_through_connection(self):
        return RMMRequest.objects.create(
            organization=self.org, ticket=self.ticket, connection=self.conn, device=self.device,
            device_external_id='d-1', tenant_id='t', actor=self.su, kind=RMMRequest.KIND_FIX,
            payload_digest='x' * 64, idempotency_key='removal-1')

    # -- the page -------------------------------------------------------------

    def test_delete_page_shows_counts_and_recommends_disable(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('data-rmm-recommended="disable"', html)
        self.assertIn(self.url('rmm_set_active'), html)
        self.assertIn('data-rmm-delete', html)
        for key, value in (('devices', 1), ('alerts', 1), ('ticket_links', 2), ('fix_requests', 0)):
            self.assertRegex(html, rf'data-count="{key}">{value}\b', key)
        self.assertIn('on 1 ticket', html)
        self.assertIn('Tickets are never removed', html)

    # -- deleting -------------------------------------------------------------

    def test_delete_keeps_tickets_and_link_history(self):
        pk = self.conn.pk
        r = self.client.post(self.url())
        self.assertRedirects(r, reverse('integrations:integration_list'), fetch_redirect_response=False)
        self.assertFalse(RMMConnection.objects.filter(pk=pk).exists())
        # Mirrored RMM data goes ...
        self.assertFalse(RMMDevice.objects.filter(pk=self.device.pk).exists())
        self.assertFalse(RMMAlert.objects.filter(pk=self.alert.pk).exists())
        # ... tickets and the alert-to-ticket history stay, readable.
        self.ticket.refresh_from_db()
        link = AlertTicketLink.objects.get(pk=self.link.pk)
        self.assertIsNone(link.connection_id)
        self.assertEqual(link.ticket_id, self.ticket.pk)
        self.assertEqual((link.connection_name, link.provider_type, link.device_name),
                         ('Tactical Prod', 'tactical_rmm', 'FRONT-01'))
        self.assertEqual(link.connection_label, 'Tactical Prod')
        r0 = Rem0teAlertTicket.objects.get(pk=self.rem0te_link.pk)
        self.assertIsNone(r0.connection_id)
        self.assertEqual((r0.ticket_id, r0.connection_name), (self.ticket.pk, 'Tactical Prod'))
        self.assertTrue(AuditLog.objects.filter(action='delete', object_type='rmm_connection', object_id=pk).exists())
        # The ticket page still renders with the orphaned links.
        self.assertEqual(self.client.get(reverse('psa:ticket_detail', args=[self.ticket.ticket_number])).status_code,
                         200)

    def test_imported_customer_with_tickets_is_never_deleted(self):
        imported = Organization.objects.create(name='RMM-Imported', slug='rmm-imported')
        RMMDevice.objects.create(organization=imported, connection=self.conn, external_id='d-2', device_name='X')
        from psa.tests.test_ticket_site import _ticket
        t = _ticket(imported, subject='Imported customer ticket')
        self.conn.delete()
        self.assertTrue(Organization.objects.filter(pk=imported.pk).exists())
        t.refresh_from_db()

    def test_blocked_delete_explains_and_offers_disable(self):
        self.request_through_connection()
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('data-rmm-delete-blocked', html)
        self.assertIn('1 ticket request', html)
        self.assertNotIn('data-rmm-delete>', html)  # no delete button
        self.assertIn(self.url('rmm_set_active'), html)
        r = self.client.post(self.url())
        self.assertEqual(r.status_code, 409)
        html = r.content.decode()
        self.assertIn('The connection was not deleted', html)
        self.assertNotIn('integrity', html.lower())
        self.assertTrue(RMMConnection.objects.filter(pk=self.conn.pk).exists())
        self.assertTrue(RMMDevice.objects.filter(pk=self.device.pk).exists())
        self.ticket.refresh_from_db()

    def test_unforeseen_protection_is_explained_not_a_500(self):
        # A request created after the page was drawn: the database refuses.
        self.request_through_connection()
        no_blockers = {'devices': 1, 'alerts': 1, 'ticket_links': 2, 'linked_tickets': 1, 'fix_requests': 0,
                       'analysis_jobs': 0, 'imported_organizations': [], 'blockers': [], 'can_delete': True}
        with mock.patch('integrations.removal.impact', return_value=no_blockers):
            r = self.client.post(self.url())
        self.assertEqual(r.status_code, 409)
        html = r.content.decode()
        self.assertIn('still refer to this connection', html)
        self.assertNotIn('integrity', html.lower())
        self.assertTrue(RMMConnection.objects.filter(pk=self.conn.pk).exists())
        self.assertTrue(AlertTicketLink.objects.filter(pk=self.link.pk, connection=self.conn).exists())

    # -- disabling --------------------------------------------------------------

    def test_disable_keeps_everything_and_is_audited(self):
        r = self.client.post(self.url('rmm_set_active'), {'active': '0'})
        self.assertRedirects(r, reverse('integrations:rmm_detail', args=[self.conn.pk]),
                             fetch_redirect_response=False)
        self.conn.refresh_from_db()
        self.assertFalse(self.conn.is_active)
        self.assertTrue(RMMDevice.objects.filter(pk=self.device.pk).exists())
        self.assertTrue(AlertTicketLink.objects.filter(pk=self.link.pk, connection=self.conn).exists())
        self.assertTrue(AuditLog.objects.filter(action='update', object_type='rmm_connection',
                                                object_id=self.conn.pk, description__startswith='Disabled').exists())
        r = self.client.post(self.url('rmm_set_active'), {'active': '1'})
        self.conn.refresh_from_db()
        self.assertTrue(self.conn.is_active)
        self.assertEqual(self.client.get(self.url('rmm_set_active')).status_code, 405)

    def test_customer_user_cannot_disable(self):
        from accounts.models import Membership
        cust = User.objects.create_user('removal_cust', 'c@x.test', 'pw')
        Membership.objects.create(user=cust, organization=self.org, role='owner')
        self.client.force_login(cust)
        r = self.client.post(self.url('rmm_set_active'), {'active': '0'})
        self.assertIn(r.status_code, (403, 404))
        self.conn.refresh_from_db()
        self.assertTrue(self.conn.is_active)
