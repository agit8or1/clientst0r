"""Phase 101.4: ticket invoices from the prepaid-hour ledger, rate cards and
billing rules, with an upgrade cutoff against back-billing."""
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import Organization
from pricing.models import BillingRule, RateCard, RateCardLine
from psa.billing import invoicing, ledger
from psa.billing_review import build_rows, contracts_for_cycle, parse_cycle
from psa.models import (
    BillingEngineSettings, Contract, Invoice, InvoiceLineItem, Queue, Ticket, TicketExpense, TicketPriority,
    TicketStatus, TicketTimeEntry, TicketType, TimesheetSubmission,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed

D = Decimal


class _Base(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.cust = Organization.objects.create(name='Billco', slug='i4-billco')
        _enable_psa_for(self.cust)
        self.admin = User.objects.create_superuser('i4_admin', 'a@x.test', 'pw-i4-123')
        self.tech = User.objects.create_user('i4_tech', 't@x.test', 'pw')
        self.ticket = self._ticket()
        self.today = timezone.localdate()
        # Everything in these tests is worked after the upgrade cutoff.
        BillingEngineSettings.objects.update_or_create(
            pk=1, defaults={'ticket_pricing_from': timezone.now() - timedelta(days=60)})

    def _ticket(self):
        return Ticket.objects.create(
            organization=self.cust, subject='Fix it', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.first())

    def _contract(self, **kw):
        d = dict(organization=self.cust, client_org=self.cust, name='Block 10h', contract_type='block_hours',
                 status='active', start_date=self.today - timedelta(days=30),
                 end_date=self.today + timedelta(days=300), total_hours=D('10'),
                 hourly_rate=D('100'), overage_rate=D('150'))
        d.update(kw)
        return Contract.objects.create(**d)

    def _card(self, rate, rate_type='standard', **kw):
        card = RateCard.objects.create(name=f'card {rate} {rate_type}', **kw)
        RateCardLine.objects.create(rate_card=card, role=None, rate_type=rate_type, hourly_rate=D(rate))
        return card

    def _entry(self, minutes, *, days_ago=0, rate_type='', ticket=None, at=None):
        start = at or (timezone.now() - timedelta(days=days_ago, minutes=minutes))
        return TicketTimeEntry.objects.create(
            ticket=ticket or self.ticket, user=self.tech, started_at=start,
            ended_at=start + timedelta(minutes=minutes), duration_minutes=minutes, is_billable=True,
            rate_type=rate_type, notes='work')

    def _approve(self, *entries):
        sub = TimesheetSubmission.objects.create(
            user=self.tech, period_start=self.today - timedelta(days=400), period_end=self.today + timedelta(days=1),
            revision=TimesheetSubmission.objects.count() + 1, status='pending')
        TicketTimeEntry.objects.filter(pk__in=[e.pk for e in entries]).update(submission=sub)
        sub.approve(user=self.admin)
        return sub

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.cust.id
        s.save()
        return c

    def _invoice(self, **post):
        before = set(Invoice.objects.values_list('pk', flat=True))
        r = self._client().post(f'/psa/invoices/from-ticket/{self.ticket.ticket_number}/', post)
        self.assertEqual(r.status_code, 302)
        return Invoice.objects.exclude(pk__in=before).first()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PrepaidInvoicingTests(_Base):

    def test_block_deduction_bills_nothing_and_shows_covered_time(self):
        self._contract()
        e = self._entry(120)
        self._approve(e)
        inv = self._invoice()
        line = inv.line_items.get()
        self.assertEqual((line.quantity, line.unit_price, line.source_id), (D('2.00'), D('0'), str(e.pk)))
        self.assertEqual(inv.total, D('0'))

    def test_partial_overage_split_from_the_ledger(self):
        self._contract(total_hours=D('1'))
        e = self._entry(180)
        self._approve(e)
        inv = self._invoice()
        lines = {ln.unit_price: ln.quantity for ln in inv.line_items.all()}
        self.assertEqual(lines, {D('0'): D('1.00'), D('150.00'): D('2.00')})
        self.assertEqual(inv.subtotal, D('300.00'))
        # The hours shown and the hours billed agree.
        c = Contract.objects.get(pk=inv.source_contract_id)
        self.assertEqual(ledger.summary(c).remaining_hours, D('0.00'))

    def test_unapproved_prepaid_time_is_not_invoiced(self):
        self._contract()
        e = self._entry(60)
        lines, info = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines, [])
        self.assertEqual(info['awaiting_approval'], [e])
        self.assertIsNone(self._invoice())
        # The old counter (unapproved time) no longer drives invoicing.
        self.assertEqual(Contract.objects.get().hours_used_minutes, 60)

    def test_overage_rounded_to_increment(self):
        c = self._contract(total_hours=D('1'))
        BillingRule.objects.create(name='15 up', contract=c, increment_minutes=15, rounding_mode='up',
                                   minimum_billable_minutes=60)
        e = self._entry(110)
        self._approve(e)
        lines, _ = self.ticket.uninvoiced_billing_lines()
        over = [ln for ln in lines if ln['unit_price'] > 0][0]
        # 50 min overage -> 60 (increment only; the minimum is not applied to overage)
        self.assertEqual(over['quantity'], D('1.00'))

    def test_unlimited_coverage_produces_no_labor_charge(self):
        self._contract(contract_type='managed_services', total_hours=D('0'))
        self._card('150')
        e = self._entry(240)
        inv = self._invoice()
        line = inv.line_items.get()
        self.assertEqual((line.unit_price, line.quantity, line.source_id), (D('0'), D('4.00'), str(e.pk)))
        self.assertEqual(inv.total, D('0'))

    def test_approving_twice_never_bills_twice(self):
        self._contract(total_hours=D('1'))
        e = self._entry(120)
        sub = self._approve(e)
        sub.approve(user=self.admin)
        ledger.post_entry(e)
        inv = self._invoice()
        self.assertEqual(inv.subtotal, D('150.00'))
        self.assertIsNone(self._invoice())

    def test_approval_threshold_reads_the_ledger(self):
        c = self._contract()
        self._entry(9 * 60)  # unapproved: the old counter says 90%
        inv = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='x',
                                     invoice_date=self.today, source_contract=c)
        self.assertFalse(inv.flag_for_approval(overage_pct_threshold=80))
        self._approve(TicketTimeEntry.objects.get())
        inv = Invoice.objects.get(pk=inv.pk)
        self.assertTrue(inv.flag_for_approval(overage_pct_threshold=80))
        self.assertIn('90%', inv.approval_reason)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChargeableInvoicingTests(_Base):

    def test_time_and_materials_priced_from_rate_card_with_parts(self):
        self._card('120')
        e = self._entry(90)
        TicketExpense.objects.create(ticket=self.ticket, description='Replacement PSU', amount=D('25'),
                                     incurred_on=self.today)
        inv = self._invoice()
        time_line = inv.line_items.get(source='time')
        self.assertEqual((time_line.quantity, time_line.unit_price, time_line.source_id),
                         (D('1.50'), D('120.00'), str(e.pk)))
        self.assertTrue(inv.line_items.filter(source='expense', unit_price=D('25')).exists())
        self.assertEqual(inv.subtotal, D('205.00'))
        self.assertEqual(inv.status, 'draft')

    def test_no_rate_is_left_off_never_billed_at_zero(self):
        e = self._entry(60)
        lines, info = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines, [])
        self.assertEqual(info['no_rate'][0][0], e)

    def test_agreement_rate_beats_msp_wide_card(self):
        self._card('150')
        self._contract(contract_type='per_incident', total_hours=D('0'), hourly_rate=D('100'))
        self._entry(60)
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines[0]['unit_price'], D('100'))

    def test_customer_card_beats_agreement_rate(self):
        self._contract(contract_type='per_incident', total_hours=D('0'), hourly_rate=D('100'))
        self._card('130', client_org=self.cust)
        self._entry(60)
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines[0]['unit_price'], D('130'))

    def test_minimum_and_increments(self):
        self._card('120')
        BillingRule.objects.create(name='Min 1h, 15 up', minimum_billable_minutes=60, increment_minutes=15,
                                   rounding_mode='up')
        self._entry(20, days_ago=2)
        self._entry(70, days_ago=1)
        lines, info = self.ticket.uninvoiced_billing_lines()
        self.assertEqual([ln['quantity'] for ln in lines], [D('1.00'), D('1.25')])
        self.assertEqual((info['chargeable_minutes'], info['billed_minutes']), (90, 135))
        self.assertIn('20 min worked', lines[0]['description'])

    def test_trip_fee_once_per_onsite_day(self):
        self._card('120')
        self._card('120', rate_type='onsite')
        BillingRule.objects.create(name='Trip', dispatch_fee=D('45'), travel_fee=D('20'))
        noon = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        self._entry(60, rate_type='onsite', at=noon - timedelta(hours=3))
        self._entry(30, rate_type='onsite', at=noon)
        self._entry(30, at=noon + timedelta(hours=2))  # remote, same day: no extra fee
        inv = self._invoice()
        fees = list(inv.line_items.filter(source='fee').values_list('description', 'unit_price'))
        self.assertEqual(sorted(p for _d, p in fees), [D('20.00'), D('45.00')])
        self.assertEqual(inv.subtotal, D('305.00'))  # 2h x 120 + 45 + 20
        # More onsite work the same day later: no second fee.
        self._entry(15, rate_type='onsite', at=noon + timedelta(hours=4))
        inv2 = self._invoice()
        self.assertFalse(inv2.line_items.filter(source='fee').exists())

    def test_holiday_rate_type_from_the_holiday_calendar(self):
        from resourcing.models import Holiday
        self._card('120')
        self._card('180', rate_type='holiday')
        Holiday.objects.create(name='Today off', date=self.today)
        e = self._entry(60, at=timezone.now() - timedelta(minutes=61))
        e.refresh_from_db()
        if timezone.localdate(e.started_at) != self.today:  # pragma: no cover - just after midnight
            self.skipTest('entry crossed midnight')
        self.assertEqual((e.rate_type, e.bill_rate_snapshot), ('holiday', D('180.00')))
        lines, _ = self.ticket.uninvoiced_billing_lines()
        self.assertEqual(lines[0]['unit_price'], D('180.00'))
        self.assertIn('holiday', lines[0]['description'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CutoffAndExistingInvoiceTests(_Base):

    def test_time_before_cutoff_is_not_back_billed(self):
        self._card('120')
        old = self._entry(60, days_ago=5)
        BillingEngineSettings.objects.filter(pk=1).update(ticket_pricing_from=timezone.now() - timedelta(days=1))
        new = self._entry(30)
        lines, info = self.ticket.uninvoiced_billing_lines()
        by_entry = {ln['source_id']: ln['unit_price'] for ln in lines}
        self.assertEqual(by_entry[str(old.pk)], D('0'))      # as before the upgrade
        self.assertEqual(by_entry[str(new.pk)], D('120.00'))
        self.assertEqual(info['before_cutoff'], [old])
        lines, info = self.ticket.uninvoiced_billing_lines(include_before_cutoff=True)
        self.assertEqual({ln['source_id']: ln['unit_price'] for ln in lines}[str(old.pk)], D('120.00'))
        inv = self._invoice(include_before_cutoff='1')
        self.assertEqual(inv.subtotal, D('180.00'))

    def test_existing_invoices_are_never_repriced(self):
        e = self._entry(60)
        draft = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Old draft',
                                       invoice_date=self.today)
        InvoiceLineItem.objects.create(invoice=draft, description='Time: work', quantity=D('1'),
                                       unit_price=D('0'), source='time', source_id=str(e.pk))
        draft.recompute_totals()
        sent = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Sent',
                                      invoice_date=self.today, status='sent')
        InvoiceLineItem.objects.create(invoice=sent, description='Manual', quantity=D('1'), unit_price=D('10'))
        sent.recompute_totals()
        snap = {i.pk: (i.subtotal, i.total, list(i.line_items.values_list('quantity', 'unit_price')))
                for i in Invoice.objects.all()}
        self._card('120')
        self._contract(contract_type='per_incident', total_hours=D('0'), hourly_rate=D('90'))
        self.assertEqual(self.ticket.uninvoiced_billing_lines()[0], [])  # already on the draft
        call_command('billing_preview', stdout=io.StringIO())
        for inv in Invoice.objects.all():
            inv.recompute_totals()
            self.assertEqual((inv.subtotal, inv.total, list(inv.line_items.values_list('quantity', 'unit_price'))),
                             snap[inv.pk])


