"""Phase 49 — billing arithmetic, the parts left after tax (v3.17.561) and
credit-memo balances (v3.17.577–579).

* Money rounds half-up everywhere it is computed, not only in the tax:
  invoice and quote line totals, the retainer amount, the prorated first
  period and late fees. Decimal's default is banker's rounding, which put
  exact half-cent results a cent below what QuickBooks / Xero compute.
* A second full credit memo for the same invoice is refused — it credited
  the same lines twice. Partial credits by amount still may exceed the
  total (account credit, by design).
* Credit memos on void invoices are refused; the amount is rounded to cents.
"""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization, SystemSetting
from psa.models import (Charge, Contract, Invoice, InvoiceLineItem, Quote,
                        QuoteLineItem)


def _invoice(org, lines, *, status='sent', tax_rate='0', due=None):
    inv = Invoice.objects.create(
        organization=org, client_org=org, title='Work', invoice_date=date.today(),
        due_date=due or date.today(), status=status, currency='USD',
        tax_rate=Decimal(tax_rate))
    for qty, price, taxable in lines:
        InvoiceLineItem.objects.create(invoice=inv, description='line',
                                       quantity=Decimal(qty), unit_price=Decimal(price),
                                       is_taxable=taxable)
    inv.recompute_totals()
    return inv


class HalfUpRoundingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Round Co', slug='round-co-49')

    def test_invoice_line_total_rounds_half_up(self):
        # 0.25 x 10.10 = 2.525 exactly. Banker's rounding gave 2.52.
        li = InvoiceLineItem(quantity=Decimal('0.25'), unit_price=Decimal('10.10'))
        self.assertEqual(li.line_total, Decimal('2.53'))
        inv = _invoice(self.org, [('0.25', '10.10', False)])
        self.assertEqual(inv.subtotal, Decimal('2.53'))
        self.assertEqual(inv.total, Decimal('2.53'))

    def test_quote_line_total_rounds_half_up(self):
        li = QuoteLineItem(quantity=Decimal('0.25'), unit_price=Decimal('10.10'))
        self.assertEqual(li.line_total, Decimal('2.53'))

    def test_retainer_amount_rounds_half_up(self):
        c = Contract(organization=self.org, client_org=self.org, name='R',
                     start_date=date(2026, 1, 1), total_hours=Decimal('0.25'),
                     hourly_rate=Decimal('10.10'))
        self.assertEqual(c.effective_recurring_amount, Decimal('2.53'))

    def test_late_fee_rounds_half_up(self):
        ss = SystemSetting.get_settings()
        ss.late_fee_pct = Decimal('5.00')
        ss.late_fee_min_days_overdue = 1
        ss.save()
        # 5% of 1000.50 = 50.025 -> 50.03 (banker's: 50.02)
        _invoice(self.org, [('1', '1000.50', False)], due=date(2020, 1, 1))
        call_command('psa_apply_late_fees', stdout=StringIO())
        fee = Charge.objects.get(description__startswith='Late fee')
        self.assertEqual(fee.amount, Decimal('50.03'))


class CreditMemoGuardTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Credit Guard', slug='credit-guard-49')

    def test_a_second_full_credit_is_refused(self):
        inv = _invoice(self.org, [('1', '1000.00', True)], tax_rate='0.10')
        first = inv.create_credit_memo()
        self.assertEqual(first.total, Decimal('-1100.00'))
        with self.assertRaises(ValueError) as ctx:
            inv.create_credit_memo()
        self.assertIn('already has 1100.00 credited', str(ctx.exception))
        self.assertEqual(inv.credit_memos.count(), 1)

    def test_full_credit_after_a_partial_is_refused_with_the_remainder(self):
        inv = _invoice(self.org, [('1', '1000.00', False)])
        inv.create_credit_memo(amount=Decimal('400.00'))
        with self.assertRaises(ValueError) as ctx:
            inv.create_credit_memo()
        self.assertIn('remaining 600.00', str(ctx.exception))

    def test_a_voided_memo_frees_the_invoice_for_a_full_credit(self):
        inv = _invoice(self.org, [('1', '1000.00', False)])
        memo = inv.create_credit_memo()
        Invoice.objects.filter(pk=memo.pk).update(status='void')
        again = inv.create_credit_memo()
        self.assertEqual(again.total, Decimal('-1000.00'))

    def test_partial_credits_may_still_exceed_the_total(self):
        """Account credit stays a deliberate option (v3.17.578)."""
        inv = _invoice(self.org, [('1', '100.00', False)])
        inv.create_credit_memo(amount=Decimal('250.00'))
        self.assertEqual(inv.credited_amount, Decimal('250.00'))
        self.assertEqual(inv.net_balance_due, Decimal('0.00'))

    def test_void_invoice_cannot_be_credited(self):
        inv = _invoice(self.org, [('1', '100.00', False)], status='void')
        with self.assertRaises(ValueError):
            inv.create_credit_memo()
        with self.assertRaises(ValueError):
            inv.create_credit_memo(amount=Decimal('10'))
        self.assertFalse(Invoice.objects.filter(is_credit_memo=True).exists())

    def test_amount_is_rounded_to_cents_and_must_be_positive(self):
        inv = _invoice(self.org, [('1', '100.00', False)])
        memo = inv.create_credit_memo(amount=Decimal('10.005'))
        self.assertEqual(memo.line_items.get().unit_price, Decimal('-10.01'))
        for bad in ('0', '-5', 'ten'):
            with self.subTest(bad), self.assertRaises(ValueError):
                inv.create_credit_memo(amount=bad)

    def test_credit_memo_number_collision_is_retried(self):
        """Another memo taking the number between read and write no longer
        surfaces as an IntegrityError."""
        from unittest.mock import patch
        inv = _invoice(self.org, [('1', '100.00', False)])
        taken = inv.create_credit_memo(amount=Decimal('1.00')).invoice_number
        n = int(taken.rsplit('-', 1)[-1])
        nxt = f'{taken.rsplit("-", 1)[0]}-{n + 1:05d}'
        calls = iter([taken, nxt])
        with patch.object(Invoice, '_next_credit_memo_number', side_effect=lambda: next(calls)):
            memo = inv.create_credit_memo(amount=Decimal('2.00'))
        self.assertEqual(memo.invoice_number, nxt)
