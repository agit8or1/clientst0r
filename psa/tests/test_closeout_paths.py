"""Every way into a closed status runs the closeout rules: change-request
verification and partner status updates (mobile API and AI actions are
covered in api_mobile/tests.py and psa_ai/tests.py)."""
import hashlib
import hmac
import json

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import (
    ChangeRequest, Queue, Ticket, TicketChecklistItem, TicketComment,
    TicketPriority, TicketShare, TicketStatus, TicketType,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChangeVerifyCloseoutTests(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.org = Organization.objects.create(name='ChgCo', slug='chg-co')
        self.tech = User.objects.create_superuser('chg_admin', 'a@x.com', 'pw')
        _make_msp_tech(self.tech)
        Membership.objects.create(user=self.tech, organization=self.org,
                                  role=Role.OWNER, is_active=True)
        change_type, _ = TicketType.objects.get_or_create(
            slug='change', defaults={'name': 'Change', 'organization': self.org})
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Swap firewall',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=change_type, status=TicketStatus.objects.get(slug='new'))
        self.cr = ChangeRequest.objects.get(ticket=self.ticket)
        self.cr.implementation_status = 'implementing'
        self.cr.save()
        self.client = Client()
        self.client.force_login(self.tech)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session['2fa_prompted'] = True
        session.save()

    def _verify(self, summary=''):
        return self.client.post(
            f'/psa/t/{self.ticket.ticket_number}/change/verify/',
            {'outcome_summary': summary})

    def test_verify_without_outcome_is_refused(self):
        r = self._verify('')
        self.assertEqual(r.status_code, 302)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any('resolution summary' in m for m in msgs), msgs)
        self.cr.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.cr.implementation_status, 'implementing')
        self.assertFalse(self.ticket.status.is_terminal)
        self.assertIsNone(self.ticket.closed_at)

    def test_verify_with_open_required_checklist_is_refused(self):
        TicketChecklistItem.objects.create(ticket=self.ticket, label='Confirm VPN',
                                           is_required=True)
        self._verify('Firewall swapped, all tunnels up.')
        self.cr.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.cr.implementation_status, 'implementing')
        self.assertFalse(self.ticket.status.is_terminal)

    def test_verify_closes_with_outcome_as_resolution(self):
        self._verify('Firewall swapped, all tunnels up.')
        self.cr.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.cr.implementation_status, 'verified')
        self.assertTrue(self.ticket.status.is_terminal)
        self.assertEqual(self.ticket.resolution_summary, 'Firewall swapped, all tunnels up.')
        self.assertEqual(self.ticket.closure_category, 'fixed')
        self.assertIsNotNone(self.ticket.closed_at)
        self.assertIsNotNone(self.ticket.resolved_at)
        self.assertTrue(TicketComment.objects.filter(
            ticket=self.ticket, body__startswith='Closed (Fixed)').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PartnerStatusCloseoutTests(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.org = Organization.objects.create(name='MspCo', slug='msp-co')
        self.partner = Organization.objects.create(
            name='Partner Inc', slug='partner-inc-co', is_outsourcing_partner=True,
            partner_endpoint_url='http://127.0.0.1:1/no-such-host')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Outsourced job',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.get(slug='new'))
        self.share = TicketShare.objects.create(
            ticket=self.ticket, partner_org=self.partner, status='accepted')

    def _send(self, status):
        raw = json.dumps({'event': 'status', 'payload': {'status': status}}).encode()
        sig = hmac.new(self.partner.partner_secret.encode(), raw, hashlib.sha256).hexdigest()
        return Client().post(f'/psa/partners/webhook/{self.share.pk}/', data=raw,
                             content_type='application/json', HTTP_X_CST0R_SIGNATURE=sig)

    def test_partner_cannot_close_local_ticket(self):
        closed = TicketStatus.objects.filter(is_terminal=True).first()
        r = self._send(closed.slug)
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.status.is_terminal)
        self.assertIsNone(self.ticket.closed_at)
        self.assertTrue(TicketComment.objects.filter(
            ticket=self.ticket, is_internal=True,
            body__contains='Close the ticket here').exists())

    def test_partner_cannot_reopen_closed_ticket(self):
        closed = TicketStatus.objects.filter(is_terminal=True).first()
        Ticket.objects.filter(pk=self.ticket.pk).update(status=closed)
        r = self._send('in-progress')
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status_id, closed.pk)

    def test_partner_completed_updates_share_only(self):
        r = self._send('completed')
        self.assertEqual(r.status_code, 200)
        self.share.refresh_from_db()
        self.assertEqual(self.share.status, 'completed')
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.status.is_terminal)
