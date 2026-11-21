"""Phase 101.5-101.7: Time & Charges on the ticket, Add Item and the ticket
billing summary.

The estimate on the ticket must be exactly what "Invoice this ticket" bills,
so most tests compare the two."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from inventory.models import InventoryItem, InventoryTransaction
from pricing.models import BillingRule, PriceBook, PriceBookItem
from psa.billing import ledger
from psa.billing import ticket_charges as tc
from psa.models import (
    Contract, Invoice, PrepaidPosting, Ticket, TicketExpense, TicketStatus, TicketTimeEntry,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _make_msp_tech
from psa.tests.test_ticket_invoicing_101_4 import _Base

D = Decimal


def _login(user, org=None):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    s.save()
    return c


class _ChargesBase(_Base):

    def _tech_with(self, scope=None, **flags):
        flags.setdefault('tickets_view', True)
        flags.setdefault('tickets_edit', True)
        flags.setdefault('docs_create', True)   # a write role (core.decorators.require_write)
        role = RoleTemplate.objects.create(name=f'r{RoleTemplate.objects.count()}', **flags)
        u = User.objects.create_user(f'tc_t{User.objects.count()}', 'x@x.test', 'pw')
        _make_msp_tech(u)
        p = u.profile
        p.global_role_template = role
        if scope is not None:
            p.client_scope = 'selected'
        p.save()
        if scope is not None:
            p.scope_organizations.set(scope)
        return u

    def _lines(self, inv):
        return sorted((ln.quantity, ln.unit_price) for ln in inv.line_items.all())

    def _est_lines(self, est):
        return sorted((D(str(ln['quantity'])).quantize(D('0.01')), D(str(ln['unit_price'])).quantize(D('0.01')))
                      for ln in est.lines)

    def assertEstimateIsInvoice(self):
        est = tc.ticket_estimate(self.ticket)
        expected_total, expected_lines = est.ready_total, self._est_lines(est)
        inv = self._invoice()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.subtotal, expected_total)
        self.assertEqual(self._lines(inv), expected_lines)
        return est, inv

    def _book_item(self, **kw):
        book = PriceBook.objects.get_or_create(name='Main', defaults={'is_active': True})[0]
        d = dict(price_book=book, name='SSD 1TB', sku='SSD1', item_type='hardware', default_price=D('120'),
                 cost=D('80'))
        d.update(kw)
        return PriceBookItem.objects.create(**d)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EstimateEqualsInvoiceTests(_ChargesBase):

    def test_prepaid_block(self):
        self._contract()
        e = self._entry(120)
        self._approve(e)
        est, inv = self.assertEstimateIsInvoice()
        self.assertEqual(inv.subtotal, D('0'))
        row = est.entries[0]
        self.assertEqual((row['state'], row['covered_hours'], row['charge']), ('ready', D('2.00'), D('0')))
        self.assertEqual(est.hours['remaining_now'], D('8.00'))

    def test_partial_overage_forecast_matches_invoice_after_approval(self):
        c = self._contract(total_hours=D('1'))
        BillingRule.objects.create(name='15 up', contract=c, increment_minutes=15, rounding_mode='up')
        e = self._entry(170)
        before = tc.ticket_estimate(self.ticket)
        row = before.entries[0]
        self.assertEqual(row['state'], 'forecast')
        self.assertEqual(before.ready_total, D('0'))
        # 60 min prepaid, 110 min overage -> 120 min billed at 150.
        self.assertEqual((row['covered_hours'], row['charged_hours'], row['charge']),
                         (D('1.00'), D('2.00'), D('300.00')))
        self.assertEqual((before.hours['remaining_now'], before.hours['remaining_after']), (D('1.00'), D('0.00')))
        self._approve(e)
        est, inv = self.assertEstimateIsInvoice()
        self.assertEqual(inv.subtotal, before.forecast_total)

    def test_time_and_materials_minimum_increment_and_trip_fee(self):
        self._card('120', rate_type='onsite')
        self._card('100')
        BillingRule.objects.create(name='Rules', minimum_billable_minutes=60, increment_minutes=15,
                                   rounding_mode='up', dispatch_fee=D('45'))
        noon = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        self._entry(20, rate_type='onsite', at=noon)        # minimum: 1h
        self._entry(70, at=noon + timedelta(hours=2))      # increment: 75 min
        est, inv = self.assertEstimateIsInvoice()
        self.assertEqual(est.fees_total, D('45'))
        hours = sorted(ln.quantity for ln in inv.line_items.filter(source='time'))
        self.assertEqual(hours, [D('1.00'), D('1.25')])  # 20 min -> 1h minimum; 70 min -> 75 min

    def test_unlimited_coverage_is_zero(self):
        self._contract(contract_type='managed_services', total_hours=D('0'))
        self._card('150')
        self._entry(240)
        est, inv = self.assertEstimateIsInvoice()
        self.assertEqual(inv.subtotal, D('0'))
        self.assertTrue(est.hours['unlimited'])

    def test_items_and_credit_on_the_invoice(self):
        self._card('100')
        self._entry(60)
        item = self._book_item()
        tc.add_item(self.ticket, self.admin, category='hardware', quantity='2', price_book_item=item)
        tc.add_item(self.ticket, self.admin, category='materials', description='Cable', unit_price='5.50',
                    quantity='3')
        tc.add_item(self.ticket, self.admin, category='credit', description='Sorry', unit_price='25')
        est, inv = self.assertEstimateIsInvoice()
        self.assertEqual(inv.subtotal, D('100') + D('240') + D('16.50') - D('25'))
        hw = inv.line_items.get(price_book_item=item)
        self.assertEqual((hw.quantity, hw.unit_price, hw.unit_cost), (D('2.00'), D('120.00'), D('80.00')))
        # Billed once.
        self.assertIsNone(self._invoice())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ClassificationTests(_ChargesBase):

    def test_no_charge_classifications(self):
        self._contract(total_hours=D('1'))
        for cls in ('warranty', 'goodwill', 'non_billable'):
            e = self._entry(30)
            TicketTimeEntry.objects.filter(pk=e.pk).update(classification=cls)
            e.refresh_from_db()
            e.save()
            self.assertFalse(TicketTimeEntry.objects.get(pk=e.pk).is_billable)
        self._approve(*TicketTimeEntry.objects.all())
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines, [])
        self.assertFalse(PrepaidPosting.objects.filter(kind='consumption').exists())
        est = tc.ticket_estimate(self.ticket)
        self.assertEqual({r['state'] for r in est.entries}, {'no_charge'})

    def test_awaiting_classification_blocks_invoicing_with_warning(self):
        c = self._contract(total_hours=D('5'))
        e = TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.tech, started_at=timezone.now() - timedelta(hours=1),
            ended_at=timezone.now(), duration_minutes=60, classification='awaiting')
        self.assertTrue(e.is_billable)
        self._approve(e)
        self.assertFalse(PrepaidPosting.objects.filter(kind='consumption', contract=c).exists())
        self.assertEqual(TicketTimeEntry.objects.get(pk=e.pk).billing_resolution, 'needs_classification')
        lines, info = self.ticket.uninvoiced_billing_lines()
        self.assertEqual((lines, info['needs_classification']), ([], [e]))
        r = self._client().post(f'/psa/invoices/from-ticket/{self.ticket.ticket_number}/', follow=True)
        self.assertContains(r, 'need')
        self.assertContains(r, 'classification')
        self.assertFalse(Invoice.objects.exists())
        self.assertTrue(any('classification' in b for b in tc.ticket_estimate(self.ticket).blockers))

    def test_covered_without_agreement_needs_review(self):
        self._card('100')
        e = self._entry(60)
        TicketTimeEntry.objects.filter(pk=e.pk).update(classification='covered')
        lines, info = self.ticket.uninvoiced_billing_lines()
        self.assertEqual((lines, len(info['needs_classification'])), ([], 1))

    def test_classification_change_on_approved_time_reverses_through_ledger(self):
        c = self._contract()
        e = self._entry(60)
        self._approve(e)
        self.assertEqual(ledger.summary(c).remaining_hours, D('9.00'))
        with self.assertRaises(tc.ChargeError):
            tc.update_entry(TicketTimeEntry.objects.get(pk=e.pk), actor=self.admin, classification='warranty')
        r = self._client().post(reverse('psa:time_entry_correct', args=[e.pk]),
                                {'classification': 'warranty', 'reason': 'under warranty',
                                 'duration_minutes': '60'})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertEqual((e.classification, e.is_billable), ('warranty', False))
        self.assertTrue(PrepaidPosting.objects.filter(kind='reversal', time_entry_ref=e.pk).exists())
        self.assertEqual(ledger.summary(c).remaining_hours, D('10.00'))

    def test_invoiced_time_cannot_be_reclassified(self):
        self._card('100')
        e = self._entry(60)
        self._invoice()
        with self.assertRaises(tc.ChargeError):
            tc.update_entry(TicketTimeEntry.objects.get(pk=e.pk), actor=self.admin, classification='goodwill')

    def test_manual_form_sets_classification_and_work_type(self):
        r = self._client().post(reverse('psa:time_entry_manual', args=[self.ticket.ticket_number]),
                                {'minutes': '30', 'classification': 'goodwill', 'work_type': 'onsite',
                                 'is_billable': '1'})
        self.assertEqual(r.status_code, 302)
        e = TicketTimeEntry.objects.get()
        self.assertEqual((e.classification, e.is_billable, e.rate_type), ('goodwill', False, 'onsite'))
        r = self._client().post(reverse('psa:ticket_time_update', args=[self.ticket.ticket_number, e.pk]),
                                {'classification': 'billable', 'work_type': 'remote'})
        e.refresh_from_db()
        self.assertEqual((e.classification, e.is_billable, e.rate_type), ('billable', True, 'remote'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AgreementPickerTests(_ChargesBase):

    def setUp(self):
        super().setUp()
        self.valid = self._contract(name='Valid block', contract_type='block_hours')
        self.expired = self._contract(name='Expired one', start_date=self.today - timedelta(days=400),
                                      end_date=self.today - timedelta(days=100))
        other = Organization.objects.create(name='Other', slug='tc-other')
        self.foreign = self._contract(name='Foreign deal', client_org=other, organization=other)

    def test_picker_only_with_permission(self):
        plain = self._tech_with()
        html = _login(plain, self.cust).get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertNotIn('id="timeAgreement"', html)
        r = _login(plain, self.cust).post(reverse('psa:time_entry_manual', args=[self.ticket.ticket_number]),
                                          {'minutes': '30', 'contract_id': self.valid.pk})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TicketTimeEntry.objects.exists())

        biller = self._tech_with(billing_view_invoices=True, billing_manage_charges=True)
        resp = _login(biller, self.cust).get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertContains(resp, 'id="timeAgreement"')
        names = {c.name for c in resp.context['agreement_options']}
        self.assertEqual(names, {'Valid block'})
        r = _login(biller, self.cust).post(reverse('psa:time_entry_manual', args=[self.ticket.ticket_number]),
                                           {'minutes': '30', 'contract_id': self.foreign.pk})
        self.assertEqual(r.status_code, 403)
        r = _login(biller, self.cust).post(reverse('psa:time_entry_manual', args=[self.ticket.ticket_number]),
                                           {'minutes': '30', 'contract_id': self.valid.pk})
        self.assertEqual(r.status_code, 302)
        e = TicketTimeEntry.objects.get()
        self.assertEqual((e.billing_contract_id, e.billing_contract_chosen), (self.valid.pk, True))

    def test_entry_agreement_endpoint_refuses_invalid(self):
        e = self._entry(30)
        plain = self._tech_with()
        url = reverse('psa:ticket_time_agreement', args=[self.ticket.ticket_number, e.pk])
        self.assertEqual(_login(plain, self.cust).post(url, {'contract_id': self.valid.pk}).status_code, 403)
        biller = self._tech_with(billing_view_invoices=True, billing_manage_charges=True)
        _login(biller, self.cust).post(url, {'contract_id': self.expired.pk})
        self.assertIsNone(TicketTimeEntry.objects.get(pk=e.pk).billing_contract_id)
        _login(biller, self.cust).post(url, {'contract_id': self.valid.pk})
        self.assertEqual(TicketTimeEntry.objects.get(pk=e.pk).billing_contract_id, self.valid.pk)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AddItemTests(_ChargesBase):

    def test_add_from_catalog_and_one_off_via_view(self):
        item = self._book_item()
        c = self._client()
        url = reverse('psa:ticket_item_add', args=[self.ticket.ticket_number])
        c.post(url, {'category': 'hardware', 'price_book_item': item.pk, 'quantity': '1', 'is_billable': '1',
                     'is_taxable': '1'})
        c.post(url, {'category': 'shipping', 'description': 'Courier', 'unit_price': '12.00', 'quantity': '1',
                     'is_billable': '1'})
        rows = {r.description: r for r in TicketExpense.objects.all()}
        self.assertEqual((rows['SSD 1TB'].unit_price, rows['SSD 1TB'].sku, rows['SSD 1TB'].unit_cost),
                         (D('120.00'), 'SSD1', D('80.00')))
        self.assertEqual((rows['Courier'].unit_price, rows['Courier'].is_taxable), (D('12.00'), False))

    def test_catalog_item_of_another_customers_book_is_refused(self):
        other = Organization.objects.create(name='O2', slug='tc-o2')
        book = PriceBook.objects.create(name='Theirs', organization=other)
        item = self._book_item(price_book=book, sku='X')
        r = self._client().post(reverse('psa:ticket_item_add', args=[self.ticket.ticket_number]),
                                {'category': 'hardware', 'price_book_item': item.pk, 'quantity': '1'})
        self.assertEqual(r.status_code, 404)

    def test_price_below_minimum_needs_discount_permission(self):
        item = self._book_item(minimum_price=D('100'))
        tech = self._tech_with()
        with self.assertRaises(tc.ChargeError):
            tc.add_item(self.ticket, tech, category='hardware', price_book_item=item, unit_price='90')
        row, _ = tc.add_item(self.ticket, self.admin, category='hardware', price_book_item=item, unit_price='90')
        self.assertEqual(row.unit_price, D('90'))

    def test_credit_needs_permission(self):
        tech = self._tech_with()
        r = _login(tech, self.cust).post(reverse('psa:ticket_item_add', args=[self.ticket.ticket_number]),
                                         {'category': 'credit', 'description': 'Goodwill', 'unit_price': '50'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TicketExpense.objects.exists())
        biller = self._tech_with(billing_manage_charges=True)
        _login(biller, self.cust).post(reverse('psa:ticket_item_add', args=[self.ticket.ticket_number]),
                                       {'category': 'credit', 'description': 'Goodwill', 'unit_price': '50'})
        row = TicketExpense.objects.get()
        self.assertTrue(row.is_credit)
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines[0]['unit_price'], D('-50'))
        # The plain technician cannot remove it either.
        r = _login(tech, self.cust).post(reverse('psa:ticket_item_remove', args=[self.ticket.ticket_number, row.pk]))
        self.assertEqual(r.status_code, 403)

    def test_cost_and_margin_hidden_without_permission(self):
        item = self._book_item()
        tc.add_item(self.ticket, self.admin, category='hardware', price_book_item=item)
        tech = self._tech_with()
        c = _login(tech, self.cust)
        resp = c.get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertFalse(resp.context['show_costs'])
        self.assertNotIn('cost', resp.context['charges'].items[0])
        self.assertIsNone(resp.context['charges'].cost_total)
        self.assertNotContains(resp, 'Unit cost')
        self.assertNotContains(resp, '$80.00')
        body = c.get(reverse('psa:ticket_charges_json', args=[self.ticket.ticket_number])).json()
        self.assertNotIn('unit_cost', body['items'][0])
        self.assertNotIn('cost_total', body)
        cat = c.get(reverse('psa:ticket_catalog_json', args=[self.ticket.ticket_number]) + '?q=SSD').json()
        self.assertEqual(cat['results'][0]['price'], '120.00')
        self.assertNotIn('cost', cat['results'][0])
        review = c.get(reverse('psa:ticket_charges_review', args=[self.ticket.ticket_number]))
        self.assertNotContains(review, 'Unit cost')
        # A posted cost from someone without the permission is ignored.
        row, _ = tc.add_item(self.ticket, tech, category='materials', description='Tape', unit_price='3',
                             unit_cost='1')
        self.assertIsNone(row.unit_cost)

        seer = self._tech_with(pricing_view_internal_cost_rates=True)
        c2 = _login(seer, self.cust)
        resp = c2.get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertContains(resp, 'Unit cost')
        body = c2.get(reverse('psa:ticket_charges_json', args=[self.ticket.ticket_number])).json()
        hw = [i for i in body['items'] if i['description'] == 'SSD 1TB'][0]
        self.assertEqual((hw['unit_cost'], hw['margin']), ('80.00', '40.00'))
        cat = c2.get(reverse('psa:ticket_catalog_json', args=[self.ticket.ticket_number])).json()
        self.assertEqual(cat['results'][0]['cost'], '80.00')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InventoryTests(_ChargesBase):

    def setUp(self):
        super().setUp()
        self.stock = InventoryItem.objects.create(name='Patch cable', quantity=5, organization=self.cust,
                                                  unit_cost=D('2'))

    def _add(self, qty='2'):
        r = self._client().post(reverse('psa:ticket_item_add', args=[self.ticket.ticket_number]),
                                {'category': 'materials', 'inventory_item': self.stock.pk, 'quantity': qty,
                                 'unit_price': '10', 'is_billable': '1'})
        self.assertEqual(r.status_code, 302)
        return TicketExpense.objects.latest('pk')

    def test_reserve_consume_once(self):
        row = self._add()
        self.stock.refresh_from_db()
        self.assertEqual((row.inventory_state, self.stock.quantity), ('reserved', 5))
        self.assertEqual(tc.available_quantity(self.stock), D('3'))
        self.assertTrue(InventoryTransaction.objects.filter(item=self.stock, transaction_type='reserve').exists())
        # Reserved stock is not billed yet.
        lines, info = self.ticket.uninvoiced_billing_lines()
        self.assertEqual((lines, info['unused_stock']), ([], [row]))
        url = reverse('psa:ticket_item_used', args=[self.ticket.ticket_number, row.pk])
        c = self._client()
        c.post(url)
        c.post(url)
        self.assertFalse(tc.consume(TicketExpense.objects.get(pk=row.pk), self.admin))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 3)
        self.assertEqual(InventoryTransaction.objects.filter(item=self.stock, transaction_type='stock_out').count(), 1)
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines[0]['quantity'], D('2'))

    def test_release_on_removal(self):
        row = self._add()
        self._client().post(reverse('psa:ticket_item_remove', args=[self.ticket.ticket_number, row.pk]))
        self.assertFalse(TicketExpense.objects.filter(pk=row.pk).exists())
        self.stock.refresh_from_db()
        self.assertEqual((self.stock.quantity, tc.available_quantity(self.stock)), (5, D('5')))
        self.assertTrue(InventoryTransaction.objects.filter(item=self.stock, transaction_type='release').exists())

    def test_used_stock_returned_on_removal_once(self):
        row = self._add('3')
        tc.consume(row, self.admin)
        self.assertEqual(tc.release(row, self.admin), 'returned')
        self.assertEqual(tc.release(row, self.admin), '')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 5)

    def test_invoiced_item_cannot_be_removed(self):
        row = self._add()
        tc.consume(row, self.admin)
        self._invoice()
        self._client().post(reverse('psa:ticket_item_remove', args=[self.ticket.ticket_number, row.pk]))
        self.assertTrue(TicketExpense.objects.filter(pk=row.pk).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BillingStatusTests(_ChargesBase):

    def _close(self, ticket=None):
        t = ticket or self.ticket
        t.status = TicketStatus.objects.filter(is_terminal=True, requires_signoff=False).first()
        t.closed_at = timezone.now()
        t.save()
        t.refresh_from_db()
        return t

    def test_closing_with_unbilled_items_flags_review(self):
        tc.add_item(self.ticket, self.admin, category='materials', description='Cable', unit_price='5')
        t = self._close()
        self.assertEqual(t.billing_status, 'review')
        self.assertIn('unbilled', t.billing_status_note)
        self.assertFalse(Invoice.objects.exists())
        # Still shown on the ticket and in the billing review.
        resp = self._client().get(f'/psa/t/{t.ticket_number}/')
        self.assertContains(resp, 'Cable')
        resp = self._client().get('/psa/billing-review/')
        self.assertContains(resp, t.ticket_number)

    def test_closing_without_unbilled_work_flags_nothing(self):
        self.assertEqual(self._close().billing_status, '')

    def test_send_to_billing_creates_no_invoice(self):
        self._card('100')
        self._entry(60)
        r = self._client().post(reverse('psa:ticket_send_to_billing', args=[self.ticket.ticket_number]))
        self.assertEqual(r.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.billing_status, 'ready')
        self.assertFalse(Invoice.objects.exists())
        inv = self._invoice()
        self.ticket.refresh_from_db()
        self.assertEqual((inv.subtotal, self.ticket.billing_status), (D('100.00'), 'invoiced'))

    def test_send_to_billing_with_blockers_is_review(self):
        TicketTimeEntry.objects.create(ticket=self.ticket, user=self.tech, started_at=timezone.now(),
                                       classification='awaiting')
        tc.send_to_billing(self.ticket, self.admin)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.billing_status, 'review')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ScopingTests(_ChargesBase):

    def setUp(self):
        super().setUp()
        self.other = Organization.objects.create(name='Cust B', slug='tc-cust-b')
        _enable_psa_for(self.other)
        self.other_ticket = Ticket.objects.create(
            organization=self.other, subject='B', queue=self.ticket.queue, priority=self.ticket.priority,
            ticket_type=self.ticket.ticket_type, status=self.ticket.status)
        self.restricted = self._tech_with(scope=[self.cust], billing_view_invoices=True,
                                          billing_manage_charges=True, pricing_view_internal_cost_rates=True)

    def test_out_of_scope_ticket_is_404(self):
        c = _login(self.restricted, self.cust)
        n = self.other_ticket.ticket_number
        self.assertEqual(c.get(reverse('psa:ticket_charges_json', args=[n])).status_code, 404)
        self.assertEqual(c.post(reverse('psa:ticket_item_add', args=[n]),
                                {'category': 'other', 'description': 'x', 'unit_price': '1'}).status_code, 404)
        self.assertEqual(c.post(reverse('psa:ticket_send_to_billing', args=[n])).status_code, 404)
        self.assertFalse(TicketExpense.objects.exists())
        self.assertEqual(c.get(reverse('psa:ticket_charges_json',
                                       args=[self.ticket.ticket_number])).status_code, 200)

    def test_stock_of_another_customer_is_refused(self):
        foreign = InventoryItem.objects.create(name='Theirs', quantity=3, organization=self.other)
        r = self._client().post(reverse('psa:ticket_item_add', args=[self.ticket.ticket_number]),
                                {'category': 'parts', 'inventory_item': foreign.pk, 'unit_price': '1'})
        self.assertEqual(r.status_code, 404)

    def test_billing_queue_per_customer(self):
        self.ticket.billing_status = 'ready'
        self.ticket.save()
        self.other_ticket.billing_status = 'review'
        self.other_ticket.save()
        self.assertEqual([t.pk for t in tc.billing_queue(self.restricted)], [self.ticket.pk])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalUserTests(_ChargesBase):

    def test_customer_user_sees_none_of_it(self):
        self.ticket.client_can_view = True
        self.ticket.save()
        self._card('100')
        e = self._entry(60)
        TicketTimeEntry.objects.filter(pk=e.pk).update(classification='warranty')
        tc.add_item(self.ticket, self.admin, category='hardware', price_book_item=self._book_item())
        cust = User.objects.create_user('tc_cust', 'c@c.test', 'pw')
        Membership.objects.create(user=cust, organization=self.cust, role=Role.ADMIN, is_active=True)
        c = _login(cust, self.cust)
        resp = c.get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['charges'])
        for leaked in ('Time &amp; Charges', 'Billing summary', 'Awaiting classification', 'SSD 1TB', 'Unit cost',
                       'Send to billing'):
            self.assertNotContains(resp, leaked)
        for name in ('psa:ticket_charges_json', 'psa:ticket_charges_review', 'psa:ticket_catalog_json'):
            self.assertEqual(c.get(reverse(name, args=[self.ticket.ticket_number])).status_code, 403, name)
        r = c.post(reverse('psa:ticket_send_to_billing', args=[self.ticket.ticket_number]))
        self.assertEqual(r.status_code, 403)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PageTests(_ChargesBase):

    def test_ticket_page_and_review_page_render(self):
        self._contract(total_hours=D('1'))
        self._entry(90)
        tc.add_item(self.ticket, self.admin, category='materials', description='Cable', unit_price='5')
        c = self._client()
        resp = c.get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertContains(resp, 'Time &amp; Charges')
        self.assertContains(resp, 'Billing summary')
        self.assertContains(resp, 'Send to billing')
        self.assertContains(resp, 'Invoice this ticket')
        resp = c.get(reverse('psa:ticket_charges_review', args=[self.ticket.ticket_number]))
        self.assertContains(resp, 'Item: Cable')
        self.assertContains(resp, 'Unbilled total before tax')
