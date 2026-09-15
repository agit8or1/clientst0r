"""Tax is charged on the taxable lines, not on the whole subtotal.

`InvoiceLineItem.is_taxable` and `QuoteLineItem.is_taxable` have existed since
these models were written, default True, are surfaced in the UI and are copied
through credit memos. No tax calculation ever read them: both
`recompute_totals()` methods computed `tax_amount` from the full subtotal.

Any invoice mixing taxable goods with non-taxable labour or reimbursed
expenses overcharged the customer. `create_credit_memo(amount=...)` makes the
disagreement explicit — it sets `is_taxable=False` on the credit line, and the
old calculation taxed it anyway, over-crediting by the tax on the credit.

Rounding moved to ROUND_HALF_UP at the same time. Decimal's default is
ROUND_HALF_EVEN (banker's rounding), which disagrees with the half-up
convention accounting providers use, by a cent, on exact half-cent results.
"""
from decimal import Decimal

from django.test import TestCase

from core.models import Organization
from psa.models import Invoice, InvoiceLineItem


class InvoiceTaxTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.msp = Organization.objects.create(name='Tax MSP', slug='tax-msp')
        cls.client_org = Organization.objects.create(name='Tax Client', slug='tax-client')

    def _invoice(self, rate='0.0825'):
        return Invoice.objects.create(
            organization=self.msp, client_org=self.client_org,
            title='Tax test', invoice_date='2026-09-15',
            tax_rate=Decimal(rate),
        )

    def _line(self, inv, desc, qty, price, taxable):
        return InvoiceLineItem.objects.create(
            invoice=inv, description=desc, quantity=Decimal(qty),
            unit_price=Decimal(price), is_taxable=taxable,
        )

    def test_non_taxable_lines_are_excluded_from_tax(self):
        """The mixed invoice an MSP actually sends: labour, hardware, travel."""
        inv = self._invoice()
        self._line(inv, 'Managed services', '1', '2000.00', False)
        self._line(inv, 'Firewall appliance', '2', '450.00', True)
        self._line(inv, 'Travel reimbursement', '1', '180.00', False)
        inv.recompute_totals()
        inv.refresh_from_db()

        self.assertEqual(inv.subtotal, Decimal('3080.00'))
        # 900.00 taxable x 8.25%. Charging on the full 3080.00 gives 254.10.
        self.assertEqual(
            inv.tax_amount, Decimal('74.25'),
            'tax was charged on non-taxable labour and reimbursed expenses',
        )
        self.assertEqual(inv.total, Decimal('3154.25'))

    def test_an_all_taxable_invoice_is_unchanged(self):
        inv = self._invoice()
        self._line(inv, 'Hardware', '1', '1000.00', True)
        inv.recompute_totals()
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, Decimal('82.50'))
        self.assertEqual(inv.total, Decimal('1082.50'))

    def test_an_invoice_with_no_taxable_lines_is_not_taxed(self):
        inv = self._invoice()
        self._line(inv, 'Labour', '1', '1000.00', False)
        inv.recompute_totals()
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, Decimal('0.00'))
        self.assertEqual(inv.total, Decimal('1000.00'))

    def test_partial_credit_memo_credits_the_amount_asked_for(self):
        """create_credit_memo(amount=...) writes is_taxable=False on the credit
        line. Honouring that flag is what makes the memo worth what was asked
        for rather than that plus tax."""
        inv = self._invoice()
        self._line(inv, 'Hardware', '1', '1000.00', True)
        inv.recompute_totals()

        memo = inv.create_credit_memo(amount=Decimal('500.00'), reason='goodwill')
        memo.refresh_from_db()
        self.assertEqual(memo.tax_amount, Decimal('0.00'))
        self.assertEqual(
            memo.total, Decimal('-500.00'),
            'a 500.00 credit memo was worth more than 500.00',
        )

    def test_full_credit_memo_credits_the_tax_too(self):
        """Copying every line, taxable flags included, credits the tax that was
        charged. This is the opposite case and must keep working."""
        inv = self._invoice()
        self._line(inv, 'Hardware', '1', '1000.00', True)
        inv.recompute_totals()

        memo = inv.create_credit_memo()
        memo.refresh_from_db()
        self.assertEqual(memo.tax_amount, Decimal('-82.50'))
        self.assertEqual(memo.total, Decimal('-1082.50'))

    def test_tax_rounds_half_up(self):
        """10.00 x 8.25% = 0.825 exactly. Banker's rounding gives 0.82."""
        inv = self._invoice()
        self._line(inv, 'Widget', '1', '10.00', True)
        inv.recompute_totals()
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, Decimal('0.83'))

    def test_zero_rate_invoice(self):
        inv = self._invoice(rate='0')
        self._line(inv, 'Hardware', '1', '1000.00', True)
        inv.recompute_totals()
        inv.refresh_from_db()
        self.assertEqual(inv.tax_amount, Decimal('0.00'))
        self.assertEqual(inv.total, Decimal('1000.00'))
