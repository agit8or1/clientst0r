"""A billing period is invoiced once.

`Contract.generate_invoice` created an Invoice unconditionally. The daily
`psa_generate_recurring_invoices` command relied for idempotency on advancing
`next_billing_date` *after* the invoice was written — two separate writes, with
no transaction around them. Anything that interrupted a run between them left
the invoice committed and the cursor unmoved, and the next day's run billed the
customer again. A manual re-run duplicated with no interruption needed.

Measured before the fix: three calls for the same September period produced
three invoices and billed 7,500.00 against a 2,500.00 contract.

`Project.generate_invoice` had guarded against exactly this since it was
written (`already_fixed_fee_invoiced`). The contract path had nothing.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from io import StringIO

from core.models import Organization
from psa.models import Contract, Invoice


class ContractInvoiceDuplicateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.msp = Organization.objects.create(name='Dup MSP', slug='dup-msp')
        cls.client_org = Organization.objects.create(name='Dup Client', slug='dup-client')

    def _contract(self, **kw):
        return Contract.objects.create(
            organization=self.msp, client_org=self.client_org,
            name=kw.pop('name', 'Managed Services'),
            start_date=date(2026, 1, 1), status='active',
            billing_frequency='monthly',
            recurring_amount=Decimal('2500.00'),
            next_billing_date=date(2026, 9, 1), **kw)

    def test_generating_twice_for_a_period_returns_the_same_invoice(self):
        c = self._contract()
        first = c.generate_invoice(on_date=date(2026, 9, 1))
        second = c.generate_invoice(on_date=date(2026, 9, 1))

        self.assertEqual(
            first.pk, second.pk,
            'the same billing period produced a second invoice',
        )
        self.assertEqual(Invoice.objects.filter(source_contract=c).count(), 1)

    def test_the_customer_is_billed_once(self):
        """The defect stated in money."""
        c = self._contract()
        for _ in range(3):
            c.generate_invoice(on_date=date(2026, 9, 1))
        billed = sum(i.total for i in Invoice.objects.filter(source_contract=c))
        self.assertEqual(billed, Decimal('2500.00'),
                         f'billed {billed} for one month of a 2500.00 contract')

    def test_a_different_period_still_invoices(self):
        c = self._contract()
        sep = c.generate_invoice(on_date=date(2026, 9, 1))
        oct_ = c.generate_invoice(on_date=date(2026, 10, 1))
        self.assertNotEqual(sep.pk, oct_.pk)
        self.assertEqual(Invoice.objects.filter(source_contract=c).count(), 2)

    def test_the_database_refuses_a_duplicate_even_without_the_guard(self):
        """The application guard closes the common case. The constraint closes
        the one two concurrent workers can both walk through."""
        c = self._contract()
        c.generate_invoice(on_date=date(2026, 9, 1))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Invoice.objects.create(
                    organization=self.msp, client_org=self.client_org,
                    title='sneaky duplicate', invoice_date=date(2026, 9, 1),
                    billing_period_start=date(2026, 9, 1), source_contract=c)

    def test_invoices_without_a_period_are_unaffected(self):
        """Manual invoices carry no billing period and must not collide with
        each other. Every invoice predating this release is in that state."""
        for i in range(3):
            Invoice.objects.create(
                organization=self.msp, client_org=self.client_org,
                title=f'manual {i}', invoice_date=date(2026, 9, 1))
        self.assertEqual(
            Invoice.objects.filter(billing_period_start__isnull=True).count(), 3)


class RecurringCommandTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.msp = Organization.objects.create(name='Cron MSP', slug='cron-msp')
        cls.client_org = Organization.objects.create(name='Cron Client', slug='cron-client')

    def _contract(self, next_billing_date=date(2026, 9, 1)):
        return Contract.objects.create(
            organization=self.msp, client_org=self.client_org,
            name='Recurring', start_date=date(2026, 1, 1), status='active',
            billing_frequency='monthly', recurring_amount=Decimal('400.00'),
            next_billing_date=next_billing_date)

    def test_a_crashed_run_does_not_double_bill_on_the_next_pass(self):
        """The exact failure: an invoice committed with the cursor left behind,
        which is what the run sees the following day."""
        c = self._contract()
        c.generate_invoice(on_date=date(2026, 9, 1))   # the "crashed" run
        c.refresh_from_db()
        self.assertEqual(c.next_billing_date, date(2026, 9, 1),
                         'precondition: the cursor did not advance')

        call_command('psa_generate_recurring_invoices', stdout=StringIO())

        sept = Invoice.objects.filter(
            source_contract=c, billing_period_start=date(2026, 9, 1))
        self.assertEqual(
            sept.count(), 1,
            'the September period was billed a second time after a crashed run',
        )
        c.refresh_from_db()
        self.assertGreater(c.next_billing_date, date(2026, 9, 1),
                           'the cursor is still stuck and will re-bill forever')

    def test_running_the_command_twice_bills_once(self):
        c = self._contract()
        for _ in range(2):
            call_command('psa_generate_recurring_invoices', stdout=StringIO())
        self.assertEqual(
            Invoice.objects.filter(
                source_contract=c, billing_period_start=date(2026, 9, 1)).count(),
            1)
