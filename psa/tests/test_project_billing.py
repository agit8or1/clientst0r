"""
Phase 35.6 (v3.17.555) — project billing.

Most of these are about not billing the same work twice. An invoice is the one
artefact in the system a client actually sees, and issuing the same hours or the
same milestone on two of them is the failure that matters.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import Organization, SystemSetting
from psa.models import (
    Contract, Invoice, InvoiceLineItem, Project, ProjectTask, Queue, Ticket,
    TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
)
from psa.tests._base import _enable_psa_for, _setup_seed

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class _BillingCase(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='BillCo', slug='bill-co')
        self.tech = User.objects.create_user('billtech', 'b@example.com', 'pw')
        self.project = Project.objects.create(
            organization=self.org, name='Migration', client_org=self.org)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Work', project=self.project,
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )

    def _log(self, minutes, *, billable=True):
        started = timezone.now() - timedelta(minutes=minutes)
        return TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.tech,
            started_at=started, ended_at=timezone.now(),
            duration_minutes=minutes, is_billable=billable)

    def _contract(self, rate=Decimal('100.00')):
        return Contract.objects.create(
            organization=self.org, client_org=self.org, name='MSA',
            status='active', start_date=date.today() - timedelta(days=90),
            hourly_rate=rate)

    def _milestone(self, title, amount=None, status='todo'):
        return ProjectTask.objects.create(
            project=self.project, title=title, is_milestone=True,
            status=status, billing_amount=amount)


class TimeAndMaterialsBillingTests(_BillingCase):
    def test_nothing_to_bill_returns_no_invoice(self):
        """An invoice with no lines is worse than none at all."""
        invoice, message = self.project.generate_invoice()
        self.assertIsNone(invoice)
        self.assertIn('No unbilled', message)

    def test_no_rate_refuses_rather_than_invoicing_zero(self):
        self._log(60)
        invoice, message = self.project.generate_invoice()
        self.assertIsNone(invoice)
        self.assertIn('no hourly rate', message.lower())

    def test_billable_time_becomes_an_invoice(self):
        self._contract()
        self._log(90)
        invoice, _ = self.project.generate_invoice()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.line_items.count(), 1)
        self.assertEqual(invoice.status, 'draft')

    def test_the_invoice_totals_the_hours_at_the_contract_rate(self):
        self._contract(Decimal('120.00'))
        self._log(90)
        invoice, _ = self.project.generate_invoice()
        self.assertEqual(invoice.subtotal, Decimal('180.00'))

    def test_non_billable_time_is_not_invoiced(self):
        self._contract()
        self._log(60, billable=False)
        invoice, _ = self.project.generate_invoice()
        self.assertIsNone(invoice)

    def test_the_same_hours_are_not_billed_twice(self):
        """The failure that matters."""
        self._contract()
        self._log(60)
        first, _ = self.project.generate_invoice()
        self.assertIsNotNone(first)
        second, message = self.project.generate_invoice()
        self.assertIsNone(second)
        self.assertIn('No unbilled', message)

    def test_new_time_after_an_invoice_is_billable_again(self):
        self._contract()
        self._log(60)
        self.project.generate_invoice()
        self._log(30)
        second, _ = self.project.generate_invoice()
        self.assertIsNotNone(second)
        self.assertEqual(second.line_items.count(), 1)

    def test_zero_length_entries_are_skipped(self):
        self._contract()
        TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.tech,
            started_at=timezone.now(), duration_minutes=0, is_billable=True)
        invoice, _ = self.project.generate_invoice()
        self.assertIsNone(invoice)

    def test_time_on_another_project_is_not_pulled_in(self):
        self._contract()
        other = Project.objects.create(organization=self.org, name='Other')
        other_ticket = Ticket.objects.create(
            organization=self.org, subject='Elsewhere', project=other,
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )
        TicketTimeEntry.objects.create(
            ticket=other_ticket, user=self.tech,
            started_at=timezone.now() - timedelta(minutes=60),
            ended_at=timezone.now(), duration_minutes=60, is_billable=True)
        invoice, _ = self.project.generate_invoice()
        self.assertIsNone(invoice)

    def test_the_invoice_is_linked_to_the_project(self):
        self._contract()
        self._log(60)
        invoice, _ = self.project.generate_invoice()
        self.assertEqual(invoice.project, self.project)


class FixedFeeBillingTests(_BillingCase):
    def setUp(self):
        super().setUp()
        self.project.billing_type = Project.BILLING_FIXED_FEE
        self.project.fixed_fee_amount = Decimal('5000.00')
        self.project.save()

    def test_a_fixed_fee_becomes_one_line(self):
        invoice, _ = self.project.generate_invoice()
        self.assertEqual(invoice.line_items.count(), 1)
        self.assertEqual(invoice.subtotal, Decimal('5000.00'))

    def test_a_fixed_fee_bills_once(self):
        self.project.generate_invoice()
        second, message = self.project.generate_invoice()
        self.assertIsNone(second)
        self.assertIn('already been invoiced', message)

    def test_no_amount_set_refuses(self):
        self.project.fixed_fee_amount = None
        self.project.save()
        invoice, message = self.project.generate_invoice()
        self.assertIsNone(invoice)
        self.assertIn('no fixed fee amount', message.lower())

    def test_logged_time_does_not_add_lines_on_a_fixed_fee_project(self):
        """The whole point of a fixed fee: hours do not change the bill."""
        self._contract()
        self._log(600)
        invoice, _ = self.project.generate_invoice()
        self.assertEqual(invoice.line_items.count(), 1)
        self.assertEqual(invoice.subtotal, Decimal('5000.00'))


class MilestoneBillingTests(_BillingCase):
    def setUp(self):
        super().setUp()
        self.project.billing_type = Project.BILLING_MILESTONE
        self.project.save()

    def test_a_completed_priced_milestone_bills(self):
        self._milestone('Phase 1', Decimal('2000.00'), status='done')
        invoice, _ = self.project.generate_invoice()
        self.assertEqual(invoice.subtotal, Decimal('2000.00'))

    def test_an_unfinished_milestone_does_not_bill(self):
        self._milestone('Phase 1', Decimal('2000.00'), status='todo')
        invoice, message = self.project.generate_invoice()
        self.assertIsNone(invoice)
        self.assertIn('No completed', message)

    def test_a_priceless_milestone_does_not_bill(self):
        self._milestone('Phase 1', None, status='done')
        invoice, _ = self.project.generate_invoice()
        self.assertIsNone(invoice)

    def test_a_milestone_is_stamped_with_its_invoice(self):
        m = self._milestone('Phase 1', Decimal('2000.00'), status='done')
        invoice, _ = self.project.generate_invoice()
        m.refresh_from_db()
        self.assertEqual(m.billed_on_invoice, invoice)

    def test_a_milestone_bills_once(self):
        self._milestone('Phase 1', Decimal('2000.00'), status='done')
        self.project.generate_invoice()
        second, _ = self.project.generate_invoice()
        self.assertIsNone(second)

    def test_a_later_milestone_bills_separately(self):
        self._milestone('Phase 1', Decimal('2000.00'), status='done')
        self.project.generate_invoice()
        self._milestone('Phase 2', Decimal('3000.00'), status='done')
        second, _ = self.project.generate_invoice()
        self.assertEqual(second.subtotal, Decimal('3000.00'))

    def test_several_ready_milestones_go_on_one_invoice(self):
        self._milestone('Phase 1', Decimal('2000.00'), status='done')
        self._milestone('Phase 2', Decimal('3000.00'), status='done')
        invoice, _ = self.project.generate_invoice()
        self.assertEqual(invoice.line_items.count(), 2)
        self.assertEqual(invoice.subtotal, Decimal('5000.00'))

    def test_a_non_milestone_task_never_bills(self):
        ProjectTask.objects.create(
            project=self.project, title='Ordinary work', status='done',
            billing_amount=Decimal('999.00'))
        invoice, _ = self.project.generate_invoice()
        self.assertIsNone(invoice)


class BillableSummaryTests(_BillingCase):
    def test_time_summary_reports_unknown_amount_without_a_rate(self):
        self._log(60)
        summary = self.project.billable_summary()
        self.assertEqual(summary['lines'], 1)
        self.assertIsNone(summary['amount'])
        self.assertFalse(summary['rate_known'])

    def test_time_summary_with_a_rate(self):
        self._contract(Decimal('100.00'))
        self._log(90)
        summary = self.project.billable_summary()
        self.assertEqual(summary['hours'], Decimal('1.50'))
        self.assertEqual(summary['amount'], Decimal('150.00'))

    def test_fixed_fee_summary_after_billing(self):
        self.project.billing_type = Project.BILLING_FIXED_FEE
        self.project.fixed_fee_amount = Decimal('1000.00')
        self.project.save()
        self.project.generate_invoice()
        summary = self.project.billable_summary()
        self.assertTrue(summary['already_billed'])
        self.assertEqual(summary['lines'], 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BillingViewTests(_BillingCase):
    def setUp(self):
        super().setUp()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        _enable_psa_for(self.org)
        self.admin = User.objects.create_superuser(
            'billadmin', 'ba@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.admin)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()

    def test_generate_creates_a_draft_invoice(self):
        self._contract()
        self._log(60)
        self.client.post(f'/psa/projects/{self.project.pk}/invoice/')
        self.assertEqual(Invoice.objects.filter(project=self.project).count(), 1)
        self.assertEqual(Invoice.objects.get().status, 'draft')

    def test_get_does_not_generate(self):
        self._contract()
        self._log(60)
        self.client.get(f'/psa/projects/{self.project.pk}/invoice/')
        self.assertEqual(Invoice.objects.count(), 0)

    def test_nothing_to_bill_creates_nothing(self):
        self.client.post(f'/psa/projects/{self.project.pk}/invoice/')
        self.assertEqual(Invoice.objects.count(), 0)

    def test_another_organizations_project_is_not_reachable(self):
        other = Organization.objects.create(name='NotUs', slug='not-us-bill')
        _enable_psa_for(other)
        foreign = Project.objects.create(organization=other, name='Theirs')
        resp = self.client.post(f'/psa/projects/{foreign.pk}/invoice/')
        self.assertEqual(resp.status_code, 404)
