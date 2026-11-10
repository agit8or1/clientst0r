"""v3.17.654: copying people on ticket replies, and secure (encrypted,
one-time) messages sent with a reply."""
from __future__ import annotations

import re
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization, SecureNote, SystemSetting
from psa.models import EmailMessage, Queue, Ticket, TicketComment, TicketDraft, TicketPriority, TicketStatus, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech, _setup_seed
from psa.ticket_secure import merge_cc, parse_addresses, scrub_secret_links, secure_status

SECRET = 'Temp-Pass-4417!'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class _Base(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='Example Dental', slug='ex-dental-654')
        self.tech = _make_msp_tech(User.objects.create_user('tech654', password='pw', email='t@msp.test'))
        Membership.objects.create(user=self.tech, organization=self.org, role=Role.OWNER, is_active=True)
        self.customer = User.objects.create_user('cust654', password='pw', email='office@dental.example.com')
        Membership.objects.create(user=self.customer, organization=self.org, role=Role.EDITOR, is_active=True)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Front desk PC locked out', description='Locked out again',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.filter(slug='new').first(),
            source='email', requester_email='office@dental.example.com', visibility='client',
            client_can_view=True)
        self.client = self._login(self.tech)

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _post(self, client=None, **extra):
        data = {'body': 'I have reset the account.'}
        data.update(extra)
        return (client or self.client).post(f'/psa/t/{self.ticket.ticket_number}/comment/', data)


class CcTests(_Base):
    def test_addresses_are_parsed_validated_and_deduplicated(self):
        valid, invalid = parse_addresses('A@x.example.com, a@x.example.com; b@y.example.com not-an-address')
        self.assertEqual(valid, ['a@x.example.com', 'b@y.example.com'])
        self.assertEqual(invalid, ['not-an-address'])

    def test_emailed_reply_is_copied_and_recorded(self):
        self._post(send_email='1', cc='manager@dental.example.com, it@dental.example.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['office@dental.example.com'])
        self.assertEqual(sorted(mail.outbox[0].cc), ['it@dental.example.com', 'manager@dental.example.com'])
        comment = TicketComment.objects.get(ticket=self.ticket)
        self.assertEqual(comment.cc_emails, ['manager@dental.example.com', 'it@dental.example.com'])
        html = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('Cc: manager@dental.example.com, it@dental.example.com', html)

    def test_cc_without_email_or_with_bad_address_posts_nothing(self):
        for extra in ({'cc': 'manager@dental.example.com'}, {'send_email': '1', 'cc': 'nope'}):
            with self.subTest(extra):
                self._post(**extra)
                self.assertFalse(TicketComment.objects.filter(ticket=self.ticket).exists())
                self.assertEqual(len(mail.outbox), 0)
                self.assertTrue(TicketDraft.objects.filter(ticket=self.ticket, user=self.tech).exists())

    def test_ticket_cc_list_is_edited_by_technicians_only(self):
        url = f'/psa/t/{self.ticket.ticket_number}/cc/'
        self.client.post(url, {'cc': 'Manager@dental.example.com office@dental.example.com'})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.cc_emails, ['manager@dental.example.com'])  # requester left out
        self.client.post(url, {'cc': 'bad address'})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.cc_emails, ['manager@dental.example.com'])
        self.assertEqual(self._login(self.customer).post(url, {'cc': ''}).status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.cc_emails, ['manager@dental.example.com'])

    def test_inbound_cc_is_merged_without_the_requester_or_our_mailbox(self):
        added = merge_cc(self.ticket, ['office@dental.example.com', 'support@msp.test', 'boss@dental.example.com'],
                         exclude={'support@msp.test'})
        self.assertEqual(added, ['boss@dental.example.com'])
        self.assertEqual(merge_cc(self.ticket, ['boss@dental.example.com']), [])

    def test_customers_cannot_cc_from_the_portal_reply(self):
        self._post(client=self._login(self.customer), send_email='1', cc='friend@elsewhere.example.com')
        comment = TicketComment.objects.get(ticket=self.ticket)
        self.assertEqual(comment.cc_emails, [])


