"""`psa_audit_late_fees` finds fees charged on already-credited money.

v3.17.578 stopped the late-fee cron charging on amounts a credit memo had
credited back, but the `Charge` rows it already wrote are still on clients'
accounts — real charges, not a display artefact. This command reports them and
writes nothing.
"""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization
from psa.models import Charge, Invoice, InvoiceLineItem


def make_invoice(org, amount, *, number=None, due=None):
    inv = Invoice.objects.create(
        organization=org, client_org=org, title='Work',
        invoice_date=due or date.today(), due_date=due or date.today(),
        status='sent', currency='USD', tax_rate=0)
    if number:
        Invoice.objects.filter(pk=inv.pk).update(invoice_number=number)
        inv.refresh_from_db()
    InvoiceLineItem.objects.create(invoice=inv, description='labour',
                                   quantity=1, unit_price=Decimal(str(amount)))
    inv.recompute_totals()
    return inv


def late_fee(org, invoice, amount, billed_on, pct='5.00', when=None):
    return Charge.objects.create(
        organization=org, client_org=org,
        description=(f'Late fee for {invoice.invoice_number} '
                     f'(overdue ${billed_on}, {pct}% applied)'),
        amount=Decimal(str(amount)), currency='USD',
        charge_date=when or date.today(), is_credit=False, recurrence='once')


def run(**kwargs):
    out = StringIO()
    call_command('psa_audit_late_fees', stdout=out, **kwargs)
    return out.getvalue()


class LateFeeAuditTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Acme Ltd', slug='lfa-acme')
        self.old = date.today() - timedelta(days=60)

    def test_a_clean_install_reports_nothing(self):
        inv = make_invoice(self.org, '1000.00', due=self.old)
        late_fee(self.org, inv, '50.00', '1000.00')
        self.assertIn('No late fees were charged on credited amounts', run())

    def test_a_fee_on_a_fully_credited_invoice_is_reported(self):
        inv = make_invoice(self.org, '1000.00', due=self.old)
        memo = inv.create_credit_memo()
        Invoice.objects.filter(pk=memo.pk).update(invoice_date=self.old)
        late_fee(self.org, inv, '50.00', '1000.00')

        out = run()
        self.assertIn('1 late fee(s) charged on amounts already credited', out)
        self.assertIn('$50.00 overcharged', out)
        self.assertIn('Acme Ltd', out)

    def test_a_partial_credit_reports_only_the_excess(self):
        """Credited $400 of $1,000: the fee should have been 5% of $600."""
        inv = make_invoice(self.org, '1000.00', due=self.old)
        memo = inv.create_credit_memo(amount=Decimal('400.00'))
        Invoice.objects.filter(pk=memo.pk).update(invoice_date=self.old)
        late_fee(self.org, inv, '50.00', '1000.00')

        out = run()
        self.assertIn('$20.00 overcharged', out)   # 50.00 charged, 30.00 correct

    def test_a_credit_issued_after_the_fee_does_not_make_it_wrong(self):
        """The fee was correct on the day it was raised."""
        inv = make_invoice(self.org, '1000.00', due=self.old)
        late_fee(self.org, inv, '50.00', '1000.00', when=self.old)
        inv.create_credit_memo()  # dated today, after the fee
        self.assertIn('No late fees were charged on credited amounts', run())

    def test_a_voided_credit_memo_does_not_count(self):
        inv = make_invoice(self.org, '1000.00', due=self.old)
        memo = inv.create_credit_memo()
        Invoice.objects.filter(pk=memo.pk).update(
            invoice_date=self.old, status='void')
        late_fee(self.org, inv, '50.00', '1000.00')
        self.assertIn('No late fees were charged on credited amounts', run())

    def test_an_unparseable_description_is_flagged_not_silently_skipped(self):
        Charge.objects.create(
            organization=self.org, client_org=self.org,
            description='Late fee for something someone retyped by hand',
            amount=Decimal('10.00'), currency='USD',
            charge_date=date.today(), is_credit=False, recurrence='once')
        self.assertIn('did not match the expected description format', run())

    def test_a_fee_naming_a_vanished_invoice_is_flagged(self):
        Charge.objects.create(
            organization=self.org, client_org=self.org,
            description='Late fee for INV-1999-00001 (overdue $10.00, 5.00% applied)',
            amount=Decimal('0.50'), currency='USD',
            charge_date=date.today(), is_credit=False, recurrence='once')
        self.assertIn('no longer exists', run())

    def test_it_writes_nothing(self):
        inv = make_invoice(self.org, '1000.00', due=self.old)
        memo = inv.create_credit_memo()
        Invoice.objects.filter(pk=memo.pk).update(invoice_date=self.old)
        charge = late_fee(self.org, inv, '50.00', '1000.00')

        before = (Charge.objects.count(), Invoice.objects.count(),
                  Decimal(str(charge.amount)))
        run()
        charge.refresh_from_db()
        after = (Charge.objects.count(), Invoice.objects.count(),
                 Decimal(str(charge.amount)))
        self.assertEqual(before, after)

    def test_the_org_filter_rejects_an_unknown_slug(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            run(org='no-such-client')

    def test_csv_output_carries_the_working(self):
        import csv as _csv
        import tempfile

        inv = make_invoice(self.org, '1000.00', due=self.old)
        memo = inv.create_credit_memo(amount=Decimal('400.00'))
        Invoice.objects.filter(pk=memo.pk).update(invoice_date=self.old)
        late_fee(self.org, inv, '50.00', '1000.00')

        with tempfile.NamedTemporaryFile(suffix='.csv', mode='r+') as fh:
            run(csv=fh.name)
            fh.seek(0)
            rows = list(_csv.DictReader(fh))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['charged'], '50.00')
        self.assertEqual(rows[0]['should_have_been'], '30.00')
        self.assertEqual(rows[0]['overcharged_by'], '20.00')
        self.assertEqual(rows[0]['credited_at_the_time'], '400.00')
