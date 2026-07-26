"""
PSA Phase 10 — Email-to-Ticket pipeline tests.

Split out of the legacy 5,465-line `psa/tests.py` in v3.17.192. Covers
all four sub-phases:
  10.1  Threading by Message-ID / In-Reply-To / References
  10.2  Body cleanup (signature/quote strip), HTML sanitize, attachments
  10.3  Auto-responder + DMARC + spam keyword gating; routing rules
  10.4  Outbound threading + per-ticket conversation panel

Helper classes (`_FakeIMAP`, `_EmailPollerSetup`, `_build_raw_email`)
are local to this module — they're only used by Phase 10.
"""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import Ticket

from psa.tests._base import (
    TEST_MIDDLEWARE,
    _setup_seed,
    _enable_psa_global,
    _enable_psa_for,
)


# ---------------------------------------------------------------------------
# Phase 10.1 — Email-to-ticket threading via Message-ID
# ---------------------------------------------------------------------------

class _FakeIMAP:
    """
    Stand-in for imaplib.IMAP4_SSL. Holds a list of (uid, raw_bytes)
    messages and answers the small subset of methods the poller calls.
    Records `seen_uids` so tests can assert the poller marked things read.
    """
    def __init__(self, messages):
        self._messages = list(messages)
        self.seen_uids = []

    # imaplib API surface used by the poller
    def login(self, *a, **kw):  # pragma: no cover - trivial
        return ('OK', [b''])

    def select(self, folder):
        return ('OK', [str(len(self._messages)).encode()])

    def search(self, charset, criterion):
        ids = b' '.join(uid for uid, _ in self._messages)
        return ('OK', [ids])

    def fetch(self, uid, parts):
        for u, raw in self._messages:
            if u == uid:
                return ('OK', [(b'%s (RFC822 {%d}' % (u, len(raw)), raw), b')'])
        return ('NO', [])

    def store(self, uid, flag, value):
        self.seen_uids.append((uid, flag, value))
        return ('OK', [b''])

    def logout(self):
        return ('BYE', [b''])


def _build_raw_email(*, message_id, from_addr, to_addr, subject,
                    body='Hello world', in_reply_to=None, references=None):
    """Compose a minimal RFC 822 byte string for the fake IMAP server."""
    headers = [
        f'From: {from_addr}',
        f'To: {to_addr}',
        f'Subject: {subject}',
        f'Message-ID: {message_id}',
        'Content-Type: text/plain; charset=utf-8',
        'MIME-Version: 1.0',
    ]
    if in_reply_to:
        headers.append(f'In-Reply-To: {in_reply_to}')
    if references:
        headers.append(f'References: {references}')
    return ('\r\n'.join(headers) + '\r\n\r\n' + body).encode('utf-8')


class _EmailPollerSetup:
    """Mixin: builds two orgs, two configs, and a base ticket per org."""

    @classmethod
    def _seed_psa(cls):
        _setup_seed()

    def _make_org_with_config(self, slug):
        from psa.models import EmailIngestionConfig, Queue, TicketPriority, TicketType
        org = Organization.objects.create(name=slug.upper(), slug=slug)
        cfg = EmailIngestionConfig.objects.create(
            organization=org,
            name=f'{slug}-helpdesk',
            imap_host='imap.example.com',
            username=f'help@{slug}.example.com',
            default_queue=Queue.objects.first(),
            default_priority=TicketPriority.objects.first(),
            default_type=TicketType.objects.first(),
        )
        cfg.set_password('imap-pw')
        cfg.save()
        return org, cfg

    def _make_ticket(self, org, **overrides):
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType
        defaults = dict(
            organization=org,
            subject='Existing ticket',
            description='Pre-existing',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            source='email',
            visibility='client',
            client_can_view=True,
            requester_email='customer@example.com',
        )
        defaults.update(overrides)
        return Ticket.objects.create(**defaults)


class EmailThreadingByInReplyToTests(TestCase, _EmailPollerSetup):
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgthread')
        self.ticket = self._make_ticket(self.org)
        # Seed an inbound EmailMessage representing the original customer email
        from psa.models import EmailMessage
        self.original = EmailMessage.objects.create(
            organization=self.org,
            ticket=self.ticket,
            ingestion_config=self.cfg,
            direction='in',
            message_id='<original-12345@example.com>',
            from_email='customer@example.com',
            subject='Original',
        )
        self.ticket.last_inbound_message_id = '<original-12345@example.com>'
        self.ticket.save(update_fields=['last_inbound_message_id'])

    def _run_poll_with(self, raw):
        from psa.management.commands import psa_poll_email
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original
        return fake

    def test_in_reply_to_threads_to_existing_ticket(self):
        from psa.models import EmailMessage, TicketComment
        raw = _build_raw_email(
            message_id='<reply-67890@example.com>',
            from_addr='customer@example.com', to_addr='help@orgthread.example.com',
            subject='no token here at all',
            in_reply_to='<original-12345@example.com>',
            body='Thanks, problem persists.',
        )
        self._run_poll_with(raw)

        # Existing ticket got a new comment
        comments = TicketComment.objects.filter(ticket=self.ticket)
        self.assertEqual(comments.count(), 1)
        self.assertIn('problem persists', comments.first().body)
        # No new ticket created
        self.assertEqual(Ticket.objects.filter(organization=self.org).count(), 1)
        # Inbound EmailMessage row persisted
        self.assertTrue(EmailMessage.objects.filter(message_id='<reply-67890@example.com>').exists())
        # last_inbound_message_id updated
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.last_inbound_message_id, '<reply-67890@example.com>')


