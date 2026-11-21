"""Phase 102.1-102.3: account charge bundling under a lock, the accurate
unbilled list and the Ready for Billing queue.

SQLite note (as in test_prepaid_ledger): SELECT ... FOR UPDATE is a no-op on
SQLite and threads cannot share the in-memory test database, so the
concurrency tests simulate the race: a second writer that read the work as
unbilled before the first committed (a stale read) must still bill nothing,
because each charge is claimed with a conditional UPDATE and every finished
invoice is checked against the other live invoices before commit. On MySQL /
PostgreSQL the customer billing lock serializes the writers before that point;
on SQLite the UPDATE in lock_customer takes the database write lock first.
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from core.models import Organization
from psa.billing import billed, invoicing
from psa.billing import queue as bq
from psa.billing import ticket_charges as tc
from psa.models import (
    BillingQueueDecision, Charge, Invoice, InvoiceLineItem, Project, ProjectTask, Ticket, TicketTimeEntry,
    get_psa_balance,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for
from psa.tests.test_ticket_time_charges_101_5 import _ChargesBase, _login

D = Decimal


class _QueueBase(_ChargesBase):

    def _charge(self, amount='10', client=None, **kw):
        client = client or self.cust
        return Charge.objects.create(organization=client, client_org=client, description=f'c{amount}',
                                     amount=D(amount), charge_date=date.today(), **kw)

    def _sent(self, ticket=None):
        t = ticket or self.ticket
        Ticket.objects.filter(pk=t.pk).update(billing_status='ready')
        t.refresh_from_db()
        return t

    def _chargeable_ticket(self):
        self._card('100')
        e = self._entry(60)
        item, _w = tc.add_item(self.ticket, self.admin, category='materials', description='Cable', unit_price='5')
        self._sent()
        return e, item

    def _void(self, inv):
        Invoice.objects.filter(pk=inv.pk).update(status='void')


# --- 102.1 --------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChargeBundlingTests(_QueueBase):

    def _post(self):
        return self._client().post(reverse('psa:charge_invoice', args=[self.cust.pk]), follow=True)

    def test_double_click_bills_once(self):
        a, b = self._charge('10'), self._charge('20', is_credit=True)
        self._post()
        r = self._post()
        self.assertEqual(Invoice.objects.count(), 1)
        inv = Invoice.objects.get()
        self.assertEqual(inv.subtotal, D('-10.00'))
        self.assertEqual(sorted(inv.line_items.values_list('source', 'source_id')),
                         [('charge', str(a.pk)), ('charge', str(b.pk))])
        self.assertTrue(any('No uninvoiced' in str(m) for m in r.context['messages']))
        for c in (a, b):
            c.refresh_from_db()
            self.assertEqual((c.invoiced, c.invoice_id), (True, inv.pk))

    def test_stale_read_race_bills_nothing_twice(self):
        a, b = self._charge('10'), self._charge('20')
        stale = billed._read_charges(self.cust)          # worker 2 reads before worker 1 commits
        first, n = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertEqual(n, 2)
        with mock.patch.object(billed, '_read_charges', return_value=stale):
            with self.assertRaises(billed.DoubleBilling):
                billed.bundle_charges(self.cust, actor=self.admin)
        self.assertEqual(list(Invoice.objects.values_list('pk', flat=True)), [first.pk])
        self.assertEqual(InvoiceLineItem.objects.count(), 2)
        self.assertEqual(set(Charge.objects.values_list('invoice_id', flat=True)), {first.pk})

    def test_stale_read_race_through_the_view(self):
        self._charge('10')
        stale = billed._read_charges(self.cust)
        self._post()
        with mock.patch.object(billed, '_read_charges', return_value=stale):
            r = self._post()
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertTrue(any('same time' in str(m) for m in r.context['messages']))

    def test_retry_after_partial_failure_rolls_back(self):
        self._charge('10')
        with mock.patch.object(Invoice, 'recompute_totals', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                billed.bundle_charges(self.cust, actor=self.admin)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(Charge.objects.get().invoiced)
        inv, n = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertEqual((n, inv.subtotal), (1, D('10.00')))

    def test_void_invoice_releases_charges(self):
        c = self._charge('10')
        inv, _ = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertTrue(billed.charge_is_billed(c))
        self._void(inv)
        self.assertFalse(billed.charge_is_billed(c))
        again, n = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertEqual(n, 1)
        self.assertNotEqual(again.pk, inv.pk)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'void')

    def test_existing_invoices_unchanged(self):
        sent = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Old',
                                      invoice_date=date.today())
        InvoiceLineItem.objects.create(invoice=sent, description='old', quantity=1, unit_price=D('50'))
        sent.recompute_totals()
        Invoice.objects.filter(pk=sent.pk).update(status='sent')
        sent.refresh_from_db()
        before = (sent.status, sent.subtotal, sent.total, list(sent.line_items.values_list('pk', 'unit_price')))
        legacy = self._charge('7', invoiced=True, invoice=sent)   # bundled before 102.1
        self._charge('10')
        billed.bundle_charges(self.cust, actor=self.admin)
        sent.refresh_from_db()
        self.assertEqual((sent.status, sent.subtotal, sent.total,
                          list(sent.line_items.values_list('pk', 'unit_price'))), before)
        legacy.refresh_from_db()
        self.assertEqual(legacy.invoice_id, sent.pk)

    def test_bundling_is_audited(self):
        self._charge('10')
        inv, _ = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertTrue(AuditLog.objects.filter(object_type='psa.Invoice', object_id=inv.pk,
                                                extra_data__event='bundle_charges').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketDraftLockTests(_QueueBase):

    def test_double_click_creates_one_draft(self):
        self._card('100')
        self._entry(60)
        self.assertIsNotNone(self._invoice())
        self.assertIsNone(self._invoice())
        self.assertEqual(Invoice.objects.count(), 1)

    def test_stale_read_race_bills_nothing_twice(self):
        self._card('100')
        self._entry(60)
        stale = self.ticket.uninvoiced_billing_lines()
        first, _i, _c = billed.draft_ticket_invoice(self.ticket, actor=self.admin)
        with mock.patch.object(Ticket, 'uninvoiced_billing_lines', return_value=stale):
            with self.assertRaises(billed.DoubleBilling):
                billed.draft_ticket_invoice(self.ticket, actor=self.admin)
        self.assertEqual(list(Invoice.objects.values_list('pk', flat=True)), [first.pk])


# --- 102.2 --------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UnbilledListTests(_QueueBase):

    def _page(self):
        return self._client().get(reverse('psa:client_account', args=[self.cust.pk]))

    def test_list_excludes_invoiced_work_and_agrees_with_invoicing(self):
        self._card('100')
        billed_entry = self._entry(60, days_ago=2)
        item, _ = tc.add_item(self.ticket, self.admin, category='materials', description='Cable', unit_price='5')
        inv = self._invoice()
        self.assertIsNotNone(inv)
        open_entry = self._entry(30)
        TicketTimeEntry.objects.create(ticket=self.ticket, user=self.tech, started_at=timezone.now(),
                                       is_billable=True)   # running: not billable yet
        open_item, _ = tc.add_item(self.ticket, self.admin, category='materials', description='Plug',
                                   unit_price='3')
        ctx = self._page().context
        self.assertEqual([e.pk for e in ctx['unbilled_time']], [open_entry.pk])
        self.assertEqual([e.pk for e in ctx['unbilled_expenses']], [open_item.pk])
        self.assertNotIn(billed_entry.pk, [e.pk for e in ctx['unbilled_time']])
        self.assertNotIn(item.pk, [e.pk for e in ctx['unbilled_expenses']])
        # Same rule as the invoice writer.
        lines, _info = invoicing.ticket_billing_lines(self.ticket)
        self.assertEqual({ln['source_id'] for ln in lines if ln['source'] == 'time'}, {str(open_entry.pk)})
        self.assertEqual({ln['source_id'] for ln in lines if ln['source'] == 'expense'}, {str(open_item.pk)})

    def test_void_invoice_puts_work_back_on_the_list(self):
        self._card('100')
        e = self._entry(60)
        inv = self._invoice()
        self.assertEqual(list(self._page().context['unbilled_time']), [])
        self._void(inv)
        self.assertEqual([x.pk for x in self._page().context['unbilled_time']], [e.pk])

    def test_credit_memo_line_does_not_count_as_billed(self):
        e = self._entry(60)
        memo = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Memo',
                                      invoice_date=date.today(), is_credit_memo=True)
        InvoiceLineItem.objects.create(invoice=memo, description='x', source='time', source_id=str(e.pk))
        self.assertEqual([x.pk for x in billed.unbilled_time(TicketTimeEntry.objects.all())], [e.pk])
        self.assertEqual(InvoiceLineItem.billed_source_ids('time'), set())

    def test_balance_uses_the_same_rule_for_charges(self):
        self._charge('10')
        inv, _ = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertEqual(get_psa_balance(self.cust)['uninvoiced_charges'], D('0'))
        self._void(inv)
        self.assertEqual(get_psa_balance(self.cust)['uninvoiced_charges'], D('10'))


# --- 102.3 --------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReadyQueueTests(_QueueBase):

    def _group(self, user=None, customer=None):
        q = bq.build_queue(user or self.admin, customer=customer)
        return {g.client.pk: g for g in q}

    def test_queue_totals_equal_invoice_and_billing_preview(self):
        self._chargeable_ticket()
        g = self._group()[self.cust.pk]
        tg = g.tickets[0]
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(tg.total, invoicing.lines_total(lines))
        self.assertEqual(tg.total, D('105.00'))
        self.assertEqual(g.ready_total, D('105.00'))
        out = io.StringIO()
        call_command('billing_preview', customer=[self.cust.pk], stdout=out)
        self.assertIn('new $105.00', out.getvalue())
        invoices, _notes = bq.draft_from_queue(self.cust, actor=self.admin, ticket_ids=[self.ticket.pk])
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].subtotal, tg.total)
        self.assertEqual(invoices[0].status, 'draft')

    def test_draft_from_queue_twice_creates_one_draft(self):
        self._chargeable_ticket()
        self._charge('10')
        first, _ = bq.draft_from_queue(self.cust, actor=self.admin, ticket_ids=[self.ticket.pk],
                                       include_charges=True)
        second, notes = bq.draft_from_queue(self.cust, actor=self.admin, ticket_ids=[self.ticket.pk],
                                            include_charges=True)
        self.assertEqual((len(first), len(second)), (2, 0))
        self.assertEqual(Invoice.objects.count(), 2)
        self.assertTrue(notes)

    def test_draft_view_double_post(self):
        self._chargeable_ticket()
        url = reverse('psa:billing_queue_draft', args=[self.cust.pk])
        for _ in range(2):
            self.assertEqual(self._client().post(url, {'ticket': [self.ticket.pk]}).status_code, 302)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_hold_keeps_line_off_until_date_then_bills(self):
        e, item = self._chargeable_ticket()
        until = timezone.localdate() + timedelta(days=5)
        n = bq.decide(self.cust, [f'time:{e.pk}'], 'hold', actor=self.admin, reason='disputed', hold_until=until)
        self.assertEqual(n, 1)
        g = self._group()[self.cust.pk]
        self.assertEqual((g.ready_total, g.held_total), (D('5.00'), D('100.00')))
        inv = self._invoice()
        self.assertEqual(list(inv.line_items.values_list('source', flat=True)), ['expense'])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.billing_status, 'review')     # held work is still unbilled
        BillingQueueDecision.objects.update(hold_until=timezone.localdate())   # the date has come
        inv2 = self._invoice()
        self.assertEqual(list(inv2.line_items.values_list('source_id', flat=True)), [str(e.pk)])
        log = AuditLog.objects.filter(extra_data__event='billing_queue_decision').get()
        self.assertEqual((log.extra_data['decision'], log.extra_data['reason']), ('hold', 'disputed'))

    def test_excluded_lines_never_bill_until_included(self):
        e, item = self._chargeable_ticket()
        c = self._charge('10')
        bq.decide(self.cust, [f'time:{e.pk}', f'charge:{c.pk}'], 'exclude', actor=self.admin,
                  reason='goodwill')
        est = tc.ticket_estimate(self.ticket)
        self.assertEqual(est.entries[0]['state'], 'excluded')
        inv, _n = billed.bundle_charges(self.cust, actor=self.admin)
        self.assertIsNone(inv)
        invoices, _ = bq.draft_from_queue(self.cust, actor=self.admin, ticket_ids=[self.ticket.pk],
                                          include_charges=True)
        self.assertEqual(len(invoices), 1)
        self.assertEqual(list(invoices[0].line_items.values_list('source', flat=True)), ['expense'])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.billing_status, 'invoiced')
        # Still excluded later; out of the ready total.
        g = self._group()[self.cust.pk]
        self.assertEqual((g.ready_total, g.excluded_total), (D('0'), D('110.00')))
        bq.decide(self.cust, [f'time:{e.pk}', f'charge:{c.pk}'], 'include', actor=self.admin)
        inv = self._invoice()
        self.assertEqual(inv.subtotal, D('100.00'))
        self.assertEqual(billed.bundle_charges(self.cust, actor=self.admin)[1], 1)
        e.refresh_from_db()
        self.assertTrue(e.is_billable)      # the source record was never edited
        self.assertEqual(AuditLog.objects.filter(extra_data__event='billing_queue_decision').count(), 4)

    def test_approve_marks_ready_and_creates_nothing(self):
        e, _ = self._chargeable_ticket()
        bq.decide(self.cust, [f'time:{e.pk}'], 'approve', actor=self.admin)
        g = self._group()[self.cust.pk]
        self.assertEqual([ln.kind for ln in g.tickets[0].lines if ln.source == 'time'], ['approved'])
        self.assertEqual(g.ready_total, D('105.00'))
        self.assertFalse(Invoice.objects.exists())

    def test_reason_and_ownership_checks(self):
        e, _ = self._chargeable_ticket()
        with self.assertRaises(bq.QueueError):
            bq.decide(self.cust, [f'time:{e.pk}'], 'exclude', actor=self.admin, reason='')
        with self.assertRaises(bq.QueueError):
            bq.decide(self.cust, [f'time:{e.pk}'], 'hold', actor=self.admin, reason='x',
                      hold_until=timezone.localdate())
        other = Organization.objects.create(name='Other', slug='q-other')
        with self.assertRaises(bq.QueueError):
            bq.decide(other, [f'time:{e.pk}'], 'approve', actor=self.admin)
        with self.assertRaises(bq.QueueError):
            bq.decide(self.cust, ['bogus:1'], 'approve', actor=self.admin)
        self._invoice()
        with self.assertRaises(bq.QueueError):     # already on an invoice
            bq.decide(self.cust, [f'time:{e.pk}'], 'hold', actor=self.admin, reason='late')
        self.assertFalse(BillingQueueDecision.objects.exists())

    def test_adjustment_is_explicit_and_audited(self):
        e, _ = self._chargeable_ticket()
        before = TicketTimeEntry.objects.filter(pk=e.pk).values().get()
        adj = bq.add_adjustment(self.cust, actor=self.admin, description='Loyalty discount', amount='15',
                                is_credit=True, reason='agreed on call', ticket=self.ticket)
        self.assertEqual((adj.adjustment_reason, adj.ticket_id, adj.signed_amount),
                         ('agreed on call', self.ticket.pk, D('-15.00')))
        self.assertEqual(TicketTimeEntry.objects.filter(pk=e.pk).values().get(), before)
        g = self._group()[self.cust.pk]
        self.assertEqual(g.ready_total, D('90.00'))
        self.assertTrue(AuditLog.objects.filter(extra_data__event='billing_queue_adjustment').exists())
        for bad in ({'reason': ''}, {'amount': '-3'}, {'amount': 'abc'}, {'amount': 'NaN'}):
            kw = dict(description='x', amount='5', is_credit=False, reason='r')
            kw.update(bad)
            with self.assertRaises(bq.QueueError):
                bq.add_adjustment(self.cust, actor=self.admin, **kw)

    def test_adjust_view(self):
        self._sent()
        r = self._client().post(reverse('psa:billing_queue_adjust', args=[self.cust.pk]), {
            'description': 'Extra cabling', 'amount': '25', 'reason': 'approved by phone',
            'ticket_number': self.ticket.ticket_number})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Charge.objects.get().adjustment_reason, 'approved by phone')

    def test_milestones_listed_and_exclusion_respected(self):
        project = Project.objects.create(organization=self.cust, client_org=self.cust, name='Move',
                                         billing_type=Project.BILLING_MILESTONE)
        m = ProjectTask.objects.create(project=project, title='Phase 1', is_milestone=True, status='done',
                                       billing_amount=D('500'))
        g = self._group()[self.cust.pk]
        self.assertEqual([ln.source_id for ln in g.milestones], [str(m.pk)])
        bq.decide(self.cust, [f'milestone:{m.pk}'], 'exclude', actor=self.admin, reason='not delivered')
        self.assertEqual(project.billable_milestones(), [])
        inv, _msg = project.generate_invoice()
        self.assertIsNone(inv)

    def test_page_lists_queue(self):
        self._chargeable_ticket()
        r = self._client().get(reverse('psa:billing_review'))
        self.assertContains(r, 'id="ready-for-billing"')
        self.assertContains(r, 'Time: work')
        self.assertContains(r, '105.00')

    def test_decide_view(self):
        e, _ = self._chargeable_ticket()
        r = self._client().post(reverse('psa:billing_queue_decide', args=[self.cust.pk]),
                                {'item': [f'time:{e.pk}'], 'decision': 'exclude', 'reason': 'warranty'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(BillingQueueDecision.objects.get().state, 'excluded')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QueuePermissionTests(_QueueBase):

    def setUp(self):
        super().setUp()
        self.other = Organization.objects.create(name='Cust B', slug='q-cust-b')
        _enable_psa_for(self.other)
        self.other_ticket = Ticket.objects.create(
            organization=self.other, subject='B', queue=self.ticket.queue, priority=self.ticket.priority,
            ticket_type=self.ticket.ticket_type, status=self.ticket.status, billing_status='ready')
        self.e, _ = self._chargeable_ticket()
        self._charge('9', client=self.other)

    def test_viewer_sees_but_cannot_act(self):
        viewer = self._tech_with(billing_view_invoices=True)
        self.assertEqual({g.client.pk for g in bq.build_queue(viewer)}, {self.cust.pk, self.other.pk})
        self.assertFalse(bq.build_queue(viewer)[0].can_manage)
        with self.assertRaises(PermissionDenied):
            bq.decide(self.cust, [f'time:{self.e.pk}'], 'approve', actor=viewer)
        c = _login(viewer, self.cust)
        r = c.post(reverse('psa:billing_queue_decide', args=[self.cust.pk]),
                   {'item': [f'time:{self.e.pk}'], 'decision': 'approve'})
        self.assertEqual(r.status_code, 403)
        r = c.post(reverse('psa:billing_queue_adjust', args=[self.cust.pk]),
                   {'description': 'x', 'amount': '5', 'reason': 'r'})
        self.assertEqual(r.status_code, 403)
        r = c.post(reverse('psa:billing_queue_draft', args=[self.cust.pk]), {'ticket': [self.ticket.pk]})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(BillingQueueDecision.objects.exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(Charge.objects.count(), 1)

    def test_no_view_permission_sees_nothing(self):
        nobody = self._tech_with()
        self.assertEqual(bq.build_queue(nobody), [])
        c = _login(nobody, self.cust)
        r = c.post(reverse('psa:billing_queue_decide', args=[self.cust.pk]),
                   {'item': [f'time:{self.e.pk}'], 'decision': 'approve'})
        self.assertEqual(r.status_code, 404)

    def test_scoped_manager_reaches_only_own_customer(self):
        mgr = self._tech_with(scope=[self.cust], billing_view_invoices=True, billing_manage_charges=True)
        self.assertEqual([g.client.pk for g in bq.build_queue(mgr)], [self.cust.pk])
        c = _login(mgr, self.cust)
        r = c.post(reverse('psa:billing_queue_decide', args=[self.other.pk]),
                   {'item': [f'charge:{Charge.objects.get().pk}'], 'decision': 'exclude', 'reason': 'x'})
        self.assertEqual(r.status_code, 404)
        r = c.post(reverse('psa:billing_queue_decide', args=[self.cust.pk]),
                   {'item': [f'time:{self.e.pk}'], 'decision': 'approve'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(BillingQueueDecision.objects.get().state, 'approved')
        # Managing charges is not invoicing: drafting needs billing_send_invoices.
        r = c.post(reverse('psa:billing_queue_draft', args=[self.cust.pk]), {'ticket': [self.ticket.pk]})
        self.assertEqual(r.status_code, 403)

    def test_portal_user_gets_nothing(self):
        from django.contrib.auth.models import User

        from accounts.models import Membership, Role
        cust = User.objects.create_user('q_cust', 'c@c.test', 'pw')
        Membership.objects.create(user=cust, organization=self.cust, role=Role.ADMIN, is_active=True)
        self.assertEqual(bq.build_queue(cust), [])
        c = _login(cust, self.cust)
        r = c.post(reverse('psa:billing_queue_decide', args=[self.cust.pk]),
                   {'item': [f'time:{self.e.pk}'], 'decision': 'approve'})
        self.assertIn(r.status_code, (403, 404))
        self.assertFalse(BillingQueueDecision.objects.exists())
