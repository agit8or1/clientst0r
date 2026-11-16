"""
Accurate profitability reporting.

Every former placeholder (60 % of the bill rate, a $150 bill rate, a $60
loaded rate) is gone: a missing rate is reported as UNKNOWN, totals carry
`unknown_cost_hours` / `unknown_cost_entries` / `is_complete`, and margins are
None while incomplete. Rates are looked up per entry date, per-entry snapshots
win when the model carries them, and labour cost / margin is behind the
staff-only `view_profitability` permission.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from core.models import Organization
from psa.models import (
    Contract, Invoice, InvoiceLineItem, Queue, Ticket, TicketPriority, TicketStatus,
    TicketTimeEntry, TicketType,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed
from resourcing.models import TechCostRate, WorkingHours


def _at(day, hour=10):
    return timezone.make_aware(datetime.combine(day, time(hour, 0)))


class _Fixture(TestCase):
    """Two client orgs, a tech, tickets; helpers for entries / rates / contracts."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        cls.today = timezone.localdate()
        cls.msp = Organization.objects.create(name='MSP Home', slug='prof-msp')
        cls.acme = Organization.objects.create(name='Acme', slug='prof-acme')
        cls.beta = Organization.objects.create(name='Beta', slug='prof-beta')
        cls.tech = User.objects.create_user('prof_tech', 't@msp.test', 'pw')
        cls.tech2 = User.objects.create_user('prof_tech2', 't2@msp.test', 'pw')
        cls.t_acme = cls._ticket(cls.acme)
        cls.t_beta = cls._ticket(cls.beta)

    @classmethod
    def _ticket(cls, org):
        return Ticket.objects.create(
            organization=org, subject=f'{org.name} work',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )

    def entry(self, minutes, *, ticket=None, user=None, day=None, billable=True):
        day = day or self.today
        start = _at(day)
        return TicketTimeEntry.objects.create(
            ticket=ticket or self.t_acme, user=user if user is not None else self.tech,
            started_at=start, ended_at=start + timedelta(minutes=minutes),
            duration_minutes=minutes, is_billable=billable,
        )

    def rate(self, amount, days_ago=365, user=None):
        return TechCostRate.objects.create(
            user=user or self.tech, rate_per_hour=Decimal(str(amount)),
            effective_from=self.today - timedelta(days=days_ago))

    def contract(self, client=None, **kw):
        # One MSP per install: a contract's organization is the customer.
        kw.setdefault('name', 'MSA')
        kw.setdefault('status', 'active')
        kw.setdefault('start_date', self.today - timedelta(days=90))
        client = client or self.acme
        return Contract.objects.create(organization=client, client_org=client, **kw)

    def invoice(self, client, total, number, **kw):
        kw.setdefault('status', 'sent')
        return Invoice.objects.create(
            organization=client, client_org=client, invoice_number=number, title=number,
            invoice_date=kw.pop('invoice_date', self.today), due_date=self.today,
            total=Decimal(str(total)), subtotal=Decimal(str(total)), amount_paid=0,
            tax_amount=0, currency='USD', **kw)


# ---------------------------------------------------------------------------
# reports.costing
# ---------------------------------------------------------------------------