class EmailThreadingByReferencesChainTests(TestCase, _EmailPollerSetup):
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgrefs')
        self.ticket = self._make_ticket(self.org)
        from psa.models import EmailMessage
        EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, ingestion_config=self.cfg,
            direction='in', message_id='<root-aaa@example.com>',
        )

    def test_references_chain_threads_when_in_reply_to_unknown(self):
        from psa.management.commands import psa_poll_email
        from psa.models import TicketComment
        raw = _build_raw_email(
            message_id='<grandchild@example.com>',
            from_addr='customer@example.com', to_addr='help@orgrefs.example.com',
            subject='Re: something',
            # In-Reply-To points to a Message-ID we never saw, but References
            # contains the original Message-ID that we DO have on file.
            in_reply_to='<unknown-middle@example.com>',
            references='<root-aaa@example.com> <unknown-middle@example.com>',
            body='Tail of the chain.',
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        self.assertEqual(TicketComment.objects.filter(ticket=self.ticket).count(), 1)
        self.assertEqual(Ticket.objects.filter(organization=self.org).count(), 1)


class EmailThreadingFallbackToSubjectTests(TestCase, _EmailPollerSetup):
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgsubj')
        self.ticket = self._make_ticket(self.org)

    def test_subject_regex_still_matches_legacy_replies_without_headers(self):
        from psa.management.commands import psa_poll_email
        from psa.models import TicketComment
        # Legacy inbound — no In-Reply-To, no References, but subject has the
        # PSA-YYYY-NNNNNN token. The poller must still attach to the ticket.
        raw = _build_raw_email(
            message_id='<no-prior-record@example.com>',
            from_addr='customer@example.com', to_addr='help@orgsubj.example.com',
            subject=f'Re: [{self.ticket.ticket_number}] follow up',
            body='Legacy reply with no threading headers.',
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        self.assertEqual(TicketComment.objects.filter(ticket=self.ticket).count(), 1)


class EmailThreadingCrossOrgIsolationTests(TestCase, _EmailPollerSetup):
    """
    Org A's Message-ID must not match when org B receives a reply that
    happens to use the same value as In-Reply-To. Same Message-ID across
    tenants is allowed; the (organization, message_id) unique constraint
    + the org filter on the lookup keep them isolated.
    """
    def setUp(self):
        self._seed_psa()
        self.orgA, self.cfgA = self._make_org_with_config('orga')
        self.orgB, self.cfgB = self._make_org_with_config('orgb')
        self.ticketA = self._make_ticket(self.orgA, subject='A ticket')
        from psa.models import EmailMessage
        # Both orgs happen to have an EmailMessage with the same Message-ID
        # value (legitimate — Message-IDs aren't globally unique across mail
        # servers). The threading lookup must respect organization.
        EmailMessage.objects.create(
            organization=self.orgA, ticket=self.ticketA,
            direction='in', message_id='<collision@example.com>',
        )

    def test_org_b_inbound_does_not_match_org_a_message_id(self):
        from psa.management.commands import psa_poll_email
        raw = _build_raw_email(
            message_id='<orgb-new@example.com>',
            from_addr='other@example.com', to_addr='help@orgb.example.com',
            subject='no ticket token',
            in_reply_to='<collision@example.com>',
            body='If isolation is broken this lands on org A.',
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfgB.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        # org A still has exactly the seeded ticket with no new comments.
        from psa.models import TicketComment
        self.assertEqual(Ticket.objects.filter(organization=self.orgA).count(), 1)
        self.assertEqual(TicketComment.objects.filter(ticket=self.ticketA).count(), 0)
        # org B got a brand-new ticket — the In-Reply-To went unmatched.
        self.assertEqual(Ticket.objects.filter(organization=self.orgB).count(), 1)


class EmailThreadingNewTicketTests(TestCase, _EmailPollerSetup):
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgnew')

    def test_unknown_inbound_creates_ticket_and_emailmessage(self):
        from psa.management.commands import psa_poll_email
        from psa.models import EmailMessage
        raw = _build_raw_email(
            message_id='<fresh@example.com>',
            from_addr='alice@customer.example', to_addr='help@orgnew.example.com',
            subject='Printer down',
            body='Please send help.',
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        tickets = Ticket.objects.filter(organization=self.org)
        self.assertEqual(tickets.count(), 1)
        t = tickets.first()
        self.assertEqual(t.subject, 'Printer down')
        self.assertEqual(t.requester_email, 'alice@customer.example')

        em = EmailMessage.objects.get(organization=self.org, message_id='<fresh@example.com>')
        self.assertEqual(em.ticket_id, t.id)
        self.assertEqual(em.direction, 'in')
        self.assertEqual(em.from_email, 'alice@customer.example')
        self.assertIn('Please send help', em.body_text)
        # Cache field is set on the new ticket.
        self.assertEqual(t.last_inbound_message_id, '<fresh@example.com>')


# ---------------------------------------------------------------------------
# Phase 10.2 — Body cleanup helpers (pure functions; no IMAP needed)
# ---------------------------------------------------------------------------

class HtmlSanitizeTests(TestCase):
    def test_strips_script_and_style(self):
        from psa.email_parsing import sanitize_html
        result = sanitize_html('<p>ok</p><script>alert(1)</script><style>p{color:red}</style>')
        self.assertNotIn('<script', result)
        self.assertNotIn('<style', result)
        self.assertIn('<p>ok</p>', result)

    def test_strips_iframe_object_embed(self):
        from psa.email_parsing import sanitize_html
        result = sanitize_html(
            '<p>hi</p><iframe src=evil></iframe>'
            '<object data=x.swf></object><embed src=y.swf>'
        )
        self.assertNotIn('iframe', result.lower())
        self.assertNotIn('object', result.lower())
        self.assertNotIn('embed', result.lower())

    def test_strips_inline_event_handlers(self):
        from psa.email_parsing import sanitize_html
        result = sanitize_html('<a href="https://x.com" onclick="bad()">x</a>')
        self.assertNotIn('onclick', result)
        self.assertIn('href="https://x.com"', result)

    def test_strips_remote_images(self):
        from psa.email_parsing import sanitize_html
        # img is not in the allowlist; bleach drops it entirely (strip=True).
        result = sanitize_html('<p>hi</p><img src="https://tracker.example/p.gif">')
        self.assertNotIn('<img', result)
        self.assertIn('<p>hi</p>', result)

    def test_links_get_safe_attrs(self):
        from psa.email_parsing import sanitize_html
        result = sanitize_html('<a href="https://x.com">x</a>')
        self.assertIn('rel="noopener noreferrer"', result)
        self.assertIn('target="_blank"', result)

    def test_empty_input_returns_empty(self):
        from psa.email_parsing import sanitize_html
        self.assertEqual(sanitize_html(''), '')
        self.assertEqual(sanitize_html(None), '')


class SignatureStripTests(TestCase):
    def test_rfc3676_sentinel_cuts_signature(self):
        from psa.email_parsing import strip_signature
        body = 'Hello there.\n\n-- \nAlice\nWidget Co.'
        self.assertEqual(strip_signature(body), 'Hello there.')

    def test_sent_from_iphone_heuristic(self):
        from psa.email_parsing import strip_signature
        self.assertEqual(strip_signature('Hi.\n\nSent from my iPhone\n'), 'Hi.')

    def test_sent_from_android_heuristic(self):
        from psa.email_parsing import strip_signature
        self.assertEqual(strip_signature('Hi.\nSent from my Android device\n'), 'Hi.')

    def test_no_signature_returns_input_unchanged(self):
        from psa.email_parsing import strip_signature
        self.assertEqual(strip_signature('Just a message.'), 'Just a message.')

    def test_empty_input(self):
        from psa.email_parsing import strip_signature
        self.assertEqual(strip_signature(''), '')


class QuotedReplyStripTests(TestCase):
    def test_apple_gmail_on_wrote_header(self):
        from psa.email_parsing import strip_quoted_reply
        body = (
            'Yes that worked, thanks.\n\n'
            'On Tue, Mar 4, 2026 at 10:00 AM Alice <a@b> wrote:\n'
            '> Try restarting it.\n'
            '> Let me know.\n'
        )
        self.assertEqual(strip_quoted_reply(body), 'Yes that worked, thanks.')

    def test_outlook_original_message_block(self):
        from psa.email_parsing import strip_quoted_reply
        body = (
            'Reply text.\n\n'
            '-----Original Message-----\n'
            'From: Alice\n'
            'Sent: Tuesday\n'
        )
        self.assertEqual(strip_quoted_reply(body), 'Reply text.')

    def test_outlook_from_sent_to_subject_block(self):
        from psa.email_parsing import strip_quoted_reply
        body = (
            'Reply.\n\n'
            'From: Alice <a@b>\n'
            'Sent: Tuesday\n'
            'To: Bob\n'
            'Subject: RE: thing\n'
            'Hi Bob,\n'
        )
        self.assertEqual(strip_quoted_reply(body), 'Reply.')

    def test_bare_gt_prefix_block(self):
        from psa.email_parsing import strip_quoted_reply
        body = 'Got it.\n\n> previous content\n> here\n'
        self.assertEqual(strip_quoted_reply(body), 'Got it.')

    def test_no_quote_returns_unchanged(self):
        from psa.email_parsing import strip_quoted_reply
        self.assertEqual(strip_quoted_reply('Plain reply.'), 'Plain reply.')


def _build_raw_email_with_attachment(*, message_id, from_addr, to_addr, subject,
                                     body, attachments):
    """
    Build a multipart/mixed email with text + attachments. ``attachments`` is
    a list of (filename, mime, payload_bytes).
    """
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email import encoders

    root = MIMEMultipart('mixed')
    root['From'] = from_addr
    root['To'] = to_addr
    root['Subject'] = subject
    root['Message-ID'] = message_id
    root.attach(MIMEText(body, 'plain', 'utf-8'))
    for filename, mime, payload in attachments:
        maintype, _, subtype = mime.partition('/')
        part = MIMEBase(maintype, subtype)
        part.set_payload(payload)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=filename)
        root.attach(part)
    return root.as_bytes()


class AttachmentIngestTests(TestCase, _EmailPollerSetup):
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgatt')

    def _run_poll(self, raw):
        from psa.management.commands import psa_poll_email
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

    def test_allowlist_hit_creates_ticket_attachment(self):
        from psa.models import TicketAttachment
        raw = _build_raw_email_with_attachment(
            message_id='<att-ok@example.com>',
            from_addr='alice@example.com', to_addr='help@orgatt.example.com',
            subject='Logs attached',
            body='See attached.',
            attachments=[('error.log', 'text/plain', b'2026-05-01 ERROR boom')],
        )
        self._run_poll(raw)

        ticket = Ticket.objects.get(organization=self.org)
        attachments = TicketAttachment.objects.filter(ticket=ticket)
        self.assertEqual(attachments.count(), 1)
        a = attachments.first()
        self.assertEqual(a.filename, 'error.log')
        self.assertEqual(a.content_type, 'text/plain')
        self.assertGreater(a.size_bytes, 0)
        self.assertFalse(a.is_internal)

    def test_allowlist_miss_skips_attachment(self):
        from psa.models import TicketAttachment
        raw = _build_raw_email_with_attachment(
            message_id='<att-block@example.com>',
            from_addr='alice@example.com', to_addr='help@orgatt.example.com',
            subject='Suspicious binary',
            body='Run this.',
            attachments=[('payload.exe', 'application/x-msdownload', b'MZ\x90\x00')],
        )
        self._run_poll(raw)

        ticket = Ticket.objects.get(organization=self.org)
        # Ticket got created (the email body went through), but attachment
        # was rejected.
        self.assertEqual(TicketAttachment.objects.filter(ticket=ticket).count(), 0)

    def test_oversize_attachment_skipped(self):
        from django.test import override_settings
        from psa.models import TicketAttachment
        raw = _build_raw_email_with_attachment(
            message_id='<att-big@example.com>',
            from_addr='alice@example.com', to_addr='help@orgatt.example.com',
            subject='Huge log',
            body='attached',
            attachments=[('huge.log', 'text/plain', b'A' * 5000)],
        )
        # Drop the cap to 1024 bytes so 5000 bytes of payload is rejected.
        with override_settings(PSA_EMAIL_ATTACHMENT_MAX_BYTES=1024):
            self._run_poll(raw)

        ticket = Ticket.objects.get(organization=self.org)
        self.assertEqual(TicketAttachment.objects.filter(ticket=ticket).count(), 0)

    def test_image_wildcard_in_allowlist_accepts_jpeg(self):
        """``image/*`` allowlist entries should accept ``image/jpeg`` etc."""
        from django.test import override_settings
        from psa.models import TicketAttachment
        raw = _build_raw_email_with_attachment(
            message_id='<att-img@example.com>',
            from_addr='alice@example.com', to_addr='help@orgatt.example.com',
            subject='Screenshot',
            body='see image',
            attachments=[('shot.jpg', 'image/jpeg', b'\xff\xd8\xff\xe0fakejpeg')],
        )
        with override_settings(PSA_EMAIL_ATTACHMENT_MIME_ALLOWLIST=['image/*']):
            self._run_poll(raw)

        ticket = Ticket.objects.get(organization=self.org)
        self.assertEqual(TicketAttachment.objects.filter(ticket=ticket).count(), 1)


class ReplyBodyCleanupTests(TestCase, _EmailPollerSetup):
    """
    On replies to an existing ticket, the comment body should have the
    customer's signature + quoted history stripped.
    """
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgclean')
        self.ticket = self._make_ticket(self.org)
        from psa.models import EmailMessage
        EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, ingestion_config=self.cfg,
            direction='in', message_id='<seed-clean@example.com>',
        )

    def test_reply_comment_drops_signature_and_quote(self):
        from psa.management.commands import psa_poll_email
        from psa.models import TicketComment
        body = (
            'Yes that worked, thanks.\n\n'
            '-- \n'
            'Bob\n'
            'Widget Co.\n\n'
            'On Tue, Mar 4, 2026 at 10:00 AM Alice <a@b> wrote:\n'
            '> Try restarting it.\n'
        )
        raw = _build_raw_email(
            message_id='<reply-clean@example.com>',
            from_addr='customer@example.com', to_addr='help@orgclean.example.com',
            subject='no token',
            in_reply_to='<seed-clean@example.com>',
            body=body,
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        c = TicketComment.objects.get(ticket=self.ticket)
        self.assertEqual(c.body.strip(), 'Yes that worked, thanks.')
        # The pristine raw body should still be on the EmailMessage row for
        # the conversation panel.
        from psa.models import EmailMessage
        em = EmailMessage.objects.get(message_id='<reply-clean@example.com>')
        self.assertIn('Widget Co.', em.body_text)
        self.assertIn('On Tue', em.body_text)


class HtmlBodyStoredSanitizedTests(TestCase, _EmailPollerSetup):
    """
    Inbound HTML bodies should be sanitized before being persisted to
    EmailMessage.body_html so the conversation panel can render them safely.
    """
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orghtml')

    def test_inbound_html_body_is_sanitized(self):
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from psa.management.commands import psa_poll_email
        from psa.models import EmailMessage
        msg = MIMEMultipart('alternative')
        msg['From'] = 'alice@example.com'
        msg['To'] = 'help@orghtml.example.com'
        msg['Subject'] = 'with html'
        msg['Message-ID'] = '<htmlbody@example.com>'
        msg.attach(MIMEText('hi', 'plain', 'utf-8'))
        msg.attach(MIMEText(
            '<p>hi</p><script>alert(1)</script>'
            '<a href="https://x.com" onclick="bad()">x</a>',
            'html', 'utf-8',
        ))
        raw = msg.as_bytes()
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        em = EmailMessage.objects.get(message_id='<htmlbody@example.com>')
        self.assertNotIn('<script', em.body_html)
        self.assertNotIn('onclick', em.body_html)
        self.assertIn('href="https://x.com"', em.body_html)


class MalformedMimeTests(TestCase, _EmailPollerSetup):
    """The poller must not crash on broken MIME — single bad message
    can't take down the whole poll cycle."""
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgmime')

    def test_garbage_message_does_not_raise(self):
        from psa.management.commands import psa_poll_email
        # Not actually a valid RFC 822 message — just bytes.
        raw = b'this is not really an email at all'
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        # Either the poller created a "(no subject)" ticket from the garbage
        # or it skipped silently — but it must not have raised.
        # Either outcome is acceptable; the assertion is "we got here".
        self.assertTrue(True)


# ---------------------------------------------------------------------------
# Phase 10.3 — Auto-responder detection, DMARC verdict, spam keywords,
# routing rules. Most of this is pure-function tests; integration tests at
# the bottom drive the poller end-to-end with mocked IMAP.
# ---------------------------------------------------------------------------

class AutoResponderDetectionTests(TestCase):
    def _msg(self, **headers):
        import email
        from email.mime.text import MIMEText
        m = MIMEText('hi', 'plain', 'utf-8')
        for k, v in headers.items():
            del m[k]
            m[k] = v
        return email.message_from_bytes(m.as_bytes())

    def test_auto_submitted_header_quarantines(self):
        from psa.email_parsing import detect_auto_responder
        m = self._msg(**{'Auto-Submitted': 'auto-replied'})
        self.assertIn('Auto-Submitted', detect_auto_responder(m))

    def test_x_autoreply_header_quarantines(self):
        from psa.email_parsing import detect_auto_responder
        m = self._msg(**{'X-Autoreply': 'yes'})
        self.assertIn('X-Autoreply', detect_auto_responder(m))

    def test_precedence_bulk_quarantines(self):
        from psa.email_parsing import detect_auto_responder
        m = self._msg(Precedence='bulk')
        self.assertIn('Precedence', detect_auto_responder(m))

    def test_subject_out_of_office_quarantines_when_no_header(self):
        from psa.email_parsing import detect_auto_responder
        m = self._msg(Subject='Out of Office: back Monday')
        self.assertIn('subject heuristic', detect_auto_responder(m))

    def test_normal_reply_passes_through(self):
        from psa.email_parsing import detect_auto_responder
        m = self._msg(Subject='Re: my support ticket')
        self.assertEqual(detect_auto_responder(m), '')


class AuthenticationResultsParseTests(TestCase):
    def test_parses_dmarc_pass(self):
        import email
        raw = (
            b'Authentication-Results: mx.example.com;\n'
            b' spf=pass smtp.mailfrom=alice@example.com;\n'
            b' dkim=pass header.d=example.com;\n'
            b' dmarc=pass action=none\n'
            b'From: alice@example.com\n'
            b'Subject: hi\n\nbody\n'
        )
        m = email.message_from_bytes(raw)
        from psa.email_parsing import parse_authentication_results
        self.assertEqual(parse_authentication_results(m).get('dmarc'), 'pass')
        self.assertEqual(parse_authentication_results(m).get('dkim'), 'pass')

    def test_no_header_returns_empty(self):
        import email
        m = email.message_from_bytes(b'From: a@b\n\nx\n')
        from psa.email_parsing import parse_authentication_results
        self.assertEqual(parse_authentication_results(m), {})


class SpamKeywordScoreTests(TestCase):
    def test_score_zero_for_clean_text(self):
        from psa.email_parsing import spam_keyword_score
        self.assertEqual(spam_keyword_score('Please reset my password thanks'), 0)

    def test_score_increments_per_pattern(self):
        from psa.email_parsing import spam_keyword_score
        text = 'CONGRATULATIONS WINNER! Claim your prize, Nigerian Prince here.'
        # Hits: "congratulations ... winner" + "claim your prize" + "nigerian ... prince"
        self.assertGreaterEqual(spam_keyword_score(text), 3)


class EmailRoutingRuleMatchTests(TestCase):
    def setUp(self):
        from core.models import Organization
        from psa.models import EmailRoutingRule
        self.msp = Organization.objects.create(name='MSP', slug='routing-msp')
        self.client_org = Organization.objects.create(name='Acme Co', slug='routing-acme')
        self.rule_domain = EmailRoutingRule.objects.create(
            organization=self.msp, name='Acme exact',
            sender_domain_glob='acme.com', target_client_org=self.client_org,
        )
        self.rule_subdomain = EmailRoutingRule.objects.create(
            organization=self.msp, name='Acme subs',
            sender_domain_glob='*.acme.com', target_client_org=self.client_org,
            order=200,
        )
        self.rule_specific_sender = EmailRoutingRule.objects.create(
            organization=self.msp, name='Acme noreply',
            sender_domain_glob='noreply@acme.com', target_client_org=self.client_org,
            order=10,
        )

    def test_exact_domain_match(self):
        self.assertTrue(self.rule_domain.matches('alice@acme.com'))
        self.assertFalse(self.rule_domain.matches('alice@globex.com'))

    def test_subdomain_glob_match(self):
        self.assertTrue(self.rule_subdomain.matches('alerts@api.acme.com'))
        # The wildcard "*.acme.com" pattern requires at least one subdomain
        # before the suffix — bare "acme.com" should NOT match the subdomain rule.
        self.assertFalse(self.rule_subdomain.matches('alice@acme.com'))

    def test_full_email_match(self):
        self.assertTrue(self.rule_specific_sender.matches('noreply@acme.com'))
        self.assertFalse(self.rule_specific_sender.matches('alice@acme.com'))

    def test_empty_inputs_no_match(self):
        self.assertFalse(self.rule_domain.matches(''))
        self.assertFalse(self.rule_domain.matches(None))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AutoResponderQuarantineIntegrationTests(TestCase, _EmailPollerSetup):
    """Auto-responder inbound is persisted as quarantined and never creates
    a ticket."""

    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgaresp')

    def test_auto_submitted_inbound_does_not_create_ticket(self):
        from psa.management.commands import psa_poll_email
        from psa.models import EmailMessage
        # Manually add Auto-Submitted via a header injected into a normal mime body.
        raw = (
            b'From: bot@example.com\r\n'
            b'To: help@orgaresp.example.com\r\n'
            b'Subject: out of office\r\n'
            b'Message-ID: <bot-1@example.com>\r\n'
            b'Auto-Submitted: auto-replied\r\n'
            b'Content-Type: text/plain; charset=utf-8\r\n\r\n'
            b'I am away.\r\n'
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        # No ticket created.
        from psa.models import Ticket
        self.assertEqual(Ticket.objects.filter(organization=self.org).count(), 0)
        # Quarantined EmailMessage row exists with no ticket and a reason.
        em = EmailMessage.objects.get(message_id='<bot-1@example.com>')
        self.assertTrue(em.was_quarantined)
        self.assertIsNone(em.ticket_id)
        self.assertIn('Auto-Submitted', em.quarantine_reason)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoutingRuleIntegrationTests(TestCase, _EmailPollerSetup):
    """A sender-domain routing rule remaps inbound mail from the MSP's
    config-org tenant to a client org tenant."""

    def setUp(self):
        self._seed_psa()
        # config_org is the MSP that owns the routing rule.
        self.msp_org, self.cfg = self._make_org_with_config('orgmsp-routing')
        # client_org is the routing target.
        from core.models import Organization
        self.client_org = Organization.objects.create(
            name='Routed Client', slug='routed-client',
        )
        from psa.models import EmailRoutingRule
        EmailRoutingRule.objects.create(
            organization=self.msp_org, name='Globex routing',
            sender_domain_glob='globex.example',
            target_client_org=self.client_org,
        )

    def test_inbound_from_matching_domain_lands_in_client_org(self):
        from psa.management.commands import psa_poll_email
        raw = _build_raw_email(
            message_id='<route-1@globex.example>',
            from_addr='alice@globex.example',
            to_addr='help@orgmsp-routing.example.com',
            subject='Printer down',
            body='it does not work',
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        # Ticket landed in client_org, NOT the MSP config_org.
        self.assertEqual(Ticket.objects.filter(organization=self.client_org).count(), 1)
        self.assertEqual(Ticket.objects.filter(organization=self.msp_org).count(), 0)

    def test_inbound_from_unmatched_domain_stays_in_msp_org(self):
        from psa.management.commands import psa_poll_email
        raw = _build_raw_email(
            message_id='<noroute-1@stranger.example>',
            from_addr='alice@stranger.example',
            to_addr='help@orgmsp-routing.example.com',
            subject='Help',
            body='hi',
        )
        fake = _FakeIMAP([(b'1', raw)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            from django.core.management import call_command
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

        self.assertEqual(Ticket.objects.filter(organization=self.msp_org).count(), 1)
        self.assertEqual(Ticket.objects.filter(organization=self.client_org).count(), 0)


# ---------------------------------------------------------------------------
# Phase 10.4 — Outbound threading + conversation panel
# ---------------------------------------------------------------------------

class OutboundThreadedReplyTests(TestCase, _EmailPollerSetup):
    """`send_threaded_reply` builds a properly-threaded outbound email,
    persists an EmailMessage(direction='out') row, and uses the ticket's
    last_inbound_message_id as In-Reply-To."""

    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgoutbound')
        self.ticket = self._make_ticket(self.org, requester_email='customer@example.com')
        # Seed a prior inbound so outbound threading has something to chain against.
        self.ticket.last_inbound_message_id = '<original-inbound@example.com>'
        self.ticket.save(update_fields=['last_inbound_message_id'])

    def test_send_sets_threading_headers_from_last_inbound(self):
        from django.core import mail
        from psa.email_outbound import send_threaded_reply
        em = send_threaded_reply(
            ticket=self.ticket, comment=None,
            body_text='Thanks for the update.',
        )
        # Django captures sent mail in mail.outbox during tests.
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.extra_headers.get('In-Reply-To'),
                         '<original-inbound@example.com>')
        self.assertEqual(sent.extra_headers.get('References'),
                         '<original-inbound@example.com>')
        self.assertIn('Message-ID', sent.extra_headers)
        # The persisted EmailMessage row records the same threading.
        self.assertEqual(em.direction, 'out')
        self.assertEqual(em.in_reply_to, '<original-inbound@example.com>')
        self.assertEqual(em.references, '<original-inbound@example.com>')
        self.assertEqual(em.ticket_id, self.ticket.id)

    def test_no_last_inbound_skips_in_reply_to(self):
        from django.core import mail
        from psa.email_outbound import send_threaded_reply
        # Fresh ticket with no captured inbound.
        ticket = self._make_ticket(
            self.org, subject='Cold outbound', requester_email='cold@example.com',
        )
        send_threaded_reply(
            ticket=ticket, comment=None,
            body_text='Hi, reaching out.',
        )
        sent = mail.outbox[-1]
        self.assertNotIn('In-Reply-To', sent.extra_headers)
        self.assertNotIn('References', sent.extra_headers)

    def test_subject_falls_back_to_re_ticket_pattern(self):
        from django.core import mail
        from psa.email_outbound import send_threaded_reply
        send_threaded_reply(
            ticket=self.ticket, comment=None,
            body_text='reply',
        )
        sent = mail.outbox[-1]
        # Default subject embeds the ticket number for legacy subject-regex
        # threading on inbound replies.
        self.assertIn(self.ticket.ticket_number, sent.subject)

    def test_explicit_subject_and_recipients_honored(self):
        from django.core import mail
        from psa.email_outbound import send_threaded_reply
        send_threaded_reply(
            ticket=self.ticket, comment=None,
            body_text='reply',
            subject='Explicit subject',
            to_emails=['someone-else@example.com'],
        )
        sent = mail.outbox[-1]
        self.assertEqual(sent.subject, 'Explicit subject')
        self.assertEqual(sent.to, ['someone-else@example.com'])

    def test_html_alternative_attached(self):
        from django.core import mail
        from psa.email_outbound import send_threaded_reply
        send_threaded_reply(
            ticket=self.ticket, comment=None,
            body_text='plain version',
            body_html='<p>html version</p>',
        )
        sent = mail.outbox[-1]
        self.assertEqual(sent.body, 'plain version')
        self.assertEqual(len(sent.alternatives), 1)
        html_body, mime_type = sent.alternatives[0]
        self.assertEqual(mime_type, 'text/html')
        self.assertIn('<p>html version</p>', html_body)

    def test_missing_recipients_raises(self):
        from psa.email_outbound import send_threaded_reply
        ticket = self._make_ticket(
            self.org, subject='No recipient', requester_email='',
        )
        with self.assertRaises(ValueError):
            send_threaded_reply(
                ticket=ticket, comment=None, body_text='hi',
            )

    def test_outbound_message_id_resolves_to_same_ticket_on_reply(self):
        """The round-trip closes: customer's reply to our outbound
        carries our generated Message-ID as In-Reply-To, and the existing
        Phase 10.1 _thread_target lookup resolves it back to the same
        ticket."""
        from psa.email_outbound import send_threaded_reply
        em = send_threaded_reply(
            ticket=self.ticket, comment=None, body_text='our reply',
        )
        # Simulate inbound carrying our outbound's Message-ID as In-Reply-To.
        import email
        raw = _build_raw_email(
            message_id='<customer-reply@example.com>',
            from_addr='customer@example.com',
            to_addr='help@orgoutbound.example.com',
            subject='no token',
            in_reply_to=em.message_id,
            body='thanks!',
        )
        msg = email.message_from_bytes(raw)
        from psa.management.commands.psa_poll_email import _thread_target
        self.assertEqual(_thread_target(msg, self.org), self.ticket)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketConversationViewTests(TestCase, _EmailPollerSetup):
    def setUp(self):
        self._seed_psa()
        self.org, self.cfg = self._make_org_with_config('orgconv')
        self.ticket = self._make_ticket(self.org)
        from psa.models import EmailMessage
        EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, direction='in',
            message_id='<inbound-1@example.com>', from_email='customer@example.com',
            subject='Original', body_text='Hello, please help.',
        )
        EmailMessage.objects.create(
            organization=self.org, ticket=self.ticket, direction='out',
            message_id='<outbound-1@example.com>',
            in_reply_to='<inbound-1@example.com>',
            from_email='help@orgconv.example.com',
            to_emails=['customer@example.com'],
            subject='Re: Original', body_text='Sure, looking now.',
        )

        # Staff user with current org pinned in session.
        from accounts.models import Membership, Role
        self.user = User.objects.create_user(
            'conv-user', email='c@x.com', password='pw', is_staff=True,
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_view_lists_inbound_and_outbound_messages(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        url = f'/psa/t/{self.ticket.ticket_number}/conversation/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Inbound', body)
        self.assertIn('Outbound', body)
        self.assertIn('inbound-1@example.com', body)
        self.assertIn('outbound-1@example.com', body)

    def test_view_404_for_other_org_ticket(self):
        from accounts.models import Membership, Role
        from core.models import SystemSetting
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()

        # Create a ticket in a DIFFERENT org and a regular (non-staff)
        # client user from yet a third org. Cross-tenant access must 404.
        other_org = Organization.objects.create(name='Other', slug='other-conv')
        other_ticket = self._make_ticket(other_org, subject='other')

        client_user = User.objects.create_user(
            'client-user-conv', password='pw', email='cu@x.com',
        )
        third_org = Organization.objects.create(name='Third', slug='third-conv')
        Membership.objects.create(
            user=client_user, organization=third_org, role=Role.READONLY, is_active=True,
        )

        c = Client()
        c.force_login(client_user)
        s2 = c.session
        s2['2fa_prompted'] = True
        s2['current_organization_id'] = third_org.id
        s2.save()
        resp = c.get(f'/psa/t/{other_ticket.ticket_number}/conversation/')
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Issue #142 — Microsoft 365 Graph mailbox source for PSA inbound
# ---------------------------------------------------------------------------

class GraphMailboxPollTests(TestCase, _EmailPollerSetup):
    """The Graph source must feed the SAME processing pipeline as IMAP: create
    tickets, thread replies, and mark messages read — just via M365 Graph."""

    def setUp(self):
        self._seed_psa()
        from psa.models import EmailIngestionConfig, Queue, TicketPriority, TicketType
        from integrations.models import M365Connection
        self.org = Organization.objects.create(name='GRAPHORG', slug='graphorg')
        self.conn = M365Connection.objects.create(
            organization=self.org, name='Tenant A', tenant_id='tenant-a', is_active=True)
        self.conn.set_credentials({'client_id': 'cid', 'client_secret': 'sec'})
        self.conn.save()
        self.cfg = EmailIngestionConfig.objects.create(
            organization=self.org, name='graph-helpdesk',
            source='graph', m365_connection=self.conn,
            graph_mailbox='support@graphorg.com',
            default_queue=Queue.objects.first(),
            default_priority=TicketPriority.objects.first(),
            default_type=TicketType.objects.first(),
        )

    def _run_graph_poll(self, messages):
        """messages: dict of graph_message_id -> raw MIME bytes."""
        import integrations.providers.m365 as m365mod
        marked = []

        class _FakeProvider:
            def __init__(self, tenant_id, client_id, client_secret):
                self.tenant_id = tenant_id

            def list_unread_message_ids(self, mailbox, folder='inbox', limit=50):
                return list(messages.keys())

            def get_message_mime(self, mailbox, message_id):
                return messages[message_id]

            def mark_message_read(self, mailbox, message_id):
                marked.append(message_id)

        original = m365mod.M365Provider
        m365mod.M365Provider = _FakeProvider
        try:
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            m365mod.M365Provider = original
        return marked

    def test_graph_creates_ticket_and_marks_read(self):
        raw = _build_raw_email(
            message_id='<g1@x.com>', from_addr='cust@client.com',
            to_addr='support@graphorg.com', subject='Printer down',
            body='It is broken')
        marked = self._run_graph_poll({'AAABBBID': raw})
        t = Ticket.objects.get(organization=self.org, subject='Printer down')
        self.assertEqual(t.source, 'email')
        self.assertEqual(t.requester_email, 'cust@client.com')
        self.assertEqual(marked, ['AAABBBID'])
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.last_poll_status, 'ok')

    def test_graph_threads_reply_onto_existing_ticket(self):
        from psa.models import EmailMessage, TicketComment
        ticket = self._make_ticket(self.org, subject='Original issue')
        EmailMessage.objects.create(
            organization=self.org, ticket=ticket, ingestion_config=self.cfg,
            direction='in', message_id='<orig@x.com>',
            from_email='cust@client.com', subject='Original issue')
        ticket.last_inbound_message_id = '<orig@x.com>'
        ticket.save(update_fields=['last_inbound_message_id'])

        raw = _build_raw_email(
            message_id='<reply1@x.com>', from_addr='cust@client.com',
            to_addr='support@graphorg.com', subject='Re: Original issue',
            body='Any update?', in_reply_to='<orig@x.com>')
        before = Ticket.objects.count()
        self._run_graph_poll({'MSG2': raw})
        self.assertEqual(Ticket.objects.count(), before)  # no new ticket
        self.assertTrue(TicketComment.objects.filter(
            ticket=ticket, body__icontains='Any update?').exists())

    def test_graph_missing_connection_records_error(self):
        self.cfg.m365_connection = None
        self.cfg.save()
        call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.last_poll_status, 'error')
        self.assertIn('M365 connection', self.cfg.last_error)


class M365ProviderMailMethodTests(TestCase):
    """Graph mail helpers build the right URLs and parse results (issue #142)."""

    def _provider(self):
        from integrations.providers.m365 import M365Provider
        return M365Provider('tenant', 'client', 'secret')

    def test_list_unread_builds_filter_and_extracts_ids(self):
        from unittest import mock
        p = self._provider()
        captured = {}

        def fake_get_all(path, params=None, *, prefer_immutable=False):
            captured['path'] = path
            captured['params'] = params
            captured['prefer_immutable'] = prefer_immutable
            return [{'id': 'a'}, {'id': 'b'}, {'no_id': 1}]

        p._get_all = fake_get_all
        ids = p.list_unread_message_ids('support@x.com', 'inbox')
        # ids are reversed (Graph default desc -> oldest-first) and rows without
        # an 'id' are dropped.
        self.assertEqual(ids, ['b', 'a'])
        self.assertIn('mailFolders/inbox/messages', captured['path'])
        self.assertEqual(captured['params']['$filter'], 'isRead eq false')
        self.assertNotIn('$orderby', captured['params'])
        # Issue #142 outbound — inbound list requests immutable ids.
        self.assertTrue(captured['prefer_immutable'])

    def test_mark_message_read_patches_isread(self):
        p = self._provider()
        captured = {}

        def fake_patch(path, body, *, prefer_immutable=False):
            captured['path'] = path
            captured['body'] = body
            captured['prefer_immutable'] = prefer_immutable

        p._patch = fake_patch
        p.mark_message_read('support@x.com', 'MSGID')
        self.assertIn('/messages/MSGID', captured['path'])
        self.assertEqual(captured['body'], {'isRead': True})
        self.assertTrue(captured['prefer_immutable'])
