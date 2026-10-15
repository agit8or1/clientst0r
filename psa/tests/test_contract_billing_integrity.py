"""Contract billing integrity (v3.17.600).

Three defects, each of which made a contract bill the wrong amount:

1. `psa_auto_renew_contracts` created the renewal without the billing
   schedule (billing_frequency defaulted to 'none') and expired the old
   contract, so recurring invoicing silently stopped at the first renewal.
   Meters were not copied either.
2. `TicketTimeEntry.save()` added every entry's minutes to the active
   contract's `hours_used_minutes`: non-billable entries and excluded roles
   counted, a re-saved entry was counted again, deletes never subtracted.
   The value is now recomputed from the entries.
3. A contract flagged cancel-at-period-end was skipped only by the scheduled
   invoice run; a manual run billed the next period and advanced the cursor,
   and the lifecycle job (which keyed off that cursor) then never cancelled it.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from psa.models import (
    Contract, ContractBundleItem, ContractMeter, Invoice, InvoiceLineItem,
    Ticket, TicketTimeEntry,
)
from psa.tests._base import _setup_seed


def _run(cmd, *args):
    call_command(cmd, *args, stdout=io.StringIO())


# ---------------------------------------------------------------------------
# 1. Auto-renewal keeps billing
# ---------------------------------------------------------------------------

class AutoRenewalKeepsBillingTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='MSP', slug='renew-msp')
        self.client_org = Organization.objects.create(name='Client', slug='renew-client')
        self.today = date.today()
        self.old = Contract.objects.create(
            organization=self.org, client_org=self.client_org,
            name='Managed Services', contract_type='managed_services',
            status='active',
            start_date=self.today - relativedelta(years=1),
            end_date=self.today - timedelta(days=1),
            auto_renew=True, auto_renew_period_months=12,
            billing_frequency='monthly', recurring_amount=Decimal('750.00'),
            proration_enabled=True,
            total_hours=Decimal('10'), hourly_rate=Decimal('120'),
            overage_rate=Decimal('150'),
            billable_role_codes=['T1', 'T2'], excluded_role_codes=['project'],
            sla_matrix={'p1': {'response_minutes': 15}},
        )
        # The old contract billed its last two periods; the cursor sits on
        # the period after them (today), exactly as the generator leaves it.
        self.last_period = self.today - relativedelta(months=1)
        self.prev_period = self.today - relativedelta(months=2)
        for p in (self.prev_period, self.last_period):
            self.assertIsNotNone(self.old.generate_invoice(on_date=p))
        self.old.next_billing_date = self.today
        self.old.save()
        ContractBundleItem.objects.create(
            contract=self.old, name='Backup', quantity=Decimal('3'),
            unit_price=Decimal('10'))
        self.meter = ContractMeter.objects.create(
            contract=self.old, name='M365 seats', unit='seat',
            unit_price=Decimal('5.00'), current_quantity=Decimal('4'))

    def _renewal(self):
        return Contract.objects.get(parent_contract=self.old)

    def test_renewal_copies_billing_terms(self):
        _run('psa_auto_renew_contracts')
        self.old.refresh_from_db()
        new = self._renewal()
        self.assertEqual(self.old.status, 'expired')
        self.assertEqual(new.status, 'active')
        self.assertEqual(new.start_date, self.today)
        self.assertEqual(new.billing_frequency, 'monthly')
        self.assertEqual(new.recurring_amount, Decimal('750.00'))
        self.assertEqual(new.next_billing_date, self.today)
        self.assertTrue(new.proration_enabled)
        self.assertEqual(new.total_hours, Decimal('10'))
        self.assertEqual(new.hourly_rate, Decimal('120'))
        self.assertEqual(new.overage_rate, Decimal('150'))
        self.assertEqual(new.billable_role_codes, ['T1', 'T2'])
        self.assertEqual(new.excluded_role_codes, ['project'])
        self.assertEqual(new.sla_matrix, {'p1': {'response_minutes': 15}})
        self.assertTrue(new.auto_renew)
        self.assertEqual(new.bundle_items.count(), 1)

    def test_meters_are_copied_with_their_unbilled_usage(self):
        _run('psa_auto_renew_contracts')
        new = self._renewal()
        meters = list(new.meters.all())
        self.assertEqual(len(meters), 1)
        self.assertEqual(meters[0].name, 'M365 seats')
        self.assertEqual(meters[0].unit_price, Decimal('5.00'))
        self.assertEqual(meters[0].current_quantity, Decimal('4'))
        self.meter.refresh_from_db()
        self.assertEqual(self.meter.current_quantity, Decimal('0'))

    def test_next_period_is_invoiced_on_the_renewed_contract(self):
        _run('psa_auto_renew_contracts')
        new = self._renewal()
        _run('psa_generate_recurring_invoices', '--no-catch-up')
        invs = Invoice.objects.filter(source_contract=new)
        self.assertEqual(invs.count(), 1)
        inv = invs.get()
        self.assertEqual(inv.billing_period_start, self.today)
        base = InvoiceLineItem.objects.get(invoice=inv, source_id=str(new.pk))
        # Full amount: not prorated as if it were a brand-new subscription.
        self.assertEqual(base.unit_price, Decimal('750.00'))
        # Carried-over meter usage is billed on the renewal.
        self.assertTrue(InvoiceLineItem.objects.filter(
            invoice=inv, source_id__startswith='meter:').exists())
        # Nothing new on the old contract; no period billed twice.
        self.assertEqual(
            Invoice.objects.filter(source_contract=self.old).count(), 2)
        periods = list(Invoice.objects.filter(
            client_org=self.client_org, is_credit_memo=False,
        ).values_list('billing_period_start', flat=True))
        self.assertEqual(len(periods), len(set(periods)))
        new.refresh_from_db()
        self.assertEqual(new.next_billing_date,
                         self.today + relativedelta(months=1))

    def test_renewal_never_restarts_on_an_already_billed_period(self):
        # Someone moved the old cursor back onto a billed period by hand.
        self.old.next_billing_date = self.prev_period
        self.old.save()
        _run('psa_auto_renew_contracts')
        new = self._renewal()
        self.assertEqual(new.next_billing_date, self.today)
        _run('psa_generate_recurring_invoices')
        self.assertFalse(Invoice.objects.filter(
            source_contract=new,
            billing_period_start__lte=self.last_period).exists())

    def test_cancel_at_period_end_contract_is_not_renewed(self):
        self.old.cancel_at_period_end = True
        self.old.save()
        _run('psa_auto_renew_contracts')
        self.assertFalse(Contract.objects.filter(parent_contract=self.old).exists())

    def test_dry_run_changes_nothing(self):
        _run('psa_auto_renew_contracts', '--dry-run')
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'active')
        self.assertFalse(Contract.objects.filter(parent_contract=self.old).exists())


# ---------------------------------------------------------------------------
# 2. Contract hour usage
# ---------------------------------------------------------------------------

class ContractHourUsageTests(TestCase):

    def setUp(self):
        _setup_seed()
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType
        self.msp = Organization.objects.create(name='MSP', slug='hours-msp')
        self.client_org = Organization.objects.create(name='Client', slug='hours-client')
        self.user = User.objects.create_user('hours-tech', password='pw')
        self.contract = Contract.objects.create(
            organization=self.msp, client_org=self.client_org, name='Block',
            status='active', start_date=date.today() - timedelta(days=10),
            total_hours=Decimal('10'),
        )
        self.ticket = Ticket.objects.create(
            organization=self.client_org, subject='Hours',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )

    def _entry(self, minutes, **kw):
        now = timezone.now()
        defaults = dict(ticket=self.ticket, user=self.user,
                        started_at=now - timedelta(minutes=minutes),
                        ended_at=now, duration_minutes=minutes)
        defaults.update(kw)
        return TicketTimeEntry.objects.create(**defaults)

    def _used(self):
        self.contract.refresh_from_db()
        return self.contract.hours_used_minutes

    def test_billable_entry_is_counted(self):
        self._entry(45)
        self.assertEqual(self._used(), 45)

    def test_non_billable_entry_is_not_counted(self):
        self._entry(45)
        self._entry(30, is_billable=False)
        self.assertEqual(self._used(), 45)

    def test_excluded_role_is_not_counted(self):
        self.contract.excluded_role_codes = ['project']
        self.contract.save()
        self._entry(20, role_code='T1')
        self._entry(40, role_code='project')
        self.assertEqual(self._used(), 20)

    def test_billable_role_list_limits_tagged_entries(self):
        self.contract.billable_role_codes = ['T1']
        self.contract.save()
        self._entry(20, role_code='T1')
        self._entry(40, role_code='T3')
        self._entry(5)  # untagged entries still count
        self.assertEqual(self._used(), 25)

    def test_delete_subtracts(self):
        keep = self._entry(30)
        gone = self._entry(60)
        self.assertEqual(self._used(), 90)
        gone.delete()
        self.assertEqual(self._used(), 30)
        keep.delete()
        self.assertEqual(self._used(), 0)

    def test_queryset_delete_subtracts(self):
        self._entry(30)
        self._entry(60)
        TicketTimeEntry.objects.filter(ticket=self.ticket).delete()
        self.assertEqual(self._used(), 0)

    def test_edit_60_to_30_yields_30(self):
        e = self._entry(60)
        self.assertEqual(self._used(), 60)
        e.duration_minutes = 30
        e.save()
        self.assertEqual(self._used(), 30)

    def test_resave_does_not_double_count(self):
        e = self._entry(60)
        e.notes = 'edited'
        e.save()
        e.save()
        self.assertEqual(self._used(), 60)

    def test_flipping_to_non_billable_gives_the_time_back(self):
        e = self._entry(60)
        e.is_billable = False
        e.save()
        self.assertEqual(self._used(), 0)

    def test_running_timer_counts_only_once_stopped(self):
        e = TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.user,
            started_at=timezone.now() - timedelta(minutes=25))
        self.assertEqual(self._used(), 0)
        e.ended_at = timezone.now()
        e.save()
        self.assertEqual(self._used(), 25)

    def test_entries_outside_the_window_do_not_count(self):
        self._entry(15, started_at=timezone.now() - timedelta(days=30),
                    ended_at=timezone.now() - timedelta(days=30) + timedelta(minutes=15))
        self.assertEqual(self._used(), 0)

    def test_recompute_command_fixes_drift(self):
        self._entry(45)
        self._entry(30, is_billable=False)
        Contract.objects.filter(pk=self.contract.pk).update(hours_used_minutes=999)
        out = io.StringIO()
        call_command('psa_recompute_contract_hours', '--dry-run', stdout=out)
        self.assertEqual(self._used(), 999)
        self.assertIn('999 -> 45', out.getvalue())
        _run('psa_recompute_contract_hours')
        self.assertEqual(self._used(), 45)
        # Idempotent.
        _run('psa_recompute_contract_hours')
        self.assertEqual(self._used(), 45)


# ---------------------------------------------------------------------------
# 3. cancel_at_period_end is never billed past the paid-up period
# ---------------------------------------------------------------------------

class CancelAtPeriodEndTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Client', slug='cape-client')
        self.today = date.today()
        self.c = Contract.objects.create(
            organization=self.org, client_org=self.org, name='Retainer',
            status='active', billing_frequency='monthly',
            recurring_amount=Decimal('500.00'),
            start_date=self.today - relativedelta(months=6),
            next_billing_date=self.today, last_billed_at=self.today - relativedelta(months=1),
            cancel_at_period_end=True,
        )

    def _invoices(self):
        return Invoice.objects.filter(source_contract=self.c).count()

    def test_manual_run_does_not_bill(self):
        _run('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(), 0)
        self.c.refresh_from_db()
        self.assertEqual(self.c.next_billing_date, self.today)

    def test_manual_catch_up_run_does_not_bill_missed_periods(self):
        self.c.next_billing_date = self.today - relativedelta(months=3)
        self.c.save()
        _run('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(), 0)

    def test_scheduled_run_does_not_bill(self):
        _run('psa_generate_recurring_invoices', '--no-catch-up')
        self.assertEqual(self._invoices(), 0)

    def test_generate_invoice_refuses_the_next_period(self):
        self.assertIsNone(self.c.generate_invoice(on_date=self.today))
        self.assertEqual(self._invoices(), 0)

    def test_lifecycle_cancels_on_the_period_end_date(self):
        _run('psa_advance_subscription_lifecycle')
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, 'cancelled')
        self.assertFalse(self.c.cancel_at_period_end)

    def test_lifecycle_then_billing_on_the_same_day_bills_nothing(self):
        _run('psa_generate_recurring_invoices')
        _run('psa_advance_subscription_lifecycle')
        _run('psa_generate_recurring_invoices')
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, 'cancelled')
        self.assertEqual(self._invoices(), 0)

    def test_lifecycle_leaves_a_paid_up_period_running(self):
        self.c.next_billing_date = self.today + timedelta(days=5)
        self.c.save()
        _run('psa_advance_subscription_lifecycle')
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, 'active')
        self.assertTrue(self.c.cancel_at_period_end)

    def test_unflagged_contract_still_bills_on_a_manual_run(self):
        self.c.cancel_at_period_end = False
        self.c.save()
        _run('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(), 1)