class CostingLookupTests(_Fixture):

    def test_no_rate_rows_is_unknown(self):
        from reports.costing import cost_rate_for
        self.assertIsNone(cost_rate_for(self.tech, self.today))
        self.assertIsNone(cost_rate_for(None, self.today))

    def test_effective_dated_rate_and_future_rows_ignored(self):
        from reports.costing import cost_rate_for
        self.rate(40, days_ago=100)
        self.rate(70, days_ago=10)
        self.rate(99, days_ago=-30)  # starts in the future
        self.assertEqual(cost_rate_for(self.tech, self.today - timedelta(days=50)), Decimal('40'))
        self.assertEqual(cost_rate_for(self.tech, self.today), Decimal('70'))
        self.assertIsNone(cost_rate_for(self.tech, self.today - timedelta(days=200)))

    def test_cost_snapshot_preferred_over_rate_rows(self):
        from reports.costing import entry_cost_rate
        self.rate(70)
        snap = SimpleNamespace(cost_rate_snapshot=Decimal('33.50'), user_id=self.tech.pk,
                               started_at=_at(self.today), duration_minutes=60)
        self.assertEqual(entry_cost_rate(snap), Decimal('33.50'))
        # Snapshot field present but unset -> falls back to the dated rate.
        snap.cost_rate_snapshot = None
        self.assertEqual(entry_cost_rate(snap), Decimal('70'))
        # A real entry (no snapshot field on this branch) uses the rate row.
        self.assertEqual(entry_cost_rate(self.entry(60)), Decimal('70'))

    def test_bill_snapshot_preferred_over_contract(self):
        from reports.costing import bill_rate_for
        self.contract(hourly_rate=Decimal('150'))
        snap = SimpleNamespace(bill_rate_snapshot=Decimal('175'), ticket=self.t_acme,
                               started_at=_at(self.today))
        self.assertEqual(bill_rate_for(snap), Decimal('175'))
        snap.bill_rate_snapshot = None
        self.assertEqual(bill_rate_for(snap), Decimal('150'))

    def test_entry_contract_fk_used_when_present(self):
        from reports.costing import bill_rate_for
        self.contract(hourly_rate=Decimal('150'))
        own = SimpleNamespace(hourly_rate=Decimal('0'), overage_rate=Decimal('210'))
        e = SimpleNamespace(contract=own, ticket=self.t_acme, started_at=_at(self.today))
        self.assertEqual(bill_rate_for(e), Decimal('210'))

    def test_bill_rate_from_contract_covering_entry_date(self):
        from reports.costing import bill_rate_for
        self.contract(name='Old', status='expired', hourly_rate=Decimal('100'),
                      start_date=self.today - timedelta(days=400),
                      end_date=self.today - timedelta(days=200))
        self.contract(name='New', hourly_rate=Decimal('0'), overage_rate=Decimal('180'),
                      start_date=self.today - timedelta(days=199))
        self.contract(name='Draft', status='draft', hourly_rate=Decimal('999'),
                      start_date=self.today - timedelta(days=500))
        old = self.entry(60, day=self.today - timedelta(days=300))
        new = self.entry(60)
        self.assertEqual(bill_rate_for(old), Decimal('100'))
        self.assertEqual(bill_rate_for(new), Decimal('180'))  # overage when hourly is 0

    def test_no_contract_or_flat_fee_is_unknown(self):
        from reports.costing import bill_rate_for
        self.assertIsNone(bill_rate_for(self.entry(60)))
        self.contract(contract_type='managed_services', hourly_rate=Decimal('0'))
        self.assertIsNone(bill_rate_for(self.entry(60)))

    def test_cost_for_period_unknown_without_rate(self):
        from reports.queries import cost_for_period
        self.assertIsNone(cost_for_period(self.tech, 120, self.today))
        self.rate(45)
        self.assertEqual(cost_for_period(self.tech, 120, self.today), Decimal('90.00'))


# ---------------------------------------------------------------------------
# Former placeholders now yield UNKNOWN
# ---------------------------------------------------------------------------