class ReviewRenewalReportTests(_Base):

    def test_billing_review_counts_approved_time_only(self):
        self._contract(total_hours=D('2'))
        a, b = self._entry(90), self._entry(60)
        self._approve(a)
        start, end = parse_cycle(self.today.strftime('%Y-%m'))
        row = build_rows(contracts_for_cycle(Contract.objects.all(), start, end), start, end)[0]
        self.assertEqual((row.included_minutes, row.overage_minutes), (90, 0))
        self._approve(b)
        row = build_rows(contracts_for_cycle(Contract.objects.all(), start, end), start, end)[0]
        self.assertEqual((row.included_minutes, row.overage_minutes), (120, 30))
        self.assertEqual(row.remaining_hours, D('0.00'))

    def test_auto_renew_rollover_from_the_ledger(self):
        c = self._contract(start_date=self.today - timedelta(days=40), end_date=self.today - timedelta(days=1),
                           auto_renew=True, rollover_percent=D('100'), total_hours=D('5'))
        approved = self._entry(60, days_ago=10)
        self._entry(120, days_ago=5)  # never approved: does not reduce the rollover any more
        self._approve(approved)
        call_command('psa_auto_renew_contracts', stdout=io.StringIO())
        renewal = Contract.objects.get(parent_contract=c)
        self.assertEqual(renewal.rolled_over_minutes, 240)

    def test_reconciliation_report_uses_approved_time(self):
        c = self._contract()
        self._entry(300)
        self._approve(self._entry(60))
        lt = ledger.totals(c)
        self.assertEqual((lt['purchased'], lt['consumed']), (D('10'), D('1')))
        snap = c.profitability_snapshot()
        self.assertEqual(snap['hours_used'], 1.0)


