"""
Opt-in "email this reply to the requester" on the ticket reply form (issue #142).

The Graph/SMTP outbound transport shipped in v3.17.507 but had no production
caller — replies were stored as comments and never left the app. These tests
cover the wiring: the checkbox is opt-in, internal notes are never emailed, and
a send failure never discards the comment that was already saved.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from integrations.models import M365Connection
from psa.models import (
    EmailIngestionConfig, EmailMessage, EmailOutboundJob, Queue, Ticket,
    TicketComment, TicketPriority, TicketStatus, TicketType,
)
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed
from psa.tests.test_graph_outbound import ACCEPTED, graph_provider


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TicketReplyEmailTests(TestCase):
    """POST /psa/t/<num>/comment/ with and without the send_email opt-in."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME', slug='acme')
        self.alice = User.objects.create_user('alice', password='pw', email='a@x.com')
        Membership.objects.update_or_create(
            user=self.alice, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        self.client = Client()
        self.client.force_login(self.alice)
        sess = self.client.session
        sess['current_organization_id'] = self.org.id
        sess.save()
        self.ticket = self._ticket()

    def _ticket(self, requester='cust@client.com'):
        return Ticket.objects.create(
            organization=self.org, subject='Printer offline', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            source='email', requester_email=requester)

    def _post(self, **extra):
        data = {'body': 'Have you tried power-cycling it?'}
        data.update(extra)
        return self.client.post(
            f'/psa/t/{self.ticket.ticket_number}/comment/', data)

    def _graph_config(self, *, active=True):
        conn = M365Connection.objects.create(
            organization=self.org, name='Tenant', tenant_id='t', is_active=True)
        conn.set_credentials({'client_id': 'cid', 'client_secret': 'sec'})
        conn.save()
        return EmailIngestionConfig.objects.create(
            organization=self.org, name='helpdesk', source='graph',
            outbound_method='graph', m365_connection=conn,
            graph_mailbox='support@x.com', is_active=active,
            default_queue=Queue.objects.first(),
            default_priority=TicketPriority.objects.first(),
            default_type=TicketType.objects.first())

    # -- opt-in gate --------------------------------------------------------

    def test_no_checkbox_sends_nothing(self):
        """The default path is unchanged: a public reply emails nobody."""
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TicketComment.objects.filter(ticket=self.ticket).exists())
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            EmailMessage.objects.filter(ticket=self.ticket, direction='out').exists())

    def test_checkbox_sends_via_smtp(self):
        resp = self._post(send_email='1')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['cust@client.com'])
        self.assertIn(self.ticket.ticket_number, sent.subject)
        self.assertIn('power-cycling', sent.body)
        row = EmailMessage.objects.get(ticket=self.ticket, direction='out')
        self.assertEqual(row.transport, 'smtp')

    def test_internal_note_is_never_emailed(self):
        """Even with the box ticked, an internal note stays internal."""
        resp = self._post(send_email='1', is_internal='1')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(
            TicketComment.objects.filter(ticket=self.ticket, is_internal=True).exists())

    def test_missing_requester_email_warns_and_keeps_comment(self):
        self.ticket = self._ticket(requester='')
        resp = self._post(send_email='1')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(TicketComment.objects.filter(ticket=self.ticket).exists())

    # -- graph transport ----------------------------------------------------

    def test_checkbox_sends_via_graph_when_configured(self):
        cfg = self._graph_config()
        EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, ingestion_config=cfg,
            direction='in', message_id='<in@x.com>', transport='graph')
        with graph_provider(ACCEPTED) as calls:
            resp = self._post(send_email='1')
        self.assertEqual(resp.status_code, 302)
        job = EmailOutboundJob.objects.get(ticket=self.ticket)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_SENT)
        self.assertEqual(job.to_recipients, ['cust@client.com'])
        self.assertEqual(len(calls), 1)
        # Graph path must not also go out over SMTP.
        self.assertEqual(len(mail.outbox), 0)

    def test_graph_failure_keeps_the_comment(self):
        """A send that blows up still leaves the saved comment behind."""
        cfg = self._graph_config()
        EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, ingestion_config=cfg,
            direction='in', message_id='<in@x.com>', transport='graph')
        with graph_provider(raise_exc=RuntimeError('boom')):
            resp = self._post(send_email='1')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            TicketComment.objects.filter(ticket=self.ticket,
                                         body__contains='power-cycling').exists())


class ResolveTicketEmailConfigTests(TestCase):
    """Which mailbox a reply goes back out of."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='ACME', slug='acme')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='S', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            requester_email='c@x.com')

    def _config(self, name, *, active=True):
        return EmailIngestionConfig.objects.create(
            organization=self.org, name=name, source='imap',
            imap_host='mail.x.com', username='u', is_active=active,
            default_queue=Queue.objects.first(),
            default_priority=TicketPriority.objects.first(),
            default_type=TicketType.objects.first())

    def _inbound(self, cfg):
        return EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, ingestion_config=cfg,
            direction='in', message_id=f'<in-{cfg.pk}@x.com>')

    def test_prefers_the_config_that_ingested_the_ticket(self):
        from psa.email_outbound import resolve_ticket_email_config
        first, second = self._config('a'), self._config('b')
        self._inbound(first)
        self.assertEqual(resolve_ticket_email_config(self.ticket), first)
        # A newer inbound on the other mailbox wins.
        self._inbound(second)
        self.assertEqual(resolve_ticket_email_config(self.ticket), second)

    def test_falls_back_to_the_only_active_config(self):
        from psa.email_outbound import resolve_ticket_email_config
        only = self._config('a')
        self.assertEqual(resolve_ticket_email_config(self.ticket), only)

    def test_ambiguous_configs_resolve_to_none(self):
        """Two candidate mailboxes and no inbound — don't guess."""
        from psa.email_outbound import resolve_ticket_email_config
        self._config('a'); self._config('b')
        self.assertIsNone(resolve_ticket_email_config(self.ticket))

    def test_inactive_ingesting_config_is_not_used(self):
        from psa.email_outbound import resolve_ticket_email_config
        dead = self._config('dead', active=False)
        self._inbound(dead)
        # Only inactive configs exist, so there is nothing to fall back to.
        self.assertIsNone(resolve_ticket_email_config(self.ticket))