class PlaceholdersRemovedTests(_Fixture):

    def test_contract_snapshot_without_rates_is_unknown_not_60_percent(self):
        c = self.contract(hourly_rate=Decimal('150'), total_hours=Decimal('10'))
        self.entry(120)
        c.recompute_hours_used()
        snap = c.profitability_snapshot()
        self.assertEqual(snap['revenue'], 300.0)
        self.assertEqual(snap['cost'], 0.0)        # not 2h × 150 × 0.60 = 180
        self.assertIsNone(snap['margin'])
        self.assertIsNone(snap['margin_pct'])
        self.assertFalse(snap['is_complete'])
        self.assertEqual(snap['unknown_cost_hours'], 2.0)
        self.assertEqual(snap['unknown_cost_entries'], 1)

    def test_contract_snapshot_with_rate_uses_tech_cost(self):
        c = self.contract(hourly_rate=Decimal('150'), total_hours=Decimal('10'))
        self.rate(55)
        self.entry(120)
        c.recompute_hours_used()
        snap = c.profitability_snapshot()
        self.assertEqual(snap['cost'], 110.0)
        self.assertEqual(snap['margin'], 190.0)
        self.assertTrue(snap['is_complete'])

    def test_profitability_by_tech_without_rates_is_unknown(self):
        from reports.queries import profitability_by_tech
        self.entry(120)
        row = profitability_by_tech(self.today, self.today)[0]
        self.assertEqual(row['cost'], 0.0)               # not 2h × $60
        self.assertEqual(row['attributed_revenue'], 0.0)  # not 2h × $60 stand-in
        self.assertEqual(row['unknown_cost_hours'], 2.0)
        self.assertEqual(row['unknown_bill_hours'], 2.0)
        self.assertIsNone(row['margin'])
        self.assertIsNone(row['margin_pct'])
        self.assertFalse(row['is_complete'])

    def test_revenue_leakage_without_bill_rate_is_unknown_not_150(self):
        from reports.queries import revenue_leakage
        self.entry(120, day=self.today - timedelta(days=60))
        data = revenue_leakage(self.today, self.today, stale_days=30)
        row = [r for r in data['stale_unbilled'] if r['client_id'] == self.acme.pk][0]
        self.assertEqual(row['amount_at_risk'], 0.0)     # not 2h × $150
        self.assertEqual(row['hours_without_rate'], 2.0)
        self.assertFalse(row['is_complete'])
        self.assertFalse(data['totals']['is_complete'])
        self.assertEqual(data['totals']['stale_hours_without_rate'], 2.0)

    def test_revenue_leakage_expired_block_without_rate_is_unknown(self):
        from reports.queries import revenue_leakage
        self.contract(status='expired', total_hours=Decimal('10'), hourly_rate=Decimal('0'),
                      start_date=self.today - timedelta(days=200),
                      end_date=self.today - timedelta(days=10))
        data = revenue_leakage(self.today, self.today)
        self.assertIsNone(data['expired_blocks'][0]['unused_value'])
        self.assertFalse(data['totals']['is_complete'])

    def test_margin_analytics_without_rates_is_unknown_not_150(self):
        from reports.queries import margin_analytics_by_service_line
        self.entry(60)
        row = margin_analytics_by_service_line(self.today, self.today)[0]
        self.assertEqual(row['revenue'], 0.0)
        self.assertEqual(row['cost'], 0.0)
        self.assertEqual(row['unknown_bill_hours'], 1.0)
        self.assertEqual(row['unknown_cost_hours'], 1.0)
        self.assertIsNone(row['margin'])

    def test_margin_analytics_costs_non_billable_time(self):
        from reports.queries import margin_analytics_by_service_line
        self.contract(hourly_rate=Decimal('100'))
        self.rate(40)
        self.entry(60)
        self.entry(60, billable=False)
        row = margin_analytics_by_service_line(self.today, self.today)[0]
        self.assertEqual(row['revenue'], 100.0)
        self.assertEqual(row['cost'], 80.0)
        self.assertEqual(row['margin'], 20.0)
        self.assertTrue(row['is_complete'])

    def test_client_profitability_without_rates_has_no_margin(self):
        from reports.queries import profitability_by_client
        self.entry(120)
        self.invoice(self.acme, 500, 'INV-P-1')
        row = profitability_by_client(self.today, self.today)[0]
        self.assertEqual(row['revenue'], 500.0)
        self.assertEqual(row['cost'], 0.0)
        self.assertIsNone(row['margin'])
        self.assertEqual(row['unknown_cost_entries'], 1)

    def test_effective_rate_by_tech_unknown_without_rates(self):
        from reports.queries import effective_hourly_rate_by_tech
        self.entry(60)
        row = effective_hourly_rate_by_tech(self.today, self.today)[0]
        self.assertIsNone(row['cost_rate'])        # not $60
        self.assertIsNone(row['effective_rate'])   # no bill rate
        self.assertIsNone(row['realization_pct'])

    def test_partial_totals_are_labelled_incomplete(self):
        from reports.costing import summarize
        from reports.queries import profitability_by_client
        self.rate(50)
        self.entry(60)                                # known: $50
        self.entry(60, ticket=self.t_beta, user=self.tech2)  # unknown
        rows = profitability_by_client(self.today, self.today)
        s = summarize(rows)
        self.assertEqual(s['total_cost'], 50.0)
        self.assertEqual(s['unknown_cost_hours'], 1.0)
        self.assertFalse(s['is_complete'])
        self.assertIsNone(s['total_margin'])


