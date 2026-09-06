"""
Phase 35.3 (v3.17.553) — project profitability.

Same thread as the budget tests: a figure that cannot be measured is reported as
unknown rather than as a number that looks like a measurement.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from psa.models import (
    Contract, Project, Queue, Ticket, TicketPriority, TicketStatus,
    TicketTimeEntry, TicketType,
)
from psa.tests._base import _setup_seed
from resourcing.models import TechCostRate


class ProjectProfitabilityTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='ProfitCo', slug='profit-co')
        self.tech = User.objects.create_user('techa', 'a@example.com', 'pw')
        self.project = Project.objects.create(
            organization=self.org, name='Migration', client_org=self.org)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Work', project=self.project,
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )

    # A sentinel: `user=None` means "an entry with nobody recorded against
    # it", which is a real case here and cannot share a default with "not
    # passed". Same trap as the budget tests' ticket fixture.
    _UNSET = object()

    def _log(self, minutes, *, user=_UNSET, days_ago=0, billable=True):
        started = timezone.now() - timedelta(days=days_ago, minutes=minutes)
        return TicketTimeEntry.objects.create(
            ticket=self.ticket,
            user=self.tech if user is self._UNSET else user,
            started_at=started,
            ended_at=started + timedelta(minutes=minutes),
            duration_minutes=minutes,
            is_billable=billable,
        )

    def _cost_rate(self, rate, days_ago=30, user=None):
        return TechCostRate.objects.create(
            user=user or self.tech,
            rate_per_hour=Decimal(str(rate)),
            effective_from=date.today() - timedelta(days=days_ago),
        )

    def _contract(self, rate):
        return Contract.objects.create(
            organization=self.org, client_org=self.org, name='MSA',
            status='active', start_date=date.today() - timedelta(days=90),
            hourly_rate=Decimal(str(rate)),
        )

    # --- cost ---

    def test_no_time_is_no_cost(self):
        self.assertEqual(self.project.actual_cost(), Decimal('0.00'))

    def test_cost_uses_the_configured_rate(self):
        self._cost_rate(50)
        self._log(120)
        self.assertEqual(self.project.actual_cost(), Decimal('100.00'))

    def test_non_billable_time_still_costs(self):
        """It cost the business the same whether or not the client pays."""
        self._cost_rate(50)
        self._log(60, billable=False)
        self.assertEqual(self.project.actual_cost(), Decimal('50.00'))

    def test_the_rate_in_force_on_the_day_is_used(self):
        """A raise in June must not retroactively make March's work more
        expensive."""
        self._cost_rate(40, days_ago=90)
        self._cost_rate(80, days_ago=1)
        self._log(60, days_ago=30)   # old rate
        self.assertEqual(self.project.actual_cost(), Decimal('40.00'))

    def test_missing_rate_is_counted_and_still_costed(self):
        """A default is better than refusing to cost anything, but the caller
        is told so a guess is not presented as a measurement."""
        self._log(60)
        breakdown = self.project.cost_breakdown()
        self.assertEqual(breakdown['used_default_for'], 1)
        self.assertGreater(breakdown['cost'], Decimal('0.00'))

    def test_a_configured_rate_is_not_flagged_as_default(self):
        self._cost_rate(50)
        self._log(60)
        self.assertEqual(self.project.cost_breakdown()['used_default_for'], 0)

    def test_entries_without_a_user_are_skipped(self):
        """Charging them at a default would attribute cost to a person who is
        not recorded."""
        self._cost_rate(50)
        self._log(60)
        self._log(60, user=None)
        self.assertEqual(self.project.actual_cost(), Decimal('50.00'))

    def test_cost_is_per_project(self):
        other = Project.objects.create(organization=self.org, name='Other')
        other_ticket = Ticket.objects.create(
            organization=self.org, subject='Other work', project=other,
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )
        self._cost_rate(50)
        TicketTimeEntry.objects.create(
            ticket=other_ticket, user=self.tech,
            started_at=timezone.now() - timedelta(minutes=60),
            ended_at=timezone.now(), duration_minutes=60)
        self.assertEqual(self.project.actual_cost(), Decimal('0.00'))

    # --- margin ---

    def test_no_contract_rate_means_no_revenue_and_no_margin(self):
        """A margin computed against unknown revenue would be a subtraction
        from nothing dressed up as a business figure."""
        self._cost_rate(50)
        self._log(120)
        p = self.project.profitability()
        self.assertIsNone(p['revenue'])
        self.assertIsNone(p['margin'])
        self.assertIsNone(p['margin_percent'])
        self.assertEqual(p['cost'], Decimal('100.00'))

    def test_margin_is_revenue_minus_cost(self):
        self._contract(150)
        self._cost_rate(50)
        self._log(120, billable=True)
        p = self.project.profitability()
        self.assertEqual(p['revenue'], Decimal('300.00'))
        self.assertEqual(p['cost'], Decimal('100.00'))
        self.assertEqual(p['margin'], Decimal('200.00'))

    def test_margin_percent(self):
        self._contract(100)
        self._cost_rate(25)
        self._log(60, billable=True)
        self.assertEqual(self.project.profitability()['margin_percent'], 75.0)

    def test_a_loss_is_reported_as_negative_not_hidden(self):
        self._contract(20)
        self._cost_rate(100)
        self._log(60, billable=True)
        p = self.project.profitability()
        self.assertLess(p['margin'], Decimal('0.00'))
        self.assertLess(p['margin_percent'], 0)

    def test_non_billable_time_hurts_the_margin(self):
        """Revenue counts billable hours only; cost counts all of them."""
        self._contract(100)
        self._cost_rate(50)
        self._log(60, billable=True)
        self._log(60, billable=False)
        p = self.project.profitability()
        self.assertEqual(p['revenue'], Decimal('100.00'))
        self.assertEqual(p['cost'], Decimal('100.00'))
        self.assertEqual(p['margin'], Decimal('0.00'))

    def test_zero_revenue_does_not_divide_by_zero(self):
        self._contract(100)
        self._cost_rate(50)
        self._log(60, billable=False)
        p = self.project.profitability()
        self.assertEqual(p['revenue'], Decimal('0.00'))
        self.assertIsNone(p['margin_percent'])
        self.assertEqual(p['margin'], Decimal('-50.00'))

    def test_hours_are_reported_alongside(self):
        self._contract(100)
        self._log(90, billable=True)
        self._log(30, billable=False)
        p = self.project.profitability()
        self.assertEqual(p['billable_hours'], Decimal('1.50'))
        self.assertEqual(p['total_hours'], Decimal('2.00'))
