"""A credit memo has to reduce what the client owes.

There are two kinds of credit in this system and only one of them counted.
An account credit is a `Charge` with `is_credit=True`, and `get_psa_balance`
subtracted it. A credit memo is an `Invoice` with `is_credit_memo=True` whose
line prices are negated, so its balance is negative — and the balance loop
skipped every non-positive balance, so a credit memo changed nothing at all.

Issuing a $500 memo against a $2,000 invoice left the client account page and
the aging report both showing $2,000 due, so the client was chased for money
already credited to them.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Organization
from psa.models import Charge, Invoice, InvoiceLineItem, Payment, get_psa_balance


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def make_invoice(org, amount, *, status='sent', due=None):
    inv = Invoice.objects.create(
        organization=org, client_org=org, title='Work',
        invoice_date=date.today(), due_date=due or date.today(),
        status=status, currency='USD', tax_rate=0)
    InvoiceLineItem.objects.create(invoice=inv, description='labour',
                                   quantity=1, unit_price=Decimal(str(amount)))
    inv.recompute_totals()
    return inv


class CreditMemoBalanceTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Acme', slug='cm-acme')

    def test_a_credit_memo_reduces_the_net_balance(self):
        inv = make_invoice(self.org, '2000.00')
        inv.create_credit_memo(amount=Decimal('500.00'), reason='goodwill')

        s = get_psa_balance(self.org)
        self.assertEqual(s['invoice_credits'], Decimal('500.00'))
        self.assertEqual(s['net_balance'], Decimal('1500.00'))

    def test_outstanding_still_means_receivables(self):
        """The aging columns are built from it, so its meaning is unchanged."""
        inv = make_invoice(self.org, '2000.00')
        inv.create_credit_memo(amount=Decimal('500.00'))
        s = get_psa_balance(self.org)
        self.assertEqual(s['outstanding'], Decimal('2000.00'))

    def test_a_credit_memo_is_not_aged(self):
        """A credit is not a receivable and has nothing to age."""
        old = date.today() - timedelta(days=200)
        inv = make_invoice(self.org, '2000.00', due=old)
        memo = inv.create_credit_memo(amount=Decimal('500.00'))
        memo.due_date = old
        memo.save(update_fields=['due_date'])

        s = get_psa_balance(self.org)
        aged = sum(s['aging'].values())
        self.assertEqual(aged, Decimal('2000.00'))

    def test_a_full_credit_memo_clears_the_net_balance(self):
        inv = make_invoice(self.org, '2000.00')
        inv.create_credit_memo()  # copies every line, negated
        s = get_psa_balance(self.org)
        self.assertEqual(s['net_balance'], Decimal('0.00'))

    def test_an_overpaid_invoice_counts_as_credit_too(self):
        """Same arithmetic: money the client is owed."""
        inv = make_invoice(self.org, '100.00')
        Payment.objects.create(invoice=inv, amount=Decimal('150.00'),
                               paid_on=date.today())
        inv.recompute_totals()
        s = get_psa_balance(self.org)
        self.assertEqual(s['invoice_credits'], Decimal('50.00'))
        self.assertEqual(s['net_balance'], Decimal('-50.00'))

    def test_account_credits_and_credit_memos_both_apply(self):
        inv = make_invoice(self.org, '2000.00')
        inv.create_credit_memo(amount=Decimal('500.00'))
        Charge.objects.create(organization=self.org, client_org=self.org,
                              description='goodwill', amount=Decimal('100.00'),
                              is_credit=True, invoiced=False,
                              charge_date=date.today())
        s = get_psa_balance(self.org)
        self.assertEqual(s['credit_total'], Decimal('100.00'))
        self.assertEqual(s['invoice_credits'], Decimal('500.00'))
        self.assertEqual(s['net_balance'], Decimal('1400.00'))

    def test_a_voided_credit_memo_stops_counting(self):
        inv = make_invoice(self.org, '2000.00')
        memo = inv.create_credit_memo(amount=Decimal('500.00'))
        memo.status = 'void'
        memo.save(update_fields=['status'])
        s = get_psa_balance(self.org)
        self.assertEqual(s['invoice_credits'], Decimal('0'))
        self.assertEqual(s['net_balance'], Decimal('2000.00'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AgingReportShowsCreditMemosTests(TestCase):

    def setUp(self):
        from core.models import SystemSetting

        # The PSA module is off in a fresh database and the report is behind
        # `require_psa_enabled`.
        settings_row = SystemSetting.get_settings()
        settings_row.psa_enabled = True
        settings_row.save()

        self.org = Organization.objects.create(name='Acme', slug='ag-acme')
        self.su = get_user_model().objects.create_user(
            'ag_su', 'a@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.su)

    def test_a_client_whose_only_balance_is_a_credit_memo_still_appears(self):
        """
        The report skipped any client with nothing outstanding and no account
        credit, which would have hidden exactly the row that needs actioning.
        """
        inv = make_invoice(self.org, '500.00')
        Payment.objects.create(invoice=inv, amount=Decimal('500.00'),
                               paid_on=date.today())
        inv.recompute_totals()
        inv.create_credit_memo(amount=Decimal('500.00'), reason='returned kit')

        r = self.client.get(reverse('psa:aging_report'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Acme')
        self.assertContains(r, 'Credit memos')
