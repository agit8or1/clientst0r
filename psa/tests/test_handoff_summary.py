"""Technician handoff summary (roadmap 52.22): content, staff-only access."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset
from core.models import Organization
from psa.handoff import build_handoff, render_text
from psa.models import (Queue, Ticket, TicketChecklistItem, TicketComment,
                        TicketPriority, TicketStatus, TicketTimeEntry, TicketType)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed
from vault.models import Password


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class HandoffSummaryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Handoff Dental', slug='handoff-dental')
        cls.other_org = Organization.objects.create(name='Other Co', slug='other-co')
        _enable_psa_for(cls.org)
        _enable_psa_for(cls.other_org)
        cls.tech = _make_msp_tech(User.objects.create_user('ho_tech', 't@msp.test', 'pw-ho-123'))
        Membership.objects.create(user=cls.tech, organization=cls.org, role=Role.EDITOR, is_active=True)
        cls.customer = User.objects.create_user('ho_cust', 'c@dental.test', 'pw-ho-123')
        Membership.objects.create(user=cls.customer, organization=cls.org, role=Role.ADMIN, is_active=True)
        cls.outsider = User.objects.create_user('ho_out', 'o@other.test', 'pw-ho-123')
        Membership.objects.create(user=cls.outsider, organization=cls.other_org, role=Role.ADMIN, is_active=True)

        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Server rebooting', client_can_view=True, assigned_to=cls.tech,
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.filter(slug='new').first())
        cls.asset = Asset.objects.create(organization=cls.org, name='SRV-HANDOFF-01', asset_type='server',
                                         hostname='srv01.local')
        foreign = Asset.objects.create(organization=cls.other_org, name='FOREIGN-BOX', asset_type='server')
        cls.ticket.related_asset = cls.asset
        cls.ticket.save()
        TicketComment.objects.create(ticket=cls.ticket, author=cls.tech, body='Rebooted the host once.')
        TicketComment.objects.create(ticket=cls.ticket, author=cls.tech, body='INTERNAL-NOTE-XYZ call vendor',
                                     is_internal=True)
        TicketComment.objects.create(ticket=cls.ticket, author=cls.tech, body='Status changed to New.',
                                     is_system=True, is_internal=True)
        now = timezone.now()
        TicketTimeEntry.objects.create(ticket=cls.ticket, user=cls.tech, started_at=now - timedelta(hours=1),
                                       ended_at=now, duration_minutes=60, notes='Checked event logs')
        TicketChecklistItem.objects.create(ticket=cls.ticket, label='Confirm backup ran')
        TicketChecklistItem.objects.create(ticket=cls.ticket, label='Already done item', is_completed=True)
        Password.objects.create(organization=cls.org, title='VAULT-TITLE-SECRET', username='vaultuser')

    def _web(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _url(self):
        return reverse('psa:ticket_detail', kwargs={'ticket_number': self.ticket.ticket_number})

    def test_summary_contents(self):
        s = build_handoff(self.ticket, self.tech)
        self.assertEqual(s['status'], 'New')
        self.assertEqual(s['assignee'], 'ho_tech')
        self.assertEqual([i['label'] for i in s['open_items']], ['Confirm backup ran'])
        self.assertEqual([d['name'] for d in s['devices']], ['SRV-HANDOFF-01'])
        kinds = {a['kind'] for a in s['actions']}
        self.assertTrue({'reply', 'internal note', 'update', 'time entry'} <= kinds)
        text = render_text(s)
        for want in ('Server rebooting', 'Rebooted the host once.', 'Confirm backup ran',
                     'SRV-HANDOFF-01', 'Checked event logs', 'Handoff Dental'):
            self.assertIn(want, text)
        self.assertNotIn('Already done item', text)

    def test_foreign_customer_device_not_listed(self):
        foreign = Asset.objects.get(name='FOREIGN-BOX')
        t2 = Ticket.objects.create(
            organization=self.org, subject='x', queue=self.ticket.queue, priority=self.ticket.priority,
            ticket_type=self.ticket.ticket_type, status=self.ticket.status, related_asset=foreign)
        self.assertEqual(build_handoff(t2, self.tech)['devices'], [])

    def test_action_limit(self):
        for i in range(12):
            TicketComment.objects.create(ticket=self.ticket, author=self.tech, body=f'bulk {i}')
        self.assertEqual(len(build_handoff(self.ticket, self.tech)['actions']), 8)

    def test_not_built_for_customer(self):
        self.assertIsNone(build_handoff(self.ticket, self.customer))

    def test_staff_page_shows_panel_with_internal_note(self):
        html = self._web(self.tech).get(self._url()).content.decode()
        self.assertIn('Handoff summary', html)
        self.assertIn('data-handoff-copy', html)
        self.assertIn('INTERNAL-NOTE-XYZ', html)
        self.assertIn('ticket_handoff.js', html)

    def test_customer_page_has_no_panel_or_internal_note(self):
        resp = self._web(self.customer).get(self._url())
        html = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Handoff summary', html)
        self.assertNotIn('data-handoff', html)
        self.assertNotIn('INTERNAL-NOTE-XYZ', html)
        self.assertNotIn('handoff_text', resp.context or {})

    def test_other_customers_user_cannot_reach_ticket(self):
        c = Client()
        c.force_login(self.outsider)
        s = c.session
        s['current_organization_id'] = self.other_org.id
        s.save()
        resp = c.get(self._url())
        self.assertIn(resp.status_code, (302, 403, 404))
        self.assertNotIn('Handoff summary', resp.content.decode())

    def test_no_vault_data(self):
        text = render_text(build_handoff(self.ticket, self.tech))
        html = self._web(self.tech).get(self._url()).content.decode()
        for blob in (text,):
            self.assertNotIn('VAULT-TITLE-SECRET', blob)
            self.assertNotIn('vaultuser', blob)
        # The handoff panel itself must not carry vault entries.
        panel = html.split('data-handoff-text>', 1)[1].split('</pre>', 1)[0]
        self.assertNotIn('VAULT-TITLE-SECRET', panel)
