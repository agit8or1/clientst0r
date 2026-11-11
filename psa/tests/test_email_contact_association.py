"""Phase 10.3.1 — automatic contact association on email intake.

A new emailed ticket is linked to the sender's existing Contact and customer
user at the customer the message was assigned to, never at another customer.
Runs through the `psa_poll_email` command with a fake IMAP server.
"""
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from accounts.models import Membership, UserType
from assets.models import Contact
from core.models import Organization
from psa.models import EmailMessage, EmailRoutingRule, Ticket, TicketComment

from psa.tests.test_phase10_email import (
    _EmailPollerSetup, _FakeIMAP, _build_raw_email,
)


class EmailContactAssociationTests(TestCase, _EmailPollerSetup):

    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('assoc-a')
        self.other_org = Organization.objects.create(name='Other', slug='assoc-b')
        self._n = 0

    def _poll(self, from_addr, **kw):
        from psa.management.commands import psa_poll_email
        self._n += 1
        raw = _build_raw_email(
            message_id=kw.pop('message_id', f'<assoc-{self._n}@example.com>'),
            from_addr=from_addr, to_addr='help@assoc-a.example.com',
            subject=kw.pop('subject', 'Printer broken'), **kw)
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **k: fake
        try:
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

    def _new_ticket(self, org=None):
        return Ticket.objects.filter(organization=org or self.org).latest('pk')

    def _member(self, username, email, org):
        user = User.objects.create_user(username, email, 'pw',
                                        first_name='Pat', last_name='Member')
        Membership.objects.create(user=user, organization=org, role='readonly')
        return user

    def test_links_existing_contact_of_that_customer(self):
        contact = Contact.objects.create(organization=self.org, first_name='Ann',
                                         last_name='Lee', email='ann@acme.example')
        self._poll('Ann Lee <ann@acme.example>')
        ticket = self._new_ticket()
        self.assertEqual(ticket.contact, contact)
        self.assertEqual(ticket.requester_email, 'ann@acme.example')

    def test_match_is_case_insensitive(self):
        contact = Contact.objects.create(organization=self.org, first_name='Ann',
                                         last_name='Lee', email='Ann@Acme.Example')
        self._poll('ANN@ACME.EXAMPLE')
        ticket = self._new_ticket()
        self.assertEqual(ticket.contact, contact)
        # No display name in From: the contact's name is used.
        self.assertEqual(ticket.requester_name, 'Ann Lee')

    def test_links_customer_user_with_active_membership(self):
        user = self._member('assoc_pat', 'pat@acme.example', self.org)
        self._poll('pat@acme.example')
        ticket = self._new_ticket()
        self.assertEqual(ticket.created_by, user)
        self.assertIsNone(ticket.contact)
        self.assertEqual(ticket.requester_name, 'Pat Member')

    def test_contact_and_user_both_linked(self):
        contact = Contact.objects.create(organization=self.org, first_name='Pat',
                                         last_name='Member', email='pat@acme.example')
        user = self._member('assoc_both', 'pat@acme.example', self.org)
        self._poll('pat@acme.example')
        ticket = self._new_ticket()
        self.assertEqual(ticket.contact, contact)
        self.assertEqual(ticket.created_by, user)

    def test_never_links_another_customers_contact_or_member(self):
        Contact.objects.create(organization=self.other_org, first_name='Bob',
                               last_name='Other', email='bob@shared.example')
        self._member('assoc_bob', 'bob@shared.example', self.other_org)
        self._poll('bob@shared.example')
        ticket = self._new_ticket()
        self.assertIsNone(ticket.contact)
        self.assertIsNone(ticket.created_by)
        self.assertEqual(ticket.requester_email, 'bob@shared.example')

    def test_inactive_membership_is_not_linked(self):
        user = self._member('assoc_gone', 'gone@acme.example', self.org)
        Membership.objects.filter(user=user).update(is_active=False)
        self._poll('gone@acme.example')
        self.assertIsNone(self._new_ticket().created_by)

    def test_msp_staff_sender_is_not_recorded_as_requester(self):
        user = self._member('assoc_tech', 'tech@msp.example', self.org)
        user.profile.user_type = UserType.STAFF
        user.profile.save()
        self._poll('tech@msp.example')
        self.assertIsNone(self._new_ticket().created_by)

    def test_ambiguous_contacts_are_left_unlinked(self):
        for first in ('Front', 'Desk'):
            Contact.objects.create(organization=self.org, first_name=first,
                                   last_name='Shared', email='frontdesk@acme.example')
        self._poll('Front Desk <frontdesk@acme.example>')
        ticket = self._new_ticket()
        self.assertIsNone(ticket.contact)
        self.assertEqual(ticket.requester_name, 'Front Desk')

    def test_no_match_leaves_fields_empty(self):
        self._poll('Stranger <nobody@unknown.example>')
        ticket = self._new_ticket()
        self.assertIsNone(ticket.contact)
        self.assertIsNone(ticket.created_by)
        self.assertEqual(ticket.requester_name, 'Stranger')

    def test_routed_mail_matches_only_the_routing_target(self):
        client_org = Organization.objects.create(name='Routed', slug='assoc-routed')
        EmailRoutingRule.objects.create(organization=self.org, name='Routed',
                                        sender_domain_glob='routed.example',
                                        target_client_org=client_org)
        # Same address at the mailbox's own customer and at the target.
        Contact.objects.create(organization=self.org, first_name='Wrong',
                               last_name='Org', email='amy@routed.example')
        right = Contact.objects.create(organization=client_org, first_name='Amy',
                                       last_name='Routed', email='amy@routed.example')
        self._poll('amy@routed.example')
        ticket = self._new_ticket(client_org)
        self.assertEqual(ticket.contact, right)

    def test_reply_does_not_change_requester(self):
        ticket = self._make_ticket(self.org, requester_email='orig@acme.example')
        EmailMessage.objects.create(organization=self.org, ticket=ticket,
                                    ingestion_config=self.cfg, direction='in',
                                    message_id='<assoc-root@example.com>')
        Contact.objects.create(organization=self.org, first_name='Carl',
                               last_name='Cc', email='carl@acme.example')
        self._member('assoc_carl', 'carl@acme.example', self.org)
        self._poll('carl@acme.example', in_reply_to='<assoc-root@example.com>',
                   subject='Re: Existing ticket')
        ticket.refresh_from_db()
        self.assertEqual(TicketComment.objects.filter(ticket=ticket).count(), 1)
        self.assertIsNone(ticket.contact)
        self.assertIsNone(ticket.created_by)
        self.assertEqual(ticket.requester_email, 'orig@acme.example')