class SecureMessageTests(_Base):
    def _send(self, **extra):
        return self._post(send_email='1', secure_message=SECRET, **extra)

    def _link(self):
        return re.search(r'/core/secret/([A-Za-z0-9_-]+)/', mail.outbox[0].body).group(0)

    def test_secret_is_sealed_emailed_as_a_link_and_never_shown_on_the_ticket(self):
        self._send()
        comment = TicketComment.objects.get(ticket=self.ticket)
        note = comment.secure_note
        self.assertIsNotNone(note)
        self.assertTrue(note.link_only and note.read_once)
        self.assertNotIn(SECRET, note.encrypted_content)
        self.assertEqual(note.get_content(), SECRET)
        self.assertNotIn(SECRET, comment.body)
        self.assertIn('/core/secret/', mail.outbox[0].body)
        self.assertNotIn(SECRET, mail.outbox[0].body)
        # The stored copy of the sent e-mail no longer carries the link.
        stored = EmailMessage.objects.get(ticket=self.ticket, direction='out')
        self.assertNotIn('/core/secret/', stored.body_text)
        staff_page = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('sent by e-mail, not opened yet', staff_page)
        self.assertNotIn(SECRET, staff_page)
        portal = self._login(self.customer).get(f'/portal/tickets/{self.ticket.ticket_number}/').content.decode()
        self.assertNotIn(SECRET, portal)

    def test_link_opens_behind_a_button_once(self):
        self._send()
        link = self._link()
        anon = Client()
        first = anon.get(link)
        self.assertContains(first, 'You have a secure message')
        self.assertNotContains(first, SECRET)
        note = SecureNote.objects.get()
        self.assertEqual(note.read_count, 0)  # a scanner's GET doesn't use it up
        self.assertContains(anon.post(link), SECRET)
        self.assertNotContains(Client().post(link), SECRET)
        page = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('opened by the recipient', page)

    def test_secure_message_needs_an_emailed_reply_without_cc(self):
        for extra in ({'secure_message': SECRET}, {'send_email': '1', 'secure_message': SECRET,
                                                   'cc': 'x@dental.example.com'}):
            with self.subTest(extra):
                self._post(**extra)
                self.assertFalse(SecureNote.objects.exists())
                self.assertFalse(TicketComment.objects.filter(ticket=self.ticket).exists())

    def test_internal_note_never_creates_a_secure_message(self):
        self._post(is_internal='1', secure_message=SECRET, send_email='1')
        self.assertFalse(SecureNote.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_failed_email_withdraws_the_message(self):
        with patch('psa.email_outbound.send_ticket_reply', side_effect=RuntimeError('smtp down')):
            self._send()
        note = SecureNote.objects.get()
        self.assertTrue(note.is_deleted)
        page = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('withdrawn', page)

    def test_scrubbing_leaves_other_text(self):
        text = 'See https://desk.example.com/core/secret/AbC_123-x/ thanks'
        self.assertEqual(scrub_secret_links(text),
                         'See [secure message link — sent to the recipient only] thanks')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SampleConversationTests(TestCase):
    def test_samples_are_created_once_and_cover_every_state(self):
        from accounts.models import Membership, Role
        from psa.activity import decorate
        from psa.my_work import annotate_activity
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        for slug, name in (('demo-globex', 'Globex'), ('demo-initech', 'Initech'), ('demo-acme', 'ACME Industries'),
                           ('demo', 'Demo Company'), ('acme-corporation', 'Acme Corporation')):
            Organization.objects.create(name=name, slug=slug)
        editor = User.objects.create_user('demo.editor', 'editor@acme.example.com', 'pw-editor-654!')
        Membership.objects.create(user=editor, organization=Organization.objects.get(slug='acme-corporation'),
                                  role=Role.EDITOR, is_active=True)
        su = _make_msp_tech(User.objects.create_superuser('admin654', 'admin@msp.test', 'pw-654-admin!'))
        call_command('psa_seed_sample_conversations', stdout=StringIO())
        call_command('psa_seed_sample_conversations', stdout=StringIO())
        self.assertEqual(Ticket.objects.count(), 10)
        # Customers opened them, not the technician.
        self.assertFalse(Ticket.objects.filter(created_by=su).exists())
        self.assertTrue(Ticket.objects.filter(created_by=editor).exists())
        self.assertTrue(User.objects.filter(username='demo.dana.whitfield', profile__user_type='org_user').exists())
        self.assertFalse(User.objects.get(username='demo.dana.whitfield').has_usable_password())
        states = {secure_status(c.secure_note)['state'] for c in TicketComment.objects.exclude(secure_note=None)}
        self.assertEqual(states, {'opened', 'waiting', 'expired'})
        steps = {t.next_step for t in decorate(annotate_activity(Ticket.objects.all()).select_related('status'))}
        self.assertEqual(steps, {'reply', 'customer', 'follow_up', 'vendor', 'closed'})
        self.assertTrue(TicketComment.objects.filter(is_internal=True).exists())
        self.assertTrue(TicketComment.objects.exclude(parent_comment=None).exists())
        self.assertTrue(TicketComment.objects.exclude(cc_emails=[]).exists())
        from psa.models import TicketAttachment
        self.assertEqual(TicketAttachment.objects.count(), 3)
        c = Client()
        c.force_login(su)
        listing = c.get(reverse('psa:ticket_list')).content.decode()
        for label in ('Needs reply', 'Follow up', 'Waiting on vendor', 'Technician reply', 'File attached'):
            self.assertIn(label, listing)
        for t in Ticket.objects.all():
            with self.subTest(t.subject):
                resp = c.get(f'/psa/t/{t.ticket_number}/')
                self.assertEqual(resp.status_code, 200)
                self.assertIn('ticketLastActivity', resp.content.decode())