class EffectiveDatedRateTests(_Fixture):

    def test_rate_change_mid_period_splits_by_entry_date(self):
        from reports.queries import cost_estimate_by_client, profitability_by_tech
        self.rate(40, days_ago=20)
        self.rate(80, days_ago=5)
        self.entry(120, day=self.today - timedelta(days=10))   # 2h × 40 = 80
        self.entry(60, day=self.today - timedelta(days=2))     # 1h × 80 = 80
        start = self.today - timedelta(days=15)
        row = cost_estimate_by_client(start, self.today)[0]
        self.assertEqual(row['cost'], 160.0)
        self.assertTrue(row['is_complete'])
        tech = profitability_by_tech(start, self.today)[0]
        self.assertEqual(tech['cost'], 160.0)

    def test_entry_before_first_rate_is_unknown(self):
        from reports.queries import cost_estimate_by_client
        self.rate(40, days_ago=5)
        self.entry(60, day=self.today - timedelta(days=10))
        self.entry(60, day=self.today - timedelta(days=1))
        row = cost_estimate_by_client(self.today - timedelta(days=15), self.today)[0]
        self.assertEqual(row['cost'], 40.0)
        self.assertEqual(row['unknown_cost_hours'], 1.0)
        self.assertFalse(row['is_complete'])

    def test_tech_revenue_uses_contract_rate_per_entry_date(self):
        from reports.queries import profitability_by_tech
        self.rate(50, days_ago=400)
        self.contract(name='Old', status='expired', hourly_rate=Decimal('100'),
                      start_date=self.today - timedelta(days=60),
                      end_date=self.today - timedelta(days=31))
        self.contract(name='New', hourly_rate=Decimal('150'),
                      start_date=self.today - timedelta(days=30))
        self.entry(60, day=self.today - timedelta(days=40))
        self.entry(60, day=self.today - timedelta(days=1))
        row = profitability_by_tech(self.today - timedelta(days=50), self.today)[0]
        self.assertEqual(row['attributed_revenue'], 250.0)
        self.assertEqual(row['cost'], 100.0)
        self.assertEqual(row['margin'], 150.0)


# ---------------------------------------------------------------------------
# MSP-wide metrics
# ---------------------------------------------------------------------------

class RecurringRevenueTests(_Fixture):

    def test_mrr_normalizes_billing_frequency(self):
        from reports.queries import recurring_revenue
        self.contract(name='M', billing_frequency='monthly', recurring_amount=Decimal('300'))
        self.contract(name='Q', billing_frequency='quarterly', recurring_amount=Decimal('900'))
        self.contract(name='Y', billing_frequency='yearly', recurring_amount=Decimal('3600'))
        self.contract(name='Draft', status='draft', billing_frequency='monthly',
                      recurring_amount=Decimal('1000'))
        self.contract(name='Paused', billing_frequency='monthly', recurring_amount=Decimal('1000'),
                      paused_at=timezone.now())
        self.contract(name='NoFreq', recurring_amount=Decimal('500'))
        rr = recurring_revenue(self.today)
        self.assertEqual(rr['mrr'], 900.0)
        self.assertEqual(rr['arr'], 10800.0)
        self.assertEqual(rr['contract_count'], 3)
        self.assertEqual(rr['contracts_without_amount'], 1)

    def test_mrr_growth_month_over_month(self):
        from reports.queries import mrr_trend
        first = self.today.replace(day=1)
        prev_month_start = (first - timedelta(days=1)).replace(day=1)
        self.contract(name='A', billing_frequency='monthly', recurring_amount=Decimal('100'),
                      start_date=(prev_month_start - timedelta(days=1)).replace(day=1))
        self.contract(name='B', billing_frequency='monthly', recurring_amount=Decimal('50'),
                      start_date=first)
        t = mrr_trend(3, self.today)
        self.assertEqual([p['mrr'] for p in t['points']][-2:], [100.0, 150.0])
        self.assertEqual(t['mom_growth'], 50.0)
        self.assertEqual(t['mom_growth_pct'], 50.0)

    def test_stopped_contract_counts_until_its_end_date(self):
        from reports.queries import recurring_revenue
        self.contract(name='Gone', status='cancelled', billing_frequency='monthly',
                      recurring_amount=Decimal('200'),
                      start_date=self.today - timedelta(days=100),
                      end_date=self.today - timedelta(days=20))
        self.assertEqual(recurring_revenue(self.today - timedelta(days=30))['mrr'], 200.0)
        self.assertEqual(recurring_revenue(self.today)['mrr'], 0.0)

    def test_undated_stop_makes_history_incomplete(self):
        from reports.queries import recurring_revenue
        self.contract(name='Undated', status='cancelled', billing_frequency='monthly',
                      recurring_amount=Decimal('200'))
        past = recurring_revenue(self.today - timedelta(days=30))
        self.assertFalse(past['is_complete'])
        self.assertEqual(past['contracts_unknown_end'], 1)


