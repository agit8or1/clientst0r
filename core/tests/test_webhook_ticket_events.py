"""Ticket, contact and invoice webhook events.

Same envelope, signing and after-commit delivery as the other events
(core.webhook_events). Customer-scoped: tickets go to the ticket's customer
and only when shared with it (`client_can_view`); invoices go to the billed
customer (`client_org`) once issued (never as drafts). Saves that change
nothing reported send nothing.
"""
import json
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.tests.test_webhook_events import WebhookEventTestBase
from core.webhook_sender import generate_signature


class TicketWebhookTests(WebhookEventTestBase):

    def setUp(self):
        super().setUp()
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType
        self.new = TicketStatus.objects.create(name='WH New', slug='wh-new')
        self.working = TicketStatus.objects.create(name='WH Working', slug='wh-working')
        self.done = TicketStatus.objects.create(name='WH Done', slug='wh-done', is_terminal=True)
        self.p_low = TicketPriority.objects.create(code='WHL', name='WH Low')
        self.p_high = TicketPriority.objects.create(code='WHH', name='WH High')
        self.ttype = TicketType.objects.create(name='WH Incident', slug='wh-incident')
        self.queue = Queue.objects.create(name='WH Desk', slug='wh-desk')

    def ticket(self, org=None, **kw):
        from psa.models import Ticket
        fields = dict(organization=org or self.org, subject='Printer offline',
                      description='Customer text', status=self.new, priority=self.p_low,
                      ticket_type=self.ttype, queue=self.queue, client_can_view=True)
        fields.update(kw)
        return self.run_commit(lambda: Ticket.objects.create(**fields))

    def test_created_payload_signed_and_minimal(self):
        hook = self.hook(['ticket.created'], secret='s3cret')
        t = self.ticket()
        calls = self.session.calls
        self.assertEqual(len(calls), 1)
        body = calls[0]['data']
        self.assertEqual(calls[0]['headers']['X-Webhook-Signature'],
                         generate_signature(body, 's3cret'))
        p = json.loads(body)
        self.assertEqual(p['event'], 'ticket.created')
        self.assertEqual(p['organization'], 'acme')
        self.assertEqual(p['webhook_id'], hook.pk)
        d = p['data']
        self.assertEqual(d['ticket_id'], t.pk)
        self.assertEqual(d['ticket_number'], t.ticket_number)
        self.assertEqual(d['subject'], 'Printer offline')
        self.assertEqual(d['status'], 'wh-new')
        self.assertEqual(d['priority'], 'WH Low')
        self.assertFalse(d['is_closed'])
        self.assertNotIn('Customer text', body)
        for key in ('description', 'comments', 'internal_notes', 'assigned_to', 'custom_fields'):
            self.assertNotIn(key, d)

    def test_other_customer_hook_gets_nothing(self):
        self.hook(['ticket.created', 'ticket.updated', 'ticket.status_changed'], org=self.other)
        t = self.ticket()
        t.status = self.working
        t.subject = 'Changed'
        self.run_commit(t.save)
        self.assertEqual(self.session.calls, [])

    def test_staff_only_ticket_not_announced_until_shared(self):
        self.hook(['ticket.created', 'ticket.updated', 'ticket.status_changed'])
        t = self.ticket(client_can_view=False)
        t.subject = 'Internal rename'
        t.status = self.working
        self.run_commit(t.save)
        self.assertEqual(self.session.calls, [])
        t.client_can_view = True
        self.run_commit(t.save)
        self.assertEqual([p['event'] for p in self.payloads()], ['ticket.created'])

    def test_status_change_sends_status_changed_only(self):
        self.hook(['ticket.updated', 'ticket.status_changed'])
        t = self.ticket()
        t.status = self.done
        self.run_commit(t.save)
        p = self.payloads()
        self.assertEqual([x['event'] for x in p], ['ticket.status_changed'])
        self.assertEqual(p[0]['data']['previous_status'], 'wh-new')
        self.assertEqual(p[0]['data']['status'], 'wh-done')
        self.assertTrue(p[0]['data']['is_closed'])

    def test_field_change_sends_updated_with_changed_fields(self):
        self.hook(['ticket.updated', 'ticket.status_changed'])
        t = self.ticket()
        t.priority = self.p_high
        t.subject = 'Printer on fire'
        self.run_commit(t.save)
        p = self.payloads()
        self.assertEqual([x['event'] for x in p], ['ticket.updated'])
        self.assertEqual(p[0]['data']['changed_fields'], ['priority', 'subject'])
        self.assertEqual(p[0]['data']['priority'], 'WH High')

    def test_reloaded_ticket_compares_against_database(self):
        from psa.models import Ticket
        self.hook(['ticket.status_changed'])
        t = self.ticket()
        fresh = Ticket.objects.get(pk=t.pk)
        fresh.status = self.working
        self.run_commit(fresh.save)
        self.assertEqual(self.payloads()[0]['data']['previous_status'], 'wh-new')

    def test_unreported_change_sends_nothing(self):
        from django.utils import timezone
        self.hook(['ticket.updated', 'ticket.status_changed'])
        t = self.ticket()
        t.description = 'Edited body'
        t.last_tech_response_at = timezone.now()
        t.tags = ['x']
        self.run_commit(t.save)
        self.run_commit(t.save)
        self.assertEqual(self.session.calls, [])

    def test_internal_comment_sends_nothing_and_never_leaks(self):
        from psa.models import TicketComment
        self.hook(['ticket.created', 'ticket.updated', 'ticket.status_changed'])
        t = self.ticket()
        self.session.calls.clear()
        fields = {f.name for f in TicketComment._meta.get_fields()}
        kwargs = {'ticket': t, 'body': 'INTERNAL ONLY note'}
        if 'is_internal' in fields:
            kwargs['is_internal'] = True
        self.run_commit(lambda: TicketComment.objects.create(**kwargs))
        for call in self.session.calls:
            self.assertNotIn('INTERNAL ONLY', call['data'])

    def test_raw_fixture_load_sends_nothing(self):
        from core.webhook_signals import ticket_saved
        self.hook(['ticket.created'])
        from psa.models import Ticket
        t = Ticket(pk=999, organization=self.org, subject='x', status=self.new,
                   priority=self.p_low, ticket_type=self.ttype, queue=self.queue,
                   client_can_view=True)
        self.run_commit(lambda: ticket_saved(Ticket, t, True, raw=True))
        self.assertEqual(self.session.calls, [])


