"""
Phase 102.7 — one set of financial definitions (reports.financials).

Pins each definition (billed, collected, recognized revenue, direct cost,
gross profit, margin) against drafts, voids, credit notes, tax, refunds and
partial costs; that every surface reports the same billed revenue for the
same customer and period; and that customer scoping still applies.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from executive.tests import TEST_MIDDLEWARE, Base, _filters  # noqa: F401  (Base has no tests)
from reports import financials
from reports.tests_profitability import _Fixture

D = Decimal


class _Money(_Fixture):

    def inv(self, client, net, tax=0, number=None, **kw):
        """An issued invoice of `net` excluding tax plus `tax`."""
        number = number or f'INV-F-{client.pk}-{net}-{tax}-{kw.get("status", "sent")}-{id(kw)}'
        kw.setdefault('status', 'sent')
        from psa.models import Invoice
        return Invoice.objects.create(
            organization=client, client_org=client, invoice_number=number[:32], title=number,
            invoice_date=kw.pop('invoice_date', self.today), due_date=self.today,
            subtotal=D(str(net)), tax_amount=D(str(tax)), total=D(str(net)) + D(str(tax)),
            amount_paid=kw.pop('amount_paid', 0), currency='USD', **kw)

    def memo(self, of, net, **kw):
        return self.inv(of.client_org, -D(str(net)), is_credit_memo=True, credits_invoice=of, **kw)

    def pay(self, invoice, amount, day=None):
        # bulk_create: Payment.save() recomputes the invoice totals from its
        # (absent) lines, which would rewrite the fixture amounts.
        from psa.models import Payment
        Payment.objects.bulk_create([Payment(invoice=invoice, amount=D(str(amount)),
                                             paid_on=day or self.today)])

    def item(self, ticket=None, *, price=None, cost=None, amount=0, qty=1, credit=False, day=None):
        from psa.models import TicketExpense
        return TicketExpense.objects.create(
            ticket=ticket or self.t_acme, description='thing', amount=D(str(amount)),
            incurred_on=day or self.today, unit_price=None if price is None else D(str(price)),
            unit_cost=None if cost is None else D(str(cost)), quantity=D(str(qty)), is_credit=credit)


class BilledRevenueTests(_Money):

    def test_issued_only_excluding_tax_net_of_credit_notes(self):
        a = self.inv(self.acme, 1000, tax=80)
        self.inv(self.acme, 500, status='draft')
        self.inv(self.acme, 700, status='void')
        self.inv(self.acme, 300, status='paid')
        self.inv(self.acme, 200, status='overdue')
        self.memo(a, 150)                         # issued credit note
        self.memo(a, 999, status='draft')         # not issued
        fig = financials.billed_revenue(self.today, self.today)
        self.assertEqual(fig.amount, D('1350.00'))   # 1000 + 300 + 200 - 150

    def test_by_invoice_date(self):
        self.inv(self.acme, 100, invoice_date=self.today - timedelta(days=40))
        self.inv(self.acme, 50)
        self.assertEqual(financials.billed_revenue(self.today - timedelta(days=30), self.today).amount,
                         D('50.00'))

    def test_credit_memo_counts_under_the_credited_contract(self):
        from reports.queries import revenue_by_contract
        c = self.contract(name='MSA', contract_type='managed_services')
        from psa.models import ContractBundleItem
        ContractBundleItem.objects.create(contract=c, description='bundle', quantity=1, unit_price=D('400'))
        a = self.inv(self.acme, 1000, tax=100, source_contract=c)
        self.memo(a, 250)
        row = [r for r in revenue_by_contract(self.today, self.today) if r['contract_id'] == c.pk][0]
        self.assertEqual(row['revenue'], 750.0)    # no tax, no unbilled bundle, net of the credit
        self.assertEqual(row['bundled'], 400.0)    # reported for reference only

    def test_project_revenue_includes_project_invoices(self):
        from psa.models import Project
        from reports.queries import revenue_by_project
        p = Project.objects.create(organization=self.acme, client_org=self.acme, name='Move')
        self.inv(self.acme, 600, tax=60, project=p)
        rows = revenue_by_project(self.today, self.today)
        self.assertEqual([(r['project_id'], r['revenue']) for r in rows], [(p.pk, 600.0)])

    def test_scoped_by_customer(self):
        self.inv(self.acme, 100)
        self.inv(self.beta, 900)
        self.assertEqual(financials.billed_revenue(self.today, self.today, [self.acme.pk]).amount, D('100.00'))
        self.assertEqual(financials.billed_revenue(self.today, self.today, self.beta).amount, D('900.00'))


class CollectedRevenueTests(_Money):

    def test_by_payment_date_excluding_tax_net_of_refunds(self):
        a = self.inv(self.acme, 1000, tax=100, invoice_date=self.today - timedelta(days=60))
        self.pay(a, 550)                          # half of 1100 → 500 net
        self.pay(a, -110)                         # refund → -100 net
        self.pay(a, 440, day=self.today - timedelta(days=45))   # outside the window
        fig = financials.collected_revenue(self.today - timedelta(days=7), self.today)
        self.assertEqual(fig.amount, D('400.00'))
        self.assertEqual(fig.gross, D('440'))
        self.assertFalse(fig.partial)

    def test_untaxed_invoice_counts_in_full(self):
        self.pay(self.inv(self.acme, 300), 125)
        self.assertEqual(financials.collected_revenue(self.today, self.today).amount, D('125.00'))

    def test_void_invoice_and_undeterminable_tax_mark_partial(self):
        self.pay(self.inv(self.acme, 300, status='void'), 100)
        bad = self.inv(self.acme, 0, tax=10)
        bad.total = 0
        bad.save(update_fields=['total'])
        self.pay(bad, 20)
        fig = financials.collected_revenue(self.today, self.today)
        self.assertEqual(fig.amount, D('120.00'))
        self.assertTrue(fig.partial)
        self.assertEqual(len(fig.reasons), 2)

    def test_scoped(self):
        self.pay(self.inv(self.acme, 100), 100)
        self.pay(self.inv(self.beta, 100), 70)
        self.assertEqual(financials.collected_revenue(self.today, self.today, [self.beta.pk]).amount, D('70.00'))


class RecognizedRevenueTests(_Money):

    def test_contract_period_spread_by_day(self):
        from datetime import date
        c = self.contract(billing_frequency='quarterly', start_date=date(2025, 1, 1))
        # Q1 2026: 90 days, 900 excluding tax.
        self.inv(self.acme, 900, tax=90, source_contract=c, billing_period_start=date(2026, 1, 1),
                 invoice_date=date(2025, 12, 20))
        jan = financials.recognized_revenue(date(2026, 1, 1), date(2026, 1, 31)).amount
        q1 = financials.recognized_revenue(date(2026, 1, 1), date(2026, 3, 31)).amount
        dec = financials.recognized_revenue(date(2025, 12, 1), date(2025, 12, 31)).amount
        self.assertEqual(jan, D('310.00'))   # 31 of 90 days
        self.assertEqual(q1, D('900.00'))
        self.assertEqual(dec, D('0'))
        # Billed revenue is by invoice date: all of it in December.
        self.assertEqual(financials.billed_revenue(date(2025, 12, 1), date(2025, 12, 31)).amount, D('900.00'))

    def test_invoice_without_period_on_its_date(self):
        self.inv(self.acme, 250)
        fig = financials.recognized_revenue(self.today, self.today)
        self.assertEqual(fig.amount, D('250.00'))
        self.assertTrue(fig.notes)


class DirectCostTests(_Money):

    def test_labour_items_expenses_and_lines(self):
        self.rate(60)
        self.entry(120)                                   # 120.00
        self.item(price=50, cost=20, qty=3)               # 60.00
        self.item(amount=D('35.50'))                      # expense 35.50
        self.item(amount=99, credit=True)                 # a credit, not a cost
        a = self.inv(self.acme, 500)
        from psa.models import InvoiceLineItem
        InvoiceLineItem.objects.create(invoice=a, description='switch', quantity=2, unit_price=200,
                                       unit_cost=D('120'), source='manual')         # 240.00
        InvoiceLineItem.objects.create(invoice=a, description='billed item', quantity=1, unit_price=50,
                                       unit_cost=D('20'), source='expense')         # counted via the item
        row = financials.direct_cost_total(self.today, self.today)
        self.assertEqual((row.labour, row.items, row.expenses, row.invoice_lines),
                         (D('120.00'), D('60.00'), D('35.50'), D('240.00')))
        self.assertEqual(row.total, D('455.50'))
        self.assertFalse(row.partial)

    def test_missing_rates_and_costs_make_it_partial(self):
        self.rate(60)
        self.entry(60)
        self.entry(120, user=self.tech2)                  # no cost rate
        self.item(price=40, cost=None)                    # no unit cost
        row = financials.direct_cost_total(self.today, self.today)
        self.assertTrue(row.partial)
        self.assertEqual(row.total, D('60.00'))           # the known part
        self.assertEqual(row.reasons, ['1 technician has no cost rate (2 h)', '1 item has no cost'])


class ProfitAndMarginTests(_Money):

    def test_gross_profit_and_margin(self):
        self.rate(50)
        self.entry(120)                                   # 100.00
        self.inv(self.acme, 400, tax=40)
        t = financials.totals(self.today, self.today)
        self.assertEqual(t['billed_revenue'], D('400.00'))
        self.assertEqual(t['gross_profit'], D('300.00'))
        self.assertEqual(t['margin_pct'], 75.0)

    def test_margin_none_when_no_revenue_or_partial_cost(self):
        self.rate(50)
        self.entry(60)
        self.assertIsNone(financials.totals(self.today, self.today)['margin_pct'])
        self.inv(self.acme, 100)
        self.entry(60, user=self.tech2)
        t = financials.totals(self.today, self.today)
        self.assertIsNone(t['gross_profit'])
        self.assertIsNone(t['margin_pct'])
        self.assertTrue(t['partial'])

    def test_profitability_rows_carry_partial_reasons(self):
        from reports.costing import summarize
        from reports.queries import profitability_by_client
        self.inv(self.acme, 100, tax=10)
        self.entry(60, user=self.tech2)
        rows = profitability_by_client(self.today, self.today)
        self.assertEqual(rows[0]['revenue'], 100.0)
        self.assertEqual(rows[0]['partial_reasons'], ['1 technician has no cost rate (1 h)'])
        s = summarize(rows)
        self.assertTrue(s['partial'])
        self.assertEqual(s['partial_reasons'], ['1 technician has no cost rate (1 h)'])


class ConsistencyTests(Base):
    """The same customer and period give the same billed revenue on every
    surface that shows revenue."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Contract, Invoice
        d = cls.today - timedelta(days=3)
        cls.contract = Contract.objects.create(organization=cls.a, client_org=cls.a, name='A MSA',
                                               contract_type='managed_services', status='active',
                                               start_date=cls.today - timedelta(days=400))
        mk = dict(organization=cls.a, client_org=cls.a, invoice_date=d)
        cls.i1 = Invoice.objects.create(title='i1', status='sent', subtotal=D('1000'), tax_amount=D('80'),
                                        total=D('1080'), source_contract=cls.contract, **mk)
        Invoice.objects.create(title='i2', status='paid', subtotal=D('500'), tax_amount=D('0'),
                               total=D('500'), amount_paid=D('500'), **mk)
        Invoice.objects.create(title='cn', status='sent', subtotal=D('-200'), tax_amount=D('-16'),
                               total=D('-216'), is_credit_memo=True, credits_invoice=cls.i1, **mk)
        Invoice.objects.create(title='dr', status='draft', subtotal=D('900'), total=D('900'), **mk)
        Invoice.objects.create(title='vd', status='void', subtotal=D('900'), total=D('900'), **mk)
        Invoice.objects.create(organization=cls.b, client_org=cls.b, invoice_date=d, title='b',
                               status='sent', subtotal=D('4000'), total=D('4000'))
        cls.expected = D('1300.00')   # 1000 + 500 - 200

    def test_every_surface_agrees(self):
        from reports import queries, widget_sources
        f = _filters()
        start, end = f.start, f.end
        org = [self.a.pk]
        values = {
            'financials.billed_revenue': financials.billed_revenue(start, end, org).amount,
            'revenue_by_client': D(str(sum(r['invoiced'] for r in queries.revenue_by_client(start, end, org)))),
            'profitability_by_client': D(str(sum(r['revenue'] for r in queries.profitability_by_client(start, end, org)))),
            'revenue_by_service_line': D(str(queries.revenue_by_service_line(start, end, org)['total'])),
            'effective_hourly_rate_by_client': D(str(sum(
                r['revenue'] for r in queries.effective_hourly_rate_by_client(start, end, org)))),
            'business_overview.revenue_trend': self.run_metric('revenue_trend', customer=self.a.pk).value,
            'financials.totals': financials.totals(start, end, org)['billed_revenue'],
        }
        for name, v in values.items():
            self.assertEqual(D(v).quantize(D('0.01')), self.expected, name)
        # The service-line split also nets the credit note under the credited contract.
        lines = {r['key']: r['revenue'] for r in queries.revenue_by_service_line(start, end, org)['rows']}
        self.assertEqual(lines['managed_services'], 800.0)
        # Contract revenue = what was billed from it, net of its credit note.
        row = [r for r in queries.revenue_by_contract(start, end, org) if r['contract_id'] == self.contract.pk][0]
        self.assertEqual(row['revenue'], 800.0)
        # Dashboard widget, last 30 days, same invoices.
        w = widget_sources.revenue_this_period({'days': 30})
        self.assertEqual(w['value'], '$5,300')   # all customers: 1300 + 4000 (widget is unscoped for a superuser)

    def test_business_overview_scope_unchanged(self):
        r = self.run_metric('revenue_trend', user=self.scoped)
        self.assertEqual(r.value, self.expected)            # customer A only
        self.assertEqual(self.run_metric('revenue_trend').value, self.expected + D('4000'))

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_profitability_page_shows_definitions_and_billed_figure(self):
        from django.test import Client
        c = Client()
        c.force_login(self.su)
        f = _filters()
        r = c.get(reverse('reports:psa_profitability_by_client'),
                  {'start': f.start.isoformat(), 'end': f.end.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-financial-definitions')
        self.assertContains(r, 'Billed revenue')
        self.assertEqual(r.context['total_revenue'], 5300.0)