class ChurnTests(_Fixture):

    def test_churn_counts_contracts_ended_without_renewal(self):
        from reports.queries import contract_churn
        start = self.today - timedelta(days=29)
        lost = self.contract(name='Lost', status='cancelled', billing_frequency='monthly',
                             recurring_amount=Decimal('400'),
                             start_date=self.today - timedelta(days=200),
                             end_date=self.today - timedelta(days=10))
        renewed = self.contract(client=self.beta, name='Renewed', status='expired',
                                billing_frequency='monthly', recurring_amount=Decimal('100'),
                                start_date=self.today - timedelta(days=200),
                                end_date=self.today - timedelta(days=5))
        self.contract(client=self.beta, name='Renewal', billing_frequency='monthly',
                      recurring_amount=Decimal('110'), start_date=self.today - timedelta(days=4),
                      parent_contract=renewed)
        out = contract_churn(start, self.today)
        self.assertEqual([r['contract_id'] for r in out['churned']], [lost.pk])
        self.assertEqual(out['churned_mrr'], 400.0)
        self.assertEqual(out['starting_mrr'], 500.0)
        self.assertEqual(out['churn_rate_pct'], 80.0)
        self.assertTrue(out['is_complete'])

    def test_back_to_back_contract_counts_as_renewal(self):
        from reports.queries import contract_churn
        self.contract(name='Y1', status='expired', start_date=self.today - timedelta(days=400),
                      end_date=self.today - timedelta(days=10))
        self.contract(name='Y2', start_date=self.today - timedelta(days=9))
        self.assertEqual(contract_churn(self.today - timedelta(days=29), self.today)['churned_count'], 0)

    def test_undated_cancellation_flags_incomplete(self):
        from reports.queries import contract_churn
        self.contract(name='Undated', status='cancelled')
        out = contract_churn(self.today - timedelta(days=29), self.today)
        self.assertEqual(out['undated_cancellations'], 1)
        self.assertFalse(out['is_complete'])


class UnbilledTimeTests(_Fixture):

    def test_unbilled_time_excludes_invoiced_and_non_billable(self):
        from reports.queries import unbilled_time
        self.contract(hourly_rate=Decimal('120'))
        open_entry = self.entry(60)
        billed = self.entry(30)
        self.entry(45, billable=False)
        inv = self.invoice(self.acme, 60, 'INV-U-1')
        InvoiceLineItem.objects.create(invoice=inv, description='t', quantity=Decimal('0.5'),
                                       unit_price=Decimal('120'), source='time',
                                       source_id=str(billed.pk))
        out = unbilled_time(self.today, self.today)
        self.assertEqual(out['entries'], 1)
        self.assertEqual(out['hours'], 1.0)
        self.assertEqual(out['amount'], 120.0)
        self.assertTrue(out['is_complete'])
        self.assertNotEqual(open_entry.pk, billed.pk)

    def test_voided_invoice_releases_time_and_unrated_time_is_counted(self):
        from reports.queries import unbilled_time
        e = self.entry(60, ticket=self.t_beta)   # Beta has no contract
        inv = self.invoice(self.beta, 0, 'INV-U-2', status='void')
        InvoiceLineItem.objects.create(invoice=inv, description='t', quantity=1,
                                       unit_price=0, source='time', source_id=str(e.pk))
        out = unbilled_time(self.today, self.today)
        self.assertEqual(out['entries'], 1)
        self.assertEqual(out['amount'], 0.0)
        self.assertEqual(out['hours_without_rate'], 1.0)
        self.assertFalse(out['is_complete'])


