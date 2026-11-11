"""Phase 12: two-way secure messaging. The requester answers a sealed
one-time message (v3.17.654) securely — from the opened message page or the
portal; staff read replies behind a logged Reveal; the text is sealed at
rest, never in e-mail or notifications, and erased after retention."""
import re
from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa.models import (ClientPSASettings, Queue, Ticket, TicketComment, TicketPriority, TicketSecureReply,
                        TicketStatus, TicketType, TicketWatcher)
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech, _setup_seed
from psa import ticket_secure

SECRET_REPLY = 'My new VPN PIN is 7741-Q'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SecureReplyTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='Example Dental', slug='ex-dental-sr')
        ClientPSASettings.objects.update_or_create(organization=self.org,
                                                   defaults={'portal_enabled': True, 'enabled': True})
        self.tech = _make_msp_tech(User.objects.create_user('tech-sr', password='pw', email='t@msp.test'))
        Membership.objects.create(user=self.tech, organization=self.org, role=Role.OWNER, is_active=True)
        self.watcher = _make_msp_tech(User.objects.create_user('watch-sr', password='pw', email='w@msp.test'))
        self.customer = User.objects.create_user('cust-sr', password='pw', email='office@dental.example.com')
        Membership.objects.create(user=self.customer, organization=self.org, role=Role.EDITOR, is_active=True)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='VPN locked', description='Locked out',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.filter(slug='new').first(),
            source='email', requester_email='office@dental.example.com', visibility='client',
            client_can_view=True, assigned_to=self.tech)
        TicketWatcher.objects.create(ticket=self.ticket, user=self.watcher)

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _send_secure_message(self):
        self._login(self.tech).post(f'/psa/t/{self.ticket.ticket_number}/comment/', {
            'body': 'Your temporary password is in the secure message.', 'send_email': '1',
            'secure_message': 'Temp-Pass-1!'})
        link = re.search(r'/core/secret/[A-Za-z0-9_-]+/', mail.outbox[-1].body).group(0)
        mail.outbox.clear()
        return link

    def _open_and_get_reply_url(self, link):
        page = Client().post(link).content.decode()
        m = re.search(r'action="(/psa/secure-reply/[^"]+/)"', page)
        self.assertIsNotNone(m, 'the opened message offers a secure reply form')
        return m.group(1)

    def test_requester_replies_from_the_opened_message(self):
        link = self._send_secure_message()
        reply_url = self._open_and_get_reply_url(link)
        r = Client().post(reply_url, {'reply': SECRET_REPLY})
        self.assertContains(r, 'Secure reply sent')
        reply = TicketSecureReply.objects.get(ticket=self.ticket)
        self.assertEqual(reply.via, 'link')
        self.assertEqual(reply.author_email, 'office@dental.example.com')
        self.assertIsNotNone(reply.in_reply_to)
        # Sealed at rest; readable through the model.
        raw = TicketSecureReply.objects.filter(pk=reply.pk).values_list('body', flat=True).get()
        self.assertNotIn('7741', raw)
        self.assertEqual(reply.get_body(), SECRET_REPLY)
        self.assertEqual(reply.expires_at.date(), (timezone.now() + timedelta(days=7)).date())

    def test_content_is_never_in_email_notifications_comments_or_audit(self):
        link = self._send_secure_message()
        Client().post(self._open_and_get_reply_url(link), {'reply': SECRET_REPLY})
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['t@msp.test', 'w@msp.test'])
        for m in mail.outbox:
            self.assertIn('secure reply', m.subject)
            self.assertNotIn('7741', m.body + m.subject)
        for c in TicketComment.objects.filter(ticket=self.ticket):
            self.assertNotIn('7741', c.body)
        note = TicketComment.objects.filter(ticket=self.ticket, is_system=True, is_internal=True).last()
        self.assertIn('Secure reply received', note.body)
        for a in AuditLog.objects.all():
            self.assertNotIn('7741', f'{a.description} {a.extra_data}')
        self.assertTrue(AuditLog.objects.filter(object_type='psa.TicketSecureReply',
                                                extra_data__event='ticket_secure_reply').exists())

    def test_staff_see_reply_status_and_reveal_is_logged(self):
        link = self._send_secure_message()
        Client().post(self._open_and_get_reply_url(link), {'reply': SECRET_REPLY})
        reply = TicketSecureReply.objects.get()
        c = self._login(self.tech)
        page = c.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('Secure replies and messages', page)
        self.assertIn('Not read yet', page)
        self.assertNotIn('7741', page)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/secure-replies/{reply.pk}/reveal/')
        self.assertContains(r, SECRET_REPLY)
        self.assertEqual(r['Cache-Control'], 'no-store')
        reply.refresh_from_db()
        self.assertEqual((reply.view_count, reply.first_viewed_by), (1, self.tech))
        self.assertTrue(AuditLog.objects.filter(object_type='psa.TicketSecureReply', action='read',
                                                user=self.tech).exists())
        self.assertEqual(c.get(f'/psa/t/{self.ticket.ticket_number}/secure-replies/{reply.pk}/reveal/').status_code,
                         405)

    def test_customers_cannot_reveal_and_portal_shows_only_metadata(self):
        c = self._login(self.customer)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/secure-reply/', {'reply': SECRET_REPLY})
        self.assertEqual(r.status_code, 302)
        reply = TicketSecureReply.objects.get()
        self.assertEqual((reply.via, reply.author), ('portal', self.customer))
        page = c.get(f'/portal/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('Your secure replies', page)
        self.assertNotIn('7741', page)
        r = c.post(f'/psa/t/{self.ticket.ticket_number}/secure-replies/{reply.pk}/reveal/')
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn('7741', r.content.decode())

    def test_bad_expired_or_revoked_tokens_are_refused(self):
        link = self._send_secure_message()
        reply_url = self._open_and_get_reply_url(link)
        self.assertEqual(Client().post('/psa/secure-reply/not-a-token/', {'reply': 'x'}).status_code, 410)
        token = reply_url.rstrip('/').rsplit('/', 1)[1]
        note = ticket_secure.note_for_reply_token(token)
        self.assertIsNotNone(note)
        # Regenerating the message link voids the reply token.
        note.generate_access_token()
        note.link_issued_at = note.link_issued_at + timedelta(seconds=5)
        note.save()
        self.assertEqual(Client().post(reply_url, {'reply': 'x'}).status_code, 410)
        from unittest import mock
        with mock.patch('psa.ticket_secure.REPLY_TOKEN_MAX_AGE', -1):  # expired
            self.assertIsNone(ticket_secure.note_for_reply_token(ticket_secure.issue_reply_token(note)))
        self.assertFalse(TicketSecureReply.objects.exists())

    def test_reply_limit_per_message(self):
        link = self._send_secure_message()
        reply_url = self._open_and_get_reply_url(link)
        for i in range(ticket_secure.MAX_REPLIES_PER_MESSAGE):
            Client().post(reply_url, {'reply': f'part {i}'})
        self.assertEqual(Client().post(reply_url, {'reply': 'one more'}).status_code, 410)
        self.assertEqual(TicketSecureReply.objects.count(), ticket_secure.MAX_REPLIES_PER_MESSAGE)

    def test_retention_erases_the_text(self):
        reply = ticket_secure.create_secure_reply(ticket=self.ticket, text=SECRET_REPLY, via='portal',
                                                  author=self.customer, author_email=self.customer.email)
        TicketSecureReply.objects.filter(pk=reply.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        reply.refresh_from_db()
        self.assertEqual(reply.state, 'expired')
        r = self._login(self.tech).post(f'/psa/t/{self.ticket.ticket_number}/secure-replies/{reply.pk}/reveal/')
        self.assertNotContains(r, '7741')
        call_command('psa_purge_secure_replies', stdout=StringIO())
        reply.refresh_from_db()
        self.assertEqual((reply.body, reply.state), ('', 'erased'))
        self.assertIsNotNone(reply.purged_at)
