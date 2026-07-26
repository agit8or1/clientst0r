"""
Microsoft Graph OUTBOUND email tests (issue #142, outbound).

Covers the 20 required scenarios: sendMail / reply / replyAll, Sent Items,
attachments, HTML+text, Cc/Bcc, Mail.Send-missing, out-of-RBAC-scope, invalid
creds, 429+Retry-After, 5xx retry, permanent 4xx, duplicate-job prevention,
SMTP-unchanged, IMAP-unchanged, the inbound/outbound transport matrix, immutable
message ids, and migration safety.
"""
from __future__ import annotations

from contextlib import contextmanager

import requests
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Organization
from integrations.models import M365Connection
from psa.models import (
    EmailIngestionConfig, EmailMessage, EmailOutboundJob, Queue, Ticket,
    TicketAttachment, TicketPriority, TicketStatus, TicketType,
)
from psa.tests._base import _setup_seed


class _FakeResp:
    def __init__(self, status_code, headers=None, json_body=None, text=''):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_body if json_body is not None else {}
        self.text = text

    def json(self):
        return self._json


@contextmanager
def graph_provider(response=None, raise_exc=None):
    """Patch integrations.providers.m365.M365Provider with a fake that records
    calls and returns/raises what the test wants. Yields the call log."""
    import integrations.providers.m365 as m365mod
    calls = []

    class _FP:
        def __init__(self, *a, **kw):
            pass

        def _do(self, kind, *args):
            calls.append((kind, *args))
            if raise_exc is not None:
                raise raise_exc
            return response

        def send_mail(self, mailbox, message, save_to_sent_items=True):
            return self._do('send', mailbox, message, save_to_sent_items)

        def reply_message(self, mailbox, message_id, *, message=None, comment=''):
            return self._do('reply', mailbox, message_id, message)

        def reply_all_message(self, mailbox, message_id, *, message=None, comment=''):
            return self._do('reply_all', mailbox, message_id, message)

        def probe_mailbox(self, mailbox, folder='inbox'):
            return {'success': True}

    orig = m365mod.M365Provider
    m365mod.M365Provider = _FP
    try:
        yield calls
    finally:
        m365mod.M365Provider = orig


class _OutboundSetup:
    def _seed(self):
        _setup_seed()

    def _config(self, *, outbound='graph', source='graph', conn_active=True):
        org = Organization.objects.create(
            name=f'OB{self._n()}', slug=f'ob-{self._n()}')
        conn = M365Connection.objects.create(
            organization=org, name='Tenant', tenant_id='t', is_active=conn_active)
        conn.set_credentials({'client_id': 'cid', 'client_secret': 'sec'})
        conn.save()
        cfg = EmailIngestionConfig.objects.create(
            organization=org, name='hd', source=source, outbound_method=outbound,
            m365_connection=conn, graph_mailbox='support@x.com',
            default_queue=Queue.objects.first(),
            default_priority=TicketPriority.objects.first(),
            default_type=TicketType.objects.first())
        return org, conn, cfg

    _counter = 0

    def _n(self):
        _OutboundSetup._counter += 1
        return _OutboundSetup._counter

    def _ticket(self, org, requester='cust@client.com'):
        return Ticket.objects.create(
            organization=org, subject='Help', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first(),
            source='email', requester_email=requester)

    def _inbound_graph(self, org, ticket, gid='IMMUT123'):
        return EmailMessage.objects.create(
            organization=org, ticket=ticket, direction='in',
            message_id='<in@x.com>', graph_message_id=gid, transport='graph')


ACCEPTED = _FakeResp(202, headers={'request-id': 'req-abc'})


class GraphOutboundSendTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    # 1. New email via sendMail
    def test_sendmail_new_message(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        with graph_provider(ACCEPTED) as calls:
            job = send_ticket_reply(ticket=ticket, config=cfg, body_text='hi', body_html='<p>hi</p>')
        self.assertIsInstance(job, EmailOutboundJob)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_SENT)
        self.assertEqual(job.operation, EmailOutboundJob.OP_SEND)
        self.assertEqual(calls[0][0], 'send')
        self.assertEqual(job.ms_request_id, 'req-abc')

    # 2. Reply via the reply endpoint using the stored immutable id
    def test_reply_uses_reply_endpoint(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        self._inbound_graph(org, ticket, gid='IMMUT-REPLY')
        with graph_provider(ACCEPTED) as calls:
            job = send_ticket_reply(ticket=ticket, config=cfg, body_text='re')
        self.assertEqual(job.operation, EmailOutboundJob.OP_REPLY)
        self.assertEqual(calls[0][0], 'reply')
        self.assertEqual(calls[0][2], 'IMMUT-REPLY')  # mailbox, message_id

    # 3. Reply-all
    def test_reply_all(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        self._inbound_graph(org, ticket, gid='IMMUT-RA')
        with graph_provider(ACCEPTED) as calls:
            job = send_ticket_reply(ticket=ticket, config=cfg, body_text='re', reply_all=True)
        self.assertEqual(job.operation, EmailOutboundJob.OP_REPLY_ALL)
        self.assertEqual(calls[0][0], 'reply_all')

    # 4. Sent Items — saveToSentItems defaults on
    def test_save_to_sent_items_default_true(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        with graph_provider(ACCEPTED) as calls:
            send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')
        self.assertTrue(calls[0][3])  # save_to_sent_items arg

    # 5. Attachments
    def test_attachments_base64_included(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        att = TicketAttachment.objects.create(
            ticket=ticket, filename='a.txt', content_type='text/plain', size_bytes=5,
            file=SimpleUploadedFile('a.txt', b'hello', content_type='text/plain'))
        with graph_provider(ACCEPTED) as calls:
            send_ticket_reply(ticket=ticket, config=cfg, body_text='hi', attachments=[att])
        message = calls[0][2]
        self.assertIn('attachments', message)
        self.assertEqual(message['attachments'][0]['name'], 'a.txt')
        self.assertTrue(message['attachments'][0]['contentBytes'])

    # 7. Cc and Bcc
    def test_cc_and_bcc(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        with graph_provider(ACCEPTED) as calls:
            send_ticket_reply(ticket=ticket, config=cfg, body_text='hi',
                              cc_emails=['cc@x.com'], bcc_emails=['bcc@x.com'])
        message = calls[0][2]
        self.assertEqual(message['ccRecipients'][0]['emailAddress']['address'], 'cc@x.com')
        self.assertEqual(message['bccRecipients'][0]['emailAddress']['address'], 'bcc@x.com')


class GraphOutboundContentTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    def _job(self, **kw):
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        from psa.graph_outbound import enqueue_graph_reply
        return enqueue_graph_reply(
            organization=org, ticket=ticket, config=cfg, operation='send',
            mailbox='support@x.com', to_recipients=['cust@client.com'],
            subject='S', **kw)

    # 6. HTML body (sanitized) vs plain text
    def test_html_body_sanitized(self):
        from psa.graph_outbound import build_graph_message
        job = self._job(body_html='<p>ok</p><script>alert(1)</script>')
        msg = build_graph_message(job)
        self.assertEqual(msg['body']['contentType'], 'HTML')
        self.assertIn('ok', msg['body']['content'])
        self.assertNotIn('<script', msg['body']['content'].lower())

    def test_plain_text_body(self):
        from psa.graph_outbound import build_graph_message
        job = self._job(body_text='just text')
        msg = build_graph_message(job)
        self.assertEqual(msg['body']['contentType'], 'Text')
        self.assertEqual(msg['body']['content'], 'just text')


class GraphOutboundErrorTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    def _send(self, response=None, raise_exc=None):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        with graph_provider(response, raise_exc=raise_exc):
            return send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')

    # 8. Mail.Send not granted
    def test_mail_send_missing_fails_auth(self):
        resp = _FakeResp(403, json_body={'error': {
            'code': 'ErrorAccessDenied', 'message': 'Access is denied.'}})
        job = self._send(resp)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_FAILED)
        self.assertEqual(job.error_category, 'auth')
        self.assertIn('Mail.Send', job.last_error)

    # 9. Mailbox outside RBAC scope
    def test_out_of_rbac_scope_reports_scope(self):
        resp = _FakeResp(403, json_body={'error': {
            'code': 'ErrorAccessDenied',
            'message': 'The mailbox is not in the allowed scope.'}})
        job = self._send(resp)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_FAILED)
        self.assertIn('RBAC', job.last_error)

    # 10. Expired / invalid credentials
    def test_invalid_credentials_fail(self):
        job = self._send(raise_exc=requests.exceptions.HTTPError('invalid_client'))
        self.assertEqual(job.status, EmailOutboundJob.STATUS_FAILED)

    # 11. HTTP 429 with Retry-After -> requeue
    def test_429_retry_after_requeues(self):
        resp = _FakeResp(429, headers={'Retry-After': '42'},
                         json_body={'error': {'message': 'throttled'}})
        job = self._send(resp)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_QUEUED)
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(job.error_category, 'transient')
        delta = (job.next_attempt_at - timezone.now()).total_seconds()
        self.assertTrue(30 <= delta <= 60, delta)

    # 12. HTTP 5xx -> retry
    def test_503_requeues(self):
        resp = _FakeResp(503, json_body={'error': {'message': 'unavailable'}})
        job = self._send(resp)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_QUEUED)
        self.assertEqual(job.retry_count, 1)

    # 13. Permanent 4xx failure
    def test_400_permanent_failure(self):
        resp = _FakeResp(400, json_body={'error': {
            'code': 'ErrorInvalidRecipients', 'message': 'bad recipient'}})
        job = self._send(resp)
        self.assertEqual(job.status, EmailOutboundJob.STATUS_FAILED)
        self.assertEqual(job.error_category, 'validation')

    # read-timeout after submission -> uncertain, no auto-resend
    def test_read_timeout_marks_uncertain(self):
        job = self._send(raise_exc=requests.exceptions.ReadTimeout('after send'))
        self.assertEqual(job.status, EmailOutboundJob.STATUS_UNCERTAIN)
        self.assertEqual(job.error_category, 'uncertain')
        self.assertIsNone(job.next_attempt_at)

    # invalid recipient rejected before any Graph call
    def test_invalid_recipient_rejected(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org, requester='not-an-email')
        with graph_provider(ACCEPTED) as calls:
            with self.assertRaises(ValueError):
                send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')
        self.assertEqual(calls, [])


class GraphOutboundJobControlTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    # 14. Duplicate-job prevention (idempotency + claim-lock)
    def test_enqueue_idempotent(self):
        from psa.graph_outbound import enqueue_graph_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        kw = dict(organization=org, ticket=ticket, config=cfg, operation='send',
                  mailbox='support@x.com', to_recipients=['a@b.com'], subject='S',
                  idempotency_key='dup-key-1')
        j1 = enqueue_graph_reply(**kw)
        j2 = enqueue_graph_reply(**kw)
        self.assertEqual(j1.pk, j2.pk)
        self.assertEqual(EmailOutboundJob.objects.filter(idempotency_key='dup-key-1').count(), 1)

    def test_process_job_claims_once(self):
        from psa.graph_outbound import enqueue_graph_reply, process_job
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        job = enqueue_graph_reply(
            organization=org, ticket=ticket, config=cfg, operation='send',
            mailbox='support@x.com', to_recipients=['a@b.com'], subject='S')
        with graph_provider(ACCEPTED) as calls:
            first = process_job(job)
            second = process_job(job)  # already terminal
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(calls), 1)  # only one Graph submission

    # worker command processes a queued (retryable) job
    def test_worker_command_processes_due_job(self):
        from django.core.management import call_command
        from psa.graph_outbound import enqueue_graph_reply
        org, conn, cfg = self._config()
        ticket = self._ticket(org)
        job = enqueue_graph_reply(
            organization=org, ticket=ticket, config=cfg, operation='send',
            mailbox='support@x.com', to_recipients=['a@b.com'], subject='S')
        with graph_provider(ACCEPTED):
            call_command('psa_send_outbound', verbosity=0)
        job.refresh_from_db()
        self.assertEqual(job.status, EmailOutboundJob.STATUS_SENT)


class TransportMatrixTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    # 15. Existing SMTP outbound remains unchanged
    def test_smtp_outbound_unchanged(self):
        from psa.email_outbound import send_threaded_reply
        org, conn, cfg = self._config(outbound='smtp')
        ticket = self._ticket(org)
        em = send_threaded_reply(ticket=ticket, comment=None, body_text='hello',
                                 body_html='<p>hello</p>')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(em.direction, 'out')
        self.assertEqual(em.transport, 'smtp')
        self.assertEqual(EmailOutboundJob.objects.count(), 0)

    # 17. Graph inbound + SMTP outbound -> routes to SMTP, no job
    def test_graph_inbound_smtp_outbound(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config(source='graph', outbound='smtp')
        ticket = self._ticket(org)
        result = send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')
        self.assertIsInstance(result, EmailMessage)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailOutboundJob.objects.count(), 0)

    # 18. Graph inbound + Graph outbound -> reply job
    def test_graph_inbound_graph_outbound(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config(source='graph', outbound='graph')
        ticket = self._ticket(org)
        self._inbound_graph(org, ticket)
        with graph_provider(ACCEPTED):
            job = send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')
        self.assertIsInstance(job, EmailOutboundJob)
        self.assertEqual(job.operation, EmailOutboundJob.OP_REPLY)

    # SMTP fallback (pre-submission) when Graph is known-unavailable
    def test_smtp_fallback_when_connection_inactive(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config(outbound='graph', conn_active=False)
        cfg.smtp_fallback_enabled = True
        cfg.save()
        ticket = self._ticket(org)
        result = send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')
        self.assertIsInstance(result, EmailMessage)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailOutboundJob.objects.count(), 0)

    def test_no_fallback_raises_when_unavailable(self):
        from psa.email_outbound import send_ticket_reply
        org, conn, cfg = self._config(outbound='graph', conn_active=False)
        ticket = self._ticket(org)
        with self.assertRaises(ValueError):
            send_ticket_reply(ticket=ticket, config=cfg, body_text='hi')


class ImmutableIdTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    # 19a. Inbound Graph poll stores the immutable id on the EmailMessage
    def test_inbound_stores_graph_message_id(self):
        from django.core.management import call_command
        import integrations.providers.m365 as m365mod
        org, conn, cfg = self._config(source='graph', outbound='smtp')
        raw = (b'From: cust@client.com\r\nTo: support@x.com\r\n'
               b'Subject: Printer\r\nMessage-ID: <m1@x.com>\r\n\r\nbody')

        class _FP:
            def __init__(self, *a, **kw):
                pass

            def list_unread_message_ids(self, mailbox, folder='inbox', limit=50):
                return ['IMMUTABLE-XYZ']

            def get_message_mime(self, mailbox, message_id):
                return raw

            def mark_message_read(self, mailbox, message_id):
                pass

        orig = m365mod.M365Provider
        m365mod.M365Provider = _FP
        try:
            call_command('psa_poll_email', config_id=cfg.pk, verbosity=0)
        finally:
            m365mod.M365Provider = orig
        em = EmailMessage.objects.get(organization=org, message_id='<m1@x.com>')
        self.assertEqual(em.graph_message_id, 'IMMUTABLE-XYZ')
        self.assertEqual(em.transport, 'graph')

    # 19b. Provider sends the ImmutableId Prefer header
    def test_prefer_immutable_header(self):
        from integrations.providers.m365 import M365Provider
        p = M365Provider('t', 'c', 's')
        p._token = 'tok'  # avoid a token round-trip
        headers = p._headers(prefer_immutable=True)
        self.assertEqual(headers['Prefer'], 'IdType="ImmutableId"')
        headers2 = p._headers(prefer_immutable=False)
        self.assertNotIn('Prefer', headers2)

    def test_reply_posts_with_immutable_pref(self):
        from integrations.providers.m365 import M365Provider
        p = M365Provider('t', 'c', 's')
        captured = {}

        def fake_post(path, body, *, prefer_immutable=False, timeout=30):
            captured['path'] = path
            captured['prefer'] = prefer_immutable
            return _FakeResp(202)

        p._post = fake_post
        p.reply_message('support@x.com', 'IMM1', message={'subject': 'x'})
        self.assertIn('/messages/IMM1/reply', captured['path'])
        self.assertTrue(captured['prefer'])


class MigrationSafetyTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    # 20. New/existing records default to SMTP; graph not auto-enabled
    def test_defaults_are_smtp(self):
        org = Organization.objects.create(name='MigCo', slug='mig-co')
        cfg = EmailIngestionConfig.objects.create(
            organization=org, name='legacy', imap_host='imap.x', username='u',
            default_queue=Queue.objects.first(),
            default_priority=TicketPriority.objects.first(),
            default_type=TicketType.objects.first())
        self.assertEqual(cfg.outbound_method, 'smtp')
        self.assertEqual(cfg.source, 'imap')
        self.assertFalse(cfg.smtp_fallback_enabled)
        self.assertIsNone(cfg.graph_send_verified_at)


class ImapInboundUnchangedTests(TestCase, _OutboundSetup):
    def setUp(self):
        self._seed()

    # 16. Existing IMAP inbound remains unchanged
    def test_imap_inbound_still_creates_ticket(self):
        from django.core.management import call_command
        from psa.management.commands import psa_poll_email
        from psa.tests.test_phase10_email import _FakeIMAP, _build_raw_email
        org, conn, cfg = self._config(source='imap', outbound='smtp')
        cfg.imap_host = 'imap.x'
        cfg.username = 'u'
        cfg.set_password('pw')
        cfg.save()
        raw = _build_raw_email(
            message_id='<i1@x.com>', from_addr='cust@client.com',
            to_addr='support@x.com', subject='New IMAP issue', body='help')
        fake = _FakeIMAP([(b'1', raw)])
        orig = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            call_command('psa_poll_email', config_id=cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = orig
        self.assertTrue(
            Ticket.objects.filter(organization=org, subject='New IMAP issue').exists())
