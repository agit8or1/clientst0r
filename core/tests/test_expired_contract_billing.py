"""An expired contract stops invoicing.

`psa_generate_recurring_invoices` filtered on `status='active'` alone, and
nothing ever set a contract to `expired` — `expired` has been a valid status
since the model was written and was never assigned. `psa_auto_renew_contracts`
only handles `auto_renew=True`, and `psa_advance_subscription_lifecycle` only
cancelled contracts explicitly flagged `cancel_at_period_end`.

So a client who simply did not renew went on being invoiced every month,
indefinitely — while `Contract.for_ticket`, which has always respected
`end_date`, had already stopped treating them as covered. Billed for a
contract that no longer covered their tickets.

Fixed at both levels: the lifecycle cron expires them, and the invoice cron
filters on `end_date` regardless, so the billing stops even on an install
where the lifecycle cron has never run.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization
from psa.models import Contract, Invoice


def contract(org, **kw):
    today = date.today()
    defaults = dict(
        organization=org, client_org=org, name='Retainer', status='active',
        billing_frequency='monthly', recurring_amount=Decimal('500.00'),
        start_date=today - timedelta(days=365), next_billing_date=today,
        auto_renew=False)
    defaults.update(kw)
    return Contract.objects.create(**defaults)


class ExpiredContractsStopBillingTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Client', slug='exp-client')
        self.today = date.today()

    def _invoices(self, c):
        return Invoice.objects.filter(source_contract=c).count()

    # -- the safety net in the invoice cron ----------------------------------

    def test_an_ended_contract_is_not_invoiced(self):
        c = contract(self.org, end_date=self.today - timedelta(days=90))
        call_command('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(c), 0)

    def test_an_open_ended_contract_still_bills(self):
        c = contract(self.org, end_date=None)
        call_command('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(c), 1)

    def test_a_contract_ending_in_the_future_still_bills(self):
        c = contract(self.org, end_date=self.today + timedelta(days=90))
        call_command('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(c), 1)

    def test_a_contract_ending_today_still_bills_its_final_period(self):
        c = contract(self.org, end_date=self.today)
        call_command('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(c), 1)

    def test_the_filter_holds_even_when_the_lifecycle_cron_never_ran(self):
        """The whole point of fixing it in two places."""
        c = contract(self.org, end_date=self.today - timedelta(days=5))
        self.assertEqual(c.status, 'active')      # never expired
        call_command('psa_generate_recurring_invoices')
        self.assertEqual(self._invoices(c), 0)

    # -- the state fix in the lifecycle cron ---------------------------------

    def test_the_lifecycle_cron_expires_an_ended_contract(self):
        c = contract(self.org, end_date=self.today - timedelta(days=1))
        call_command('psa_advance_subscription_lifecycle')
        c.refresh_from_db()
        self.assertEqual(c.status, 'expired')

    def test_it_leaves_an_auto_renewing_contract_for_the_renewal_cron(self):
        """Expiring it here would race `psa_auto_renew_contracts`."""
        c = contract(self.org, end_date=self.today - timedelta(days=1),
                     auto_renew=True)
        call_command('psa_advance_subscription_lifecycle')
        c.refresh_from_db()
        self.assertEqual(c.status, 'active')

    def test_an_auto_renewing_contract_that_was_renewed_is_expired(self):
        """Once succeeded, it is no longer the live agreement."""
        c = contract(self.org, end_date=self.today - timedelta(days=40),
                     auto_renew=True)
        contract(self.org, name='Renewal', auto_renew=True,
                 start_date=self.today - timedelta(days=39),
                 end_date=self.today + timedelta(days=300),
                 parent_contract=c)
        call_command('psa_advance_subscription_lifecycle')
        c.refresh_from_db()
        self.assertEqual(c.status, 'expired')

    def test_it_leaves_a_live_contract_alone(self):
        c = contract(self.org, end_date=self.today + timedelta(days=30))
        call_command('psa_advance_subscription_lifecycle')
        c.refresh_from_db()
        self.assertEqual(c.status, 'active')

    def test_it_is_idempotent(self):
        c = contract(self.org, end_date=self.today - timedelta(days=10))
        call_command('psa_advance_subscription_lifecycle')
        call_command('psa_advance_subscription_lifecycle')
        c.refresh_from_db()
        self.assertEqual(c.status, 'expired')

    def test_dry_run_changes_nothing(self):
        c = contract(self.org, end_date=self.today - timedelta(days=10))
        call_command('psa_advance_subscription_lifecycle', '--dry-run')
        c.refresh_from_db()
        self.assertEqual(c.status, 'active')

    # -- the two together ----------------------------------------------------

    def test_expiring_then_billing_produces_no_invoice(self):
        c = contract(self.org, end_date=self.today - timedelta(days=90))
        call_command('psa_advance_subscription_lifecycle')
        call_command('psa_generate_recurring_invoices')
        c.refresh_from_db()
        self.assertEqual(c.status, 'expired')
        self.assertEqual(self._invoices(c), 0)
