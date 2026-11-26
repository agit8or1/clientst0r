"""113.7: the billing review and Ready for Billing queue read their rows once
for all customers instead of once per customer, ticket or agreement.

Every batched reader must give exactly what the per-item reader gives: the
same invoice lines, info, rules and agreements. These tests build a mixed
fixture (prepaid time with overage, chargeable time, onsite fees, items, held
and excluded lines, a running timer, agreements and billing rules with open
and closed windows at every scope) and compare both paths.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from pricing.models import BillingRule
from pricing.services import BillingRuleBook, resolve_billing_rule
from psa import billing_review as br
from psa.billing import coverage, invoicing
from psa.billing import queue as bq
from psa.billing import ticket_charges as tc
from psa.models import BillingQueueDecision, Contract, Invoice, Ticket, TicketTimeEntry
from psa.tests._base import _enable_psa_for
from psa.tests.test_ticket_invoicing_101_4 import _Base

D = Decimal


def _comparable(result):
    """(lines, info) with model rows as pks and the resolution time dropped."""
    lines, info = result

    def line(ln):
        return {k: v for k, v in ln.items() if k != 'price_resolved_at'}

    def pk(v):
        return getattr(v, 'pk', v)

    out = {}
    for k, v in info.items():
        if k in ('held', 'excluded'):
            out[k] = [(line(ln), d.pk) for ln, d in v]
        elif isinstance(v, (list, tuple)):
            out[k] = [tuple(pk(x) for x in item) if isinstance(item, tuple) else pk(item) for item in v]
        else:
            out[k] = v
    return [line(ln) for ln in lines], out


class _Mixed(_Base):

    def setUp(self):
        super().setUp()
        self.other = Organization.objects.create(name='Otherco', slug='bb-otherco')
        _enable_psa_for(self.other)
        t = self.today
        # Prepaid block with an approved entry that goes over the allowance.
        self.block = self._contract(total_hours=D('1'))
        BillingRule.objects.create(name='15 up', contract=self.block, client_org=self.cust,
                                   increment_minutes=15, rounding_mode='up')
        self._approve(self._entry(100, days_ago=2))
        self._entry(30, days_ago=1)                      # not approved yet
        # A third customer without agreements: time and materials with fees.
        self.third = Organization.objects.create(name='Thirdco', slug='bb-thirdco')
        _enable_psa_for(self.third)
        self.tm = Ticket.objects.create(
            organization=self.third, subject='T&M', queue=self.ticket.queue, priority=self.ticket.priority,
            ticket_type=self.ticket.ticket_type, status=self.ticket.status)
        self._card('120')
        self._card('140', rate_type='onsite')
        BillingRule.objects.create(name='cust', client_org=self.third, increment_minutes=30,
                                   rounding_mode='up', dispatch_fee=D('25'), travel_fee=D('10'),
                                   effective_from=t - timedelta(days=20))
        BillingRule.objects.create(name='old cust', client_org=self.third, increment_minutes=6,
                                   rounding_mode='nearest', effective_to=t - timedelta(days=21))
        BillingRule.objects.create(name='msp', increment_minutes=10, rounding_mode='up')
        BillingRule.objects.create(name='msp future', increment_minutes=60, rounding_mode='up',
                                   effective_from=t + timedelta(days=5))
        BillingRule.objects.create(name='inactive', client_org=self.third, increment_minutes=1, is_active=False)
        BillingRule.objects.create(name='block rule open', client_org=self.cust, increment_minutes=5,
                                   rounding_mode='up', effective_to=t + timedelta(days=2))
        self.onsite = self._entry(50, days_ago=3, rate_type='onsite', ticket=self.tm)
        self._entry(20, days_ago=25, ticket=self.tm)
        self.held_entry = self._entry(15, days_ago=4, ticket=self.tm)
        self.excluded_entry = self._entry(10, days_ago=4, ticket=self.tm)
        tc.add_item(self.tm, self.admin, category='materials', description='Cable', unit_price='5')
        BillingQueueDecision.objects.create(client_org=self.third, source='time', source_id=str(self.held_entry.pk),
                                            ticket=self.tm, state='held')
        BillingQueueDecision.objects.create(client_org=self.third, source='time',
                                            source_id=str(self.excluded_entry.pk), ticket=self.tm, state='excluded')
        # A running timer on a third ticket.
        self.running = self._ticket()
        self._entry(40, days_ago=1, ticket=self.running)
        TicketTimeEntry.objects.create(ticket=self.running, user=self.tech, started_at=timezone.now(),
                                       is_billable=True, notes='timer')
        # Another customer with a flat agreement that ended and one that covers.
        self.other_ticket = Ticket.objects.create(
            organization=self.other, subject='Other', queue=self.ticket.queue, priority=self.ticket.priority,
            ticket_type=self.ticket.ticket_type, status=self.ticket.status)
        Contract.objects.create(organization=self.other, client_org=self.other, name='Ended', status='active',
                                contract_type='managed_services', start_date=t - timedelta(days=90),
                                end_date=t - timedelta(days=10), hourly_rate=D('90'))
        Contract.objects.create(organization=self.other, client_org=self.other, name='Managed', status='active',
                                contract_type='managed_services', start_date=t - timedelta(days=9),
                                hourly_rate=D('80'), billing_priority=5)
        Contract.objects.create(organization=self.other, client_org=self.other, name='Draft', status='draft',
                                contract_type='managed_services', start_date=t - timedelta(days=90))
        self._entry(45, days_ago=12, ticket=self.other_ticket)
        self._entry(45, days_ago=2, ticket=self.other_ticket)
        Ticket.objects.filter(pk__in=[self.ticket.pk, self.tm.pk, self.running.pk, self.other_ticket.pk]).update(
            billing_status='ready')
        self.tickets = list(Ticket.objects.filter(billing_status='ready').order_by('pk'))


class BatchedLinesTests(_Mixed):

    def test_many_tickets_give_the_lines_of_one_ticket_each(self):
        one = {t.pk: _comparable(invoicing.ticket_billing_lines(t)) for t in self.tickets}
        many = {pk: _comparable(r) for pk, r in invoicing.ticket_billing_lines_many(self.tickets).items()}
        self.assertEqual(many, one)
        # The fixture exercises what it claims to.
        lines, info = one[self.tm.pk]
        self.assertTrue(any(ln['source'] == 'fee' for ln in lines))
        self.assertEqual(len(info['held']), 1)
        self.assertEqual(len(info['excluded']), 1)
        self.assertTrue(one[self.ticket.pk][1]['awaiting_approval'])
        self.assertTrue(one[self.ticket.pk][1]['overage_minutes'])

    def test_queue_groups_match_one_ticket_at_a_time(self):
        queue = bq.build_queue(self.admin)
        for g in queue:
            for tg in g.tickets:
                single = bq._ticket_group(tg.ticket)
                self.assertEqual(tg.blockers, single.blockers)
                self.assertEqual(tg.total, single.total)
                self.assertEqual([(ln.source, ln.source_id, ln.total, ln.kind) for ln in tg.lines + tg.withheld],
                                 [(ln.source, ln.source_id, ln.total, ln.kind)
                                  for ln in single.lines + single.withheld])
        blockers = {tg.ticket.pk: tg.blockers for g in queue for tg in g.tickets}
        self.assertIn('A timer is still running.', blockers[self.running.pk])

    def test_fee_candidates_match_per_customer(self):
        from psa.billing.consolidated import fee_candidates, fee_candidates_many
        Contract.objects.filter(client_org=self.other, name='Managed').update(billing_frequency='monthly')
        many = fee_candidates_many([self.cust, self.other])
        for client in (self.cust, self.other):
            self.assertEqual([(s.contract.pk, s.reason, s.period) for s in many[client.pk]],
                             [(s.contract.pk, s.reason, s.period) for s in fee_candidates(client)])


class BatchedReferenceDataTests(_Mixed):

    def test_rule_book_resolves_like_the_query(self):
        contracts = list(Contract.objects.all()) + [None]
        book = BillingRuleBook([self.cust.pk, self.other.pk, self.third.pk])
        for days in range(-40, 15, 3):
            on = self.today + timedelta(days=days)
            for client in (self.cust, self.other, self.third, None):
                for contract in contracts:
                    self.assertEqual(book.resolve(client=client, contract=contract, on_date=on),
                                     resolve_billing_rule(client=client, contract=contract, on_date=on),
                                     (days, client, contract))

    def test_preloaded_agreements_match_the_query_for_every_date(self):
        for days in range(-100, 20, 1):
            on = self.today + timedelta(days=days)
            for client in (self.cust, self.other, self.third):
                expected = coverage._agreements_on(client.pk, on)
                with coverage.agreements_read_once():
                    coverage.preload_agreements([self.cust.pk, self.other.pk, self.third.pk])
                    self.assertEqual(coverage.candidate_agreements(client.pk, on), expected, (days, client))

    def test_review_rows_match_one_agreement_at_a_time(self):
        start, end = br.parse_cycle(f'{self.today:%Y-%m}')
        Invoice.objects.create(organization=self.other, client_org=self.other,
                               source_contract=Contract.objects.get(name='Managed'), status='draft',
                               invoice_date=self.today, billing_period_start=start)
        contracts = br.contracts_for_cycle(Contract.objects.all(), start, end)
        rows = br.build_rows(contracts, start, end)
        single = [r for c in contracts for r in br.build_rows(Contract.objects.filter(pk=c.pk), start, end)]
        fields = ('allowance_minutes', 'cycle_minutes', 'included_minutes', 'overage_minutes', 'to_date_minutes',
                  'remaining_override', 'state')
        self.assertEqual([(r.contract.pk, [getattr(r, f) for f in fields], getattr(r.invoice, 'pk', None),
                           [i.pk for i in r.other_invoices]) for r in rows],
                         [(r.contract.pk, [getattr(r, f) for f in fields], getattr(r.invoice, 'pk', None),
                           [i.pk for i in r.other_invoices]) for r in single])
        self.assertTrue(any(r.invoice is not None for r in rows))

    def test_ledger_sums_match_one_agreement_at_a_time(self):
        from psa.billing import ledger
        self.assertIsNotNone(ledger.totals(self.block))
        contracts = list(Contract.objects.order_by('pk'))
        for start, end in ((None, None), (self.today - timedelta(days=3), self.today + timedelta(days=1)),
                           (None, self.today - timedelta(days=1)), (self.today + timedelta(days=1), None)):
            self.assertEqual(ledger.totals_many(contracts, start=start, end=end),
                             {c.pk: ledger.totals(c, start=start, end=end) for c in contracts})
        tracked = [c for c in contracts if ledger.totals(c) is not None]
        for days in (-40, -30, -2, 0, 5, 400):
            on = self.today + timedelta(days=days)
            many = ledger.summaries_many(Contract.objects.filter(pk__in=[c.pk for c in tracked]),
                                         {c.pk: on for c in tracked})
            self.assertEqual(many, {c.pk: ledger.summary(c, as_of=on) for c in tracked}, days)
