"""Phase 102.4 (consolidated invoices) and 102.8 (Settings → Billing).

SQLite note: as in test_billing_queue_102, concurrency is simulated with a
stale read (a writer that read the work as unbilled before another one
committed); the claim-and-verify checks must still bill it once.
"""
import io
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa.billing import billed, consolidated
from psa.billing import config as cfg
from psa.billing import queue as bq
from psa.billing import ticket_charges as tc
from psa.models import (
    BillingSettingOverride, Charge, Contract, Invoice, InvoiceLineItem, Ticket,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for
from psa.tests.test_billing_queue_102 import _QueueBase
from psa.tests.test_ticket_time_charges_101_5 import _login

D = Decimal


class _ConsBase(_QueueBase):

    def setUp(self):
        super().setUp()
        self._card('100')
        self.t2 = self._ticket()
        self.t3 = self._ticket()

    def _work(self, ticket, minutes=60, item_price='5'):
        e = self._entry(minutes, ticket=ticket)
        item, _w = tc.add_item(ticket, self.admin, category='materials', description='Cable',
                               unit_price=item_price)
        Ticket.objects.filter(pk=ticket.pk).update(billing_status='ready')
        return e, item

    def _managed(self, **kw):
        d = dict(organization=self.cust, client_org=self.cust, name='Managed', contract_type='managed_services',
                 status='active', start_date=self.today - timedelta(days=60), total_hours=D('0'),
                 recurring_amount=D('500'), billing_frequency='monthly', next_billing_date=self.today)
        d.update(kw)
        return Contract.objects.create(**d)

    def _cons(self, tickets=(), charges=False, contract=None, user=None):
        return consolidated.draft_consolidated(
            self.cust, actor=user or self.admin, ticket_ids=[t.pk for t in tickets], include_charges=charges,
            contract_id=getattr(contract, 'pk', contract))


# --- 102.4 consolidated invoices -----------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConsolidatedDraftTests(_ConsBase):

    def test_contains_exactly_the_selected_lines_grouped_by_ticket(self):
        e1, i1 = self._work(self.ticket)
        e2, i2 = self._work(self.t2, minutes=30, item_price='7')
        e3, _i3 = self._work(self.t3)                     # not selected
        c = self._charge('10')
        res = self._cons([self.t2, self.ticket], charges=True)
        inv = res.invoice
        self.assertEqual(inv.status, 'draft')
        lines = list(inv.line_items.order_by('sort_order'))
        self.assertEqual([(ln.ticket_id, ln.source, ln.source_id) for ln in lines], [
            (self.ticket.pk, 'time', str(e1.pk)), (self.ticket.pk, 'expense', str(i1.pk)),
            (self.t2.pk, 'time', str(e2.pk)), (self.t2.pk, 'expense', str(i2.pk)),
            (None, 'charge', str(c.pk))])
        self.assertTrue(lines[0].description.startswith(self.ticket.ticket_number))
        self.assertEqual(inv.subtotal, D('100') + D('5') + D('50') + D('7') + D('10'))
        self.assertIsNone(inv.source_ticket_id)
        c.refresh_from_db()
        self.assertEqual(c.invoice_id, inv.pk)
        # The unselected ticket is untouched and still billable.
        self.assertFalse(InvoiceLineItem.objects.filter(source='time', source_id=str(e3.pk)).exists())
        for t, status in ((self.ticket, 'invoiced'), (self.t2, 'invoiced'), (self.t3, 'ready')):
            t.refresh_from_db()
            self.assertEqual(t.billing_status, status)
        log = AuditLog.objects.get(extra_data__event='consolidated_invoice')
        self.assertEqual(len(log.extra_data['lines']), 5)

    def test_retry_bills_once(self):
        self._work(self.ticket)
        self._charge('10')
        first = self._cons([self.ticket], charges=True)
        second = self._cons([self.ticket], charges=True)
        self.assertIsNotNone(first.invoice)
        self.assertIsNone(second.invoice)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_double_post_through_the_view(self):
        self._work(self.ticket)
        url = reverse('psa:billing_queue_draft', args=[self.cust.pk])
        data = {'ticket': [self.ticket.pk, self.t2.pk], 'consolidated': '1'}
        r1 = self._client().post(url, data)
        r2 = self._client().post(url, data)
        inv = Invoice.objects.get()
        self.assertEqual(r1.url, reverse('psa:invoice_detail', args=[inv.pk]))
        self.assertEqual(r2.status_code, 302)
        self.assertNotEqual(r2.url, r1.url)

    def test_stale_ticket_read_bills_nothing_twice(self):
        self._work(self.ticket)
        stale = self.ticket.uninvoiced_billing_lines()
        first = self._cons([self.ticket]).invoice
        with mock.patch.object(Ticket, 'uninvoiced_billing_lines', return_value=stale):
            with self.assertRaises(billed.DoubleBilling):
                self._cons([self.ticket])
        self.assertEqual(list(Invoice.objects.values_list('pk', flat=True)), [first.pk])

    def test_stale_charge_read_rolls_everything_back(self):
        self._work(self.t2)
        c = self._charge('10')
        stale = billed._read_charges(self.cust)
        first, _n = billed.bundle_charges(self.cust, actor=self.admin)
        with mock.patch.object(billed, '_read_charges', return_value=stale):
            with self.assertRaises(billed.DoubleBilling):
                self._cons([self.t2], charges=True)
        self.assertEqual(list(Invoice.objects.values_list('pk', flat=True)), [first.pk])
        # The ticket's work was not billed either: the whole draft rolled back.
        self.assertIsNotNone(self._cons([self.t2]).invoice)
        c.refresh_from_db()
        self.assertEqual(c.invoice_id, first.pk)

    def test_queue_reports_a_race_instead_of_failing(self):
        self._work(self.ticket)
        stale = self.ticket.uninvoiced_billing_lines()
        self._cons([self.ticket])
        with mock.patch.object(Ticket, 'uninvoiced_billing_lines', return_value=stale):
            inv, notes = bq.draft_consolidated_from_queue(self.cust, actor=self.admin, ticket_ids=[self.ticket.pk])
        self.assertIsNone(inv)
        self.assertIn('same time', notes[0])

    def test_held_and_excluded_are_never_included(self):
        e1, i1 = self._work(self.ticket)
        e2, _i2 = self._work(self.t2)
        c1, c2 = self._charge('10'), self._charge('20')
        bq.decide(self.cust, [f'time:{e1.pk}', f'charge:{c1.pk}'], 'hold', actor=self.admin, reason='disputed')
        bq.decide(self.cust, [f'time:{e2.pk}'], 'exclude', actor=self.admin, reason='goodwill')
        inv = self._cons([self.ticket, self.t2], charges=True).invoice
        pairs = set(inv.line_items.values_list('source', 'source_id'))
        self.assertNotIn(('time', str(e1.pk)), pairs)
        self.assertNotIn(('time', str(e2.pk)), pairs)
        self.assertNotIn(('charge', str(c1.pk)), pairs)
        self.assertIn(('charge', str(c2.pk)), pairs)
        self.assertIn(('expense', str(i1.pk)), pairs)
        c1.refresh_from_db()
        self.assertFalse(c1.invoiced)

    def test_nothing_selected_or_left_creates_nothing(self):
        res = self._cons([self.ticket], charges=True)
        self.assertIsNone(res.invoice)
        self.assertFalse(Invoice.objects.exists())
        self.assertTrue(res.notes)

    def test_other_customers_tickets_are_ignored(self):
        other = Organization.objects.create(name='Other', slug='c102-other')
        _enable_psa_for(other)
        t = Ticket.objects.create(organization=other, subject='x', queue=self.ticket.queue,
                                  priority=self.ticket.priority, ticket_type=self.ticket.ticket_type,
                                  status=self.ticket.status)
        self._entry(60, ticket=t)
        self.assertIsNone(self._cons([t]).invoice)

    def test_permissions(self):
        self._work(self.ticket)
        viewer = self._tech_with(billing_view_invoices=True, billing_manage_charges=True)
        with self.assertRaises(PermissionDenied):
            bq.draft_consolidated_from_queue(self.cust, actor=viewer, ticket_ids=[self.ticket.pk])
        r = _login(viewer, self.cust).post(reverse('psa:billing_queue_draft', args=[self.cust.pk]),
                                           {'ticket': [self.ticket.pk], 'consolidated': '1'})
        self.assertEqual(r.status_code, 403)
        portal = User.objects.create_user('c102_portal', 'p@x.test', 'pw')
        Membership.objects.create(user=portal, organization=self.cust, role=Role.ADMIN, is_active=True)
        r = _login(portal, self.cust).post(reverse('psa:billing_queue_draft', args=[self.cust.pk]),
                                           {'ticket': [self.ticket.pk], 'consolidated': '1'})
        self.assertIn(r.status_code, (403, 404))
        self.assertFalse(Invoice.objects.exists())

    def test_page_offers_the_consolidated_button(self):
        self._work(self.ticket)
        self._managed()
        r = self._client().get(reverse('psa:billing_review'))
        self.assertContains(r, 'Create one consolidated draft for selected')
        self.assertContains(r, 'Managed — period')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ContractFeeTests(_ConsBase):

    def test_fee_billed_once_per_period_and_generator_skips_it(self):
        k = self._managed()
        self._work(self.ticket)
        inv = self._cons([self.ticket], contract=k).invoice
        fee = inv.line_items.get(source='contract')
        self.assertEqual((fee.source_id, fee.unit_price), (str(k.pk), D('500.00')))
        self.assertEqual((inv.source_contract_id, inv.billing_period_start), (k.pk, self.today))
        k.refresh_from_db()
        self.assertGreater(k.next_billing_date, self.today)
        # Retrying finds the period billed.
        res = self._cons(contract=k)
        self.assertIsNone(res.invoice)
        self.assertIn('not included', ' '.join(res.notes))
        # The recurring generator does not bill the period again (cursor moved,
        # and the period key would refuse it anyway).
        call_command('psa_generate_recurring_invoices', '--no-catch-up', stdout=io.StringIO())
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(k.generate_invoice(on_date=self.today).pk, inv.pk)

    def test_generator_first_then_consolidated_defers(self):
        k = self._managed()
        call_command('psa_generate_recurring_invoices', '--no-catch-up', stdout=io.StringIO())
        self._work(self.ticket)
        res = self._cons([self.ticket], contract=k)
        self.assertFalse(res.invoice.line_items.filter(source='contract').exists())
        self.assertIn('due on', res.fee_deferred)
        self.assertEqual(Invoice.objects.filter(source_contract=k, billing_period_start=self.today).count(), 1)

    def test_period_billed_concurrently_rolls_back(self):
        k = self._managed()
        self._work(self.ticket)
        stale = consolidated.contract_fee_status(k)          # read before the generator committed
        self.assertTrue(stale.ok)
        k.generate_invoice(on_date=self.today)
        with mock.patch.object(consolidated, 'contract_fee_status', return_value=stale):
            with self.assertRaises(billed.DoubleBilling):
                self._cons([self.ticket], contract=k)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertFalse(InvoiceLineItem.objects.filter(source='time').exists())

    def test_fee_deferred_when_behind_or_not_due(self):
        k = self._managed(next_billing_date=self.today - timedelta(days=70))
        st = consolidated.contract_fee_status(k)
        self.assertFalse(st.ok)
        self.assertIn('periods behind', st.reason)
        k2 = self._managed(name='Later', next_billing_date=self.today + timedelta(days=5))
        self.assertIn('due on', consolidated.contract_fee_status(k2).reason)
        k3 = self._managed(name='Ending', cancel_at_period_end=True)
        self.assertFalse(consolidated.contract_fee_status(k3).ok)
        res = self._cons(contract=k)
        self.assertIsNone(res.invoice)
        self.assertFalse(Invoice.objects.exists())

    def test_fee_alone_with_charges(self):
        k = self._managed()
        self._charge('10')
        inv = self._cons(charges=True, contract=k).invoice
        self.assertEqual(sorted(inv.line_items.values_list('source', flat=True)), ['charge', 'contract'])
        self.assertEqual(inv.subtotal, D('510.00'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FinalizedInvoiceTests(_ConsBase):

    def _sent_consolidated(self):
        self._work(self.ticket)
        self._work(self.t2)
        inv = self._cons([self.ticket, self.t2]).invoice
        Invoice.objects.filter(pk=inv.pk).update(status='sent')
        inv.refresh_from_db()
        return inv

    def test_edits_refused_once_sent(self):
        inv = self._sent_consolidated()
        before = list(inv.line_items.values_list('pk', 'description', 'quantity', 'unit_price'))
        lines = list(inv.line_items.all())
        r = self._client().post(reverse('psa:invoice_edit', args=[inv.pk]), {
            'li_description': [ln.description for ln in lines], 'li_quantity': [str(ln.quantity) for ln in lines],
            'li_unit_price': ['1'] * len(lines), 'li_id': [ln.pk for ln in lines]})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'can no longer be changed')
        r = self._client().post(reverse('psa:invoice_edit', args=[inv.pk]), {'title': 'Rewritten'})
        inv.refresh_from_db()
        self.assertEqual(list(inv.line_items.values_list('pk', 'description', 'quantity', 'unit_price')), before)
        self.assertNotEqual(inv.title, 'Rewritten')
        from tax.services import apply_manual_override
        with self.assertRaises(ValueError):
            apply_manual_override(inv, self.admin, '1', 'try')

    def test_credit_note_is_the_correction_and_work_stays_billed(self):
        inv = self._sent_consolidated()
        r = self._client().post(reverse('psa:invoice_credit_memo', args=[inv.pk]),
                                {'reason': 'goodwill', 'amount': '20'})
        self.assertEqual(r.status_code, 302)
        memo = Invoice.objects.get(is_credit_memo=True)
        self.assertEqual((memo.credits_invoice_id, memo.total), (inv.pk, D('-20.00')))
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')
        self.assertIsNone(self._cons([self.ticket, self.t2]).invoice)   # nothing re-billed


# --- 102.8 Settings → Billing ----------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BillingSettingsTests(_ConsBase):

    URL = '/core/settings/billing/'

    def test_resolution_order_contract_customer_global(self):
        ss = SystemSetting.get_settings()
        ss.invoice_approval_threshold_total = D('1000')
        ss.save()
        k = self._managed()
        e = cfg.effective('invoice_approval_threshold_total', self.cust, k)
        self.assertEqual((e.value, e.source), (D('1000'), 'global'))
        cfg.save_override(self.cust, None, {'invoice_approval_threshold_total': '500'}, actor=self.admin)
        e = cfg.effective('invoice_approval_threshold_total', self.cust, k)
        self.assertEqual((e.value, e.source), (D('500'), 'customer'))
        cfg.save_override(self.cust, k, {'invoice_approval_threshold_total': '250'}, actor=self.admin)
        e = cfg.effective('invoice_approval_threshold_total', self.cust, k)
        self.assertEqual((e.value, e.source, e.customer_value), (D('250'), 'contract', D('500')))
        self.assertEqual(cfg.effective('invoice_approval_threshold_total', self.cust).value, D('500'))
        # Global-only settings ignore overrides.
        self.assertEqual(cfg.effective('psa_default_currency', self.cust, k).source, 'global')
        # Blank = inherit: clearing the contract value falls back to the customer.
        cfg.save_override(self.cust, k, {'invoice_approval_threshold_total': ''}, actor=self.admin)
        self.assertFalse(BillingSettingOverride.objects.filter(contract=k).exists())
        self.assertEqual(cfg.effective('invoice_approval_threshold_total', self.cust, k).source, 'customer')

    def test_override_drives_the_approval_flag(self):
        cfg.save_override(self.cust, None, {'invoice_approval_threshold_total': '50'}, actor=self.admin)
        self._work(self.ticket)
        inv = self._cons([self.ticket]).invoice
        inv.refresh_from_db()
        self.assertTrue(inv.requires_approval)

    def test_global_save_validates_and_audits(self):
        c = self._client()
        r = c.post(self.URL, {'action': 'save_global', 'invoice_approval_threshold_total': '-5',
                              'late_fee_pct': 'abc', 'psa_default_currency': 'dollars'})
        self.assertEqual(r.status_code, 200)
        for msg in ('cannot be negative', 'enter a number', 'three-letter'):
            self.assertContains(r, msg)
        ss = SystemSetting.get_settings()
        self.assertEqual(ss.invoice_approval_threshold_total, D('0'))
        self.assertFalse(AuditLog.objects.filter(extra_data__event='billing_settings').exists())
        for bad in ({'late_fee_pct': '150'}, {'late_fee_pct': '1.234'}, {'late_fee_min_days_overdue': '2.5'},
                    {'psa_default_tax_rate': 'NaN'}):
            with self.assertRaises(cfg.SettingError):
                cfg.save_global(bad, actor=self.admin)
        r = c.post(self.URL, {'action': 'save_global', 'invoice_approval_threshold_total': '2500',
                              'invoice_approval_overage_pct': '90', 'late_fee_pct': '1.5',
                              'late_fee_min_days_overdue': '30', 'psa_auto_push_recurring_invoices': '1',
                              'psa_default_tax_rate': '8.75', 'psa_default_currency': 'eur',
                              'quote_approval_threshold_total': '0'})
        self.assertEqual(r.status_code, 302)
        ss.refresh_from_db()
        self.assertEqual((ss.invoice_approval_threshold_total, ss.invoice_approval_overage_pct, ss.late_fee_pct,
                          ss.late_fee_min_days_overdue, ss.psa_auto_push_recurring_invoices,
                          ss.psa_default_tax_rate, ss.psa_default_currency),
                         (D('2500'), 90, D('1.5'), 30, True, D('0.0875'), 'EUR'))
        log = AuditLog.objects.get(extra_data__event='billing_settings')
        self.assertEqual(log.extra_data['changed']['invoice_approval_threshold_total'],
                         {'from': '0.00', 'to': '2500.00'})
        # Unticking the checkbox turns automatic push off.
        c.post(self.URL, {'action': 'save_global', 'late_fee_pct': '1.5'})
        ss.refresh_from_db()
        self.assertFalse(ss.psa_auto_push_recurring_invoices)

    def test_override_save_validates_and_audits(self):
        k = self._managed()
        c = self._client()
        r = c.post(self.URL, {'action': 'save_override', 'customer': self.cust.pk, 'contract': k.pk,
                              'late_fee_pct': '-1'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(BillingSettingOverride.objects.exists())
        c.post(self.URL, {'action': 'save_override', 'customer': self.cust.pk, 'contract': k.pk,
                          'late_fee_pct': '2', 'note': 'per contract terms'})
        row = BillingSettingOverride.objects.get()
        self.assertEqual((row.scope_key, row.late_fee_pct, row.note), (f'contract:{k.pk}', D('2.00'),
                                                                        'per contract terms'))
        self.assertTrue(AuditLog.objects.filter(extra_data__event='billing_settings', extra_data__scope='contract',
                                                organization=self.cust).exists())
        r = c.get(self.URL, {'customer': self.cust.pk, 'contract': k.pk})
        self.assertContains(r, 'Contract override')
        c.post(self.URL, {'action': 'delete_override', 'customer': self.cust.pk, 'contract': k.pk})
        self.assertFalse(BillingSettingOverride.objects.exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='billing_settings', action='delete').exists())
        # A contract of another customer is refused.
        other = Organization.objects.create(name='Other', slug='c102-o2')
        with self.assertRaises(cfg.SettingError):
            cfg.save_override(other, k, {'late_fee_pct': '1'}, actor=self.admin)

    def test_no_retroactive_change_to_existing_invoices(self):
        sent = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Old',
                                      invoice_date=self.today - timedelta(days=60),
                                      due_date=self.today - timedelta(days=40))
        InvoiceLineItem.objects.create(invoice=sent, description='old', quantity=1, unit_price=D('5000'))
        sent.recompute_totals()
        Invoice.objects.filter(pk=sent.pk).update(status='sent')
        fee = Charge.objects.create(organization=self.cust, client_org=self.cust, amount=D('7'),
                                    description=f'Late fee for {sent.invoice_number} (old)',
                                    charge_date=self.today - timedelta(days=5))
        sent.refresh_from_db()
        snap = lambda i: (i.status, i.subtotal, i.tax_rate, i.tax_amount, i.total, i.currency,  # noqa: E731
                          i.requires_approval, i.approval_reason,
                          list(i.line_items.values_list('pk', 'description', 'quantity', 'unit_price')))
        before = snap(sent)
        cfg.save_global({'invoice_approval_threshold_total': '100', 'invoice_approval_overage_pct': '1',
                         'late_fee_pct': '5', 'late_fee_min_days_overdue': '1', 'psa_default_tax_rate': '10',
                         'psa_default_currency': 'EUR'}, actor=self.admin)
        cfg.save_override(self.cust, None, {'invoice_approval_threshold_total': '10', 'late_fee_pct': '9'},
                          actor=self.admin)
        # The invoice is saved again (as a status / payment update does) and
        # the late-fee job runs.
        sent.refresh_from_db()
        sent.save()
        sent.recompute_totals()
        call_command('psa_apply_late_fees', stdout=io.StringIO())
        sent.refresh_from_db()
        after = snap(sent)
        self.assertEqual(after, before)
        fee.refresh_from_db()
        self.assertEqual(fee.amount, D('7'))
        # New drafts get the new values.
        self._work(self.ticket)
        new = self._cons([self.ticket]).invoice
        new.refresh_from_db()
        self.assertTrue(new.requires_approval)

    def test_late_fee_uses_the_customer_override(self):
        inv = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Late',
                                     invoice_date=self.today - timedelta(days=60),
                                     due_date=self.today - timedelta(days=20))
        InvoiceLineItem.objects.create(invoice=inv, description='x', quantity=1, unit_price=D('1000'))
        inv.recompute_totals()
        Invoice.objects.filter(pk=inv.pk).update(status='sent')
        out = io.StringIO()
        call_command('psa_apply_late_fees', stdout=out)            # global off
        self.assertIn('disabled', out.getvalue())
        cfg.save_override(self.cust, None, {'late_fee_pct': '2', 'late_fee_min_days_overdue': '10'},
                          actor=self.admin)
        call_command('psa_apply_late_fees', stdout=io.StringIO())
        self.assertEqual(Charge.objects.get().amount, D('20.00'))
        call_command('psa_apply_late_fees', stdout=io.StringIO())   # once per invoice
        self.assertEqual(Charge.objects.count(), 1)
        cfg.save_override(self.cust, None, {'late_fee_pct': '2', 'late_fee_min_days_overdue': '30'},
                          actor=self.admin)
        Charge.objects.all().delete()
        call_command('psa_apply_late_fees', stdout=io.StringIO())   # not overdue long enough
        self.assertFalse(Charge.objects.exists())

    def test_page_permissions(self):
        other = Organization.objects.create(name='Other', slug='c102-o3')
        _enable_psa_for(other)
        self.assertEqual(self._client().get(self.URL).status_code, 200)
        nobody = self._tech_with(billing_view_invoices=True)
        self.assertEqual(_login(nobody, self.cust).get(self.URL).status_code, 404)
        portal = User.objects.create_user('c102_portal2', 'p@x.test', 'pw')
        Membership.objects.create(user=portal, organization=self.cust, role=Role.ADMIN, is_active=True)
        self.assertEqual(_login(portal, self.cust).get(self.URL).status_code, 404)
        self.assertFalse(cfg.can_view(portal))

        billing_admin = self._tech_with(billing_approve_invoices=True)
        c = _login(billing_admin, self.cust)
        r = c.get(self.URL)
        self.assertTrue(r.context['can_edit_global'])
        c.post(self.URL, {'action': 'save_global', 'late_fee_pct': '3'})
        self.assertEqual(SystemSetting.get_settings().late_fee_pct, D('3'))

        scoped = self._tech_with(scope=[self.cust], billing_approve_invoices=True)
        c = _login(scoped, self.cust)
        r = c.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['can_edit_global'])
        self.assertEqual([o.pk for o in r.context['customers']], [self.cust.pk])
        r = c.post(self.URL, {'action': 'save_global', 'late_fee_pct': '9'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(SystemSetting.get_settings().late_fee_pct, D('3'))
        r = c.post(self.URL, {'action': 'save_override', 'customer': other.pk, 'late_fee_pct': '1'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(c.get(self.URL, {'customer': other.pk}).status_code, 404)
        c.post(self.URL, {'action': 'save_override', 'customer': self.cust.pk, 'late_fee_pct': '1'})
        self.assertEqual(BillingSettingOverride.objects.get().client_org_id, self.cust.pk)

    def test_page_shows_effective_values_and_sources(self):
        cfg.save_override(self.cust, None, {'late_fee_pct': '4'}, actor=self.admin)
        r = self._client().get(self.URL, {'customer': self.cust.pk})
        self.assertContains(r, 'Customer override')
        self.assertContains(r, 'Settings → Billing (all customers)')
        effective = {e.key: e for e in r.context['effective']}
        self.assertEqual(effective['late_fee_pct'].value, D('4'))

    def test_nav_links_the_page(self):
        from core import navigation
        names = {t.url_name for s in navigation.SECTIONS for t in s.tabs}
        self.assertIn('core:settings_billing', names)