class ExpiringAndUtilizationTests(_Fixture):

    def test_contracts_expiring_in_30_60_90(self):
        from reports.queries import contracts_expiring
        for days in (10, 45, 80, 120):
            self.contract(name=f'E{days}', end_date=self.today + timedelta(days=days),
                          billing_frequency='monthly', recurring_amount=Decimal('100'))
        self.contract(name='Open')   # no end date
        out = contracts_expiring(self.today)
        self.assertEqual(out['windows'][30]['count'], 1)
        self.assertEqual(out['windows'][60]['count'], 2)
        self.assertEqual(out['windows'][90]['count'], 3)
        self.assertEqual(out['windows'][90]['mrr'], 300.0)

    def test_utilization_from_working_hours_and_unknown_without_basis(self):
        from reports.queries import technician_utilization
        monday = self.today - timedelta(days=self.today.weekday() + 7)
        WorkingHours.objects.create(user=self.tech, weekday=0, start_time=time(9), end_time=time(17))
        self.entry(240, day=monday)
        self.entry(60, day=monday, user=self.tech2)
        rows = {r['tech_id']: r for r in technician_utilization(monday, monday)}
        self.assertEqual(rows[self.tech.pk]['available_hours'], 8.0)
        self.assertEqual(rows[self.tech.pk]['utilization_pct'], 50.0)
        self.assertEqual(rows[self.tech.pk]['basis'], 'working_hours')
        self.assertIsNone(rows[self.tech2.pk]['utilization_pct'])

    def test_revenue_by_service_line(self):
        from reports.queries import revenue_by_service_line
        c = self.contract(contract_type='managed_services')
        self.invoice(self.acme, 1000, 'INV-S-1', source_contract=c)
        self.invoice(self.acme, 200, 'INV-S-2', source_ticket=self.t_acme)
        self.invoice(self.acme, 50, 'INV-S-3')
        out = revenue_by_service_line(self.today, self.today)
        by = {r['key']: r['revenue'] for r in out['rows']}
        self.assertEqual(by, {'managed_services': 1000.0, 'ticket': 200.0, 'unattributed': 50.0})
        self.assertFalse(out['is_complete'])


class TenantIsolationTests(_Fixture):

    def test_queries_scope_to_the_given_customers(self):
        from reports.queries import (
            profitability_by_client, profitability_by_tech, recurring_revenue, unbilled_time,
        )
        self.rate(50)
        self.entry(60)
        self.entry(120, ticket=self.t_beta)
        self.contract(billing_frequency='monthly', recurring_amount=Decimal('100'))
        self.contract(client=self.beta, billing_frequency='monthly', recurring_amount=Decimal('900'))
        rows = profitability_by_client(self.today, self.today, organization=self.acme)
        self.assertEqual([r['client_id'] for r in rows], [self.acme.pk])
        self.assertEqual(profitability_by_tech(self.today, self.today, organization=self.acme)[0]['cost'], 50.0)
        self.assertEqual(recurring_revenue(self.today, organization=self.acme)['mrr'], 100.0)
        self.assertEqual(recurring_revenue(self.today, organization=[self.beta])['mrr'], 900.0)
        self.assertEqual([r['client_id'] for r in unbilled_time(self.today, self.today, [self.beta])['rows']],
                         [self.beta.pk])


# ---------------------------------------------------------------------------
# view_profitability permission + pages
# ---------------------------------------------------------------------------

def _role(name, **flags):
    from django.db import models as dj
    values = {f.name: False for f in RoleTemplate._meta.get_fields()
              if isinstance(f, dj.BooleanField) and f.name != 'is_system_template'}
    values.update(flags)
    return RoleTemplate.objects.create(name=name, **values)


def _staff(username, role):
    user = User.objects.create_user(username, f'{username}@msp.test', 'pw-prof-123')
    profile, _ = UserProfile.objects.get_or_create(user=user)
    user.profile.user_type = UserType.STAFF
    user.profile.global_role_template = role
    user.profile.save()
    return user