class ContactWebhookTests(WebhookEventTestBase):

    def contact(self, org=None, **kw):
        from assets.models import Contact
        fields = dict(organization=org or self.org, first_name='Ada', last_name='Lovelace',
                      email='ada@acme.test', phone='555', notes='Staff-only remark')
        fields.update(kw)
        return self.run_commit(lambda: Contact.objects.create(**fields))

    def test_created_without_notes(self):
        self.hook(['contact.created'])
        c = self.contact()
        p = self.payloads()
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['data']['contact_id'], c.pk)
        self.assertEqual(p[0]['data']['email'], 'ada@acme.test')
        self.assertNotIn('notes', p[0]['data'])
        self.assertNotIn('Staff-only remark', self.session.calls[0]['data'])

    def test_updated_only_when_reported_field_changes(self):
        self.hook(['contact.updated'])
        c = self.contact()
        c.notes = 'Changed notes'
        self.run_commit(c.save)
        self.assertEqual(self.session.calls, [])
        c.phone = '556'
        self.run_commit(c.save)
        p = self.payloads()
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['data']['changed_fields'], ['phone'])

    def test_other_customer_hook_gets_nothing(self):
        self.hook(['contact.created', 'contact.updated'], org=self.other)
        c = self.contact()
        c.phone = '1'
        self.run_commit(c.save)
        self.assertEqual(self.session.calls, [])


class InvoiceWebhookTests(WebhookEventTestBase):

    def invoice(self, client=None, **kw):
        from psa.models import Invoice
        fields = dict(organization=self.org, client_org=client or self.org,
                      title='October support', invoice_date=date(2026, 10, 31),
                      total=Decimal('100.00'), subtotal=Decimal('100.00'),
                      description='Internal billing remark')
        fields.update(kw)
        return self.run_commit(lambda: Invoice.objects.create(**fields))

    EVENTS = ['invoice.created', 'invoice.updated', 'invoice.status_changed']

    def test_draft_is_never_announced(self):
        self.hook(self.EVENTS)
        inv = self.invoice()
        inv.total = Decimal('120.00')
        self.run_commit(inv.save)
        self.assertEqual(self.session.calls, [])

    def test_issuing_sends_created(self):
        self.hook(self.EVENTS, secret='k')
        inv = self.invoice()
        inv.status = 'sent'
        self.run_commit(inv.save)
        p = self.payloads()
        self.assertEqual([x['event'] for x in p], ['invoice.created'])
        d = p[0]['data']
        self.assertEqual(d['invoice_number'], inv.invoice_number)
        self.assertEqual(d['total'], '100.00')
        self.assertEqual(d['balance_due'], '100.00')
        self.assertIn('X-Webhook-Signature', self.session.calls[0]['headers'])
        body = self.session.calls[0]['data']
        for leaked in ('Internal billing remark', 'accounting_external_id', 'last_push_error'):
            self.assertNotIn(leaked, body)

    def test_created_issued_and_status_and_payment(self):
        self.hook(self.EVENTS)
        inv = self.invoice(status='sent')
        inv.status = 'partial'
        inv.amount_paid = Decimal('40.00')
        self.run_commit(inv.save)
        p = self.payloads()
        self.assertEqual([x['event'] for x in p],
                         ['invoice.created', 'invoice.status_changed', 'invoice.updated'])
        self.assertEqual(p[1]['data']['previous_status'], 'sent')
        self.assertEqual(p[2]['data']['changed_fields'], ['amount_paid'])
        self.assertEqual(p[2]['data']['balance_due'], '60.00')

    def test_goes_to_billed_customer_only(self):
        self.hook(self.EVENTS)  # self.org issues the invoice
        other_hook = self.hook(self.EVENTS, org=self.other)
        self.invoice(client=self.other, status='sent')
        p = self.payloads()
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['webhook_id'], other_hook.pk)
        self.assertEqual(p[0]['organization'], 'other')

    def test_unreported_save_sends_nothing(self):
        self.hook(self.EVENTS)
        inv = self.invoice(status='sent')
        self.session.calls.clear()
        inv.last_push_error = 'boom'
        self.run_commit(inv.save)
        self.assertEqual(self.session.calls, [])


class NewEventsOfferedTests(TestCase):

    def test_form_offers_new_events(self):
        from core.webhook_forms import WebhookForm
        offered = {v for v, _ in WebhookForm().fields['events'].choices}
        for event in ('ticket.created', 'ticket.updated', 'ticket.status_changed',
                      'contact.created', 'contact.updated',
                      'invoice.created', 'invoice.updated', 'invoice.status_changed'):
            self.assertIn(event, offered)
