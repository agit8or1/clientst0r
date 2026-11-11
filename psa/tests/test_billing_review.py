"""Phase 36: per-cycle agreement billing review with approve / hold feeding
the pre-invoice approval gate."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa import billing_review as br
from psa.models import (Contract, Invoice, InvoiceLineItem, Queue, Ticket, TicketPriority, TicketStatus,
                        TicketTimeEntry, TicketType)
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech, _setup_seed


def _at(d, hour=10):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hour, 0))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BillingReviewTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.msp = Organization.objects.create(name='MSP Billing', slug='msp-billing-36')
        self.client_org = Organization.objects.create(name='Dental Office', slug='dental-36')
        self.other_msp = Organization.objects.create(name='Other MSP', slug='other-msp-36')
        self.admin = _make_msp_tech(User.objects.create_user('br-admin', password='pw'))
        Membership.objects.create(user=self.admin, organization=self.msp, role=Role.OWNER, is_active=True)
        self.customer_admin = User.objects.create_user('br-cust', password='pw')
        Membership.objects.create(user=self.customer_admin, organization=self.msp, role=Role.ADMIN,
                                  is_active=True)
        self.contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_org, name='Block 10h',
            status='active', start_date=date(2026, 9, 1), total_hours=Decimal('10'),
            hourly_rate=Decimal('100'), overage_rate=Decimal('150'), billing_frequency='monthly')
        self.ticket = Ticket.objects.create(
            organization=self.client_org, subject='Work', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.first())
        # September: 8 h. October: 4 h (2 included, 2 overage) + 1 h non-billable.
        self._time(date(2026, 9, 10), 480)
        self._time(date(2026, 10, 5), 240)
        self._time(date(2026, 10, 6), 60, billable=False)
        self.invoice = Invoice.objects.create(
            organization=self.msp, client_org=self.client_org, title='Oct', invoice_date=date(2026, 10, 1),
            billing_period_start=date(2026, 10, 1), source_contract=self.contract, status='draft')
        InvoiceLineItem.objects.create(invoice=self.invoice, description='Block', quantity=1,
                                       unit_price=Decimal('1000'))
        self.invoice.recompute_totals()

    def _time(self, d, minutes, billable=True):
        TicketTimeEntry.objects.create(ticket=self.ticket, user=self.admin, started_at=_at(d),
                                       ended_at=_at(d) + timedelta(minutes=minutes), is_billable=billable)

    def _login(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = (org or self.msp).id
        s.save()
        return c

    def _rows(self, period):
        start, end = br.parse_cycle(period)
        return br.build_rows(br.contracts_for_cycle(Contract.objects.all(), start, end), start, end)

    def test_cycle_split_into_included_and_overage(self):
        (row,) = self._rows('2026-10')
        self.assertEqual(row.cycle_hours, Decimal('4.00'))
        self.assertEqual(row.included_hours, Decimal('2.00'))
        self.assertEqual(row.overage_hours, Decimal('2.00'))
        self.assertEqual(row.overage_value, Decimal('300.00'))
        self.assertEqual(row.remaining_hours, Decimal('0.00'))
        self.assertEqual(row.invoice, self.invoice)
        self.assertEqual(row.state, 'draft')
        (sept,) = self._rows('2026-09')
        self.assertEqual((sept.included_hours, sept.overage_hours, sept.invoice), (Decimal('8.00'), Decimal('0.00'), None))

    def test_page_lists_agreement_hours_and_invoice(self):
        r = self._login(self.admin).get('/psa/billing-review/?period=2026-10')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Block 10h')
        self.assertContains(r, self.invoice.invoice_number)
        self.assertContains(r, '≈ 300.00 at 150')

    def test_hold_gates_the_invoice_and_approve_clears_it(self):
        c = self._login(self.admin)
        c.post(f'/psa/billing-review/invoices/{self.invoice.pk}/decide/',
               {'decision': 'hold', 'note': 'check overage with AM', 'period': '2026-10'})
        self.invoice.refresh_from_db()
        self.assertTrue(self.invoice.requires_approval)
        self.assertEqual(self.invoice.approval_reason, 'Held at billing review: check overage with AM')
        self.assertEqual(self._rows('2026-10')[0].state, 'held')
        # The existing gate (invoice_form refuses 'sent', push is blocked) reads this flag.
        self.assertIn(self.invoice, Invoice.objects.filter(requires_approval=True, approved_at__isnull=True))

        c.post(f'/psa/billing-review/invoices/{self.invoice.pk}/decide/', {'decision': 'approve', 'period': '2026-10'})
        self.invoice.refresh_from_db()
        self.assertFalse(self.invoice.requires_approval)
        self.assertEqual(self.invoice.approved_by, self.admin)
        self.assertEqual(self._rows('2026-10')[0].state, 'approved')
        logs = AuditLog.objects.filter(object_type='psa.Invoice', object_id=self.invoice.pk,
                                       extra_data__event='billing_review')
        self.assertEqual(sorted(l.extra_data['decision'] for l in logs), ['approve', 'hold'])

    def test_sent_invoices_are_not_changed(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status='sent')
        self._login(self.admin).post(f'/psa/billing-review/invoices/{self.invoice.pk}/decide/',
                                     {'decision': 'hold'})
        self.invoice.refresh_from_db()
        self.assertFalse(self.invoice.requires_approval)

    def test_other_tenants_and_customer_users_are_kept_out(self):
        self.contract.organization = self.other_msp
        self.contract.save(update_fields=['organization'])
        c = self._login(self.admin)
        r = c.get('/psa/billing-review/?period=2026-10')
        self.assertNotContains(r, 'Block 10h')
        r = c.post(f'/psa/billing-review/invoices/{self.invoice.pk}/decide/', {'decision': 'hold'})
        self.assertEqual(r.status_code, 404)
        # A customer-side admin is not MSP staff.
        r = self._login(self.customer_admin).get('/psa/billing-review/')
        self.assertEqual(r.status_code, 404)

    def test_bad_period_falls_back_to_the_current_month(self):
        start, end = br.parse_cycle('nonsense', today=date(2026, 11, 10))
        self.assertEqual((start, end), (date(2026, 11, 1), date(2026, 12, 1)))
