"""
Phase 35.2 (v3.17.549) — project budget vs actuals.

The thread running through these: an unknown number is reported as unknown, not
as zero. A project showing no spend because nobody recorded a rate reads as
comfortably under budget, when the truth is that it has not been measured.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from psa.models import (
    Contract, Project, Queue, Ticket, TicketPriority, TicketStatus,
    TicketTimeEntry, TicketType,
)
from psa.tests._base import _setup_seed


class ProjectBudgetTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='BudgetCo', slug='budget-co')
        self.user = User.objects.create_user('budgetuser', 'b@example.com', 'pw')
        self.project = Project.objects.create(
            organization=self.org, name='Migration', client_org=self.org)

    # A sentinel, because `project=None` is a meaningful argument here — a
    # ticket with no project at all — and cannot share a default with "not
    # passed". This is the same conflation the code under test avoids.
    _UNSET = object()

    def _ticket(self, project=_UNSET):
        return Ticket.objects.create(
            organization=self.org, subject='Work',
            project=self.project if project is self._UNSET else project,
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )

    def _log(self, minutes, *, billable=True, ticket=None):
        return TicketTimeEntry.objects.create(
            ticket=ticket or self._ticket(),
            user=self.user,
            started_at=timezone.now() - timedelta(minutes=minutes),
            ended_at=timezone.now(),
            duration_minutes=minutes,
            is_billable=billable,
        )

    def _contract(self, rate):
        return Contract.objects.create(
            organization=self.org, client_org=self.org, name='MSA',
            status='active', start_date=date.today() - timedelta(days=30),
            hourly_rate=rate,
        )

    # --- actuals ---

    def test_no_time_logged_is_zero_hours(self):
        self.assertEqual(self.project.actual_hours(), Decimal('0.00'))

    def test_hours_come_from_tickets_on_the_project(self):
        self._log(90)
        self.assertEqual(self.project.actual_hours(), Decimal('1.50'))

    def test_time_on_another_projects_ticket_is_excluded(self):
        other = Project.objects.create(organization=self.org, name='Other')
        self._log(60, ticket=self._ticket(project=other))
        self.assertEqual(self.project.actual_hours(), Decimal('0.00'))

    def test_time_on_a_ticket_with_no_project_is_excluded(self):
        self._log(60, ticket=self._ticket(project=None))
        self.assertEqual(self.project.actual_hours(), Decimal('0.00'))

    def test_billable_only_excludes_non_billable(self):
        self._log(60, billable=True)
        self._log(30, billable=False)
        self.assertEqual(self.project.actual_hours(), Decimal('1.50'))
        self.assertEqual(
            self.project.actual_hours(billable_only=True), Decimal('1.00'))

    # --- rate and amount ---

    def test_no_contract_means_no_rate_and_no_amount(self):
        """Not zero. A project reporting no spend because nobody recorded a
        rate reads as under budget when it simply has not been measured."""
        self._log(120)
        self.assertIsNone(self.project.billing_rate())
        self.assertIsNone(self.project.actual_amount())

    def test_a_contract_without_a_rate_is_still_unknown(self):
        self._contract(0)
        self.assertIsNone(self.project.billing_rate())
        self.assertIsNone(self.project.actual_amount())

    def test_amount_is_billable_hours_times_the_rate(self):
        self._contract(Decimal('120.00'))
        self._log(120, billable=True)
        self._log(60, billable=False)
        self.assertEqual(self.project.actual_amount(), Decimal('240.00'))

    def test_an_inactive_contract_is_not_used(self):
        c = self._contract(Decimal('120.00'))
        c.status = 'expired'
        c.save(update_fields=['status'])
        self.assertIsNone(self.project.billing_rate())

    # --- state ---

    def test_no_budget_set_reads_as_no_budget(self):
        self._log(600)
        self.assertEqual(self.project.budget_state(), 'no_budget')

    def test_within_budget(self):
        self.project.budget_hours = Decimal('10')
        self.project.save()
        self._log(60)
        self.assertEqual(self.project.budget_state(), 'ok')

    def test_warning_at_the_threshold(self):
        self.project.budget_hours = Decimal('10')
        self.project.budget_warn_at_percent = 80
        self.project.save()
        self._log(8 * 60)
        self.assertEqual(self.project.budget_state(), 'warning')

    def test_over_at_a_hundred_percent(self):
        self.project.budget_hours = Decimal('10')
        self.project.save()
        self._log(10 * 60)
        self.assertEqual(self.project.budget_state(), 'over')

    def test_custom_warning_threshold_is_honoured(self):
        self.project.budget_hours = Decimal('10')
        self.project.budget_warn_at_percent = 50
        self.project.save()
        self._log(5 * 60)
        self.assertEqual(self.project.budget_state(), 'warning')

    def test_worst_of_the_two_budgets_wins(self):
        """A project inside its hours but over its money is over. Saying
        otherwise would be the comfortable answer rather than the true one."""
        self._contract(Decimal('200.00'))
        self.project.budget_hours = Decimal('100')
        self.project.budget_amount = Decimal('100.00')
        self.project.save()
        self._log(60, billable=True)  # 1h = £200 against a £100 budget
        self.assertEqual(self.project.budget_state(), 'over')

    def test_an_unmeasurable_amount_does_not_mask_hours(self):
        """No rate means the money budget cannot be judged, but the hours
        budget still can."""
        self.project.budget_hours = Decimal('1')
        self.project.budget_amount = Decimal('1000.00')
        self.project.save()
        self._log(120)
        self.assertIsNone(self.project.amount_budget_percent())
        self.assertEqual(self.project.budget_state(), 'over')

    def test_percentages(self):
        self.project.budget_hours = Decimal('4')
        self.project.save()
        self._log(60)
        self.assertEqual(self.project.hours_budget_percent(), 25.0)

    def test_percent_is_none_without_a_budget(self):
        self._log(60)
        self.assertIsNone(self.project.hours_budget_percent())

    def test_budget_summary_shape(self):
        self._contract(Decimal('100.00'))
        self.project.budget_hours = Decimal('10')
        self.project.budget_amount = Decimal('1000.00')
        self.project.save()
        self._log(60)
        summary = self.project.budget_summary()
        self.assertEqual(summary['state'], 'ok')
        self.assertEqual(summary['hours_actual'], Decimal('1.00'))
        self.assertEqual(summary['rate'], Decimal('100.00'))
        self.assertEqual(summary['amount_actual'], Decimal('100.00'))
