"""The tax audit report finds the affected invoices and changes nothing.

The second half matters as much as the first: this command exists to inform a
refund decision on real customer invoices, so a test asserts it leaves every
stored value exactly as it found it.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization
from psa.models import Invoice, InvoiceLineItem


class TaxAuditReportTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.msp = Organization.objects.create(name='Audit MSP', slug='audit-msp')
        cls.acme = Organization.objects.create(name='Acme Co', slug='acme-co')

    def _invoice(self, *, status='sent', rate='0.0825'):
        return Invoice.objects.create(
            organization=self.msp, client_org=self.acme, title='t',
            invoice_date='2026-03-01', status=status, tax_rate=Decimal(rate))

    def _line(self, inv, price, taxable):
        return InvoiceLineItem.objects.create(
            invoice=inv, description='l', quantity=Decimal('1'),
            unit_price=Decimal(price), is_taxable=taxable)

    def _run(self, *args):
        out = StringIO()
        call_command('psa_tax_audit', *args, stdout=out)
        return out.getvalue()

    def test_flags_an_invoice_taxed_on_non_taxable_lines(self):
        inv = self._invoice()
        self._line(inv, '2000.00', False)
        self._line(inv, '900.00', True)
        # The state an affected invoice is actually in: tax stored from the
        # old whole-subtotal calculation.
        Invoice.objects.filter(pk=inv.pk).update(
            subtotal=Decimal('2900.00'), tax_amount=Decimal('239.25'),
            total=Decimal('3139.25'))

        out = self._run()
        self.assertIn('1 with a discrepancy', out)
        self.assertIn('239.25', out)          # charged
        self.assertIn('74.25', out)           # correct
        self.assertIn('165.00', out)          # delta
        self.assertIn('Acme Co', out)
        self.assertIn('overcharged', out)

    def test_a_correct_invoice_is_not_flagged(self):
        inv = self._invoice()
        self._line(inv, '1000.00', True)
        inv.recompute_totals()
        out = self._run()
        self.assertIn('0 with a discrepancy', out)

    def test_drafts_and_voids_are_excluded_unless_asked_for(self):
        for status in ('draft', 'void'):
            inv = self._invoice(status=status)
            self._line(inv, '1000.00', False)
            Invoice.objects.filter(pk=inv.pk).update(tax_amount=Decimal('82.50'))
        self.assertIn('0 with a discrepancy', self._run())
        self.assertIn('2 with a discrepancy', self._run('--all-statuses'))

    def test_changes_nothing(self):
        inv = self._invoice()
        self._line(inv, '2000.00', False)
        self._line(inv, '900.00', True)
        Invoice.objects.filter(pk=inv.pk).update(
            subtotal=Decimal('2900.00'), tax_amount=Decimal('239.25'),
            total=Decimal('3139.25'), status='sent')

        before = Invoice.objects.filter(pk=inv.pk).values(
            'subtotal', 'tax_amount', 'total', 'status', 'amount_paid').first()
        self._run()
        after = Invoice.objects.filter(pk=inv.pk).values(
            'subtotal', 'tax_amount', 'total', 'status', 'amount_paid').first()
        self.assertEqual(
            before, after,
            'the audit report modified an invoice; it must be read-only',
        )

    def test_csv_output(self):
        import csv
        import tempfile
        import os
        inv = self._invoice()
        self._line(inv, '2000.00', False)
        self._line(inv, '900.00', True)
        Invoice.objects.filter(pk=inv.pk).update(tax_amount=Decimal('239.25'))

        path = os.path.join(tempfile.mkdtemp(), 'audit.csv')
        self._run('--csv', path)
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['delta'], '165.00')
        self.assertEqual(rows[0]['non_taxable_lines'], '1')

    def test_unknown_org_is_an_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run('--org', 'no-such-client')