def _client(user, org=None):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    else:
        s['global_view_mode'] = True
    s.save()
    return c


MARGIN_PAGES = ('reports:psa_profitability_by_client', 'reports:psa_profitability_by_tech',
                'reports:psa_profitability_by_contract', 'reports:psa_profitability_by_project',
                'reports:psa_margin_analytics', 'reports:psa_effective_hourly_rate')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewProfitabilityPermissionTests(_Fixture):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _enable_psa_global()
        _enable_psa_for(cls.acme)
        cls.fin_only = _staff('prof_fin', _role('ProfFinOnly', reports_view_dashboards=True,
                                                 reports_view_financial=True))
        cls.profit = _staff('prof_profit', _role('ProfProfit', reports_view_dashboards=True,
                                                  reports_view_financial=True,
                                                  view_profitability=True))
        cls.su = User.objects.create_superuser('prof_su', 'su@msp.test', 'pw-prof-123')

    def test_registry_entry_is_staff_only(self):
        from accounts import permission_registry as reg
        p = reg.get('view_profitability')
        self.assertTrue(p.staff_only)
        self.assertFalse(p.customer_assignable)
        self.assertIn('view_profitability', reg.STAFF_ONLY_KEYS)
        self.assertFalse(RoleTemplate._meta.get_field('view_profitability').default)

    def test_margin_pages_need_view_profitability(self):
        for name in MARGIN_PAGES:
            with self.subTest(name=name):
                self.assertEqual(_client(self.fin_only).get(reverse(name)).status_code, 403)
                self.assertEqual(_client(self.fin_only).get(reverse(name), {'format': 'csv'}).status_code, 403)
                self.assertEqual(_client(self.profit).get(reverse(name)).status_code, 200)
                self.assertEqual(_client(self.su).get(reverse(name)).status_code, 200)

    def test_revenue_only_page_still_follows_financial_flag(self):
        r = _client(self.fin_only).get(reverse('reports:psa_revenue_leakage'))
        self.assertEqual(r.status_code, 200)

    def test_scorecard_hides_margin_without_flag(self):
        r = _client(self.fin_only).get(reverse('reports:exec_scorecard'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['can_see_margin'])
        self.assertEqual(r.context['pie_data'], [])
        r = _client(self.profit).get(reverse('reports:exec_scorecard'))
        self.assertTrue(r.context['can_see_margin'])

    def test_legacy_owner_membership_keeps_profitability(self):
        u = User.objects.create_user('prof_owner', 'o@msp.test', 'pw')
        m = Membership.objects.create(user=u, organization=self.msp, role=Role.OWNER)
        self.assertTrue(m.get_permissions().view_profitability)
        m2 = Membership.objects.create(user=u, organization=self.acme, role=Role.EDITOR)
        self.assertFalse(m2.get_permissions().view_profitability)

    def test_contract_snapshot_needs_flag(self):
        c = self.contract(hourly_rate=Decimal('150'))
        Membership.objects.create(user=self.fin_only, organization=self.acme, role=Role.EDITOR)
        Membership.objects.create(user=self.profit, organization=self.acme, role=Role.EDITOR)
        r = _client(self.fin_only, self.acme).get(f'/psa/contracts/{c.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['snapshot'])
        r = _client(self.profit, self.acme).get(f'/psa/contracts/{c.pk}/')
        self.assertIsNotNone(r.context['snapshot'])

    def test_customer_never_sees_costs_or_margins(self):
        """Even a customer role that (wrongly) holds view_profitability: the
        flag is staff-only, the contract page shows no snapshot and every
        margin page is refused."""
        from accounts.permission_utils import user_has_org_perm
        role = _role('CustProfit', view_profitability=True, reports_view_financial=True,
                     tickets_view=True)
        cust = User.objects.create_user('prof_cust', 'c@acme.test', 'pw-prof-123')
        Membership.objects.create(user=cust, organization=self.acme, role=Role.OWNER,
                                  role_template=role, is_active=True)
        self.assertFalse(user_has_org_perm(cust, self.acme, 'view_profitability'))
        c = self.contract(hourly_rate=Decimal('150'))
        self.rate(50)
        self.entry(60)
        client = _client(cust, self.acme)
        r = client.get(f'/psa/contracts/{c.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['snapshot'])
        self.assertNotContains(r, 'Profitability snapshot')
        self.assertNotContains(r, 'Labour cost')
        for name in MARGIN_PAGES:
            with self.subTest(name=name):
                self.assertIn(client.get(reverse(name)).status_code, (302, 403))

    def _scoped_staff(self, username, *orgs):
        user = _staff(username, self.profit.profile.global_role_template)
        user.profile.client_scope = 'selected'
        user.profile.save()
        user.profile.scope_organizations.set(orgs)
        return user

    def test_scoped_staff_only_see_their_customers_figures(self):
        """One MSP per install: MSP-wide figures add up only the customers the
        viewing technician's client scope reaches."""
        self.rate(50)
        self.entry(60)
        self.entry(120, ticket=self.t_beta)
        self.invoice(self.acme, 500, 'INV-SC-1')
        self.invoice(self.beta, 900, 'INV-SC-2')
        self.contract(billing_frequency='monthly', recurring_amount=Decimal('100'))
        self.contract(client=self.beta, billing_frequency='monthly', recurring_amount=Decimal('900'))
        scoped = self._scoped_staff('prof_scoped', self.acme)
        c = _client(scoped)
        r = c.get(reverse('reports:psa_profitability_by_client'))
        self.assertEqual([row['client_id'] for row in r.context['rows']], [self.acme.pk])
        self.assertEqual(r.context['total_revenue'], 500.0)
        r = c.get(reverse('reports:psa_profitability_by_tech'))
        self.assertEqual(r.context['rows'][0]['cost'], 50.0)
        r = c.get(reverse('reports:psa_margin_analytics'))
        self.assertEqual(r.context['total_cost'], 50.0)
        r = c.get(reverse('reports:exec_scorecard'))
        self.assertEqual(r.context['metrics']['recurring']['mrr'], 100.0)
        r = c.get(reverse('reports:psa_revenue_leakage'))
        self.assertEqual(r.status_code, 200)
        # Unscoped staff see every customer of the install.
        r = _client(self.profit).get(reverse('reports:exec_scorecard'))
        self.assertEqual(r.context['metrics']['recurring']['mrr'], 1000.0)

    def test_staff_scoped_to_nobody_see_nothing(self):
        self.rate(50)
        self.entry(60)
        self.invoice(self.acme, 500, 'INV-SC-3')
        scoped = self._scoped_staff('prof_none')
        r = _client(scoped).get(reverse('reports:psa_profitability_by_client'))
        self.assertEqual(r.context['rows'], [])

    def test_incomplete_page_shows_badge_label_and_cost_rate_link(self):
        self.entry(120)
        self.invoice(self.acme, 500, 'INV-V-1')
        r = _client(self.profit).get(reverse('reports:psa_profitability_by_client'))
        self.assertContains(r, 'Operational profitability estimate — not your accounting P&amp;L')
        self.assertContains(r, 'data-incomplete-badge')
        self.assertContains(r, 'Unknown — 2.00 hours without a cost rate')
        self.assertContains(r, reverse('resourcing:tech_cost_rate_list'))
        self.assertFalse(r.context['is_complete'])

    def test_complete_page_has_label_but_no_incomplete_badge(self):
        self.rate(60)
        self.entry(120)
        self.invoice(self.acme, 500, 'INV-V-2')
        r = _client(self.profit).get(reverse('reports:psa_profitability_by_client'))
        self.assertContains(r, 'Operational profitability estimate')
        self.assertNotContains(r, 'data-incomplete-badge')
        self.assertEqual(r.context['total_margin'], 380.0)

    def test_csv_marks_incomplete_rows(self):
        self.entry(120)
        self.invoice(self.acme, 500, 'INV-V-3')
        r = _client(self.profit).get(reverse('reports:psa_profitability_by_client'), {'format': 'csv'})
        body = r.content.decode()
        self.assertIn('Operational profitability estimate', body.splitlines()[0])
        self.assertIn('incomplete', body)
