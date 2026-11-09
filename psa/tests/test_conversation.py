"""
Ticket conversation (psa/conversation.py + templates/psa/_conversation.html).

Sender role comes from provenance — trusted authorship, customer membership
and the channel a message arrived on — never from an email address alone.
Visibility (internal vs public) is a separate axis, enforced server-side.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, UserProfile, UserType
from core.models import Organization
from psa.conversation import (
    ROLE_CUSTOMER, ROLE_SYSTEM, ROLE_TECHNICIAN, ROLE_UNKNOWN,
    build_conversation, classify_opening, classify_sender,
)
from psa.models import (
    Queue, Ticket, TicketAttachment, TicketComment, TicketPriority, TicketStatus, TicketType,
)
from psa.templatetags.ticket_conversation import conversation_body
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed,
)


def _ticket(org, **kw):
    defaults = dict(
        organization=org, subject='Printer offline', client_can_view=True,
        queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
        ticket_type=TicketType.objects.first(),
        status=TicketStatus.objects.filter(slug='new').first(),
    )
    defaults.update(kw)
    return Ticket.objects.create(**defaults)


def _customer_user(username, email, org):
    u = User.objects.create_user(username, email, 'pw-conv-123',
                                 first_name='Dana', last_name='Customer')
    profile, _ = UserProfile.objects.get_or_create(user=u)
    profile.user_type = UserType.ORG_USER
    profile.save()
    Membership.objects.create(user=u, organization=org, role=Role.READONLY, is_active=True)
    return u


class SenderClassificationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        cls.org = Organization.objects.create(name='Conv Co', slug='conv-co')
        cls.tech = _make_msp_tech(User.objects.create_user(
            'conv_tech', 'tech@msp.test', 'pw-conv-123', first_name='Jordan', last_name='Tech'))
        cls.customer = _customer_user('conv_cust', 'dana@customer.test', cls.org)
        cls.outsider = User.objects.create_user('conv_out', 'out@else.test', 'pw-conv-123')
        cls.ticket = _ticket(cls.org, requester_email='requester@customer.test')

    def _c(self, **kw):
        return TicketComment.objects.create(ticket=self.ticket, body=kw.pop('body', 'x'), **kw)

    def test_staff_user_is_technician(self):
        s = classify_sender(self._c(author=self.tech), self.ticket)
        self.assertEqual(s.role, ROLE_TECHNICIAN)
        self.assertEqual(s.label, 'Technician')
        self.assertEqual(s.name, 'Jordan Tech')

    def test_superuser_is_technician(self):
        su = User.objects.create_superuser('conv_su', 'su@msp.test', 'pw')
        self.assertEqual(classify_sender(self._c(author=su), self.ticket).role, ROLE_TECHNICIAN)

    def test_portal_customer_with_django_user_is_customer(self):
        s = classify_sender(self._c(author=self.customer, source='portal'), self.ticket)
        self.assertEqual(s.role, ROLE_CUSTOMER)
        self.assertEqual(s.label, 'Customer')
        self.assertEqual(s.name, 'Dana Customer')
        self.assertEqual(s.via, 'portal')

    def test_customer_user_posting_from_ticket_page_is_customer(self):
        # Customer users can reach /psa/t/<n>/ (manual source) — still customers.
        s = classify_sender(self._c(author=self.customer), self.ticket)
        self.assertEqual(s.role, ROLE_CUSTOMER)

    def test_user_without_staff_or_membership_is_neutral(self):
        s = classify_sender(self._c(author=self.outsider), self.ticket)
        self.assertEqual(s.role, ROLE_UNKNOWN)
        self.assertEqual(s.label, '')

    def test_inbound_email_from_unknown_address_is_neutral(self):
        s = classify_sender(self._c(source='email', author_name='Who Knows',
                                    author_email='stranger@nowhere.test'), self.ticket)
        self.assertEqual(s.role, ROLE_UNKNOWN)
        self.assertEqual(s.name, 'Who Knows')
        self.assertEqual(s.via, 'email')

    def test_inbound_email_from_staff_address_is_not_technician(self):
        # Inbound mail is unauthenticated: a From header naming a tech's
        # address is no proof a tech wrote it.
        s = classify_sender(self._c(source='email', author_email='TECH@msp.test'), self.ticket)
        self.assertNotEqual(s.role, ROLE_TECHNICIAN)
        self.assertEqual(s.role, ROLE_UNKNOWN)

    def test_inbound_email_from_requester_or_member_is_customer(self):
        for addr in ('requester@customer.test', 'Dana@Customer.test'):
            s = classify_sender(self._c(source='email', author_email=addr), self.ticket)
            self.assertEqual(s.role, ROLE_CUSTOMER, addr)

    def test_inbound_email_from_ticket_contact_is_customer(self):
        from assets.models import Contact
        contact = Contact.objects.create(organization=self.org, first_name='Aaron',
                                         last_name='Dock', email='aaron@customer.test')
        t = _ticket(self.org, contact=contact)
        c = TicketComment.objects.create(ticket=t, body='x', source='email',
                                         author_email='aaron@customer.test')
        self.assertEqual(classify_sender(c, t).role, ROLE_CUSTOMER)

    def test_portal_row_whose_author_was_deleted_is_customer(self):
        s = classify_sender(self._c(source='portal', author_name='Gone User'), self.ticket)
        self.assertEqual(s.role, ROLE_CUSTOMER)
        self.assertEqual(s.name, 'Gone User')

    def test_legacy_row_without_author_is_neutral(self):
        s = classify_sender(self._c(author_name='Old Import'), self.ticket)
        self.assertEqual(s.role, ROLE_UNKNOWN)
        self.assertEqual(s.name, 'Old Import')
        s = classify_sender(self._c(), self.ticket)
        self.assertEqual((s.role, s.name), (ROLE_UNKNOWN, 'Unknown sender'))

    def test_partner_sync_is_neutral(self):
        s = classify_sender(self._c(source='partner', author_name='Partner MSP'), self.ticket)
        self.assertEqual(s.role, ROLE_UNKNOWN)

    def test_system_event(self):
        s = classify_sender(self._c(author=self.tech, is_system=True, is_internal=True,
                                    body='Status changed: New → In Progress'), self.ticket)
        self.assertEqual(s.role, ROLE_SYSTEM)

    def test_role_is_independent_of_visibility(self):
        s = classify_sender(self._c(author=self.tech, is_internal=True), self.ticket)
        self.assertEqual(s.role, ROLE_TECHNICIAN)

    def test_opening_request(self):
        self.assertEqual(classify_opening(_ticket(self.org, created_by=self.customer)).role,
                         ROLE_CUSTOMER)
        self.assertEqual(classify_opening(_ticket(self.org, created_by=self.tech)).role,
                         ROLE_TECHNICIAN)
        self.assertEqual(classify_opening(_ticket(
            self.org, source='email', requester_email='new@customer.test')).role, ROLE_CUSTOMER)
        self.assertEqual(classify_opening(_ticket(self.org, source='manual')).role, ROLE_UNKNOWN)


class BuildConversationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        cls.org = Organization.objects.create(name='Build Co', slug='build-co')
        cls.tech = _make_msp_tech(User.objects.create_user('b_tech', 'bt@msp.test', 'pw'))
        cls.ticket = _ticket(cls.org, description='It is broken')
        cls.note = TicketComment.objects.create(
            ticket=cls.ticket, author=cls.tech, body='NOTE-BODY secret', is_internal=True)
        cls.reply = TicketComment.objects.create(
            ticket=cls.ticket, author=cls.tech, body='Public answer', parent_comment=cls.note)
        cls.event = TicketComment.objects.create(
            ticket=cls.ticket, author=cls.tech, body='Status changed', is_system=True)

    def test_public_view_drops_internal_rows_and_parent_preview(self):
        # Even when handed every comment, the public build drops the note
        # and does not quote it from the public reply.
        entries = build_conversation(self.ticket, list(self.ticket.comments.all()),
                                     include_internal=False)
        self.assertEqual([e.kind for e in entries], ['message', 'message', 'event'])
        self.assertTrue(entries[0].is_opening)
        reply = entries[1]
        self.assertEqual(reply.id, self.reply.pk)
        self.assertIsNone(reply.reply_to)
        self.assertNotIn('NOTE-BODY', repr([e.body for e in entries]))

    def test_staff_view_quotes_internal_parent(self):
        entries = build_conversation(self.ticket, list(self.ticket.comments.all()),
                                     include_internal=True)
        kinds = [e.kind for e in entries]
        self.assertEqual(kinds, ['message', 'note', 'message', 'event'])
        self.assertEqual(entries[2].reply_to['id'], self.note.pk)
        self.assertTrue(entries[2].reply_to['is_internal'])


class ConversationBodyFilterTests(TestCase):

    def test_escapes_and_keeps_code(self):
        html = conversation_body('<b>hi</b>\nrun `ls -l`\n```\nERR <x>\n  at line 2\n```\nbye')
        self.assertIn('&lt;b&gt;hi&lt;/b&gt;', html)
        self.assertIn('<code>ls -l</code>', html)
        self.assertIn('<pre class="tc-code"><code>ERR &lt;x&gt;\n  at line 2</code></pre>', html)
        self.assertIn('bye', html)
        self.assertNotIn('<b>', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StaffTicketPageConversationTests(TestCase):

    @classmethod
    def setUpClass(cls):
        # MEDIA_ROOT must be overridden before setUpTestData saves files.
        cls._media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Staff Conv Co', slug='staff-conv')
        _enable_psa_for(cls.org)
        cls.tech = _make_msp_tech(User.objects.create_user(
            'sc_tech', 'sc@msp.test', 'pw', first_name='Jordan', last_name='Tech'))
        Membership.objects.create(user=cls.tech, organization=cls.org, role=Role.OWNER,
                                  is_active=True)
        cls.customer = _customer_user('sc_cust', 'sc@customer.test', cls.org)
        Membership.objects.filter(user=cls.customer).update(role=Role.ADMIN)
        cls.ticket = _ticket(cls.org, description='Opening request text')
        TicketComment.objects.create(ticket=cls.ticket, author=cls.customer,
                                     body='Customer says hello', source='portal')
        cls.note = TicketComment.objects.create(
            ticket=cls.ticket, author=cls.tech, body='Private triage NOTE-XYZ', is_internal=True)
        TicketAttachment.objects.create(
            ticket=cls.ticket, comment=cls.note, filename='triage-dump.txt',
            file=SimpleUploadedFile('triage-dump.txt', b'secret'))
        TicketComment.objects.create(
            ticket=cls.ticket, author=cls.tech, body='Public fix applied', parent_comment=cls.note)

    def _web(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s['2fa_prompted'] = True
        s.save()
        return c

    def url(self):
        return f'/psa/t/{self.ticket.ticket_number}/'

    def test_staff_sees_roles_note_and_reply_context(self):
        r = self._web(self.tech).get(self.url())
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('ticket_conversation.css', html)
        self.assertIn('tc-msg--customer', html)
        self.assertIn('tc-msg--technician', html)
        self.assertIn('Internal note · staff only', html)
        self.assertIn('Private triage NOTE-XYZ', html)
        self.assertIn('triage-dump.txt', html)
        self.assertIn('Replying to <strong>Jordan Tech</strong>', html)
        self.assertIn('Opening request text', html)

    def test_customer_user_on_staff_page_gets_no_private_content(self):
        r = self._web(self.customer).get(self.url())
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Public fix applied', html)
        self.assertNotIn('NOTE-XYZ', html)
        self.assertNotIn('triage-dump', html)
        self.assertNotIn('Internal note · staff only', html)
        self.assertNotIn('tc-replyto', html)

    def test_post_comment_records_parent(self):
        r = self._web(self.tech).post(f'/psa/t/{self.ticket.ticket_number}/comment/', {
            'body': 'Threaded tech reply', 'parent_id': str(self.note.pk)})
        self.assertEqual(r.status_code, 302)
        c = TicketComment.objects.get(body='Threaded tech reply')
        self.assertEqual(c.parent_comment_id, self.note.pk)

    def test_customer_cannot_thread_under_internal_note(self):
        self._web(self.customer).post(f'/psa/t/{self.ticket.ticket_number}/comment/', {
            'body': 'Customer threaded attempt', 'parent_id': str(self.note.pk)})
        c = TicketComment.objects.filter(body='Customer threaded attempt').first()
        self.assertIsNotNone(c, 'customer post was refused')
        self.assertIsNone(c.parent_comment_id)