class PreviewCommandTests(_Base):

    def test_preview_shows_old_and_new_per_customer(self):
        self._card('120')
        self._entry(60)
        out = io.StringIO()
        call_command('billing_preview', stdout=out)
        text = out.getvalue()
        self.assertIn('old $0.00 -> new $120.00 (difference $120.00)', text)
        self.assertIn('Billco: old $0.00 -> new $120.00', text)
        self.assertFalse(Invoice.objects.exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReconciliationDrilldownTests(_Base):
    """The agreement reconciliation summary row and its drill-down read the
    same ledger figures; unapproved time is listed apart and uses nothing."""

    def _summary_row(self, contract):
        r = self._client().get('/reports/agreement-reconciliation/')
        self.assertEqual(r.status_code, 200)
        return next(row for row in r.context['rows'] if row['contract'].pk == contract.pk)

    def _detail(self, contract):
        r = self._client().get(f'/reports/agreement-reconciliation/{contract.pk}/')
        self.assertEqual(r.status_code, 200)
        return r

    def _assert_match(self, contract):
        row, r = self._summary_row(contract), self._detail(contract)
        ctx = r.context
        self.assertEqual(D(ctx['covered_total'] + ctx['overage_total']) / 60,
                         D(str(row['consumed_hours'])))
        self.assertEqual(D(ctx['overage_total']) / 60, D(str(row['overage_hours'])))
        self.assertEqual(D(ctx['allowance_minutes']) / 60, D(str(row['allowance_hours'])))
        return row, r

    def test_drilldown_matches_summary_with_unapproved_time(self):
        c = self._contract()
        approved = self._entry(660, days_ago=2)
        pending = self._entry(120, days_ago=1)
        self._approve(approved)
        row, r = self._assert_match(c)
        self.assertEqual((r.context['covered_total'], r.context['overage_total']), (600, 60))
        self.assertEqual([p['entry'] for p in r.context['pending']], [pending])
        self.assertEqual(r.context['pending_minutes'], 120)
        self.assertContains(r, 'Not yet approved')
        self.assertContains(r, 'uses nothing')
        self.assertEqual([x['classification'] for x in r.context['rows']], ['split'])
        # The old counter counted the unapproved time; neither screen does.
        self.assertEqual(Contract.objects.get(pk=c.pk).hours_used_minutes, 780)
        self.assertEqual(row['consumed_hours'], 11.0)
        csv = self._client().get(f'/reports/agreement-reconciliation/{c.pk}/?format=csv').content.decode()
        self.assertIn('not yet approved; uses nothing', csv)

    def test_drilldown_matches_summary_with_overlapping_agreements(self):
        high = self._contract(name='Block A', billing_priority=2, total_hours=D('2'))
        low = self._contract(name='Block B', billing_priority=1, total_hours=D('5'))
        e1 = self._entry(90, days_ago=3)
        e2 = self._entry(60, days_ago=2)
        TicketTimeEntry.objects.filter(pk=e2.pk).update(billing_contract=low, billing_contract_chosen=True)
        e3 = self._entry(45, days_ago=1)  # not approved: would go to Block A
        self._approve(e1, TicketTimeEntry.objects.get(pk=e2.pk))
        _row_h, rh = self._assert_match(high)
        _row_l, rl = self._assert_match(low)
        self.assertEqual([x['entry'].pk for x in rh.context['rows']], [e1.pk])
        self.assertEqual([x['entry'].pk for x in rl.context['rows']], [e2.pk])
        self.assertEqual(rh.context['covered_total'], 90)
        self.assertEqual(rl.context['covered_total'], 60)
        # The unapproved entry is pending under the agreement it would use, only there.
        self.assertEqual([p['entry'].pk for p in rh.context['pending']], [e3.pk])
        self.assertEqual(rl.context['pending'], [])
        # The two agreements together hold exactly the approved time, once.
        self.assertEqual(rh.context['covered_total'] + rl.context['covered_total'], 150)
